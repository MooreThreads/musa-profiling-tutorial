# GPU Kernel Programming Guidelines

## Target platform

This document covers MUSA kernel development and performance analysis on the Moore Threads PH1 architecture (S5000). Peak numbers come from PH1 architecture material. The instructions, tile shapes, counters, and compiler options actually available must be taken from the MUSA Toolkit, driver, and Moore Perf Compute report on the target machine.

- **GPU:** S5000 (PH1)
- **Programming model:** MUSA Runtime / MUSA C++ extensions. The MUSA API is broadly compatible with the CUDA API, but PH1 Wave32, TCE, and TME constraints differ.
- **Compiler:** `mcc`
- **Compile target:** Confirm the `--cuda-gpu-arch` value from the current `mcc --help` and the installed MUSA Toolkit. Some PH1 environments use `mp_31`; do not treat it as universal for every PH1 device or Toolkit version.

Example (replace the architecture with the value confirmed by the target toolchain):

```bash
mcc -std=c++17 -mtgpu -O3 \
    --cuda-gpu-arch=<target-arch> -lmusart \
    -o my_kernel my_kernel.cu
```

Reproduce performance conclusions with the same compiler, driver, and Moore Perf Compute version as the target device. Do not apply NVIDIA `sm_` architecture names, NCU metric names, or CUDA PTX shapes directly to PH1.

---

## PH1 S5000 architecture quick reference

The table below lists the architecture facts most often needed when writing a kernel. `MP` is a MUSA Processor, `MPC` is an MP Cluster, `MPE` is an execution element inside an MP, `TCE` is the Tensor Compute Engine, and `TME` is the Tensor Memory Engine. Some values are product peaks or design targets and differ across sources. When they conflict, use the target card and the Moore Perf Compute report.

| Parameter | PH1 / S5000 |
|------|-------------|
| GPU architecture | PH1 |
| MPC / MPX / MP | 8 MPC / 32 MPX / 64 MP |
| MPEs per MP | 4 |
| FP32 cores per MP | 128 (4 x 32) |
| FP32 cores per GPU | 8192 |
| FP64 cores per MP | 64 |
| FP64 cores per GPU | 4096 |
| INT cores per MP | 64 |
| INT cores per GPU | 4096 |
| TCEs per MP | 1 (256 tensor cores per GPU) |
| Execution granularity | Native Wave32, with a Wave128 compatibility path |
| GPR per MP | About 512 KB (about 128 KB and 4 banks per MPE) |
| Local memory per MP | About 192 KB; the capacity and reservation available to TME/LMS follow the current FD/compiler |
| LLC/L3 | 60 MB |
| L2 per MPC | 1.5 MB |
| Memory | 80 GB GDDR6 |
| Memory interface / data rate | 640-bit / 20 Gbps |
| Memory bandwidth | About 1.6 TB/s |
| Boost clock (product material) | About 1.91 GHz |
| Vector FP32/FP16/BF16 peak | About 31.2 TFLOPS |
| Vector FP64 peak | About 15.6 TFLOPS |
| Tensor TF32 peak | About 250 TFLOPS |
| Tensor FP16/BF16 peak | About 500 TFLOPS |
| Tensor FP8/INT8 peak | About 1000 TFLOPS |
| W4A16/W8A16 peak | About 500 TFLOPS |
| MT Link V2 | 14 links x 2 lanes x 112 Gbps; supports topologies such as a fully connected 8-GPU node |

These numbers choose a direction. They are not a guaranteed throughput for one kernel. Actual performance also depends on shape, layout, clocks, concurrency, cache residency, compiler version, and how the report was collected.

---

## PH1-specific features and programming notes

### 1. Native Wave32 and four-MPE cooperation

A PH1 Musa processor executes natively as Wave32, and one MP contains four MPEs. A Wave128 compatibility path may still exist, so a kernel, library, or compiler-generated code must not guess the actual wave mode from the source file alone.

**Practical guidance:**

- Start with a block size that is a multiple of 32. Confirm the wave mode of the current compilation path before using warp/wave intrinsics.
- For a TCE operation that needs four waves to cooperate, PDS should group four consecutive waves into one squad and keep the wave0-to-MPE0, wave1-to-MPE1 mapping.
- Do not force a single-wave operation into a squad just to "fill" the hardware. Extra synchronization and local-memory movement can erase the gain.
- Split variable-length work on block/wave boundaries so that only a few lanes in one wave do not run for a long time.

