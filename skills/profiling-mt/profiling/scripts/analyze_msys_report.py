#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moore Perf System 报告分析脚本

用法:
    python analyze_msys_report.py <report.msys-rep> [output_dir]

功能:
    1. 自动检测报告类型 (opengl / musa)
    2. 分析 top3 热点数据
    3. 输出分析报告
"""

import subprocess
import sys
import os
import json
import tempfile
import shutil


def run_command(cmd):
    """运行命令并返回输出"""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def export_msys_report(report_path, output_path, report_type):
    """导出 Moore Perf System 报告"""
    cmd = f"msys stats -f json -o {output_path} -r {report_type} {report_path}"
    run_command(cmd)
    # msys stats 会自动追加 _report_type.json 后缀
    actual_path = output_path + "_" + report_type + ".json"
    if os.path.exists(actual_path):
        return actual_path
    return None


def check_report_type(report_path, temp_dir):
    """检测报告类型并导出所有 MUSA Compute 数据"""
    print("正在检测报告类型...")

    results = {}

    # 检查 OpenGL 报告
    opengl_output = os.path.join(temp_dir, "opengl_api_sum")
    opengl_actual = export_msys_report(report_path, opengl_output, "opengl_api_sum")
    if opengl_actual and os.path.getsize(opengl_actual) > 0:
        try:
            with open(opengl_actual, 'r') as f:
                data = json.load(f)
                if data:
                    results["opengl"] = opengl_actual
        except:
            pass

    # 检查 MUSA GPU Kernel 报告
    musa_gpu_output = os.path.join(temp_dir, "musa_gpu_kern_sum")
    musa_gpu_actual = export_msys_report(report_path, musa_gpu_output, "musa_gpu_kern_sum")
    if musa_gpu_actual and os.path.getsize(musa_gpu_actual) > 0:
        try:
            with open(musa_gpu_actual, 'r') as f:
                data = json.load(f)
                if data:
                    results["musa_gpu"] = musa_gpu_actual
        except:
            pass

    # 检查 MUSA API 报告
    musa_api_output = os.path.join(temp_dir, "musa_api_sum")
    musa_api_actual = export_msys_report(report_path, musa_api_output, "musa_api_sum")
    if musa_api_actual and os.path.getsize(musa_api_actual) > 0:
        try:
            with open(musa_api_actual, 'r') as f:
                data = json.load(f)
                if data:
                    results["musa_api"] = musa_api_actual
        except:
            pass

    # 如果是 MUSA Compute 报告，导出所有相关数据
    if "musa_gpu" in results or "musa_api" in results:
        print("  报告类型：MUSA Compute (包含 GPU Kernel 数据)")

        # 导出额外的 MUSA Compute 数据
        print("  正在导出扩展数据...")

        # musa_api_trace (可能很大，选择性导出)
        # api_trace_output = os.path.join(temp_dir, "musa_api_trace")
        # export_msys_report(report_path, api_trace_output, "musa_api_trace")

        # musa_gpu_kern_gb_sum - GPU Kernel 数据传输
        gb_output = os.path.join(temp_dir, "musa_gpu_kern_gb_sum")
        export_msys_report(report_path, gb_output, "musa_gpu_kern_gb_sum")

        # musa_gpu_mem_size_sum - GPU 内存大小
        mem_size_output = os.path.join(temp_dir, "musa_gpu_mem_size_sum")
        export_msys_report(report_path, mem_size_output, "musa_gpu_mem_size_sum")

        # musa_gpu_mem_time_sum - GPU 内存操作时间
        mem_time_output = os.path.join(temp_dir, "musa_gpu_mem_time_sum")
        export_msys_report(report_path, mem_time_output, "musa_gpu_mem_time_sum")

        # musa_gpu_sum - GPU 汇总
        gpu_sum_output = os.path.join(temp_dir, "musa_gpu_sum")
        export_msys_report(report_path, gpu_sum_output, "musa_gpu_sum")

        # musa_kern_exec_sum - Kernel 执行
        kern_exec_output = os.path.join(temp_dir, "musa_kern_exec_sum")
        export_msys_report(report_path, kern_exec_output, "musa_kern_exec_sum")

        # musa_api_gpu_sum - API 到 GPU 映射
        api_gpu_output = os.path.join(temp_dir, "musa_api_gpu_sum")
        export_msys_report(report_path, api_gpu_output, "musa_api_gpu_sum")

        print("  扩展数据导出完成")

        # 优先返回 musa_gpu
        if "musa_gpu" in results:
            return "musa_gpu", results["musa_gpu"]
        elif "musa_api" in results:
            return "musa_api", results["musa_api"]

    # 返回检测到的类型
    if results:
        if "opengl" in results:
            print("  报告类型：OpenGL")
            return "opengl", results["opengl"]

    print("  报告类型：未知")
    return None, None




def export_msys_trace_json(report_path, output_path):
    """导出 Moore Perf System trace json"""
    cmd = f"msys export -t json -o {output_path} {report_path}"
    run_command(cmd)
    if os.path.exists(output_path):
        return output_path
    return None


def get_event_track_name(event):
    """获取 trace event 所属轨道名"""
    for key in ("tid", "name", "cat"):
        value = event.get(key)
        if isinstance(value, str) and value in ("MUSA HW", "HW"):
            return value
    args = event.get("args")
    if isinstance(args, dict):
        for value in args.values():
            if value in ("MUSA HW", "HW"):
                return value
    return None


def is_gpu_workload_event(event, track_name):
    """判断 event 是否属于指定 GPU 轨道的工作负载事件"""
    if event.get("ph") != "X":
        return False
    if get_event_track_name(event) != track_name:
        return False
    return "ts" in event and "dur" in event


def detect_gpu_track(trace_data):
    """优先检测 MUSA HW，否则回退到 HW"""
    trace_events = trace_data.get("traceEvents", [])
    for track_name in ("MUSA HW", "HW"):
        events = [
            event for event in trace_events
            if is_gpu_workload_event(event, track_name)
        ]
        if events:
            events.sort(key=lambda event: float(event.get("ts", 0) or 0))
            return track_name, events
    return None, []


def analyze_gpu_gaps(events):
    """分析相邻 GPU 事件之间的 gap"""
    if len(events) < 2:
        return {
            "gap_count": 0,
            "total_gap_us": 0,
            "max_gap_us": 0,
            "avg_gap_us": 0,
            "top_gaps": [],
        }

    sorted_events = sorted(events, key=lambda event: float(event.get("ts", 0) or 0))
    gaps = []

    for previous, current in zip(sorted_events, sorted_events[1:]):
        previous_end = float(previous.get("ts", 0) or 0) + float(previous.get("dur", 0) or 0)
        current_start = float(current.get("ts", 0) or 0)
        gap_us = current_start - previous_end
        if gap_us > 0:
            gaps.append({
                "before": previous.get("name", "Unknown"),
                "after": current.get("name", "Unknown"),
                "start_us": previous_end,
                "end_us": current_start,
                "gap_us": gap_us,
            })

    total_gap_us = sum(gap["gap_us"] for gap in gaps)
    gap_count = len(gaps)
    max_gap_us = max((gap["gap_us"] for gap in gaps), default=0)
    avg_gap_us = total_gap_us / gap_count if gap_count else 0
    top_gaps = sorted(gaps, key=lambda gap: gap["gap_us"], reverse=True)[:3]

    return {
        "gap_count": gap_count,
        "total_gap_us": total_gap_us,
        "max_gap_us": max_gap_us,
        "avg_gap_us": avg_gap_us,
        "top_gaps": top_gaps,
    }


def generate_gap_report(trace_json_path):
    """基于导出的 trace json 输出 GPU gap 摘要"""
    trace_data = load_json_data(trace_json_path)
    track_name, events = detect_gpu_track(trace_data)

    print("\n" + "=" * 70)
    print("GPU Gap 分析")
    print("=" * 70)

    if not track_name:
        print("未找到 MUSA HW 或 HW 轨道，无法分析 GPU gap")
        return

    gap_analysis = analyze_gpu_gaps(events)
    first_start_us = float(events[0].get("ts", 0) or 0)
    last_end_us = float(events[-1].get("ts", 0) or 0) + float(events[-1].get("dur", 0) or 0)
    total_span_us = max(last_end_us - first_start_us, 0)
    gap_ratio = (gap_analysis["total_gap_us"] / total_span_us * 100) if total_span_us > 0 else 0

    print(f"分析轨道：{track_name}")
    print(f"GPU 事件数：{len(events)}")
    print(f"GPU 总时间跨度：{total_span_us:.3f} us")
    print(f"Gap 次数：{gap_analysis['gap_count']}")
    print(f"总 Gap：{gap_analysis['total_gap_us']:.3f} us")
    print(f"Gap 占比：{gap_ratio:.3f}%")
    print(f"最大 Gap：{gap_analysis['max_gap_us']:.3f} us")
    print(f"平均 Gap：{gap_analysis['avg_gap_us']:.3f} us")

    phenomenon = None
    likely_cause = None
    if gap_ratio >= 50:
        phenomenon = "GPU 供给不连续"
        likely_cause = "CPU 提交不及时、同步等待或数据传输阻塞"
    elif gap_analysis["max_gap_us"] >= 50:
        phenomenon = "存在明显 GPU 空洞"
        likely_cause = "可能有较长同步等待或阶段切换"
    elif gap_analysis["gap_count"] == 0:
        phenomenon = "未观察到明显 GPU Gap"
        likely_cause = "瓶颈可能不在 GPU 空洞"

    if phenomenon:
        print(f"现象判断：{phenomenon}")
    if likely_cause:
        print(f"可能原因：{likely_cause}")

    primary_gap = None
    if gap_analysis["top_gaps"]:
        print("\nTop GPU Gaps:")
        print("-" * 70)
        for index, gap in enumerate(gap_analysis["top_gaps"], 1):
            print(f"  #{index}: {gap['before']} -> {gap['after']}")
            print(f"      Gap: {gap['gap_us']:.3f} us")
            print(f"      区间: {gap['start_us']:.3f} ~ {gap['end_us']:.3f} us")

        primary_gap = gap_analysis["top_gaps"][0]
        print(
            f"优先排查：重点查看 {primary_gap['before']} -> {primary_gap['after']} 之间的 CPU 提交、同步或 memcpy 行为"
        )

    diagnosis_cause = likely_cause or "需要结合 timeline 继续判断"
    diagnosis_hint = "优先检查对应 gap 前后的 CPU 提交、同步与数据搬运行为"
    if primary_gap:
        gap_pair = f"{primary_gap['before']} -> {primary_gap['after']}"
        gap_pair_lower = gap_pair.lower()
        if "synchronize" in gap_pair_lower or "sync" in gap_pair_lower:
            diagnosis_cause = "同步等待阻塞了后续 GPU 工作发射"
            diagnosis_hint = f"优先检查 {gap_pair} 前后的同步位置、等待依赖与 stream 串行化行为"
        elif "memcpy" in gap_pair_lower or "memset" in gap_pair_lower:
            diagnosis_cause = "数据搬运或内存准备阻塞 GPU 连续发射"
            diagnosis_hint = f"优先检查 {gap_pair} 前后的 memcpy、memset、同步与 CPU 提交节奏"
        else:
            diagnosis_hint = f"优先检查 {gap_pair} 前后的 CPU 提交、同步与数据搬运行为"

    if phenomenon and primary_gap:
        print("\n诊断结论：")
        print(f"- 现象：GPU 时间线上存在明显空洞，{phenomenon}")
        print(f"- 证据：Gap 占比 {gap_ratio:.3f}%，最大 Gap {gap_analysis['max_gap_us']:.3f} us")
        print(f"- 最可能原因：{diagnosis_cause}")
        print(f"- 排查建议：{diagnosis_hint}")


def load_json_data(file_path):
    """加载 JSON 数据"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)



