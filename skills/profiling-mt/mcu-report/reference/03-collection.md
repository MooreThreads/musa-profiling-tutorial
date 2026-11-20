# Profile Collection Commands

This document lists the exact `mcu` commands you should run, in what order, and what each flag does.

---

## Prerequisites recap

- `mcu` available on PATH.
- Writable `$HOME` so mcu can cache section files.
- Kernel name known; use the demangled name shown by the harness or profiler if unsure.

Quick permission test:
```bash
MCU_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ && $1 != "WarpStateStatistics" { print $1 }')"
QUICK_SECTION="$(printf '%s\n' "$MCU_SECTIONS" | sed -n '1p')"
test -n "$QUICK_SECTION" || { echo "mcu --list-sections returned no sections" >&2; exit 1; }
mcu --sections "$QUICK_SECTION" -k "regex:YOUR_KERNEL_NAME" -c 1 ./harness [args]
# If performance-counter permission is denied, see 09-common-issues.md.
# A table for the selected section plus a successful regex match means permissions and the basic invocation work.
```

---

## Recipe 1: Overview profile (first pass)

First discover the sections exposed by the installed mcu build, then collect all of them except `WarpStateStatistics`. This keeps the first run aligned with newer Moore Perf Compute versions.

```bash
MCU_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ && $1 != "WarpStateStatistics" { print $1 }' | paste -sd, -)"
test -n "$MCU_SECTIONS" || { echo "mcu --list-sections returned no sections" >&2; exit 1; }
mcu --sections "$MCU_SECTIONS" \
    -k "regex:KERNEL_REGEX" \
    -c 1 \
    -o $PROFILE_RUN_DIR/reports/full_<tag> \
    ./harness [args]
```

| Flag | Meaning |
|---|---|
| `mcu --list-sections` | Discover the section identifiers supported by the installed mcu build. |
| `--sections "$MCU_SECTIONS"` | Run every discovered section except `WarpStateStatistics`. |
| `-k "regex:..."` | Only profile kernels whose demangled name matches. Reduces replay count. |
| `-c 1` | Only profile the first matching kernel launch. Avoids duplicates when the kernel is called in a loop. |
| `-o $PROFILE_RUN_DIR/reports/full_<tag>` | Output path — `.mcu-rep` is appended automatically. |

Replay count depends on the selected sections and metrics. If iteration is slow, start with `SpeedOfLight,LaunchStats,MemoryWorkloadAnalysis` and add sections only for the missing question.

---

## Recipe 2: Details page (quick rule summary)

No need to collect again — just import an existing `full_<tag>.mcu-rep`:

```bash
mcu --import $PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep --page details > analysis/details_<tag>.txt
```

This produces Moore Perf Compute's human-readable details page. Read the complete output
before interpreting the raw metrics; use any diagnostic text it provides as
context, but cite the raw CSV for exact values.

---

## Recipe 3: Raw metric export

```bash
# Full metric table as CSV — one row per kernel launch, one column per metric
mcu --import $PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep --page raw --csv > analysis/raw_<tag>.csv
```

This is the default source for exact metric values. Use `details_<tag>.txt` for diagnostic context and `raw_<tag>.csv` for the numbers you cite in the final report.

---

## Recipe 4: Targeted metrics only (fast)