### 2. TCE and SQMMA: large-tile matrix multiply-accumulate

PH1 TCE provides WMMA and SQMMA paths. SQMMA (Squad Matrix Multiply and Accumulate) uses four Wave32 waves on four MPEs to complete one MMA: A/B are read from local memory, C is read from registers/accumulators, and D is written back to registers. TCE handles A/B/ACC buffer reuse and the internal K loop, reducing repeated local-memory-to-register movement.

Key constraints of the programming model:

- SQMMA works only in Wave32 mode. One squad must collect all four waves.
- Instructions are processed in issue and commit order within the squad. Consecutive SQMMA instructions must wait until the synchronization fence associated with the previous instruction clears. Do not push an unbounded number of instructions from the same squad into TCE.
- A large M/N lets the hardware reuse weights across instructions and reduces instruction-issue overhead. A typical PH1 starting point in the material is `128x128x64`. INT8 often starts trials at K=64/128, and FP16/BF16 often starts at K=32/64.
- The exact M/N/K, data types, accumulator, and layout are defined by the current SQMMA FD and Toolkit. Do not write NVIDIA shapes such as `m16n8k16` as PH1 requirements.

Pseudocode showing the dependency, not guaranteed to compile:

```text
for each K tile:
    wait_until_A_B_tile_ready()
    sqmma.<type>.<M>x<N>x<K>(A_in_local, B_in_local, C_in_reg, D_out_reg)
    sqmma_wait_or_sync_fence()
    // apply bias / activation / store only after D has been written back
```

For large matrix work such as GEMM, attention, and convolution, prefer muBLAS, muDNN, Triton-MUSA, or another MUSA library already tuned for PH1. A hand-written SQMMA must check squad collection, fences, local-memory layout, and register pressure together.

### 3. WMMA: compatibility path and fine-grained matrix operations

WMMA lets threads in one wave contribute matrix data together. It can reduce some register traffic, but data is not shared across waves, so a larger tile may reload A/B. PH1 WMMA material covers combinations such as INT8, FP16/BF16, and TF32. The shape set changes with the FD/Toolkit version.

**Selection rules:**

- Prefer evaluating SQMMA for large tiles that need A/B reuse across waves.
- WMMA may be simpler for small matrices, existing WMMA code, or cases that cannot meet the squad/fence constraints.
- Compare both paths on local-memory bandwidth, register usage, instruction-issue overhead, and end-to-end time. Do not look only at theoretical tensor FLOPS.

### 4. TME V2: asynchronous tensor movement

TME is a DMA-like pipeline outside the MP. It connects the BIF, L2 bridge, local memory, and asynchronous transaction barriers directly. It moves 1D-5D tensors between global and local memory and supports modes such as TILE, IM2COL, TRANSPOSE.IM2COL, and BLK. Convolution can use IM2COL to perform address transformation and boundary zero-fill during the move.

The TME programming model separates "submit the move" from "wait for completion":

1. Initialize the barrier arrival count from the number of warps designed to execute `arrive`, not from a guess at how many threads actually issue the TME instruction.
2. Before submitting TME, record the bytes to move as the transaction count.
3. One or more waves issue the warp-level TME instruction. Hardware executes only the first valid instance of that instruction.
4. Call `arrive` to obtain the phase, then `wait` before computation. TME completes the move in the background and decrements the transaction count.

Pseudocode:

```cpp
// Actual intrinsic names and arguments follow the current MUSA Toolkit
if (threadIdx.x == 0) {
    __musa_async_init_arrival(bar_id, producer_warps, /*phase=*/0);
}
__musa_barrier0();

if (threadIdx.x < 32) {                 // one DMA wave
    __musa_async_add_trans(bar_id, bytes_A);
    __musa_tme_ld_tile_2d(bar_id, local_A, desc_A, pos_A, shape_A);
    __musa_async_add_trans(bar_id, bytes_B);
    __musa_tme_ld_tile_2d(bar_id, local_B, desc_B, pos_B, shape_B);
}
auto phase = __musa_async_arrive(bar_id);

do_independent_work();
__musa_async_wait(bar_id, phase);
// only now read local_A/local_B and issue MMA
```