def parse_top3(data, sort_key, reverse=True):
    """解析 top3 数据"""
    if not data or not isinstance(data, list):
        return []
    sorted_data = sorted(data, key=lambda x: float(x.get(sort_key, 0) or 0), reverse=reverse)
    return sorted_data[:3]


def analyze_opengl_report(data):
    """分析 OpenGL 报告"""
    print("\n" + "=" * 70)
    print("OpenGL 报告分析")
    print("=" * 70)

    top3 = parse_top3(data, "Total Time(ns)")

    print("\nTop 3 OpenGL API 调用:")
    print("-" * 70)

    for i, item in enumerate(top3, 1):
        print(f"\n  #{i}: {item.get('Name', 'Unknown')}")
        duration_ns = float(item.get("Total Time(ns)", 0) or 0)
        duration_ms = duration_ns / 1000000
        print(f"      总执行时间：{duration_ms:.3f} ms")
        print(f"      调用次数：{item.get('Num Calls', item.get('Count', 1))}")

        if duration_ms > 10:
            print(f"      建议：该 API 执行时间较长，考虑优化或批处理")


def analyze_musa_gpu_report(data, temp_dir):
    """分析 MUSA GPU Kernel 报告"""
    print("\n" + "=" * 70)
    print("MUSA GPU Kernel 分析")
    print("=" * 70)

    top3 = parse_top3(data, "Total Time(ns)")

    print("\nTop 3 GPU Kernels (按总执行时间):")
    print("-" * 70)

    for i, item in enumerate(top3, 1):
        kernel_name = item.get("Name", "Unknown")
        if len(kernel_name) > 70:
            kernel_name = kernel_name[:67] + "..."

        print(f"\n  #{i}: {kernel_name}")

        total_time_ns = float(item.get("Total Time(ns)", 0) or 0)
        total_time_ms = total_time_ns / 1000000
        instances = item.get("Instances", item.get("Count", 0))
        avg_time_ns = float(item.get("Avg(ns)", 0) or 0)
        avg_time_ms = avg_time_ns / 1000000
        max_time_ns = float(item.get("Max(ns)", 0) or 0)
        max_time_ms = max_time_ns / 1000000
        time_pct = float(item.get("Time(%)", 0) or 0)

        print(f"      总执行时间：{total_time_ms:.2f} ms ({time_pct:.2f}%)")
        print(f"      调用次数：{instances}")
        print(f"      平均时间：{avg_time_ms:.3f} ms")
        print(f"      最大时间：{max_time_ms:.3f} ms")

        if time_pct > 30:
            print(f"      建议：该 kernel 占总时间 {time_pct:.1f}%，是主要优化目标")
        elif total_time_ms > 50:
            print(f"      建议：该 kernel 执行时间较长，考虑优化")

    # 分析 GPU Kernel 数据传输 (GB 级别)
    gb_file = os.path.join(temp_dir, "musa_gpu_kern_gb_sum_musa_gpu_kern_gb_sum.json")
    if os.path.exists(gb_file):
        try:
            gb_data = load_json_data(gb_file)
            if gb_data:
                print("\n" + "-" * 70)
                print("Top 3 GPU Kernels (按数据传输时间):")
                print("-" * 70)

                gb_top3 = parse_top3(gb_data, "Total Time(ns)")
                for i, item in enumerate(gb_top3, 1):
                    kernel_name = item.get("Name", "Unknown")
                    if len(kernel_name) > 70:
                        kernel_name = kernel_name[:67] + "..."

                    print(f"\n  #{i}: {kernel_name}")
                    total_time_ns = float(item.get("Total Time(ns)", 0) or 0)
                    total_time_ms = total_time_ns / 1000000
                    instances = item.get("Instances", 0)
                    block_xyz = item.get("BlockXYZ", "N/A")
                    grid_xyz = item.get("GridXYZ", "N/A")

                    print(f"      总执行时间：{total_time_ms:.2f} ms")
                    print(f"      调用次数：{instances}")
                    print(f"      Block: {block_xyz}")
                    print(f"      Grid: {grid_xyz}")
        except Exception as e:
            pass


