#!/usr/bin/env python3
"""Extract and compare key metrics from .mcu-rep files via the mcu CLI.

Produces in `<run_dir>/analysis/`:
    details_<tag>.txt         — `mcu --import ... --page details`
    raw_<tag>.csv             — `mcu --import ... --page raw --csv`
    metrics_all_<tag>.json    — every raw metric row, archival
    metrics_key_<tag>.txt/json — first value for every metric in the raw CSV
    compare_<tag1>_vs_<tag2>.txt (when >= 2 reports given) — side-by-side

Usage examples:
    # Single report
    python3 analyze_reports.py --run-dir profile/myrun \\
            --report profile/myrun/reports/full_<tag>.mcu-rep --tag <tag>

    # Multiple reports → side-by-side compare
    python3 analyze_reports.py --run-dir profile/myrun \\
            --report profile/myrun/reports/full_<tag1>.mcu-rep --tag <tag1> \\
            --report profile/myrun/reports/full_<tag2>.mcu-rep --tag <tag2>
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

def run_mcu_import(mcu_bin: str, report_path: Path, page: str, out_path: Path, csv_output: bool = False) -> None:
    cmd = [mcu_bin, "--import", str(report_path), "--page", page]
    if csv_output:
        cmd.append("--csv")
    with open(out_path, "w", newline="") as f:
        try:
            subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, check=True)
        except subprocess.CalledProcessError as e:
            if e.stderr:
                print(e.stderr, file=sys.stderr, end="")
            raise


def parse_metric_value(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return value


def parse_raw_csv(path: Path) -> tuple[list[dict], dict]:
    rows = []
    metrics = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return rows, metrics
        fields = {name.strip(): name for name in reader.fieldnames}
        name_col = fields.get("Metric Name")
        unit_col = fields.get("Metric Unit")
        value_col = fields.get("Metric Value")
        if not name_col or not value_col:
            raise ValueError(f"{path} does not look like a Moore Perf Compute raw CSV export")
        for row in reader:
            rows.append(row)
            name = row.get(name_col, "")
            if not name:
                continue
            value = row.get(value_col)
            unit = row.get(unit_col, "") if unit_col else ""
            rec = {
                "value": parse_metric_value(value),
                "unit": unit,
                "gpu_id": row.get(fields.get("GPU ID", ""), ""),
                "kernel_id": row.get(fields.get("Kernel ID", ""), ""),
                "kernel_name": row.get(fields.get("Kernel Name", ""), ""),
                "context": row.get(fields.get("Context", ""), ""),
                "stream": row.get(fields.get("Stream", ""), ""),
                "block_size": row.get(fields.get("Block Size", ""), ""),
                "grid_size": row.get(fields.get("Grid Size", ""), ""),
                "device": row.get(fields.get("Device", ""), ""),
            }
            metrics.setdefault(name, []).append(rec)
    return rows, metrics


def first_metric(metrics: dict, name: str):
    values = metrics.get(name, [])
    if not values:
        return None
    return values[0].get("value")


def collect(report_path: Path, tag: str, analysis_dir: Path, mcu_bin: str) -> dict:
    details_path = analysis_dir / f"details_{tag}.txt"
    raw_path = analysis_dir / f"raw_{tag}.csv"

    run_mcu_import(mcu_bin, report_path, "details", details_path)
    print(f"[{tag}] details -> {details_path}")

    run_mcu_import(mcu_bin, report_path, "raw", raw_path, csv_output=True)
    print(f"[{tag}] raw -> {raw_path}")

    rows, metrics = parse_raw_csv(raw_path)
    print(f"[{tag}] {report_path.name}: {len(metrics)} unique raw metrics")

    all_rows = {
        "report": str(report_path),
        "details": str(details_path),
        "raw": str(raw_path),
        "rows": rows,
    }
    (analysis_dir / f"metrics_all_{tag}.json").write_text(
        json.dumps(all_rows, indent=2, default=str)
    )

    key = {m: first_metric(metrics, m) for m in sorted(metrics)}
    key["__report__"] = str(report_path)
    key["__details__"] = str(details_path)
    key["__raw__"] = str(raw_path)
    if rows:
        first = rows[0]
        key["__kernel_name__"] = first.get("Kernel Name")
        key["__kernel_id__"] = first.get("Kernel ID")
        key["__device__"] = first.get("Device")
        key["__grid_size__"] = first.get("Grid Size")
        key["__block_size__"] = first.get("Block Size")

    (analysis_dir / f"metrics_key_{tag}.json").write_text(json.dumps(key, indent=2, default=str))
    with open(analysis_dir / f"metrics_key_{tag}.txt", "w") as f:
        f.write(f"===== {tag} =====\nReport: {report_path}\nRaw CSV: {raw_path}\n\n")
        for m, v in key.items():
            if m.startswith("__"):
                continue
            f.write(f"{m:95s} = {v}\n")
    print(f"  -> metrics_key_{tag}.{{json,txt}}")
    return key


def compare(collected: dict, analysis_dir: Path):
    tags = list(collected.keys())
    if len(tags) < 2:
        return
    out_path = analysis_dir / f"compare_{'_vs_'.join(tags)}.txt"
    with open(out_path, "w") as f:
        col_w = max(20, max(len(t) for t in tags) + 2)
        f.write(f"{'Metric':<95}")
        for t in tags:
            f.write(f"{t:>{col_w}}")
        f.write("\n" + "-" * (95 + col_w * len(tags)) + "\n")
        metric_names = sorted({
            m for report_key in collected.values()
            for m in report_key
            if not m.startswith("__")
        })
        for m in metric_names:
            f.write(f"{m:<95}")
            for t in tags:
                v = collected[t].get(m, "N/A")
                if isinstance(v, (int, float)):
                    v = f"{v:.4g}"
                f.write(f"{str(v):>{col_w}}")
            f.write("\n")
    print(f"compare -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Extract key Moore Perf Compute metrics and compare.")
    ap.add_argument("--run-dir", type=Path, required=True,
                    help="The profile run directory — outputs go to <run-dir>/analysis/")
    ap.add_argument("--report", type=Path, action="append", required=True,
                    help="Path to a .mcu-rep file. Can be passed multiple times.")
    ap.add_argument("--tag", type=str, action="append", required=True,
                    help="Short tag for each report. Must be passed once per --report.")
    ap.add_argument("--mcu-bin", default="mcu",
                    help="mcu executable to use for `--import` extraction.")
    args = ap.parse_args()

    if len(args.report) != len(args.tag):
        ap.error("--report and --tag counts must match")

    analysis_dir = args.run_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    collected = {}
    for rep, tag in zip(args.report, args.tag):
        if not rep.exists():
            print(f"[skip] {rep} does not exist", file=sys.stderr)
            continue
        collected[tag] = collect(rep, tag, analysis_dir, args.mcu_bin)

    compare(collected, analysis_dir)


if __name__ == "__main__":
    main()