**Descriptor and capacity notes:**

- The current PH1 TME FD requires 16-byte alignment for LMS addresses. Register encoding of BLK/descriptors, descriptor-address alignment, and the usable LMS total are version-dependent.
- One FD implementation defines the TME LMS size as 144 KB and says the total bytes of one block must not exceed that value. Product material lists MP local memory as about 192 KB. Do not treat these as the same capacity. Verify both against the current compiler allocation report and the FD.
- Alignment requirements for the global address, stride, and interleave of APIs such as `muTensorMapEncodeTiled` may differ from NVIDIA TMA. PH1 material commonly uses a minimum global alignment of 4 bytes, and the stride must also satisfy the data type and interleave requirements.
- TME OOB, stride, padding, swizzle, and the descriptor cache constrain both correctness and performance. Recheck boundaries and the transaction count after every tile-shape change.

### 5. Asynchronous transaction barriers, double buffering, and warp specialization

A single buffer leaves TCE idle while waiting for the global-to-local move. A common PH1 approach uses two or more local buffers and two barriers: the DMA wave fills the next block while math waves consume the current block. Before reusing a buffer, wait for the "empty" and "data ready" states separately.

```text
init empty_bar[0..N-1] and ready_bar[0..N-1]
DMA wave:  wait empty[i] -> TME load into buffer[i] -> arrive ready[i]
Math waves: wait ready[i] -> SQMMA/WMMA on buffer[i] -> arrive empty[i]
```

**Practical guidance:**

- Verify correctness with 2 stages first, then use the Moore Perf Compute timeline and local-memory occupancy to evaluate 3 stages. More buffers reduce the number of resident blocks.
- `arrive` and `wait` must use the correct phase of the same barrier. Missing one transaction or counting one extra producer warp can wait forever.
- Warp specialization, where only the DMA wave issues TME and math waves issue TCE, needs explicit roles and an exit protocol. No wave may `return` early while another wave can still reach the barrier.
- For SQMMA, keep A/B reuse within one squad run when possible, and reduce the cost of writing results back to local memory for every small instruction.

### 6. Data types, conversion, and special functions

PH1 TCE supports data-type combinations such as FP16, BF16, TF32, INT8/UINT8, and FP8. The architecture also provides W4A16/W8A16 decompression paths. PH1 Musa-core type conversion is faster than QY2. The SFU improves EXP2 and provides hardware tanh/GELU, but the exact supported APIs, saturation modes, and accumulators are still defined by the Toolkit/library.

**Practical guidance:**

- Training usually starts with BF16/FP16 inputs and FP32 accumulation. Inference can evaluate FP8 or W4A16/W8A16, but verify accuracy and decompression cost layer by layer.
- Do not write Blackwell FP4/FP6, NVFP4/MXFP4, or `tcgen05` instructions into a PH1 kernel. The corresponding PH1 paths are FP8, INT8, W4A16/W8A16, and similar.
- Use MUSA fast-math intrinsics only when the approximation error is acceptable. Keep softmax, normalization, probability, and loss calculations numerically stable.
- Write floating-point literals as `1.0f` and `0.5f` to avoid accidental FP64. Use FP64 only when the algorithm actually needs it.

### 7. PH1 memory hierarchy and cache policy

PH1's 1.5 MB/MPC L2, 60 MB LLC, and about 1.6 TB/s of DRAM bandwidth give large-model weights and repeated accesses a larger cache. A large cache does not make random access free. Cross-MP locality, request coalescing, and data residency still need to be verified by the report.

TME cache control includes policies such as `NEW_ALLOC` and `BYPASS`, plus inner and outer persistence hints. The exact fields follow the current API/ISA:

- For reusable weights, descriptors, or hot data, start from the normal allocation policy and the measured hit rate.
- Consider bypass only for one-shot streaming reads or writes that will not be used again, and confirm that it does not break reuse in the same kernel or a neighboring kernel.
- Check consistency separately for TME, ordinary load/store, and fences. A cache policy does not replace a required memory fence.

### 8. CE, MT Link, and multi-device kernels

PH1 Copy Engine V2 handles host-to-device and cross-chip asynchronous data communication. MT Link V2 provides high-bandwidth multi-GPU connectivity. The bottleneck of an MCCL, P2P, or CE kernel may be the link, the CE queue, or synchronization rather than MP compute.