def analyze_musa_api_report(data):
    """分析 MUSA API 报告"""
    print("\n" + "=" * 70)
    print("MUSA API 分析")
    print("=" * 70)

    top3 = parse_top3(data, "Total Time(ns)")

    print("\nTop 3 MUSA API 调用 (按总执行时间):")
    print("-" * 70)

    for i, item in enumerate(top3, 1):
        api_name = item.get("Name", "Unknown")
        print(f"\n  #{i}: {api_name}")

        total_time_ns = float(item.get("Total Time(ns)", 0) or 0)
        total_time_ms = total_time_ns / 1000000
        time_pct = float(item.get("Time(%)", 0) or 0)
        count = item.get("Num Calls", item.get("Count", 0))
        avg_time_ns = float(item.get("Avg(ns)", 0) or 0)
        avg_time_ms = avg_time_ns / 1000000
        max_time_ns = float(item.get("Max(ns)", 0) or 0)
        max_time_ms = max_time_ns / 1000000

        print(f"      总执行时间：{total_time_ms:.2f} ms ({time_pct:.1f}%)")
        print(f"      调用次数：{count}")
        print(f"      平均时间：{avg_time_ms:.3f} ms")
        print(f"      最大时间：{max_time_ms:.3f} ms")

        if time_pct > 50:
            print(f"      警告：该 API 占用 {time_pct:.1f}% 的时间，存在严重瓶颈！")
        elif time_pct > 20:
            print(f"      建议：该 API 执行时间较长，检查是否可优化")


