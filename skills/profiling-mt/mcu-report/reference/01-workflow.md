# Profiling Workflow — End-to-End

This is the complete checklist from "user asks to profile" to "final report". Every step has a short rationale and a pointer to the detailed doc.

---

## Phase 0 — Create a new run directory

**Always start here.** See [`00-directory-layout.md`](00-directory-layout.md) for the full convention.

```bash
# At the repo root
PROFILE_RUN_DIR=profile/<descriptive_run_name>        # e.g. <kernel>_v1_baseline
mkdir -p "$PROFILE_RUN_DIR"/{harness,reports,analysis}
```

- Pick a new, descriptive name for this run. Never reuse an existing directory.
- If you're profiling a new version of a kernel you've profiled before, that's a **new** run (e.g. `<kernel>_v2_optimized/`, not overwriting `<kernel>_v1_baseline/`).
- If you're profiling the same version against a different workload, that's also a new run — or, at minimum, each workload's `.mcu-rep` gets a distinct tag and the analysis scripts are kept separate.

Every artifact produced in subsequent phases is written **only** under `$PROFILE_RUN_DIR`. Never into a sibling run's directory.

---

## Phase 0.5 — Frame the problem (before any tools)

Before typing any commands, answer these in your head (or in a short note to the user):

1. **What kernel(s) am I profiling?** Get the exact kernel name or regex. Kernels are often templated (`foo_kernel<8, 256>`) and mcu's `-k "regex:..."` needs to match the *demangled* name.
2. **Which workload / input shape?** If the kernel takes variable-sized inputs, pick a **specific** real workload — don't invent shapes. If the user has multiple representative shapes, profile the hottest one first; profile others only if the first reveals nothing.
3. **Which dispatch path?** Many production kernels branch on input shape or other runtime values to pick different grid configs or template instantiations. Profile each *active* dispatch path separately — treating them as one kernel will average out the real patterns.
4. **What question am I answering?** "Why is this slow?" is too vague. Better: "At shape X, is the kernel latency-bound or bandwidth-bound?" or "We spent 2 weeks on optimization Y — did it actually help?"
5. **What is the baseline?** If there's a reference implementation (torch_musa, muBLAS, a previous version), profile it too for comparison.

If any of 1-4 are unclear, **ask the user** before profiling. Profiling the wrong thing wastes an hour.

---

## Phase 1 — Environment check

```bash
# 1. mcu CLI is available
mcu --version   # confirm the installed Moore Perf Compute version

# 2. GPU is visible
mthreads-gmi      # confirm the GPU model and driver version

# 3. MUSA compiler and runtime library paths
MCC_BIN="${MCC_BIN:-$(command -v mcc || true)}"
# If mcc is not on PATH, set MCC_BIN to the target machine's actual install.
# Example from one S5000/PH100 host:
# MCC_BIN=/usr/local/musa/bin/mcc
test -n "$MCC_BIN" || { echo "Set MCC_BIN to the target machine's mcc path" >&2; exit 1; }
# Example from the same host; set this only when it matches the target:
# MUSA_LIB_DIR=/usr/local/musa/lib
test -n "${MUSA_LIB_DIR:-}" || { echo "Set MUSA_LIB_DIR to the target machine's MUSA lib path" >&2; exit 1; }
test -d "$MUSA_LIB_DIR" || { echo "MUSA_LIB_DIR does not exist; set the target machine's actual path" >&2; exit 1; }
export PATH="$(dirname "$MCC_BIN"):$PATH"
export LD_LIBRARY_PATH="$MUSA_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$MCC_BIN" --version  # MUSA SDK used to compile the harness

# 4. Permissions. On a clean server, mcu usually works without sudo. If
#    performance-counter access is denied, see 09-common-issues.md.
```

The `/usr/local/musa/bin` and `/usr/local/musa/lib` paths above are examples from one S5000/PH100 host. Do not treat them as defaults for every machine. Before compiling or running a harness, confirm that `MCC_BIN` and `MUSA_LIB_DIR` point at the current target, and keep `LD_LIBRARY_PATH` set at runtime.

Confirm the target architecture from the actual device, then match it to a flag the compiler accepts. On this host, `musaInfo` reported compute capability 3.1 and the build used `mp_31`. `mcc --help` only confirms accepted flags; it cannot infer the target architecture by itself:

```bash
musaInfo                         # read the current device's compute capability
"$MCC_BIN" --help | grep -n -- '--cuda-gpu-arch'
```

Also set a writable `HOME` before running mcu to silence the "Could not deploy stock section files" warning:
```bash
export HOME=/some/writable/dir   # or just use your normal $HOME
```

---

## Phase 2 — Build a profile target

**Option A (preferred): standalone harness.** Build a small C++ driver that launches your kernel directly. See [`02-harness-guide.md`](02-harness-guide.md). This is the right choice when:

- The kernel lives inside a JIT/template build system (TVM-FFI, PyTorch inline, Triton-MUSA, MUTLASS) where isolation or input control is difficult.
- You want fast iteration — the harness compiles in < 5 seconds, vs minutes for rebuilding the whole framework.
- You want precise control over inputs (e.g., load specific workload tensors from the dataset).

**Option B: profile through existing binary.** Skip the harness if:

- You *need* to profile in-context (e.g., kernel interacts with other kernels, host-side CPU work matters).

---

## Phase 3 — Collect profiles

Run an mcu invocation — the output goes under `$PROFILE_RUN_DIR/reports/`. Details in [`03-collection.md`](03-collection.md).

