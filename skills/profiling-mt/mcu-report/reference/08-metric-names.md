# PH1 Metric Names

Use the metric names emitted by the target Moore Perf Compute build. Do not translate names
from another profiler or GPU generation into PH1 names by convention.

## Inspect the current report

Export the raw page and search the actual `Metric Name` column:

```bash
REPORT="$PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep"
ANALYSIS_DIR="$PROFILE_RUN_DIR/analysis"

mcu --import "$REPORT" --page raw --csv \
  > "$ANALYSIS_DIR/raw_<tag>.csv"
grep -iE 'throughput|duration|hit_rate|cycles|tensor|stall' \
  "$ANALYSIS_DIR/raw_<tag>.csv"
```

The report also carries useful launch metadata in CSV columns:

```text
Kernel Name
Block Size
Grid Size
Device
```

Treat these columns as metadata rather than inventing `launch__*` metric names.

## Stall names

**Moore Perf Compute does not support the `WarpStateStatistics` section. Do not search for or cite warp-state stall metrics.** Even when `SchedulerStats` is available, it only provides scheduler summaries such as active and eligible that actually appear in the current raw CSV. Do not infer a specific stall reason from them. If the corresponding columns are absent, write "cannot determine the specific stall reason" and do not cite NCU `smsp__pcsamp_*` names.

## Names observed in a PH1 report

The following names were observed in the PH1 AXPY report available on the
Ubuntu development machine. They are a starting point, not a guarantee that
every section or kernel produces every name.

### Timing and throughput

```text
gpu_time_duration.max
mp_throughput.avg.pct_of_peak_sustained_elapsed
mp_memory_throughput.avg.pct_of_peak_sustained_elapsed
gpu_compute_memory_throughput.avg.pct_of_peak_sustained_elapsed
gpu_compute_memory_access_throughput.avg.pct_of_peak_sustained_elapsed
gpu_compute_memory_request_throughput.avg.pct_of_peak_sustained_elapsed
dram_throughput.avg.pct_of_peak_sustained_elapsed
dram_throughput.avg.per_second
dram_bytes.sum.per_second
```

### Cache and memory hierarchy

```text
l1_sector_hit_rate.pct
l1_throughput.avg.pct_of_peak_sustained_active
l1_throughput.avg.per_second
l2pu_sector_hit_rate.pct
l2pu_throughput.avg.pct_of_peak_sustained_elapsed
l2pu_throughput.avg.per_second
llc_sector_hit_rate.pct
llc_throughput.avg.pct_of_peak_sustained_elapsed
llc_throughput.avg.per_second
```

### MP and tensor throughput

```text
mp_cycles_active.max
mp_cycles_elapsed.max
mp_fp32_throughput.avg.per_second
mp_fp64_throughput.avg.per_second
mp_tc_fp32_throughput.avg.per_second
```

Peak reference values may also be present:

```text
dram_peak_bandwidth.avg
mp_fp32_peak_throughput.sum
mp_fp64_peak_throughput.sum
mp_tc_fp32_peak_throughput.sum
```

## Metrics from optional sections

**Moore Perf Compute does not support `WarpStateStatistics`; do not add it to the section filter below.** `ComputeWorkloadAnalysis`, `SchedulerStats`, and `InstructionStats` are optional, version-dependent sections. Filter for the sections the target actually provides, then collect the corresponding raw CSV:

```bash
AVAILABLE_SECTIONS="$(mcu --list-sections | awk 'NF && $1 != "Identifier" && $1 !~ /^-+$/ { print $1 }')"
OPTIONAL_SECTIONS="$(printf '%s\n' "$AVAILABLE_SECTIONS" | grep -E '^(ComputeWorkloadAnalysis|SchedulerStats|InstructionStats)$' | paste -sd, -)"
test -n "$OPTIONAL_SECTIONS" || { echo "The target provides no optional analysis sections" >&2; exit 1; }
mcu --sections "$OPTIONAL_SECTIONS" \
  -k "regex:KERNEL_REGEX" -c 1 \
  -o "$PROFILE_RUN_DIR/reports/detailed_<tag>" \
  ./harness [args]

mcu --import "$PROFILE_RUN_DIR/reports/detailed_<tag>.mcu-rep" \
  --page raw --csv > "$PROFILE_RUN_DIR/analysis/raw_detailed_<tag>.csv"
```

If a metric is not in the raw CSV, do not cite it in the report. The names listed here are search hints only; the current raw CSV is the only source of truth.