def analyze_musa_gpu_sum(data):
    """分析 musa_gpu_sum 数据"""
    print("\n" + "=" * 70)
    print("GPU 汇总统计")
    print("=" * 70)

    top3 = parse_top3(data, "Total Time(ns)")

    print("\nTop 3 GPU 操作:")
    print("-" * 70)

    for i, item in enumerate(top3, 1):
        op_name = item.get("Operation", "Unknown")
        category = item.get("Category", "N/A")
        if len(op_name) > 70:
            op_name = op_name[:67] + "..."

        print(f"\n  #{i}: [{category}] {op_name}")

        total_time_ns = float(item.get("Total Time(ns)", 0) or 0)
        total_time_ms = total_time_ns / 1000000
        instances = item.get("instances", item.get("Count", 0))
        time_pct = float(item.get("Time(%)", 0) or 0)

        print(f"      总执行时间：{total_time_ms:.2f} ms ({time_pct:.1f}%)")
        print(f"      调用次数：{instances}")


def analyze_musa_kern_exec_sum(data):
    """分析 musa_kern_exec_sum 数据"""
    print("\n" + "=" * 70)
    print("Kernel 执行队列分析")
    print("=" * 70)

    def get_queue_time(x):
        return float(x.get("QMax(ns)", 0) or 0)

    sorted_data = sorted(data, key=get_queue_time, reverse=True)
    top3 = sorted_data[:3]

    print("\nTop 3 Kernel (按最大排队时间):")
    print("-" * 70)

    for i, item in enumerate(top3, 1):
        kernel_name = item.get("Kernel Name", "Unknown")
        api_name = item.get("Api Name", "Unknown")
        if len(kernel_name) > 50:
            kernel_name = kernel_name[:47] + "..."

        print(f"\n  #{i}: {kernel_name}")
        print(f"      调用 API: {api_name}")

        q_avg_ns = float(item.get("QAvg(ns)", 0) or 0)
        q_avg_ms = q_avg_ns / 1000000
        q_max_ns = float(item.get("QMax(ns)", 0) or 0)
        q_max_ms = q_max_ns / 1000000
        k_avg_ns = float(item.get("KAvg(ns)", 0) or 0)
        k_avg_ms = k_avg_ns / 1000000

        print(f"      平均排队时间：{q_avg_ms:.3f} ms")
        print(f"      最大排队时间：{q_max_ms:.3f} ms")
        print(f"      平均执行时间：{k_avg_ms:.3f} ms")

        if q_avg_ms > 1:
            print(f"      建议：排队时间较长，检查 stream 调度")