**Practical guidance:**

- Use streams and events to overlap communication with compute. Confirm topology, links, and peer access before interpreting Moore Perf Compute numbers for a communication kernel.
- Do not use single-GPU MP throughput to judge the overall performance of a cross-GPU all-reduce. Also record CE/MT Link bandwidth, message size, concurrent streams, and end-to-end time.
- Some known PH1 engine-wait, buffer-stall, and cross-core synchronization constraints need software workarounds. When a fence or barrier behaves unexpectedly, check the driver/firmware version and known limitations first.

---

## Why this document exists

GPU kernel performance problems are usually not as simple as "one missing optimization." The same code can be limited at once by the grid tail, variable-length inputs, TME movement, SQMMA collection, cache hits, and synchronization. PH1 also has wave, local-memory, TCE/TME, and report-metric semantics that differ from CUDA/NVIDIA.

This document is meant to:

1. Choose a suitable PH1 execution path before writing or changing a kernel: ordinary MUSA, TME+WMMA, TME+SQMMA, or a library implementation.
2. Connect each guideline to actual Moore Perf Compute output. Cite a metric only when the current report contains it.
3. Mark reasonable exceptions. An element-wise kernel does not need TCE, LLM decode may naturally have a small grid, and synchronization in a communication kernel cannot simply be deleted.

**How to use it:**

- **Before writing a kernel:** read "PH1-specific features," then walk the checklist.
- **While optimizing a kernel:** collect `details` and `raw --csv` through the repository `mcu-report` flow, then use the guidelines below to interpret the data.
- **During review:** separate "applicable to the architecture" from "confirmed by the report." Do not treat a theoretical peak or a candidate metric as a measured conclusion.

---

## Guideline overview

| # | Guideline | PH1 / Moore Perf Compute focus | Common exceptions |
|---|------|------------------|----------|
| 1 | Provide enough parallelism | `Grid Size`, `Block Size`, `mp_cycles_active.max` / `mp_cycles_elapsed.max`, occupancy notes on the details page | decode, tail reduction |
| 2 | Coalesce global accesses | DRAM/cache throughput, L1/L2/LLC hit rate, sector/access notes in details | gather, sparse, graph traversal |
| 3 | Reuse data with local memory/TME | Relationship between DRAM and MP throughput, TME traffic, local-memory usage | one-shot element-wise access |
| 4 | Avoid local-memory bank conflicts | Local/shared bank metrics provided by details or the current report | no local memory, broadcast reads |
| 5 | Avoid wave divergence | Warp/wave/branch metrics in the current report; check whether conditions are uniform per wave | boundary masks, tree reduction |
| 6 | Control GPR and spills | GPR usage, local-memory spills, occupancy limits (cite only fields present in the report) | large fused kernels |
| 7 | Hide memory latency | DRAM utilization and whether TME is asynchronous. Moore Perf Compute does not support `WarpStateStatistics`; do not judge this from warp-state stalls | pointer chasing |
| 8 | Choose suitable precision and functions | FP32/FP64/TCE throughput, numerical error, FP8/W4A16 support | precision-critical paths |
| 9 | Reduce host-device synchronization | MUSA streams/events/graphs; end-to-end timeline, not a single Moore Perf Compute metric | decisions that must be made on the host |
| 10 | Use TCE appropriately | Fields that actually exist, such as `mp_tc_fp32_throughput.avg.per_second`, and the SQMMA/WMMA path | non-matrix and small-matrix work |
| 11 | Tune grid/block configuration | Wave32 alignment, squad mapping, partial waves, tail | dynamic shapes |
| 12 | Reduce atomic contention | LLC/memory throughput, scheduler stalls, actual atomic metrics | histograms, communication |
| 13 | Vectorize and move data in bulk | LSU/memory throughput, alignment, TME BLK/TILE | unaligned or small tensors |
| 14 | Use caches and cache policy | L1/L2/LLC hit rate, TME NEW_ALLOC/BYPASS, working set | purely streaming data |
| 15 | Pipeline TME/TCE | details/timeline, active/elapsed cycles, barrier stalls | very short kernels, too few stages |
| 16 | Reduce synchronization overhead | Stalls and correctness of async barriers, fences, and barriers | cases that require a full block or grid synchronization |

