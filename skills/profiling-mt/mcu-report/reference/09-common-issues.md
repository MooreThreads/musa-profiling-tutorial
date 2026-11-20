# Common Issues & Gotchas

Collected solutions for the recurring frustrations of profiling MUSA kernels.

---

## mcu permissions

### Performance-counter permission error

Two solutions:

**A) Use sudo (simplest on dedicated servers):**
```bash
sudo mcu [...]
```

**B) Make it persistent (preferred on shared servers):** configure the
MUSA driver according to the target host's profiling-permission documentation,
then reboot if the driver requires it.

### `Could not deploy stock section files to the user cache directory`

Set `HOME` to a writable directory:
```bash
export HOME=/any/writable/path
mcu [...]
```

This warning is harmless but noisy. mcu falls back to reading from the MUSA install dir.

---

## `-k "regex:..."` matches nothing

1. **Use the demangled name.** Templates produce something like `void my_kernel<(int)8, (int)256>(...)`. Check:
   ```bash
   # Use the demangled kernel name shown by the harness or profiler.
   ```
   Match against the visible string.
2. **Escape regex metacharacters.** `<` and `>` don't need escaping in most regex flavors, but be careful with parentheses.
3. **The kernel might not have been launched.** Run the harness without mcu and confirm the kernel actually runs.

---

## PM sampling returns nothing

1. **The current Moore Perf Compute build may not expose PM-sampling sections.** Check `mcu --list-sections` before assuming timeline data exists.
2. **vGPU / virtualized environments may not support sampling.** Use metric-based analysis only.
3. **Kernel too short.** Kernels under ~20 µs produce few samples even when sampling exists; what comes back is dominated by warmup noise.
4. **The report did not collect per-instance timeline metrics.** Do not make timeline plots a required artifact; use `details` and `raw --csv` instead.

---

## mcu takes forever to finish

1. **Many `--sections` need multiple replay passes.** That's normal — each pass reruns the kernel for a different metric group. If your kernel takes 3 ms, a multi-section profile can take much longer. Mitigation: profile a smaller representative workload if possible.
2. **Kernel launches aren't isolated.** If your binary does other expensive work (data loading, MUSA context init) before every kernel launch, that runs on every replay too. Move it outside the profile window (mcu only profiles kernel launches matching `-k`).
3. **Don't profile a debug device build.** Moore Perf Compute source correlation uses `mcc -g -gD`; that is for importing source into a report, not for performance numbers. For timing, keep `-O2`/`-O3` and omit device debug flags such as `-gD` and `--cuda-noopt-device-debug`.

---

## Kernel crashes / produces NaN only under mcu

1. **Profiler clock jitter.** Between replays, mcu resets GPU state. Kernels that depend on specific uninitialized values (bad practice) can behave differently. Fix: initialize all inputs.
2. **Out-of-order pre-replay memory**: mcu saves/restores GPU memory between replays but that can expose latent bugs like reading uninitialized global memory.

---

## Metric is missing from raw output

1. **Wrong metric name.** See `08-metric-names.md`. Many stock docs use names that do not exist on PH1.
2. **Metric not in the collected sections.** Add the relevant `--sections` value or targeted `--metrics`.
3. **Value is legitimately missing.** Some metrics (like tensor pipe counters) return 0 when the feature wasn't used; others are absent for hardware or section reasons.

Always verify against the actual report:

```bash
mcu --import "$REPORT" --page raw --csv > raw.csv
grep -i '<metric-fragment>' raw.csv
```

If the metric is not present, do not cite it in the report.

---

## TVM-FFI specific

### "I can't profile my kernel, it's built by `tvm_ffi.cpp.build`"

- Locate the cached `.so` and `kernel.cu`:
  ```
  ~/.cache/flashinfer_bench/cache/tvm_ffi/<solution_hash>/
  ```
- You'll see `build.ninja` with the mcc invocation for the generated kernel.
- **Workaround:** build a standalone harness from the cached `kernel.cu` (see `02-harness-guide.md`).

### "The Python benchmarking script runs but mcu sees no matching kernel"

`-k "regex:..."` must match the demangled name. TVM-FFI wraps kernels in `__global__ void kernel(...)` with a fixed name — obtain that name from the harness or profiler output.

---

## PyTorch specific

### Profiling a PyTorch model's kernel

1. Identify the kernel. Use `torch.profiler` to name it, or look for the generated kernel from `torch.compile`.
2. The kernel is often auto-generated (Triton-MUSA, MUTLASS, muDNN). For Triton kernels specifically, Triton recompiles between runs and the kernel name changes. Profile a single script invocation.
3. For `torch.compile`-generated Triton, inspect `TORCH_LOGS=+dynamo` or `TORCH_COMPILE_DEBUG=1` to see the emitted code.

### Profiling MUSA Graph-captured kernels

mcu handles MUSA Graph launches fine — each captured kernel shows up as a separate "kernel launch". Use `-k` regex + `-c N` to target.

---

## Reproducibility

### Results jitter between runs

1. **Record device state:** use `mthreads-gmi` before and after profiling. If
   the target platform supports clock locking, use its documented command and
   restore the original setting.
2. **Pin the MUSA stream** explicitly rather than relying on default stream.

### Reports don't match colleague's results

- Check mcu version (`mcu --version`). Metric names change between major versions.
- Check GPU driver version (`mthreads-gmi`). Some metrics only exist on certain drivers.
- Check the exact mcc invocation and target architecture.

---

## Output interpretation

### "`mp_throughput = X%`, is that good?"

It depends on the kernel type:
- GEMM / matmul: compare against a tuned PH1 baseline. Do not reuse thresholds from another GPU generation.
- Element-wise / reduction: usually 10-30%, because they're DRAM-BW-bound.
- Attention / recurrence kernels: varies wildly; compare against a reference implementation.

Always check Speed-of-Light alongside: `dram_throughput.avg.pct_of_peak_sustained_elapsed`. If DRAM is saturated, low MP throughput is expected and OK. If DRAM is idle and MP throughput is also low, you're under-utilized or latency-bound.