def analyze_musa_mem_time_sum(data):
    """分析 musa_gpu_mem_time_sum 数据"""
    print("\n" + "=" * 70)
    print("GPU 内存操作时间分析")
    print("=" * 70)

    top3 = parse_top3(data, "Total Time(ns)")

    print("\nTop 3 内存操作 (按总时间):")
    print("-" * 70)

    for i, item in enumerate(top3, 1):
        op = item.get("Operation", "Unknown")
        print(f"\n  #{i}: {op}")

        total_time_ns = float(item.get("Total Time(ns)", 0) or 0)
        total_time_ms = total_time_ns / 1000000
        count = item.get("Count", 0)
        time_pct = float(item.get("Time(%)", 0) or 0)
        avg_ns = float(item.get("Avg(ns)", 0) or 0)
        avg_ms = avg_ns / 1000000

        print(f"      总执行时间：{total_time_ms:.3f} ms ({time_pct:.1f}%)")
        print(f"      调用次数：{count}")
        print(f"      平均时间：{avg_ms:.3f} ms")


def generate_report(report_type, data, temp_dir):
    """生成分析报告"""
    if report_type == "opengl":
        analyze_opengl_report(data)
    elif report_type == "musa_gpu":
        analyze_musa_gpu_report(data, temp_dir)
        # 同时显示 API 分析
        musa_api_file = os.path.join(temp_dir, "musa_api_sum_musa_api_sum.json")
        if os.path.exists(musa_api_file):
            try:
                api_data = load_json_data(musa_api_file)
                analyze_musa_api_report(api_data)
            except:
                pass
    elif report_type == "musa_api":
        analyze_musa_api_report(data)
    else:
        print("未知报告类型，无法分析")
        return

    # 额外的汇总分析
    print("\n" + "=" * 70)
    print("扩展分析")
    print("=" * 70)

    # GPU 汇总
    gpu_sum_file = os.path.join(temp_dir, "musa_gpu_sum_musa_gpu_sum.json")
    if os.path.exists(gpu_sum_file):
        try:
            gpu_sum_data = load_json_data(gpu_sum_file)
            analyze_musa_gpu_sum(gpu_sum_data)
        except:
            pass

    # Kernel 执行队列分析
    kern_exec_file = os.path.join(temp_dir, "musa_kern_exec_sum_musa_kern_exec_sum.json")
    if os.path.exists(kern_exec_file):
        try:
            kern_exec_data = load_json_data(kern_exec_file)
            analyze_musa_kern_exec_sum(kern_exec_data)
        except:
            pass

    # 内存时间分析
    mem_time_file = os.path.join(temp_dir, "musa_gpu_mem_time_sum_musa_gpu_mem_time_sum.json")
    if os.path.exists(mem_time_file):
        try:
            mem_time_data = load_json_data(mem_time_file)
            analyze_musa_mem_time_sum(mem_time_data)
        except:
            pass

    print("\n" + "=" * 70)


