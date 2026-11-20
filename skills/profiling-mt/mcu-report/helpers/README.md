# Helpers

Reusable code for profiling harnesses and report analysis. See `../SKILL.md` for context.

## C++ / MUSA

| File | Purpose |
|---|---|
| `harness_template.cu` | Starting point for a profiling harness. Copy into your run dir, fill in the `TODO(you)` sections. |
| `safetensors_loader.h` | Header-only safetensors reader (no external deps). Use from your harness to load real workload tensors. |

### Typical harness setup

```bash
cd profile/<run_name>/harness/
cp /path/to/skills/profiling-mt/mcu-report/helpers/harness_template.cu my_kernel_harness.cu
cp /path/to/skills/profiling-mt/mcu-report/helpers/safetensors_loader.h .
# edit my_kernel_harness.cu to include your kernel + fill in main()
# Confirm --cuda-gpu-arch from the installed mcc; do not assume mp_31.
mcc -o my_kernel_harness -std=c++17 -mtgpu -O2 \
     --cuda-gpu-arch=<target-arch> -lmusart my_kernel_harness.cu
```

## Optional post-processing helpers

| File | Purpose |
|---|---|
| `analyze_reports.py` | Runs `mcu --import --page details/raw`, extracts key metrics, and compares reports |
| `list_flashinfer_workloads.py` | Browse a flashinfer-trace dataset: show axes, histogram workload shapes, print safetensors paths for specific UUIDs |

### Optional helper workflow

```bash
export PROFILE_RUN_DIR=profile/<run_name>
HELPERS=/path/to/skills/profiling-mt/mcu-report/helpers
export FIB_DATASET_PATH=/path/to/flashinfer-trace  # if using FIB workloads

# (Optional) Browse workload shapes for a flashinfer-trace dataset
python3 $HELPERS/list_flashinfer_workloads.py --definition <def_name>
python3 $HELPERS/list_flashinfer_workloads.py --definition <def_name> --unique-axes <axis1>,<axis2> --no-paths

# Extract details/raw pages and key metrics for each report
python3 $HELPERS/analyze_reports.py --run-dir $PROFILE_RUN_DIR \
    --report $PROFILE_RUN_DIR/reports/full_<tag1>.mcu-rep --tag <tag1> \
    --report $PROFILE_RUN_DIR/reports/full_<tag2>.mcu-rep --tag <tag2>

```

`analyze_reports.py` uses the `mcu` CLI and writes under `<run-dir>/analysis/`;
the direct CLI commands in [`../reference/04-report-cli.md`](../reference/04-report-cli.md)
remain the canonical workflow.
