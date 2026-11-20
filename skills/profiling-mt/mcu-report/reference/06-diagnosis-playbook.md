# Diagnosis Playbook — Pattern → Cause → Fix

For each observed Moore Perf Compute signal, what does it typically mean, and what's the first fix to try? This combines architecture-neutral kernel programming principles with the profiling signals.

Read this after you've gathered the metrics (via [`05-analysis-dimensions.md`](05-analysis-dimensions.md)) — here you translate metrics into diagnoses and fix directions.

**Moore Perf Compute does not support the `WarpStateStatistics` section.** Do not collect extra data or switch tools for a warp-state/stall breakdown. The diagnoses below use only metrics already present on the current details page and in the raw CSV. If there is no specific stall column, write "cannot determine the specific stall reason".

---

## How to use this doc

For each *observation* below, read:

- **Signals** — what specific metric values flag this pattern.
- **Why** — the underlying cause.
- **First-line fix** — the cheapest change to try.
- **Deeper fixes** — when first-line isn't enough.
- **Exceptions** — kernel types where this pattern is actually *expected* and should be left alone.

Most kernels will match 2-4 patterns simultaneously. **Rank them by magnitude** using the observed metric values, details output, and stall-percentage breakdown. Fix the biggest evidenced problem first.

---

## Pattern A — Small grid / MP idle

**Signals:**
- The raw CSV `Grid Size` is small for the target device, or the details page reports that the grid leaves multiprocessors idle.
- `mp_cycles_active.max` is much smaller than `mp_cycles_elapsed.max`, when both are present.
- Moore Perf Compute details output may report that the grid leaves multiprocessors idle; cite the output and the raw launch metadata.

**Why:** each CTA occupies at most one MP. With fewer CTAs than MPs, some MPs stay idle for the whole kernel. PH1 S5000 has 64 MPs; do not compare the grid against an NVIDIA SM count.

**First-line fix:** increase grid size. Look for a dimension the kernel currently doesn't parallelize:
- Add a split along `K` (split-K for reductions / attention).
- Split across heads / channels if grouped.
- Use Grid-stride loops so one block does multiple work units — but only if work units are cheap.

**Deeper fixes:**
- **Persistent kernel**: launch one block per MP, each block dequeues work items from an atomic counter. Good for dynamic-shape cases.
- **Fuse with adjacent kernels** so more work fits in one launch.

**Exceptions:**
- LLM decode (batch=1, query_len=1) is fundamentally small. Split-K over KV length is the standard mitigation.
- Final reduction stages of a multi-level reduction are naturally small; fuse them into the producing kernel.

---

## Pattern B — Tail effect (variable-length inputs)

**Signals:**
- Multi-workload: `max_seq_len / avg_seq_len > 3` in input distribution.
- The details page reports a large active-cycle spread or a partial-wave warning.
- `mp_cycles_active.max` versus `mp_cycles_elapsed.max` is consistent with substantial inactive time, when both are present.
- An optional timeline shows a long gradual tail, but only when per-instance data was actually collected.
- Details output may report that a partial wave accounts for part of the total runtime.

**Why:** each CTA iterates some variable-size inner loop. When sequences have vastly different lengths, a few long-sequence CTAs keep running after everyone else finished.

**First-line fix (cheap):**
- **Packed batching / sorting**: sort inputs by length (at the application level) so CTAs running comcurrently do roughly equal work.
- **Split long sequences across more CTAs**: add a `split_factor` grid dimension; each CTA handles `ceil(seq_len / split_factor)` tokens, and a small post-reduction combines partials.

**Deeper fixes:**
- **Chunkwise kernel**: break each sequence into fixed-size chunks, process chunks in parallel, then stitch with a small recurrence. This is the approach of flash-linear-attention's `chunk_delta_rule_fwd` for Mamba/GLA-style recurrences.
- **Classify-and-dispatch**: short sequences go through the simple path (one CTA per seq), long sequences through the chunked path.

