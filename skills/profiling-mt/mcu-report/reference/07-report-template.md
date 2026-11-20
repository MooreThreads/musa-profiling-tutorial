# Final Report Template

The report is the deliverable. Everything else (`.mcu-rep`, imported details pages, and raw CSVs) is evidence. Structure matters: a busy reader should see the top findings in 30 seconds and be able to drill into details if they want.

Save as `$PROFILE_RUN_DIR/REPORT.md`.

---

## Template

```markdown
# `<kernel_name>` Profiling Report

**Kernel:** `<exact kernel name or template instantiation>`
**Target GPU:** PH1 architecture (record the exact device and reported MP count)
**Moore Perf Compute:** 2026.x.x
**Compile flags:** `mcc -o harness -std=c++17 -mtgpu -O2 --cuda-gpu-arch=<target-arch> -lmusart`
**Profile date:** YYYY-MM-DD
**Run directory:** `profile/<run_name>/`

---

## 0. Profiling setup

> How exactly did we get these numbers? Required for reproducibility.

- Harness: `profile/<run_name>/harness/*.cu` — what it is (standalone driver / the original binary / something else). Why.
- Workloads: which real tensors / shapes were used. Cite the workload UUID or shape tuple.
- Dispatch paths covered: list each `(SF / template params, grid, block)` combination profiled.
- Metric-name caveats: any metric names that differ from stock Moore Perf Compute docs; verify them against the PH1 report.

Minimal runnable command listing:

    # Compile
    mcc -o harness -std=c++17 -mtgpu -O2 --cuda-gpu-arch=<target-arch> -lmusart harness.cu

    # Discover every section, then exclude unsupported WarpStateStatistics
    MCU_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ && $1 != "WarpStateStatistics" { print $1 }' | paste -sd, -)"
    test -n "$MCU_SECTIONS" || { echo "mcu --list-sections returned no sections" >&2; exit 1; }
    mcu --sections "$MCU_SECTIONS" \
        -k "regex:<kernel_regex>" -c 1 \
        -o profile/<run_name>/reports/full_<tag> \
        profile/<run_name>/harness/harness [args]

    # Extract report data
    mcu --import profile/<run_name>/reports/full_<tag>.mcu-rep --page details \
        > profile/<run_name>/analysis/details_<tag>.txt
    mcu --import profile/<run_name>/reports/full_<tag>.mcu-rep --page raw --csv \
        > profile/<run_name>/analysis/raw_<tag>.csv

### Artifacts

    profile/<run_name>/
    ├── REPORT.md                       ← this file
    ├── harness/...                     ← standalone harness
    ├── reports/                        ← raw .mcu-rep files (re-openable with mcu)
    └── analysis/                       ← details/raw exports + extracted metrics

---

## 1. Headline numbers

> A single table that tells the whole story at a glance.

| Metric | `<tag1>` | `<tag2>` | Source |
|---|---:|---:|---|
| **Duration** | X µs | Y µs | `gpu_time_duration.max` |
| MP throughput (% peak) | X% | Y% | `mp_throughput.avg.pct_of_peak_sustained_elapsed` |
| Memory throughput (% peak) | X% | Y% | `gpu_compute_memory_throughput.avg.pct_of_peak_sustained_elapsed` |
| DRAM throughput (% peak) | X% | Y% | `dram_throughput.avg.pct_of_peak_sustained_elapsed` |
| DRAM bandwidth | X GB/s | Y GB/s | `dram_bytes.sum.per_second` |
| L1 hit rate | X% | Y% | `l1_sector_hit_rate.pct` |
| L2PU hit rate | X% | Y% | `l2pu_sector_hit_rate.pct` |
| LLC hit rate | X% | Y% | `llc_sector_hit_rate.pct` |
| Tensor/TC throughput | X | Y | `mp_tc_*` metrics if present |
| Grid / Block size | X / Y | ... | raw CSV `Grid Size` / `Block Size` columns |

**One-line read:** <"The kernel reaches X% MP throughput while DRAM throughput is Y%; the details page points to Z."> — this is the punchline.

---

## 2. Per-dimension analysis

> Walk through the five analysis dimensions, cite metrics, state findings. Moore Perf Compute does not support `WarpStateStatistics`; do not write an instruction-level stall analysis.

### 2.1 MP occupancy & launch geometry
<raw CSV grid/block metadata plus any launch or occupancy rule from details>

### 2.2 Thread-block balance (tail effect)
<details-page imbalance rule, active/elapsed cycle evidence, and input distribution>

### 2.3 Tensor Core utilization
<PH1 tensor-throughput metric values or "not collected">

### 2.4 MP utilization timeline
<aggregate MP/DRAM throughput; optional timeline shape only if per-instance data exists>

### 2.5 Memory access pattern
<cache hit rates, DRAM throughput, and exact optional instruction metrics>

### 2.6 Additional findings
<items from Moore Perf Compute details output not otherwise mentioned, each supported by raw metric values>

---

## 3. Summary diagnosis

| Factor | `<tag1>` | `<tag2>` | Impact |
|---|---|---|---|
| <factor 1> | <status> | <status> | <ranked impact> |
| <factor 2> | ... | ... | ... |

---

## 4. Optimization directions (ranked by impact)

> Each priority: name the change, cite evidence, estimate magnitude, flag effort.

### Priority 1 — <one-line name>

<what to do, concretely, with line numbers / function names from the existing kernel>

**Evidence:**
- <metric + value>
- <details output and supporting metric values>

**Expected impact:** <X% end-to-end, Y% on the hot path>, <which workloads benefit>

**Effort:** <low/medium/high + rough description of the code change>

### Priority 2 — ...

<same structure>

### Priority 3 — ...

(Stop at 3-5. More dilutes the signal.)

---

## 5. Confidence & caveats

- What I'm sure about: <list>
- What I'm uncertain about: <list + what would resolve the uncertainty>
- Anything the profile couldn't answer that the user should know: <list>

---

## 6. Reproduction

    cd /abs/path/to/repo
    export PROFILE_RUN_DIR=profile/<run_name>
    <one-block runnable script that builds the harness, runs mcu, and parses>
```

---

## Style rules

- **Cite specific metric values for every claim.** "`mp_throughput` X.X%" (with the actual number from your report) > "MP throughput is low".
- **Name files and line numbers.** "Line L of `harness.cu`" (pasting the actual file/line) > a high-level description like "the main memory load".
- **Validate expected gains.** Use an A/B profile instead of presenting an unverified performance estimate.
- **Rank by magnitude.** Fix the 50% problem before the 5% problem.
- **Keep the top-line summary dense.** A reader should be able to get the #1 finding in 10 seconds of reading.
- **Link to artifacts.** Don't paste huge tables into the prose — link to `analysis/compare_<tag1>_vs_<tag2>.txt` etc.

## Anti-patterns

- ❌ Generic advice without evidence ("you might consider using shared memory").
- ❌ More than 5 "priorities" — you're probably padding.
- ❌ Re-running the same profile with different tags and copy-pasting the same analysis — consolidate.
- ❌ Reporting from the CLI table directly. Extract, interpret, write — don't dump.
- ❌ Omitting the setup section. Without it, nobody can reproduce or trust the numbers.