```bash
# (1) Overview — collect every discovered section except WarpStateStatistics
MCU_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ && $1 != "WarpStateStatistics" { print $1 }' | paste -sd, -)"
test -n "$MCU_SECTIONS" || { echo "mcu --list-sections returned no sections" >&2; exit 1; }
mcu --sections "$MCU_SECTIONS" \
    -k "regex:YOUR_KERNEL_NAME" \
    -c 1 \
    -o "$PROFILE_RUN_DIR/reports/full_<tag>" \
    "$PROFILE_RUN_DIR/harness/your_harness" [args]

```

Run once per (kernel, dispatch path, representative workload) combination.

Each multi-section run may replay the workload several times. Plan your time budget, and reduce sections or metrics when iterating quickly.

---

## Phase 4 — Read report pages and extract evidence

Do not diagnose from the live profiling console output. Re-open the saved
report with Moore Perf Compute's CLI pages: read `details` first for diagnostic context, then use
`raw --csv` for exact collected metric values. The standard workflow uses only
Moore Perf Compute's CLI pages. See
[`04-report-cli.md`](04-report-cli.md).

```bash
REPORT="$PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep"
ANALYSIS_DIR="$PROFILE_RUN_DIR/analysis"
mkdir -p "$ANALYSIS_DIR"

mcu --import "$REPORT" --page details \
    > "$ANALYSIS_DIR/details_<tag>.txt"
mcu --import "$REPORT" --page raw --csv \
    > "$ANALYSIS_DIR/raw_<tag>.csv"
```

The optional `analyze_reports.py` helper uses these same CLI pages for repeated
extraction and comparisons. The CLI pages remain the source of truth.

Minimum analysis artifacts to produce:

| Artifact | Tool | What it tells you |
|---|---|---|
| `details_<tag>.txt` | `mcu --import ... --page details` | Moore Perf Compute's details output and any diagnostic information it provides |
| `raw_<tag>.csv` | `mcu --import ... --page raw --csv` | All collected metric values in CSV form |
| `metrics_key_<tag>.txt` | optional `analyze_reports.py` | First value for every metric present in the raw CSV |
| `metrics_all_<tag>.json` | optional `analyze_reports.py` | Full metric archive for later programmatic analysis |
| `compare_<a>_vs_<b>.txt` | optional `analyze_reports.py` | Side-by-side metric comparison between workloads / versions |

Save everything under `$PROFILE_RUN_DIR/analysis/`. The user will want to re-inspect these; if two runs mix artifacts, you've already failed.

---

## Phase 5 — Diagnose

Work through the five analysis dimensions — see [`05-analysis-dimensions.md`](05-analysis-dimensions.md). Moore Perf Compute does not support `WarpStateStatistics`. Do not perform instruction-level stall analysis, and do not collect extra data for it.

1. **Launch geometry** — are enough blocks launched to fill the MPs? Does the details page report an occupancy limiter?
2. **Thread-block balance (tail effect)** — do active-cycle signals or details-page rules show imbalance?
3. **Tensor Core utilization** — if this is a GEMM-ish kernel, are the PH1 tensor-throughput metrics present and significant?
4. **MP/DRAM utilization** — compare aggregate MP and DRAM throughput; inspect per-instance data only when the report provides it.
5. **Memory access pattern** — cache hit rates, memory throughput, and any exact instruction metrics present in the raw CSV.

For each dimension, write down the observed signal *and the specific metric value* that produced it. "Kernel is memory bound" is useless; something like "`dram_throughput.avg.pct_of_peak_sustained_elapsed = X%` and `mp_throughput.avg.pct_of_peak_sustained_elapsed = Y%` shows whether the kernel is bandwidth-bound or generally under-utilized. Fill in X and Y from your own report.

Then consult [`06-diagnosis-playbook.md`](06-diagnosis-playbook.md) which maps observed patterns to likely causes and concrete fixes.

---

## Phase 6 — Write the report

Structure described in [`07-report-template.md`](07-report-template.md). Key elements:

1. **Setup section**: exactly how you profiled (harness path, workloads, mcu commands, metric-name caveats). Required for reproducibility.
2. **Headline numbers**: duration, MP throughput, DRAM throughput, grid/block metadata, and optional tensor throughput. A table on the first page.
3. **Per-dimension analysis** with evidence (metric values + relevant details output).
4. **Optimization directions** ranked by the observed metrics and the strength of the evidence.
5. **Confidence & caveats**.

Keep the report short enough that a busy reader can see the top 3 findings in 30 seconds. Put deep detail in the artifacts, not the prose.

---

## Anti-patterns to avoid

- ❌ **"I ran mcu and it says memory throughput is 14%"** — without naming the metric, workload, and kernel, this is un-actionable. Always give metric + value + what it means.
- ❌ **Profiling with synthetic shapes that don't match real workloads.** A uniform-element batch is a very different problem than a batch with highly skewed per-element work (the latter exposes tail effects the former hides). If the production workload has imbalance, you must profile on an imbalanced workload.
- ❌ **Dumping the full Moore Perf Compute CLI output into the report.** It's noisy, narrow-formatted, and has no interpretation. Extract the numbers, cite the source, add your reading.
- ❌ **Proposing optimizations without evidence.** "Maybe we should use shared memory" is not a profiling result. A real proposal cites exact raw CSV values, any relevant details output, and the mechanism of the fix — e.g. cache hit rates are below the same-workload baseline and the details page reports inefficient global loads; reshaping the per-thread index from stride-K to contiguous should improve locality.
- ❌ **Missing the #1 finding because you got distracted by a smaller one.** Rank findings by impact. Tail effects and MP idle time often dwarf coalescing issues; fix the big one first.