If you already know which metrics you want (e.g., you're re-running after a code change and only want to check if the fix worked), collect just those:

```bash
mcu --metrics \
    "gpu_time_duration.max,mp_throughput.avg.pct_of_peak_sustained_elapsed,mp_memory_throughput.avg.pct_of_peak_sustained_elapsed,gpu_compute_memory_throughput.avg.pct_of_peak_sustained_elapsed,dram_throughput.avg.pct_of_peak_sustained_elapsed,dram_bytes.sum.per_second,l1_sector_hit_rate.pct,l2pu_sector_hit_rate.pct,llc_sector_hit_rate.pct" \
  -k "regex:KERNEL_REGEX" -c 1 \
  ./harness [args]
```

Takes one or two replay passes. Prints a table directly to stdout. No `-o` output file.

---

## Recipe 5: A/B comparison (before vs after optimization)

```bash
# Discover the sections separately for the installed mcu build
MCU_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ && $1 != "WarpStateStatistics" { print $1 }' | paste -sd, -)"
test -n "$MCU_SECTIONS" || { echo "mcu --list-sections returned no sections" >&2; exit 1; }

# Before
mcu --sections "$MCU_SECTIONS" \
    -k "regex:my_kernel" -c 1 \
    -o $PROFILE_RUN_DIR/reports/v1 ./harness_v1 [args]

# After
mcu --sections "$MCU_SECTIONS" \
    -k "regex:my_kernel" -c 1 \
    -o $PROFILE_RUN_DIR/reports/v2 ./harness_v2 [args]
```

Then export the same CLI pages for each report and compare the CSVs:

```bash
for tag in v1 v2; do
    mcu --import "$PROFILE_RUN_DIR/reports/${tag}.mcu-rep" --page details \
        > "$PROFILE_RUN_DIR/analysis/details_${tag}.txt"
    mcu --import "$PROFILE_RUN_DIR/reports/${tag}.mcu-rep" --page raw --csv \
        > "$PROFILE_RUN_DIR/analysis/raw_${tag}.csv"
done

diff -u "$PROFILE_RUN_DIR/analysis/raw_v1.csv" \
        "$PROFILE_RUN_DIR/analysis/raw_v2.csv"
```

For repeated extraction and comparisons, use the optional `analyze_reports.py`
helper; it reads the same `details` and `raw --csv` pages.

---

## Available sections

```bash
mcu --list-sections       # section identifiers for --sections
```

`--list-groups` is not supported by every mcu version. mcu 1.4.0 on this host reports `unrecognised option`. Use it only after the current `mcu --help` explicitly lists the option. The main collection flow always discovers sections dynamically with `mcu --list-sections`.

The following sections were observed on the PH1 Ubuntu environment. This is an
example list only; always use the identifiers returned by `mcu --list-sections`
on the target host.

| Section | Default | Use when |
|---|---|---|
| `SpeedOfLight` | yes | First-pass throughput and duration |
| `LaunchStats` | yes | Grid/block metadata |
| `MemoryWorkloadAnalysis` | yes | DRAM, cache, and memory throughput |
| `MemoryWorkloadAnalysis_Chart` | no | Memory-workload charts, when supported |
| `MemoryWorkloadAnalysis_Tables` | no | Detailed memory-workload tables, when supported |
| `ComputeWorkloadAnalysis` | no | Compute-pipeline or tensor throughput questions |
| `SchedulerStats` | no | Scheduler and issue behavior |
| `InstructionStats` | no | Instruction mix and low-level instruction counters |

**Moore Perf Compute does not support the `WarpStateStatistics` section.** `mcu --list-sections` may still print it. Remove it before passing identifiers to `--sections`. Do not switch versions or take a detour to collect a warp-state/stall breakdown. Use only the `SchedulerStats` and raw CSV already present in the current report.

---

## Profiling multiple kernel launches

If the kernel is called multiple times and you want different iterations:

```bash
# Skip the first 5 invocations, then profile 3 consecutive launches
mcu -k "regex:my_kernel" -s 5 -c 3 -o report ./harness
```

`-s N` skips the first N matches. `-c N` limits to N matches. Useful for ignoring warmup or focusing on a steady-state iteration.

When comparing different kernels, prefer one report/tag per kernel with the same workload and device state. A broad regex such as `regex:kernel_a|kernel_b` may be useful for discovery, but it can make `-s`/`-c` selection and per-kernel replay behavior ambiguous; do not average unlike kernels into one diagnosis.

---

## Kernel-name matching and invocation context

Kernel names, option spellings, and supported launch controls vary by Moore Perf Compute version. Treat the installed CLI as the source of truth:

```bash
mcu --version
mcu --help > "$PROFILE_RUN_DIR/analysis/mcu-help.txt"
mcu --list-sections > "$PROFILE_RUN_DIR/analysis/mcu-sections.txt"
```

Start with the visible demangled kernel name and a narrow regex:

```bash
mcu -k 'regex:my_kernel' -c 1 -o "$PROFILE_RUN_DIR/reports/<tag>" ./app [args]
```

Some builds expose an exact-name mode or `--kernel-name-base` selector. Use those only when the current `mcu --help` documents them; do not copy an option from another release. If matching fails, run the workload once, obtain the kernel name from `msys`, the harness, or Moore Perf Compute output, and then narrow the regex.

Prefer shell primitives for environment and working-directory control because they do not depend on Moore Perf Compute option spelling:

```bash
(
  cd /actual/workdir
  env LD_LIBRARY_PATH="${MUSA_LIB_DIR}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    mcu -k 'regex:my_kernel' -c 1 \
        -o "$PROFILE_RUN_DIR/reports/<tag>" ./app [args]
)
```

For device selection, dump mode, replay mode, sampling interval/buffer size, or forced overwrite, first confirm the exact flag and accepted values in the installed `mcu --help`. Record every non-default option in `REPORT.md`. Never use forced overwrite to reuse a run directory.

## Multi-process and MPI workloads

First decide whether the target kernel runs in one rank or every rank. A profiler wrapped around `mpirun` may not follow child processes on every Moore Perf Compute/MPI combination, while profiling every rank can multiply replay cost and cause output collisions.

Preferred procedure:

1. Use `msys` or an unprofiled run to identify the rank that launches the target kernel.
2. Profile one representative rank when ranks execute equivalent work.
3. If multiple ranks must be profiled, launch one `mcu` per rank and give every rank a unique output path.
4. Verify the rank environment variable used by the installed MPI implementation; do not assume a Moore Perf Compute filename placeholder such as `%r` is supported.

Example wrapper for common MPI rank variables:

```bash
export PROFILE_RUN_DIR
mpirun -n 4 sh -c '
  rank=${OMPI_COMM_WORLD_RANK:-${PMI_RANK:-${PMIX_RANK:-}}}
  test -n "$rank" || { echo "cannot determine MPI rank" >&2; exit 1; }
  mkdir -p "$PROFILE_RUN_DIR/reports"
  mcu -k "regex:my_kernel" -c 1 \
      -o "$PROFILE_RUN_DIR/reports/rank_${rank}" \
      ./my_mpi_app [args]
'
```

The launcher and quoting may need adjustment for the target scheduler. Keep workload inputs and rank placement identical when comparing runs.

## Remote collection

Run Moore Perf Compute on the host that owns the target GPU, then copy the self-contained `.mcu-rep` and recorded environment metadata back for analysis. Do not assume the remote MUSA installation is under `/usr/local/musa`.

```bash
# On the remote host, discover and verify actual paths first.
ssh user@host 'command -v mcu; mcu --version; mthreads-gmi'

# Create a unique remote run, collect there, then retrieve it.
ssh user@host 'bash -s' <<'REMOTE'
set -e
RUN="$HOME/profile/<unique_run>"
mkdir -p "$RUN/reports" "$RUN/analysis"
command -v mcu > "$RUN/analysis/mcu-path.txt"
mcu --version > "$RUN/analysis/mcu-version.txt"
mthreads-gmi > "$RUN/analysis/device.txt"
# Set MUSA_LIB_DIR only if the remote application actually needs it.
# export LD_LIBRARY_PATH="$MUSA_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mcu -k 'regex:my_kernel' -c 1 -o "$RUN/reports/<tag>" /path/to/app [args]
REMOTE

scp -r user@host:'~/profile/<unique_run>' profile/
```

If the remote host already has a compatible Moore Perf Compute installation, use it. Copying an arbitrary local `mcu` binary can introduce driver, library, architecture, or section-file incompatibilities. Import the report locally only with a compatible Moore Perf Compute version; otherwise extract `details` and `raw --csv` on the remote host and copy those artifacts too.

## Optional GUI inspection

`mcu-ui` may be useful for a human to explore a report, Roofline view, session metadata, or Green Context resources when the installed product provides those views. It is optional and is not the evidence path for this skill. Preserve CLI `details` and `raw` artifacts so findings remain reproducible and reviewable without GUI access.

## GPU frequency locking (for reproducibility)

```bash
# Check current device state
mthreads-gmi

# If the target platform supports clock locking, use its documented
# mthreads-gmi command and restore the original setting after profiling.
```

For the target device this may be unnecessary when repeated runs already reach a stable state, but do not assume Moore Perf Compute always performs a fixed number of replays. Record the observed replay behavior and device state. If same-workload results remain jittery, use the target platform's documented clock controls and restore the original setting afterward.

---

## Gotchas

- **Profile run time blows up with many sections**: that's normal, each replay is a full kernel execution.
- **`regex:...` doesn't match anything**: verify the demangled kernel name shown by the harness or profiler. Templates produce names like `void my_kernel<(int)8, (int)256>(...)` — the regex needs to match this string.
- **Report file is empty / 0 KB**: profile terminated before the kernel launched. Usually means `-k` regex didn't match, or the harness crashed.
- **A section's metrics are missing from raw CSV**: check that the section was requested with `--sections` and that `mcu --list-sections` contains the identifier on the target host.
- **"Could not deploy stock section files to $HOME"**: set `HOME` to a writable directory first.
