#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读的基线报告门禁。

判定一个 run 目录里的 Moore Perf System / Moore Perf Compute 报告是否达到 profiling-mt 规定的"有效报告"。
不调用 msys 或 mcu，因此在没有 GPU 的机器上也能复查；采集必须先由调用方完成。

用法:
    python3 gate.py --snapshot-source <原始文件> <run 目录>
    python3 gate.py <run 目录>

第一次调用记录原始文件的 SHA-256。之后每次调用都重新计算；
文件内容变化时返回 blocked。生成 patch、测试和优化都不构成修改这些文件的授权。

退出码 0 表示报告有效且原始文件未变化，可以进入优化；
退出码 2 表示门禁未通过，调用方必须停止，并按 required_action 处理。
"""

import argparse
import csv
import hashlib
import json
import os
import sys

# 只认这些由 msys stats 导出的 Moore Perf System 报告。文件名后缀即报告类型。
MSYS_ACTIVITY_SUFFIXES = (
    "_musa_gpu_kern_sum.json",
    "_musa_gpu_kern_gb_sum.json",
    "_musa_kern_exec_sum.json",
    "_musa_gpu_mem_size_sum.json",
    "_musa_gpu_sum.json",
    "_musa_api_sum.json",
    "_musa_api_trace.json",
)

MCU_FAILURE_MARKERS = (
    "mcu cannot be used in the current environment",
    "permission denied",
    "operation not permitted",
    "another profiler",
    "already in use",
)

MIN_REPORT_BYTES = 64


def load_json(path):
    """读取 JSON，失败时返回 None。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def has_entries(data):
    """Moore Perf System 的 msys stats 有效导出是非空的 list 或 dict。"""
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return len(data) > 0
    return False


def check_msys(run_dir):
    """返回 (是否有效, 证据路径, 失败原因)。"""
    candidates = sorted(
        os.path.join(run_dir, name)
        for name in os.listdir(run_dir)
        if name.endswith(".msys-rep")
    )
    if not candidates:
        return False, "", "no .msys-rep found"
    reasons = []
    for report in candidates:
        if os.path.getsize(report) < MIN_REPORT_BYTES:
            reasons.append(os.path.basename(report) + ": file is empty")
            continue
        exports = [
            os.path.join(run_dir, name)
            for name in os.listdir(run_dir)
            if name.endswith(MSYS_ACTIVITY_SUFFIXES)
            and os.path.getsize(os.path.join(run_dir, name)) > 0
        ]
        if not exports:
            reasons.append(
                os.path.basename(report)
                + ": no Moore Perf System stats export with kernel, memcpy or API records"
            )
            continue
        for export in sorted(exports):
            if has_entries(load_json(export)):
                return True, export, ""
        reasons.append(
            os.path.basename(report) + ": stats export contains no activity records"
        )
    return False, "", "; ".join(reasons)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def check_mcu(run_dir):
    """返回 (是否有效, 证据路径, 失败原因)。"""
    candidates = sorted(
        os.path.join(run_dir, name)
        for name in os.listdir(run_dir)
        if name.endswith(".mcu-rep")
    )
    if not candidates:
        return False, "", "no .mcu-rep found"
    reasons = []
    for report in candidates:
        if os.path.getsize(report) < MIN_REPORT_BYTES:
            reasons.append(os.path.basename(report) + ": file is empty")
            continue
        stem = os.path.splitext(os.path.basename(report))[0]
        details = os.path.join(run_dir, "details_" + stem + ".txt")
        raw = os.path.join(run_dir, "raw_" + stem + ".csv")
        if not os.path.isfile(details) or not os.path.isfile(raw):
            reasons.append(
                os.path.basename(report)
                + ": missing details_" + stem + ".txt or raw_" + stem + ".csv"
            )
            continue
        details_text = read_text(details).strip()
        lowered = details_text.lower()
        marker = next((item for item in MCU_FAILURE_MARKERS if item in lowered), "")
        if marker:
            reasons.append(os.path.basename(report) + ": details report tool failure: " + marker)
            continue
        if not details_text:
            reasons.append(os.path.basename(report) + ": details page is empty")
            continue
        if not raw_has_metric(raw):
            reasons.append(os.path.basename(report) + ": raw csv has no metric value")
            continue
        return True, raw, ""
    return False, "", "; ".join(reasons)