Moore Perf Compute metric names change with the version and the collected sections. The standard procedure is:

```bash
mcu --list-sections
mcu --import <report>.mcu-rep --page details
mcu --import <report>.mcu-rep --page raw --csv
```

The names in [`reference/08-metric-names.md`](reference/08-metric-names.md) are only a starting point observed in PH1 reports. The current raw CSV is the authority.

---

## Guideline details

### Guideline 1: Provide enough parallelism

PH1 has 64 MPs, but whether a kernel fills them depends on the grid, block resources, and the actual dispatch. Read `Grid Size`, `Block Size`, and `Device` from the raw CSV first, then combine the occupancy notes on the details page with `mp_cycles_active.max` and `mp_cycles_elapsed.max` when both are present.

**Fix direction:** Add a parallel dimension, split along K/head/channel, fuse adjacent small kernels, or use persistent/work-stealing for dynamic workloads. Do not enlarge the block unconditionally just to fill the MPs. Too much local memory, GPR, or too many barriers can reduce the number of resident blocks.

**Exceptions:** Decode with batch=1, the last reduction stage, and kernels with only a few tail elements naturally have low parallelism. Prefer split-K, head fusion, or fusion with a neighboring operation.

### Guideline 2: Coalesce global accesses

Lanes in a Wave32 should access contiguous, aligned addresses when possible. Do not derive PH1 sector, cache-line, and request-coalescing rules from NCU names or a fixed 32/128-byte assumption. Use the access notes in Moore Perf Compute details and the L1/L2/LLC metrics that actually exist in the raw CSV.

**Fix direction:** Map `threadIdx.x` to the contiguous dimension, change AoS to SoA, use local memory for a transpose when needed, and check alignment of every row, TME tile, and descriptor. Random gather/scatter, sparse matrices, and graph traversal need a separate locality assessment. Do not apply only the coalescing rule.

### Guideline 3: Use local memory/TME to reduce repeated global accesses

When the same data is reused by multiple lanes, multiple waves, or multiple K iterations, place the tile in local memory, move it asynchronously with TME, and then consume it with WMMA/SQMMA. If each element is accessed once, local memory only adds movement and synchronization.

Read `dram_throughput.avg.pct_of_peak_sustained_elapsed`, `mp_throughput.avg.pct_of_peak_sustained_elapsed`, cache hit rate, and kernel duration together. High DRAM and low MP may mean bandwidth or wasted accesses. Low DRAM and low MP may mean latency, parallelism, or synchronization. Do not jump to a conclusion.

### Guideline 4: Avoid local-memory bank conflicts

Do not copy CUDA's 32-bank experience onto the bank count, bank width, and access-instruction mapping of PH1 local memory. After collecting `MemoryWorkloadAnalysis_Tables`, Moore Perf Compute Memory Tables report shared-memory `Bank Conflicts`. Quantify a conflict only with bank metrics that the current report or the PH1 FD explicitly provides.

**Fix direction:** Confirm the access pattern and conflict evidence first, then try padding, swizzle, or a new layout. TME swizzle parameters must match the tile's swizzle granularity, stride, and line combination. Blindly adding one column to a 2D array can break the layout required by TCE/TME. Broadcasting one address is usually not a conflict.

### Guideline 5: Avoid wave divergence

Different paths across lanes in a Wave32 reduce the effective instruction execution rate. Check dynamic lengths, boundary masks, early exits, and error branches. If the report has no branch/wave metric, judge qualitatively from the source and result correctness. Do not invent a fixed branch-efficiency threshold.

**Fix direction:** Let neighboring lanes process the same kind of data, lift branches to wave or block granularity, and handle a small number of boundaries with masks/predication. Halving the active lanes at each tree-reduction level is inherent to the algorithm. Prefer wave shuffle or the equivalent MUSA primitive.

### Guideline 6: Control GPR, local memory, and spills

PH1 has about 512 KB of GPR per MP, shared by four cooperating MPEs. TCE can keep most matrix accumulation in hardware buffers, but the epilogue, fused operators, and WMMA inputs still consume registers. High GPR can reduce residency, and spills add local/global traffic.