**Exceptions:**
- Short kernels (< 10 µs) where partial-wave cost is absolute-small.
- Workloads where you already pre-sort / pre-pack.

---

## Pattern C — Uncoalesced global loads

**Signals:**
- `l1_sector_hit_rate.pct`, `l2pu_sector_hit_rate.pct`, or `llc_sector_hit_rate.pct` is materially worse than the baseline for the same workload.
- Details output may report excessive sectors or low sector utilization; cite the exact text and raw metric values.
- Moore Perf Compute does not provide a warp-state stall breakdown. Do not use `mpe_warps_issue_stalled_long_scoreboard` as a signal; cite only the cache/sector evidence already present on the details page and in the raw CSV.

**Why:** lanes in a wave access non-contiguous addresses; hardware fetches extra sectors that only a few lanes use.

**First-line fix:** rework the thread ↔ data mapping:
- If current pattern is `x[lane * K + i]` (stride K), flip to `x[lane + i * 32]` (coalesced).
- Check AoS layouts: `struct { float a, b; } arr[N]` → `struct { float a[N], b[N]; }` so each field is a separate coalesced stream.

**Deeper fixes:**
- Use shared memory as a transposer: coalesced-load to shared, then arbitrary-access from shared.
- Vectorize: replace scalar loads with wider loads where the data layout permits it (use `float2` / `float4` / `ushort2` types).

**Exceptions:**
- Gather/scatter by random index (sparse matmul, embedding lookup) — fundamentally uncoalesced. Sort the indices for locality if possible.
- Graph / tree traversal.

---

## Pattern D — Sparse writes (low store efficiency)

**Signals:**
- An `InstructionStats` or memory-section metric explicitly reports poor store efficiency; use its exact raw CSV name and unit.
- The details page reports inefficient stores or the cache hit-rate evidence is worse than the same-workload baseline.
- Code contains patterns like `if (lane_id < K) { output[...] = ... }`.

**Why:** only a subset of wave lanes write, so the L1 store buffer flushes half-empty sectors.

**First-line fix:** pack the write. Have the wave collectively produce `K` values first (via shuffle or local/shared reduction), then have exactly `K` contiguous lanes perform `K` consecutive writes.

If `K ≥ 32`: all lanes can write; make sure the per-lane index is contiguous.

If `K < 8`: consider batching multiple iterations' results into a vectorized write (e.g., 4 iterations' output packed into a single `float4`).

**Deeper fixes:**
- Write into shared memory first, then do a coalesced global store at the end of the block.

**Exceptions:**
- Histogram / scatter (inherently sparse) — different optimization path, see Pattern G.

---

## Pattern E — Latency-bound (long-scoreboard-dominated)

**Signals:**
- Moore Perf Compute does not support `WarpStateStatistics`, so do not use `mpe_warps_issue_stalled_long_scoreboard` to classify this pattern. Treat it as a latency-bound candidate only when DRAM utilization is low, the kernel is still slow, and the code has a long dependency chain.
- `dram_throughput.avg.pct_of_peak_sustained_elapsed` is low while the kernel remains slow.

**Why:** waves issue a load, then stall waiting for it to return before the next dependent op. Usually combined with low occupancy or insufficient ILP.

**First-line fix:** increase in-flight memory requests:
- **Unroll the load loop** so 4-8 loads are issued before any value is used. Compiler + hardware reorders.
- **Add more independent waves** — raise occupancy (Pattern J).
- Use PH1 TME (`__musa_tme_ld_tile_*` / `__musa_tme_ld_blk`) plus `__musa_async_*` barriers for bulk loads that do not block issue.

**Deeper fixes:**
- Software pipelining: while tile N is being computed, pre-load tile N+1 into local/shared memory with TME.
- Move reused data to local/shared memory so subsequent loads hit L1.

**Exceptions:**
- Pointer chasing / graph traversal — data dep chain is fundamental.

---

## Pattern F — Compute-bound but not on tensor cores

**Signals:**
- `mp_fp32_throughput.avg.per_second` is significant while
  `mp_tc_fp32_throughput.avg.per_second` is absent or low.