def raw_has_metric(path):
    """raw 导出必须有表头、至少一行，且除维度列外存在非空的指标值。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle))
    except OSError:
        return False
    if len(rows) < 2 or not rows[0]:
        return False
    dimension_columns = {"kernel", "name", "metric", "section", "unit"}
    value_columns = [
        index
        for index, header in enumerate(rows[0])
        if header.strip().lower() not in dimension_columns
    ]
    if not value_columns:
        return False
    return any(
        any(index < len(row) and row[index].strip() for index in value_columns)
        for row in rows[1:]
    )


def first_action(msys_ok, mcu_ok):
    if not msys_ok:
        return "collect a Moore Perf System report with msys, then export stats json into this run directory"
    if not mcu_ok:
        return "collect mcu report, then export details txt and raw csv into this run directory"
    return ""


def evaluate(run_dir):
    """汇总两个工具的结论。任一无效即 blocked。"""
    msys_ok, msys_evidence, msys_reason = check_msys(run_dir)
    mcu_ok, mcu_evidence, mcu_reason = check_mcu(run_dir)
    ready = msys_ok and mcu_ok
    return {
        "status": "ready" if ready else "blocked",
        "optimization_allowed": ready,
        "run_dir": os.path.abspath(run_dir),
        "msys": {
            "valid": msys_ok,
            "evidence": msys_evidence,
            "reason": msys_reason,
        },
        "mcu": {
            "valid": mcu_ok,
            "evidence": mcu_evidence,
            "reason": mcu_reason,
        },
        "required_action": first_action(msys_ok, mcu_ok),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="检查 run 目录是否同时具备有效的 Moore Perf System 和 Moore Perf Compute 基线报告。"
    )
    parser.add_argument("run_dir", help="存放 .msys-rep、.mcu-rep 及其导出文件的目录")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if not os.path.isdir(args.run_dir):
        print("gate: run directory does not exist: " + args.run_dir, file=sys.stderr)
        return 2
    result = evaluate(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["optimization_allowed"] else 2


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def source_sha256(path):
    return hashlib.sha256(read_bytes(path)).hexdigest()


def manifest_path(run_dir):
    return os.path.join(run_dir, "source-manifest.json")


def snapshot_sources(run_dir, sources):
    """记录优化开始前的原始文件。同名文件已存在时拒绝覆盖。"""
    path = manifest_path(run_dir)
    if os.path.exists(path):
        raise FileExistsError("source manifest already exists: " + path)
    missing = [item for item in sources if not os.path.isfile(item)]
    if missing:
        raise FileNotFoundError("source file not found: " + ", ".join(missing))
    files = [
        {"path": os.path.abspath(item), "sha256": source_sha256(item)}
        for item in sources
    ]
    payload = {"files": files}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return payload


def check_sources(run_dir):
    """原始文件必须与快照逐字节一致。没有快照表示优化边界尚未建立。"""
    path = manifest_path(run_dir)
    manifest = load_json(path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        return False, [], "source-manifest.json is missing or invalid"
    current = []
    changed = []
    for item in manifest["files"]:
        source = item.get("path", "")
        expected = item.get("sha256", "")
        if not source or not expected:
            return False, [], "source manifest contains an invalid entry"
        if not os.path.isfile(source):
            changed.append(source + ": file is missing")
            continue
        digest = source_sha256(source)
        current.append({"path": source, "sha256": digest})
        if digest != expected:
            changed.append(source + ": content changed")
    if changed:
        return False, current, "; ".join(changed)
    return True, current, ""


def build_parser():
    parser = argparse.ArgumentParser(
        description="检查报告门禁，并锁定优化开始前的原始源码。"
    )
    parser.add_argument("run_dir", help="存放报告、导出文件和 source-manifest.json 的目录")
    parser.add_argument(
        "--snapshot-source",
        action="append",
        default=[],
        help="记录一个必须保持不变的原始文件；可重复传入",
    )
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    os.makedirs(args.run_dir, exist_ok=True)
    if args.snapshot_source:
        try:
            snapshot_sources(args.run_dir, args.snapshot_source)
        except (OSError, FileNotFoundError, FileExistsError) as error:
            print("gate: " + str(error), file=sys.stderr)
            return 2
    if not os.path.isdir(args.run_dir):
        print("gate: run directory does not exist: " + args.run_dir, file=sys.stderr)
        return 2
    result = evaluate(args.run_dir)
    unchanged, current, reason = check_sources(args.run_dir)
    result["sources_unchanged"] = unchanged
    result["sources"] = current
    result["source_reason"] = reason
    result["optimization_allowed"] = result["optimization_allowed"] and unchanged
    if not unchanged:
        result["status"] = "blocked"
        result["required_action"] = (
            "restore the original source files from the isolated copy; "
            "do not edit files recorded in source-manifest.json"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["optimization_allowed"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