**Fix direction:** Read the compiler resource report and the actual register, occupancy, and spill evidence in Moore Perf Compute details. Reduce simultaneously live intermediate values, split an oversized fused kernel, or use an appropriate `__launch_bounds__` after confirming that the MUSA compiler supports it and what it means. Do not cut registers just because one "low occupancy" number is low. If the kernel is already compute-bound and has no spills, low occupancy may be intentional.

### Guideline 7: Hide memory latency and raise ILP/TLP

When a wave issues one global load and immediately waits for its result, the MP sees a long dependency stall. TME's advantage is that it moves data in the background after submission. Ordinary loads need more independent requests, more effectively resident waves, or reordered computation.

**Fix direction:** Use TME plus async-barrier double buffering, unroll parallel loads where legal, overlap computation of the current tile with movement of the next tile, and improve the algorithm or data layout for inherently serial accesses such as pointer chasing instead of blindly adding blocks.

### Guideline 8: Choose suitable precision and built-in functions

PH1 FP8/INT8 TCE throughput is much higher than vector FP32. FP64 is stronger than the previous generation but can still become the throughput bottleneck. Precision selection must consider accuracy, the accumulator, conversion, and movement cost together.

**Fix direction:** Use FP16/BF16 inputs with FP32 accumulation for stable training. Evaluate FP8/W4A16/W8A16 layer by layer for inference. Enable fast math only within the error budget. Avoid accidental double literals. If Moore Perf Compute shows nonzero `mp_fp64_throughput` while the algorithm expects FP32, check literals, template deduction, and library calls.

### Guideline 9: Minimize host-device synchronization

`musaDeviceSynchronize()`, synchronous memcpy, and frequent event queries create pipeline bubbles outside a single kernel. Moore Perf Compute can describe the device time of one kernel launch. It cannot prove that end-to-end synchronization is fine.

**Fix direction:** Use MUSA streams and asynchronous memcpy, wait for a specific dependency with an event, record a stable kernel sequence as a graph when the target Toolkit supports it, and concentrate unavoidable host decisions at a few synchronization points. Dynamic control flow that needs the host to read a result may still require synchronization. Record that boundary explicitly.

### Guideline 10: Use TCE appropriately

GEMM, attention, convolution, and quantized matrix multiplication should first check whether SQMMA/WMMA or a PH1-optimized library is available. SQMMA needs a four-wave Wave32 squad, A/B in local memory, the correct sync fence, and a long enough K loop. WMMA fits compatibility or finer-grained paths.

**Moore Perf Compute diagnosis:** Cite tensor throughput only when the current report collected the corresponding ComputeWorkloadAnalysis/SpeedOfLight section and the raw CSV contains `mp_tc_fp32_throughput.avg.per_second` or another actual TCE field. A missing field means "not collected," not "no TCE."

If a matrix kernel has very low TCE throughput, check in order: whether the tile satisfies the current FD, whether A/B are in local memory, whether TME creates pipeline bubbles, whether the squad is fully collected, whether sync fences are too dense, and whether GPR/local memory limits residency. Do not force TCE on a small matrix or a non-matrix kernel.

### Guideline 11: Tune grid/block configuration

A block should be at least a multiple of 32. SQMMA also requires the roles and mapping of a four-wave squad. The grid should cover enough MPs and keep the tail cost of the last wave acceptable.

**Practical method:** Start from the actual `Grid Size`, `Block Size`, and input shape, and try block sizes such as 128/256. Compare full kernel time, active/elapsed cycles, local/GPR resources, and the tail, not occupancy alone. Dynamic shapes can use a grid-stride loop, persistent workers, or dispatch grouped by length.

### Guideline 12: Reduce atomic contention

PH1 LLC supports a larger working set and several data paths, but high LLC throughput does not mean atomics are not serialized. For histograms, reductions, queues, and communication kernels, first confirm the number of conflicting addresses and the actual report evidence for atomic operations.

**Fix direction:** Shuffle-reduce inside a wave, local-memory-reduce inside a block, then one atomic per block. Build a histogram in per-block buckets first. Leave communication to the existing MCCL/CE protocol and focus on overlap. Do not break cross-block memory consistency just to reduce the atomic count.

### Guideline 13: Vectorize and move data in bulk