def main():
    if len(sys.argv) < 2:
        print("用法：python analyze_msys_report.py <report.msys-rep> [output_dir]")
        print("")
        print("参数:")
        print("  report.msys-rep  Moore Perf System 报告文件路径")
        print("  output_dir       可选，输出目录（默认创建临时目录）")
        sys.exit(1)

    report_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(report_path):
        print(f"错误：报告文件不存在：{report_path}")
        sys.exit(1)

    ret, out, err = run_command("msys --version")
    if ret != 0:
        print("错误：未找到 msys 命令，请确保已安装 Moore Perf System")
        sys.exit(1)

    print("")
    print("=" * 70)
    print("Moore Perf System 报告分析")
    print(f"报告文件：{report_path}")
    print("=" * 70)
    print("")

    temp_dir = output_dir
    if not temp_dir:
        temp_dir = tempfile.mkdtemp(prefix="msys_analysis_")
    else:
        os.makedirs(temp_dir, exist_ok=True)

    print(f"输出目录：{temp_dir}")
    print("")

    try:
        report_type, data_file = check_report_type(report_path, temp_dir)

        if not report_type:
            print("\n错误：无法识别报告类型")
            print("请确认报告文件有效")
            sys.exit(1)

        trace_json_path = os.path.join(temp_dir, "trace.json")
        trace_json_file = export_msys_trace_json(report_path, trace_json_path)
        if trace_json_file:
            generate_gap_report(trace_json_file)

        data = load_json_data(data_file)
        generate_report(report_type, data, temp_dir)

        print(f"\n详细数据已导出至：{data_file}")
        print(f"\n使用以下命令在 GUI 中查看:")
        print(f"  msys-ui {report_path}")

    finally:
        if not output_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
