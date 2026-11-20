# Profile Directory Layout & Naming

**Read this first, before any collection.** Bad directory layout is the single most common cause of mixing results from different runs, overwriting prior profiles, or losing track of which `.mcu-rep` belongs to which kernel version. The rules below are non-negotiable for work in this repo.

---

## Top-level rule

**All profiling artifacts live under a single `profile/` directory at the repo root of the project being profiled.** Never scatter `.mcu-rep` files across random locations. Never put profile artifacts under source, build, or dataset directories.

```
<project_root>/
├── profile/                        ← everything profiling-related lives here
│   ├── <run_1>/
│   ├── <run_2>/
│   └── ...
├── src/                            ← untouched by profiling
└── ...
```

---

## One run = one subdirectory

Every time you profile a kernel — whether it's a new kernel, a new version of the same kernel, or the same kernel on a different workload — **create a new subdirectory under `profile/`**. Never write into an existing run's directory.

Rationale:

- Profiles of different implementations of the same kernel must not overwrite each other. If you profile `<kernel>_v1` today and `<kernel>_v2` tomorrow, both reports need to coexist for A/B comparison.
- The harness itself is part of the profile: it encodes which kernel code was compiled, with which flags, against which workload. Keeping the harness source in the run dir pins the provenance.
- Analysis artifacts (`metrics_*.json`, `compare_*.txt`, ASCII plots) are tied to a specific set of `.mcu-rep` files; they must not be mixed.

---

## Run directory naming

Use descriptive, short, kebab-case names. Include **what** was profiled and **when/why**, not how.

Good:
```
profile/<kernel>_v1_baseline/
profile/<kernel>_v2_optimized/
profile/<kernel>_v2_optimized_vs_v1/      # for comparison run
profile/moe_fp8_v4_tma_prefetch/
profile/flash_attn_ph1_h128_baseline/
```

Bad:
```
profile/test/                   # too vague
profile/run1/                   # meaningless
profile/20260413/               # dates with no context
profile/final/                  # there's never a "final"
```

If you genuinely have multiple runs on the same day for the same kernel/version combo, append a short distinguisher or a date suffix: `<kernel>_v1_baseline_20260413_am` / `<kernel>_v1_baseline_20260413_pm`.

---

## Standard run layout

Inside each run subdirectory, use this structure:

```
profile/<run_name>/
├── REPORT.md                       ← human-readable final report (Markdown)
├── harness/
│   ├── <kernel>_harness.cu         ← the exact source that was compiled
│   ├── <kernel>_harness            ← compiled binary
│   └── build_command.sh            ← optional: shell script that compiled it
├── reports/
│   ├── full_<tag1>.mcu-rep         ← mcu --sections ... output
│   └── full_<tag2>.mcu-rep
└── analysis/
    ├── extract_commands.sh         ← optional: exact import/export commands used
    ├── metrics_all_<tag>.json      ← optional: archived raw CSV rows from helper
    ├── metrics_key_<tag>.{txt,json}← optional: curated key metrics from helper
    ├── compare_<a>_vs_<b>.txt      ← optional: side-by-side
    ├── details_<tag>.txt           ← required: mcu --import --page details
    └── raw_<tag>.csv               ← required: mcu --import --page raw --csv
```

Notes:

- `<tag>` is the per-workload / per-dispatch-path label, e.g. `path_a_shapeA`, `path_b_shapeB`. Pick tags that are short and name the representative workload, not the file UUID.
- If you profile only one tag, you can omit the tag suffix from filenames. But as soon as you profile a second, backfill the tag to avoid ambiguity.
- Keep the exact extraction commands in `analysis/extract_commands.sh` or the report's reproduction section. If you use helper scripts, record their path and command line.

---

## Comparing two runs

For A/B comparisons (optimization-before vs after, or two dispatch variants on the same build), create a comparison run that *references* both underlying runs:

```
profile/<kernel>_v2_vs_v1/
├── REPORT.md                       ← describes both runs + the comparison
└── analysis/
    ├── compare.py                  ← loads reports from the two runs below
    └── compare_key_metrics.txt     ← side-by-side on key metrics
    (No mcu-rep files — they live in the referenced runs)
```

In `compare.py`, hardcode the paths to both referenced runs:
```python
V1_DIR = Path("/abs/path/to/profile/<kernel>_v1_baseline")
V2_DIR = Path("/abs/path/to/profile/<kernel>_v2_optimized")
```

The comparison run does not re-profile; it only produces comparison artifacts and prose.

---

## What does NOT go in a run directory

- `.mcu-rep.old` backup files — if you need a prior version, you should have made it a separate run.
- Temporary scratch files — `/tmp` is for those.
- The dataset / workload files themselves — keep them in a shared dataset directory and reference them by absolute path in scripts. Do not copy large tensors into the run dir.
- Compiler intermediates (`*.o`, `*.d`). Put them under `harness/build/` or just rely on rebuilding from source.
- `mcu_home/` or mcu cache directories — delete these after profiling, they're huge and regenerable. Set `HOME=$HOME` before running mcu rather than letting it cache inside the run dir.

Add a simple `.gitignore` inside `profile/` if you want to keep the run dirs out of git:
```
profile/*/
!profile/README.md
```

Or, if you want a few canonical runs tracked in git, `.gitignore` only the data-heavy subdirs:
```
profile/*/reports/
profile/*/analysis/metrics_all_*.json
profile/*/analysis/raw_*.csv
profile/*/harness/*_harness          # binary only, keep the .cu
```

---

## Environment variable convention (optional but recommended)

Scripts and mcu invocations should pick up the run directory from a single env var, so they're easy to redirect to different runs:

```bash
export PROFILE_RUN_DIR=/abs/path/to/profile/<kernel>_v1_baseline
mkdir -p "$PROFILE_RUN_DIR"/{harness,reports,analysis}

# build harness
mcc -o "$PROFILE_RUN_DIR/harness/kernel_harness" \
    -std=c++17 -mtgpu -O2 --cuda-gpu-arch=<target-arch> -lmusart \
    harness.cu

# discover every section, then exclude unsupported WarpStateStatistics
MCU_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ && $1 != "WarpStateStatistics" { print $1 }' | paste -sd, -)"
test -n "$MCU_SECTIONS" || { echo "mcu --list-sections returned no sections" >&2; exit 1; }
mcu --sections "$MCU_SECTIONS" \
    -k "regex:my_kernel" -c 1 \
    -o "$PROFILE_RUN_DIR/reports/full_<tag>" \
    "$PROFILE_RUN_DIR/harness/kernel_harness" [args]

# extract report pages
mcu --import "$PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep" --page details \
  > "$PROFILE_RUN_DIR/analysis/details_<tag>.txt"
mcu --import "$PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep" --page raw --csv \
  > "$PROFILE_RUN_DIR/analysis/raw_<tag>.csv"
```

The helper scripts in `../helpers/` can generate the same artifacts, but the canonical source remains the imported `details` and `raw` pages.

---

## Checklist before starting a profile run

1. `mkdir -p profile/<new_run_name>/{harness,reports,analysis}` — make the three subdirs up front.
2. Copy or write the harness source into `profile/<new_run_name>/harness/`.
3. Compile into the same dir.
4. Run mcu with `-o profile/<new_run_name>/reports/full_<tag>`.
5. Put analysis scripts under `profile/<new_run_name>/analysis/`.
6. Write `REPORT.md` at `profile/<new_run_name>/REPORT.md`.
7. Before starting a *new* run, go back to step 1 with a new name — never write into the existing one.