- The workload is matmul-ish (GEMM, attention, conv).

**Why:** kernel uses scalar FMA via the ALU pipe instead of tensor cores. On the target architecture, matrix/tensor instructions may provide substantially higher throughput than scalar pipes for supported low-precision types.

**First-line fix:** use SQMMA/WMMA or a PH1-tuned library (muBLAS, muDNN, MUTLASS, Triton-MUSA).

**Deeper fixes:**
- Restructure data layout to a current SQMMA/WMMA tile from the installed Toolkit/FD. A common PH1 trial shape is `128×128×64`; do not require NVIDIA `m16n8k16`.
- Stage A/B through local/shared memory with TME and an async barrier before SQMMA.

**Exceptions:**
- Non-matrix workloads (reduction, sort, element-wise) — tensor cores don't help.
- Small matrices (M, N, K < 32) — tensor-core tiles are too coarse.

---

## Pattern G — Atomics contention

**Signals:**
- An optional `InstructionStats` or scheduler metric identifies atomic/reduction activity.
- `llc_throughput.avg.pct_of_peak_sustained_elapsed` is high while MP throughput is low.

**Why:** many threads atomically updating few locations → serialization.

**First-line fix:** hierarchical reduction.
- Within-wave: `__shfl_down_sync` (no atomic).
- Within-block: shared memory reduction (no atomic).
- Between blocks: single atomic at the end per block.

**Deeper fixes:**
- Shared-memory histogram that flushes to global in one coalesced pass.
- Bucketing: thread writes to `output[tid % N_buckets]`, followed by a merge kernel.

**Exceptions:**
- MCCL / CE / P2P communication — atomics and fences are part of the protocol there.

---

## Pattern H — Shared-memory bank conflicts

**Signals:**
- The details page or an optional scheduler/instruction section identifies shared-memory serialization.
- The raw CSV contains a shared-memory or bank-conflict metric; use its exact name.
- Access pattern has regular strides that align to bank boundaries.

**Why:** local/shared memory is banked. Same-bank accesses serialize. Moore Perf Compute Memory Tables report this as Shared Memory `Bank Conflicts`. Do not assume CUDA's 32-bank map; use the current report and PH1 FD.

**First-line fix:** if Moore Perf Compute shows bank conflicts, try padding or swizzle. Moore Perf Compute's transpose example uses `__shared__ float tile[32][33]` instead of `[32][32]`; confirm that padding still matches TCE/TME layout.

**Deeper fixes:**
- Swizzle: XOR-scramble indices so accesses spread across banks.
- Restructure data layout so wave lanes access different banks.

**Exceptions:**
- Broadcast reads (all lanes read same address) are conflict-free.
- Low shared-mem access volume — don't bother.

---

## Pattern I — Synchronization overhead

**Signals:**
- Moore Perf Compute does not support `WarpStateStatistics`, so do not use `mpe_warps_issue_stalled_barrier` to classify this pattern. Use only the barrier/synchronization count in the source and stall descriptions that actually appear in the current report.

**Why:** `__syncthreads()` / `__musa_barrier0()` wait for the slowest wave. Combined with any per-wave work imbalance, this amplifies.

**First-line fix:**
- Replace block-level syncs with wave primitives (`__shfl_sync`, `__ballot_sync`, `__syncwarp`) when only wave-scoped synchronization is needed. These names exist in the MUSA headers.
- Reduce total sync count — consolidate multiple synchronized phases.

**Deeper fixes:**
- Wave-specialized execution: a DMA wave issues TME, math waves issue SQMMA/WMMA, and they rendezvous with `__musa_async_init_arrival` / `__musa_async_arrive` / `__musa_async_wait` instead of a full block barrier.

---

## Pattern J — Low achieved vs theoretical occupancy

**Signals:**
- The details page reports a gap between theoretical and achieved occupancy, or between active and elapsed cycles.
- `mp_cycles_active.max` is materially below `mp_cycles_elapsed.max`, when both are present.
- Details output may identify a gap between calculated theoretical and measured achieved occupancy; cite the exact text and raw metric values.