PH1 provides higher LD/ST throughput, and TME can move a multidimensional tile or BLK in one operation. For contiguous, aligned data, vector types or bulk TME operations reduce instructions and address arithmetic. For irregular, very small, or tail data, the scalar path is safer.

**Practical guidance:** Check element, pointer, and stride alignment for ordinary global load/store. Check the descriptor, LMS address, and total transaction size for TME. Handle the tail separately. Vectorization only reduces instruction pressure. It does not fix random access or a wrong tile layout.

### Guideline 14: Use caches and cache policy

Choose normal allocation or bypass from the working set and reuse distance. Verify the choice with L1/L2/LLC hit rate, DRAM bytes, and end-to-end time. Do not mark all data persistent just because the LLC is large, and do not force streaming data into cache.

Understand TME cache policy, fences, and consistency fields as a group. After changing `NEW_ALLOC`/`BYPASS`, remeasure at least cold cache, hot cache, data shared with a neighboring kernel, and cross-stream cases.

### Guideline 15: Pipeline TME/TCE

An ideal PH1 GEMM/convolution main loop has the DMA wave load tile N+1 while math waves execute SQMMA/WMMA on tile N. If Moore Perf Compute details or the timeline shows alternating active/DRAM cycles, long waits, or repeated barriers, the pipeline usually has bubbles.

**Fix direction:** Implement a correct single-buffer version first, then add double buffering and async barriers. Evaluate deeper stages from local-memory capacity and occupancy. Schedule address calculation, the epilogue, and stores while TCE is busy. For a very short kernel or only one K tile, the pipeline complexity may not be worth it.

### Guideline 16: Reduce synchronization overhead while preserving correctness

`__musa_barrier0()`, async barriers, SQMMA sync fences, and stream/event waits are different levels of synchronization and are not interchangeable. Reducing synchronization is valid only when the data dependence is still expressed correctly.

**Practical guidance:**

- Use the wave primitives provided by MUSA when communication stays inside a wave. Use a block barrier only for local-memory data that crosses waves.
- A TME `arrive` only means the producer has submitted. `wait` means the transactions for that phase are complete. Do not replace a transaction wait with an ordinary barrier.
- Consecutive SQMMA instructions follow the sync-fence clear rule. Do not let different squads submit without control.
- Every wave that can reach the same barrier must execute the same control flow. Handle boundary conditions with predication or a uniform exit protocol.

---

## Quick reference for special kernel types

### LLM decode attention (single-token generation)

| Observation | Cause | PH1 optimization direction |
|------|------|-------------|
| Small grid, low MP utilization | Batch/query is small, so the amount of work is naturally limited | Split KV with split-K, fuse heads, persistent workers |
| Obvious DRAM wait | KV traffic is large and reuse distance is long | Tile by head/sequence; evaluate LLC residency and TME tiles |
| High quantization decompression cost | W4A16/W8A16 decompression does not overlap compute | Use a PH1-supported decompression/TCE path and prefetch asynchronously |
| High synchronization share | Barrier/fence fixed cost is significant on small tiles | Reduce stages and synchronization points; use a graph to lower launch cost when appropriate |

Do not automatically call low decode occupancy a bug. Compare per-token end-to-end latency and the KV layout first.

### Element-wise kernels (ReLU, Add, Scale, Cast)

When each element is accessed once, local memory, WMMA, and SQMMA are unnecessary. Focus on coalesced access, vectorization, avoiding accidental FP64, fusing adjacent element-wise operations, and reducing host/kernel-launch synchronization.

### Reduction (Sum, Max, Softmax)

The later stages of a tree reduction reduce parallelism. Shuffle inside Wave32 first, reduce in local memory inside the block, and let a small number of blocks finish the cross-block merge. Softmax max, sum, and normalization must stay numerically stable. Do not remove synchronization by using unsafe precision or ordering.

### GEMM / matmul

Check, in order:

1. Whether SQMMA/WMMA matches the current data type, shape, and layout.
2. Whether TME moves A/B into local memory asynchronously.
3. Whether the squad/fence keeps the four waves cooperating.
4. Whether local memory, GPR, and stage count create a resource limit.
5. Whether the output epilogue writes results back to global/local memory repeatedly and too early.

`128x128x64` SQMMA is a common trial starting point in PH1 material, not the best value for every shape. Choose the final tile with the Moore Perf Compute report and an end-to-end benchmark.

