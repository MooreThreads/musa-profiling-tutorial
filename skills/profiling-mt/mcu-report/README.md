# mcu-report module

> [!IMPORTANT]
> This module is rewritten for MUSA, based on [ncu-report-skill](https://github.com/mit-han-lab/ncu-report-skill).

This directory is the kernel-level Moore Perf Compute module used by the parent [`profiling-mt`](../SKILL.md) skill. It covers the full PH1 workflow: build a standalone harness, run Moore Perf Compute (`mcu`), read `details`/`raw` report pages, walk through five analysis dimensions, match evidence to the diagnosis playbook, and write an evidence-backed optimization report.

It is not a separate skill entry point. System-level triage and task routing live in `../SKILL.md`; this module contains the Moore Perf Compute reference docs and reusable helpers selected by that workflow.

---

## Directory layout

```text
mcu-report/
├── README.md                         ← this module overview
├── helpers/                          ← reusable code
│   ├── harness_template.cu           ← standalone profiling harness template
│   ├── safetensors_loader.h          ← header-only safetensors reader
│   ├── list_flashinfer_workloads.py  ← browse flashinfer-trace datasets
│   ├── analyze_reports.py            ← extract/compare .mcu-rep metrics via mcu
│   └── README.md
├── reference/                        ← detailed reference docs
│   ├── 00-directory-layout.md        ← profile/ directory conventions
│   ├── 01-workflow.md                ← end-to-end profiling checklist
│   ├── 02-harness-guide.md           ← standalone harness guidance
│   ├── 03-collection.md              ← collection, launch, MPI, and remote recipes
│   ├── 04-report-cli.md              ← CLI-first report extraction
│   ├── 05-analysis-dimensions.md     ← five analysis dimensions
│   ├── 06-diagnosis-playbook.md      ← pattern → cause → fix
│   ├── 07-report-template.md         ← final report structure
│   ├── 08-metric-names.md            ← PH1 metric-name hints
│   └── 09-common-issues.md           ← permissions and recurring issues
└── ph1-musa-programming.md           ← companion PH1 programming reference
```

---

## How the parent skill uses this module

The parent `profiling-mt` workflow routes work as follows:

1. Use `msys` first when profiling a complete application with unknown hotspots.
2. Enter this module when the target kernel is already known or `msys` identifies a MUSA kernel hotspot.
3. For an existing `.mcu-rep`, skip collection and start at `reference/04-report-cli.md`.
4. Collect evidence, diagnose, propose one primary change, validate correctness, and compare the same workload before/after.

The canonical Moore Perf Compute path is `reference/01-workflow.md` phases 0–6. Metric names, CLI flags, pages, and sections remain version/device dependent and must be verified against the installed Moore Perf Compute and the current report.

---

## Running the helpers directly

The helpers can also process an existing `.mcu-rep` without invoking the complete skill workflow:

```bash
# Path to this directory inside the profiling-mt skill checkout.
MCU_REPORT_DIR=/path/to/skills/profiling-mt/mcu-report
RUN=/path/to/repository/profile/<run_name>

python3 "$MCU_REPORT_DIR/helpers/analyze_reports.py" \
    --run-dir "$RUN" \
    --report "$RUN/reports/full_<tag>.mcu-rep" --tag <tag>

FIB_DATASET_PATH=/path/to/flashinfer-trace \
python3 "$MCU_REPORT_DIR/helpers/list_flashinfer_workloads.py" \
    --definition <your_definition_name>
```

Copy the harness template and optional safetensors loader into the current run's `harness/` directory. See `reference/02-harness-guide.md` for details.

---

## Requirements

- MUSA compiler `mcc`
- Moore Perf Compute CLI `mcu`
- A PH1 device with permission to access performance counters; see `reference/09-common-issues.md`

The references are optimized for PH1. Metric names and supported collection options may differ between Moore Perf Compute versions and devices; verify them against `mcu --help`, `mcu --list-sections`, and the current report's raw output. Treat `reference/08-metric-names.md` only as search guidance.

---

## License

MIT