**Why:** Theoretical occupancy is the max waves that *could* be resident. Achieved is how many are *actually* running. Gap is caused by: stalls (leaves slots empty), imbalance (some MPs empty), short kernel (warmup dominates).

**Reading:** if the gap is large AND Pattern B (tail effect) is present, fixing imbalance will close the gap. If no imbalance, look at stall reasons (Pattern E, H, I).

**First-line fix:** look for the stall reason causing the gap and address that pattern.

---

## Pattern K — Register spill

**Signals:**
- An `InstructionStats` or memory metric explicitly reports local-memory traffic or register spilling. Use the exact raw CSV name.
- Instruction Statistics may report bytes spilled to local memory; cite the exact metric name and value.
- The details page reports register pressure or an occupancy limit caused by registers.

**Why:** compiler couldn't fit all live variables in registers, spilled some to local memory (which is DRAM-backed).

**First-line fix:** `__launch_bounds__(maxThreadsPerBlock, minBlocksPerMultiprocessor)` on the kernel. This tells the compiler to stay within a register budget.

**Deeper fixes:**
- Reduce the number of live values: recompute values instead of caching, split the kernel into two.
- Move per-thread arrays to shared memory with explicit indexing.

**Exceptions:**
- Large fused kernels (FlashAttention) accept some spill in exchange for larger savings upstream.

---

## Pattern L — FP64 used unintentionally

**Signals:**
- `mp_fp64_throughput.avg.per_second` is non-zero in a kernel that should be FP32, or the details page identifies FP64 activity.

**Why:** C/C++ floating-point literals (`1.0`, `0.5`, `3.14`) default to `double`. A `float x = a + 1.0 * b;` promotes `a + 1.0*b` to double.

**First-line fix:** add `f` suffix to all literals: `1.0f`, `0.5f`, `3.14f`. Add `__expf` / `__logf` / `__sinf` variants for transcendentals.

---

## Pattern M — Pipeline bubbles (no compute/memory overlap)

**Signals:**
- An optional per-instance timeline shows a sawtooth between MP and DRAM throughput.
- `dram_throughput.avg.pct_of_peak_sustained_elapsed` is high and the details page or optional scheduler metrics show memory waits.

**Why:** kernel loads a tile, computes on it, loads next tile — single-buffered.

**First-line fix:** double-buffer. Use two local/shared tiles with two async barriers: a DMA wave fills tile N+1 while math waves consume tile N.

**Deeper fixes:**
- Multi-stage pipeline (3-4 stages may help if local memory still allows enough resident blocks). Use TME rather than blocking global loads.

---

## Pattern N — Wave divergence

**Signals:**
- The details page reports divergent or inefficient wave execution, or an optional instruction metric shows low active-lane efficiency.
- Branch efficiency metric low in `--page details`.
- Divergent branches cluster at specific branch sites.

**Why:** lanes in a wave take different paths at a branch; hardware serializes.

**First-line fix:**
- Rearrange so all lanes in a wave take the same branch. Sort / partition data if possible.
- Convert `if (cond) a else b` to branchless `mask * a + (1-mask) * b` — cheap if both sides are cheap.

**Exceptions:**
- Tree reductions in a wave (last few steps have half / quarter / ... active). Use `__shfl_down_sync` to handle cleanly.
- Boundary handling (a few waves at tensor edge) — not worth fighting.

---

## Ranking template for the final report

When you hand back an optimization plan, rank by the observed impact and the effort required to address it. Validate any expected gain with an A/B profile.

```
Priority 1: <pattern> — <concrete fix>
  Evidence: <metric value(s)>
  Evidence: <metric values and relevant details output>
  Effort: <low / medium / high>
  Why now: <reason this is the highest-leverage fix>

Priority 2: ...
```

A good rule of thumb: at most 3-5 priorities in the plan. More than that dilutes the signal.
