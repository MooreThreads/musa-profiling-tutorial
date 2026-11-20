# Moore Perf Compute Report CLI Extraction

Use Moore Perf Compute's import and page commands to read an existing report. This is the complete report extraction path for the standard workflow.

## 1. Read the details page first

```bash
mcu --import "$REPORT" --page details > "$ANALYSIS_DIR/details_<tag>.txt"
```

Use this output for:

- Diagnostic information provided by the current Moore Perf Compute build.
- launch, occupancy, stall, memory, and tensor-core summaries shown by the details page.
- warnings about missing counters or unsupported sections.

Read the complete file before forming a diagnosis. Preserve the raw text as an analysis artifact.

## 2. Export raw metrics

```bash
mcu --import "$REPORT" --page raw --csv > "$ANALYSIS_DIR/raw_<tag>.csv"
```

Use the CSV for exact metric values, comparisons between reports, and targeted `grep`/`awk`/spreadsheet analysis. Keep the raw CSV next to the details output so every claim in `REPORT.md` can be traced to the imported report.

If the installed Moore Perf Compute version does not accept `--csv` for the raw page, first save the plain raw page and inspect its help/output:

```bash
mcu --import "$REPORT" --page raw > "$ANALYSIS_DIR/raw_<tag>.txt"
mcu --help
```

Do not assume that a metric exists just because it appears in another GPU generation's documentation. Confirm its presence in the raw page and record the exact name used by the current report.

## 3. Minimal extraction workflow

```bash
REPORT="$PROFILE_RUN_DIR/reports/full_<tag>.mcu-rep"
ANALYSIS_DIR="$PROFILE_RUN_DIR/analysis"
mkdir -p "$ANALYSIS_DIR"

mcu --import "$REPORT" --page details \
  > "$ANALYSIS_DIR/details_<tag>.txt"
mcu --import "$REPORT" --page raw --csv \
  > "$ANALYSIS_DIR/raw_<tag>.csv"
```

Then:

1. Read `details_<tag>.txt` and record any diagnostic information relevant to the kernel.
2. Search `raw_<tag>.csv` for the exact metric names needed to support each finding.
3. Copy the metric values and units into the report with the artifact path as evidence.
4. If a needed metric is absent, report that limitation and use only metrics actually collected.


## 4. Session metadata, Green Contexts, and optional GUI

The standard evidence path deliberately depends only on `details` and `raw`, because page availability differs across Moore Perf Compute releases. If the installed version exposes additional session/device pages, use only page names documented by its own help or import output and save them beside the other artifacts.

When a report was collected under a Green Context or another resource partition:

- record the context/resource identifiers and assigned MP/device resources shown by the report;
- interpret grid size, occupancy, throughput, and active-cycle evidence against the assigned resources, not automatically against the full physical GPU;
- do not infer resource partitioning from a GUI color or button state alone;
- state explicitly when the CLI report does not expose enough allocation metadata to normalize the result.

`mcu-ui` is an optional human inspection aid for report pages and Roofline plots. It must not replace saved CLI artifacts or raw metric values in an agent-produced diagnosis. A Roofline position is context, not a standalone bottleneck verdict: confirm it with the current report's exact throughput, cache/memory, launch, and stall evidence and compare against a same-workload baseline.