### Convolution / implicit GEMM

PH1 TME supports IM2COL/TRANSPOSE.IM2COL modes and can perform part of the address calculation, padding, and layout conversion during the move. Check the tensor descriptor, convolution parameters, stride/dilation, OOB behavior, and TME transaction count. Do not apply the linear-address assumptions of ordinary GEMM directly to convolution boundaries.

### Scatter / gather / embedding lookup

Index-driven access usually cannot be fully coalesced. Sorting indexes, bucketing, caching repeated indexes, or batching can improve locality. If an address depends on the previous load, adding threads usually does not remove the fundamental latency. Use the measured LLC/L2 hit rate and end-to-end time to decide whether reordering the data is worth it.

### Communication kernels (MCCL, CE, P2P)

Cross-GPU synchronization, the CE queue, and MT Link bandwidth are first-class constraints. Verify topology, peer access, message size, stream overlap, and link bandwidth first. Do not replace communication-path analysis with a single MP/TCE metric. Do not manually delete atomics and fences already handled by MCCL without understanding the protocol.

---

## Checklist before writing a kernel

### PH1-specific

1. **Device and toolchain:** Record the actual GPU, driver, MUSA Toolkit, and mcc version. Confirm the architecture flag with the current `mcc --help`. Do not default to `mp_31`.
2. **Wave mode:** Is the current path Wave32 or compatibility Wave128? Is the block size a multiple of 32?
3. **TCE path:** Is this ordinary ALU, WMMA, or SQMMA? For SQMMA, are the four-wave squad, MPE mapping, A/B local-memory layout, and sync fence complete?
4. **TME descriptor:** Do the global dimensions/strides, descriptor, LMS address, swizzle, OOB behavior, and total transaction bytes satisfy the current FD?
5. **Async barrier:** Is the arrival count set from the producer warp count? Are the `arrive`/`wait` phase and buffer-reuse protocol consistent?
6. **Resource budget:** Do local memory, TME LMS, GPR, stage count, and block size leave enough blocks resident?
7. **Data type:** Do the inputs, accumulator, conversion, and accuracy requirements match for FP16/BF16/TF32/INT8/FP8 or W4A16/W8A16?
8. **Cache policy:** Is the access hot data or one-shot streaming data? Is TME bypass/persistence actually needed?
9. **Multi-GPU path:** If CE/MT Link is involved, is the topology and overlap confirmed instead of looking only at MP metrics?

### General guidelines

1. Does the grid cover the target MPs, and is the tail acceptable?
2. Are accesses inside a wave contiguous, aligned, and coalescable?
3. Is there data reuse? Introduce local memory only when there is reuse.
4. Is there actual evidence for local-memory banks and TME swizzle?
5. Are branches uniform per wave? Do boundary masks affect only the tail?
6. Are there register spills or an oversized live range?
7. Can global loads, TME, compute, and stores overlap?
8. Is there unnecessary host, stream, block, or fence synchronization?
9. Can atomics be pushed down to wave/block scope?
10. Have compiler resources, result correctness, and the benchmark all been verified?
11. Was `mcu --list-sections` run first, followed by collection of the sections supported by the installed version?
12. Was the full `--page details` read before citing specific values from `--page raw --csv`?

---

## How to verify details that change

This document is a self-contained programming guide. Architecture facts, SQMMA/WMMA/TME constraints, and the checklist are in the body and do not depend on external page links. Instructions, tile shapes, intrinsics, alignment requirements, and counter names follow the MUSA Toolkit, driver, FD, and current Moore Perf Compute report on the target machine. Do not treat an expired external page ID or an NVIDIA document link as the PH1 specification.

When current public MUSA documentation is needed, search the current Toolkit documentation at the time of use. Do not freeze a URL in this document. Collection flow, report CLI, and metric-name hints are in these repository-relative paths:

- [profiling-mt usage](../SKILL.md)
- [collection commands](reference/03-collection.md)
- [report CLI](reference/04-report-cli.md)
- [five analysis dimensions](reference/05-analysis-dimensions.md)
- [PH1 metric-name hints](reference/08-metric-names.md)

[`reference/08-metric-names.md`](reference/08-metric-names.md) is only a search starting point. The current `mcu --import <report>.mcu-rep --page raw --csv` is the authority.
