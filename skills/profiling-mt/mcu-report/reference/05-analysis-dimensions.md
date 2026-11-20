# Five Analysis Dimensions

Every kernel profile report is ambiguous until you look at it through specific lenses. These five dimensions are the ones that consistently matter. Walk through all five; don't stop at the first finding.

Moore Perf Compute does not support `WarpStateStatistics`, so there is no instruction-level stall-analysis dimension. Do not collect that section, and do not infer a specific stall reason from other metrics.

For each dimension this doc describes:

- **What you're answering**
- **Which metrics to read** (candidate names; verify them on the target device)
- **How to read them** (what's "normal", what's "bad")
- **Which CLI page to read and which optional `helpers/` to run**

---

## Dimension 1 — MP occupancy & launch geometry

**What:** is the grid large enough to fill the GPU's MPs? Is occupancy being limited by registers, local/shared memory, or block-size constraints?

**Metrics:**
```
# Raw CSV metadata
Grid Size
Block Size
Kernel Name
Device

# Aggregate timing / activity
gpu_time_duration.max
mp_cycles_active.max
mp_cycles_elapsed.max
```

**Reading:**

- Read `Grid Size` and `Block Size` from the raw CSV; do not invent `launch__*` metric names.
- Use the details page for any launch and occupancy diagnostics. If it reports a small grid or an occupancy limiter, cite that output together with the supporting raw CSV values.
- Use `mp_cycles_active.max` versus `mp_cycles_elapsed.max` only when both are present. A large gap is evidence of inactive cycles, but it does not identify the cause by itself; continue with the memory dimension.

**Optional helper:** `analyze_reports.py` prints all the key launch metrics under "Launch geometry" in the output txt.

**Resource partitions / Green Contexts:** if the details or optional session metadata says the workload ran in a Green Context, record the context/resource identifiers and assigned MP resources. Compare launch geometry and utilization with that allocation rather than automatically using the full physical GPU. A GUI color/state is not sufficient evidence; if allocation metadata is unavailable, state that the result cannot be normalized confidently.

---

## Dimension 2 — Thread-block balance (tail effect)

**What:** are blocks finishing at roughly the same time, or do a few outliers drag out the kernel?

**Metrics:**

There is no single "imbalance" metric — use these signals together:

```
# Aggregate activity, if present in the raw CSV
mp_cycles_active.max
mp_cycles_elapsed.max

# Optional per-instance metrics
# Discover exact names only after collecting the relevant section.
```

**Reading:**

- Moore Perf Compute's `details` page may report active-cycle or partial-wave imbalance. Treat that output as the primary evidence.
- If the report contains per-instance values, an optional timeline can show:
  - **Flat high → clean drop**: ideal. Well-balanced, good MP fill.
  - **Flat high → gradual tail**: tail effect. The tail's length is how much time a few slow blocks waste. Usually caused by variable-length inputs (e.g. seq_len varies per batch element).
  - **Flat low**: grid is too small (Dimension 1).
  - **Periodic waves / sawtooth**: pipeline bubbles — compute and memory alternate, nothing overlaps.

**Where imbalance typically comes from:**

1. **Variable-length per-CTA work**: when each CTA's iteration count depends on an input axis (e.g., per-element lengths driven by a prefix-sum / cumulative-length array), CTAs take very different times.
2. **Branch-and-early-exit inside the kernel**: some blocks bail early via `return`, others don't.
3. **Work-stealing without proper load balancing**: custom scheduling logic that happens to assign heavy work to a few blocks.

**Fix direction:** chunk the variable-length work (e.g., time-chunking for sequence-style workloads), or oversubscribe with work-stealing.

Per-instance data is optional. The standard workflow uses the details page and raw CSV only.

Additionally, **always inspect the input distribution**. If per-CTA work is driven by an array like `per_element_lengths`:
```python
# Example: given a per-CTA work-count array, compute imbalance ratios
work_per_cta = [...]  # derive this from whatever drives the inner loop count
avg = sum(work_per_cta) / len(work_per_cta)
print(f"max/avg = {max(work_per_cta)/avg:.2f}x, max/min = {max(work_per_cta)/min(work_per_cta):.2f}x")
```

Ratios > 5x indicate significant potential for tail effect.

---

## Dimension 3 — Tensor Core utilization

**What:** is the kernel using tensor cores at all? If yes, how well?

**Metrics:**
```
mp_fp32_throughput.avg.per_second
mp_fp32_peak_throughput.sum
mp_tc_fp32_throughput.avg.per_second
mp_tc_fp32_peak_throughput.sum
mp_fp64_throughput.avg.per_second
```

**Reading:**

- Compare `mp_tc_fp32_throughput.avg.per_second` with its peak reference when both are present.
- If the tensor-throughput metric is absent or zero, do not infer that the kernel cannot use tensor operations; first check whether the corresponding compute section was collected.

