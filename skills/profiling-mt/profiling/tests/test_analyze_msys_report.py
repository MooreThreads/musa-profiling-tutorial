import importlib.util
import io
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "analyze_msys_report.py"
spec = importlib.util.spec_from_file_location("analyze_msys_report", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AnalyzeMsysReportTest(unittest.TestCase):
    def test_prefers_musa_hw_track_for_gap_analysis(self):
        trace = {
            "traceEvents": [
                {"name": "kernel_a", "ph": "X", "cat": "gpu", "ts": 0, "dur": 10, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "cat": "gpu", "ts": 30, "dur": 5, "tid": "MUSA HW"},
                {"name": "kernel_c", "ph": "X", "cat": "gpu", "ts": 100, "dur": 8, "tid": "HW"},
            ]
        }

        track_name, events = module.detect_gpu_track(trace)

        self.assertEqual(track_name, "MUSA HW")
        self.assertEqual([event["name"] for event in events], ["kernel_a", "kernel_b"])

    def test_falls_back_to_hw_track_when_musa_hw_missing(self):
        trace = {
            "traceEvents": [
                {"name": "gfx_a", "ph": "X", "cat": "gpu", "ts": 5, "dur": 10, "tid": "HW"},
                {"name": "gfx_b", "ph": "X", "cat": "gpu", "ts": 40, "dur": 10, "tid": "HW"},
            ]
        }

        track_name, events = module.detect_gpu_track(trace)

        self.assertEqual(track_name, "HW")
        self.assertEqual([event["name"] for event in events], ["gfx_a", "gfx_b"])

    def test_computes_gpu_gaps_from_adjacent_events(self):
        events = [
            {"name": "kernel_a", "ts": 0, "dur": 10},
            {"name": "kernel_b", "ts": 25, "dur": 5},
            {"name": "kernel_c", "ts": 50, "dur": 10},
        ]

        analysis = module.analyze_gpu_gaps(events)

        self.assertEqual(analysis["gap_count"], 2)
        self.assertEqual(analysis["total_gap_us"], 35)
        self.assertEqual(analysis["max_gap_us"], 20)
        self.assertEqual(analysis["avg_gap_us"], 17.5)
        self.assertEqual(analysis["top_gaps"][0]["before"], "kernel_b")
        self.assertEqual(analysis["top_gaps"][0]["after"], "kernel_c")
        self.assertEqual(analysis["top_gaps"][0]["gap_us"], 20)

    def test_generate_gap_report_prints_summary_for_detected_track(self):
        trace = {
            "traceEvents": [
                {"name": "kernel_a", "ph": "X", "ts": 0, "dur": 10, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "ts": 40, "dur": 5, "tid": "MUSA HW"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("GPU Gap 分析", output)
        self.assertIn("分析轨道：MUSA HW", output)
        self.assertIn("Gap 次数：1", output)
        self.assertIn("最大 Gap：30.000 us", output)

    def test_generate_gap_report_prints_gap_ratio_and_total_span(self):
        trace = {
            "traceEvents": [
                {"name": "kernel_a", "ph": "X", "ts": 0, "dur": 10, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "ts": 40, "dur": 5, "tid": "MUSA HW"},
                {"name": "kernel_c", "ph": "X", "ts": 70, "dur": 10, "tid": "MUSA HW"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("GPU 总时间跨度：80.000 us", output)
        self.assertIn("Gap 占比：68.750%", output)

    def test_generate_gap_report_uses_detected_track_span_not_whole_report(self):
        trace = {
            "traceEvents": [
                {"name": "cpu_marker", "ph": "X", "ts": 0, "dur": 1000, "tid": "CPU"},
                {"name": "kernel_a", "ph": "X", "ts": 100, "dur": 10, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "ts": 140, "dur": 5, "tid": "MUSA HW"},
                {"name": "cpu_tail", "ph": "X", "ts": 0, "dur": 5000, "tid": "CPU"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("GPU 总时间跨度：45.000 us", output)
        self.assertIn("总 Gap：30.000 us", output)
        self.assertIn("Gap 占比：66.667%", output)

    def test_generate_gap_report_prints_interpretation_for_high_gap_ratio(self):
        trace = {
            "traceEvents": [
                {"name": "kernel_a", "ph": "X", "ts": 0, "dur": 10, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "ts": 40, "dur": 5, "tid": "MUSA HW"},
                {"name": "kernel_c", "ph": "X", "ts": 70, "dur": 10, "tid": "MUSA HW"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("现象判断：GPU 供给不连续", output)
        self.assertIn("可能原因：CPU 提交不及时、同步等待或数据传输阻塞", output)

    def test_generate_gap_report_prints_top_gap_investigation_hint(self):
        trace = {
            "traceEvents": [
                {"name": "kernel_a", "ph": "X", "ts": 0, "dur": 10, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "ts": 120, "dur": 5, "tid": "MUSA HW"},
                {"name": "kernel_c", "ph": "X", "ts": 130, "dur": 5, "tid": "MUSA HW"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("优先排查：重点查看 kernel_a -> kernel_b 之间的 CPU 提交、同步或 memcpy 行为", output)

    def test_generate_gap_report_prints_structured_diagnosis_summary(self):
        trace = {
            "traceEvents": [
                {"name": "Memcpy HtoD", "ph": "X", "ts": 0, "dur": 10, "tid": "MUSA HW"},
                {"name": "Memset", "ph": "X", "ts": 60, "dur": 5, "tid": "MUSA HW"},
                {"name": "kernel_c", "ph": "X", "ts": 80, "dur": 10, "tid": "MUSA HW"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("诊断结论：", output)
        self.assertIn("- 现象：GPU 时间线上存在明显空洞，GPU 供给不连续", output)
        self.assertIn("- 证据：Gap 占比 72.222%，最大 Gap 50.000 us", output)
        self.assertIn("- 最可能原因：数据搬运或内存准备阻塞 GPU 连续发射", output)
        self.assertIn("- 排查建议：优先检查 Memcpy HtoD -> Memset 前后的 memcpy、memset、同步与 CPU 提交节奏", output)

    def test_generate_gap_report_biases_to_sync_wait_when_gap_starts_after_sync(self):
        trace = {
            "traceEvents": [
                {"name": "musaStreamSynchronize", "ph": "X", "ts": 0, "dur": 20, "tid": "MUSA HW"},
                {"name": "kernel_b", "ph": "X", "ts": 120, "dur": 5, "tid": "MUSA HW"},
                {"name": "kernel_c", "ph": "X", "ts": 130, "dur": 5, "tid": "MUSA HW"},
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = pathlib.Path(temp_dir) / "trace.json"
            trace_path.write_text(module.json.dumps(trace), encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                module.generate_gap_report(str(trace_path))

        output = buffer.getvalue()
        self.assertIn("- 最可能原因：同步等待阻塞了后续 GPU 工作发射", output)
        self.assertIn("- 排查建议：优先检查 musaStreamSynchronize -> kernel_b 前后的同步位置、等待依赖与 stream 串行化行为", output)

    def test_main_exports_trace_json_before_stats_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = pathlib.Path(temp_dir) / "sample.msys-rep"
            report_path.write_text("dummy", encoding="utf-8")

            call_order = []

            def fake_run_command(cmd):
                self.assertEqual(cmd, "msys --version")
                return 0, "msys version", ""

            def fake_check_report_type(input_report_path, work_dir):
                self.assertEqual(input_report_path, str(report_path))
                data_file = pathlib.Path(work_dir) / "musa_gpu_kern_sum_musa_gpu_kern_sum.json"
                data_file.write_text(module.json.dumps([]), encoding="utf-8")
                return "musa_gpu", str(data_file)

            def fake_export_trace(input_report_path, output_path):
                self.assertEqual(input_report_path, str(report_path))
                pathlib.Path(output_path).write_text(module.json.dumps({"traceEvents": []}), encoding="utf-8")
                return output_path

            def fake_generate_gap_report(trace_path):
                call_order.append(("gap", pathlib.Path(trace_path).name))

            def fake_generate_report(report_type, data, work_dir):
                call_order.append(("stats", report_type, data, pathlib.Path(work_dir).exists()))

            original_run_command = module.run_command
            original_check_report_type = module.check_report_type
            original_export_trace = module.export_msys_trace_json
            original_generate_gap_report = module.generate_gap_report
            original_generate_report = module.generate_report
            original_argv = module.sys.argv

            try:
                module.run_command = fake_run_command
                module.check_report_type = fake_check_report_type
                module.export_msys_trace_json = fake_export_trace
                module.generate_gap_report = fake_generate_gap_report
                module.generate_report = fake_generate_report
                module.sys.argv = [str(SCRIPT_PATH), str(report_path), temp_dir]

                with redirect_stdout(io.StringIO()):
                    module.main()
            finally:
                module.run_command = original_run_command
                module.check_report_type = original_check_report_type
                module.export_msys_trace_json = original_export_trace
                module.generate_gap_report = original_generate_gap_report
                module.generate_report = original_generate_report
                module.sys.argv = original_argv

            self.assertEqual(call_order[0][0], "gap")
            self.assertEqual(call_order[1][0], "stats")
            self.assertEqual(call_order[1][1], "musa_gpu")
            self.assertEqual(call_order[1][2], [])
            self.assertTrue(call_order[1][3])