**Architecture-specific note:** tensor-core instructions, memory staging features, and their programming interfaces vary by target architecture. Use the documented PH1 instructions or a tuned MUSA library for the target device instead of assuming another GPU generation's instruction set.

**Fix direction:** if tensor throughput is absent or near zero and the workload is matrix-multiplication-shaped, redesign around SQMMA/WMMA or a PH1-tuned library. This is usually a major refactor but can give large gains on compute-bound paths.

---

## Dimension 4 — MP utilization timeline

**What:** how does MP utilization vary over the kernel's lifetime?

**Metrics (aggregate; optional timeline only when available):**
```
mp_throughput.avg.pct_of_peak_sustained_elapsed
dram_throughput.avg.pct_of_peak_sustained_elapsed
mp_cycles_active.max
mp_cycles_elapsed.max
```

**Reading (timeline shapes):**

- **Flat high, clean drop**: ideal.
- **Flat high, long tail**: tail effect (Dimension 2).
- **Flat low**: grid too small (Dimension 1). Moore Perf Compute does not support `WarpStateStatistics`; do not add an instruction-level stall analysis.
- **Periodic sawtooth (compute ↕ memory)**: no compute-memory overlap — missing pipeline/double-buffering.
- **Slow ramp up, flat middle, clean drop**: kernel has warmup work (prologue), then steady state. Usually fine.

Per-instance timeline data is optional. The standard report still consists of the details page and raw CSV.

**Note:** PM sampling interval depends on the target device, driver, and Moore Perf Compute version. Very short kernels (< 20 µs) produce few samples — interpret with care.

---

## Dimension 5 — Memory access pattern & cache efficiency

**What:** are global loads coalesced? Are caches hit? Is DRAM actually busy?

**Metrics:**
```
# DRAM
dram_bytes.sum.per_second
dram_throughput.avg.pct_of_peak_sustained_elapsed
dram_throughput.avg.per_second
dram_peak_bandwidth.avg

# Cache hierarchy
l1_sector_hit_rate.pct
l1_throughput.avg.pct_of_peak_sustained_active
l2pu_sector_hit_rate.pct
l2pu_throughput.avg.pct_of_peak_sustained_elapsed
llc_sector_hit_rate.pct
llc_throughput.avg.pct_of_peak_sustained_elapsed

# General memory pressure
gpu_compute_memory_throughput.avg.pct_of_peak_sustained_elapsed
gpu_compute_memory_access_throughput.avg.pct_of_peak_sustained_elapsed
```

**Reading:**

- **High `dram_throughput.avg.pct_of_peak_sustained_elapsed`**: the kernel may be DRAM-bandwidth-bound; confirm against a tuned PH1 baseline.
- Do not use universal cutoffs such as “occupancy > 70%” or “bandwidth > 80%” to classify a kernel. Thresholds depend on the workload, device, resource partition, collected section, and metric semantics.
- A Roofline position alone does not prove memory-bound or compute-bound behavior. Corroborate it with the exact MP/DRAM throughput, launch geometry, cache/memory evidence, and a same-workload baseline. Moore Perf Compute does not support `WarpStateStatistics`; do not use a stall breakdown as supporting evidence.
- **Low DRAM and low `mp_throughput.avg.pct_of_peak_sustained_elapsed`**: the kernel is under-utilized or latency-bound; continue with the details page and optional scheduler sections.
- **Low cache hit rate**: investigate reuse and access layout, but do not apply a fixed threshold without a workload baseline.
- Store efficiency, instruction mix, and register-spill evidence are optional. Collect `InstructionStats` and cite only the exact metrics that appear in the raw CSV.

Moore Perf Compute's details output may report the coalescing issue directly:
```
The output may describe that the memory access pattern for global loads is
not optimal. Preserve that text and support it with the exact utilization and
unit values from the raw CSV.
```

**Fix directions (by pattern):**

- Strided access (e.g. `x[lane * stride + i]`): change the per-thread layout so lanes access contiguous elements.
- AoS → SoA: restructure the data.
- Sparse writes: pack writes into a single coalesced store at the end of the wave.
- Register spill: add `__launch_bounds__` (supported by MUSA), reduce intermediate variables, or split the kernel.

---

## Cross-dimension synthesis

After walking through all five, write a one-line diagnosis combining them. Structure: name the top 3–4 signals, each tied to a specific dimension. For example:

> "The kernel reaches X% MP throughput and Y% DRAM throughput (Dims 1, 5). Cache hit rates are `<values>` (Dim 5). Active versus elapsed cycles are `<values>` (Dims 1, 2), and tensor throughput is `<value>` when the compute metrics are present (Dim 3). Do not infer an instruction-level stall reason; Moore Perf Compute does not support `WarpStateStatistics`."

Fill in the X/Y/Z/W values and <classifications> from your own report. That sentence is the deliverable. Everything else in the report is evidence backing it.
