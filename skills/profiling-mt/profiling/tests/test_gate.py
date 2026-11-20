import importlib.util
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "gate.py"
spec = importlib.util.spec_from_file_location("profiling_gate", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write(path, content):
    pathlib.Path(path).write_text(content, encoding="utf-8")


class GateTest(unittest.TestCase):
    def test_blocks_when_run_directory_has_no_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.evaluate(temp_dir)

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["optimization_allowed"])
        self.assertIn("no .msys-rep", result["msys"]["reason"])
        self.assertIn("no .mcu-rep", result["mcu"]["reason"])
        self.assertIn("collect a Moore Perf System report with msys", result["required_action"])

    def test_rejects_empty_report_and_stats_without_activity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            write(pathlib.Path(temp_dir) / "baseline.msys-rep", "x" * 128)
            write(pathlib.Path(temp_dir) / "baseline_musa_gpu_kern_sum.json", "[]")

            result = module.evaluate(temp_dir)

        self.assertFalse(result["msys"]["valid"])
        self.assertIn("no activity records", result["msys"]["reason"])

    def test_accepts_msys_stats_that_list_target_activity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            write(pathlib.Path(temp_dir) / "baseline.msys-rep", "x" * 128)
            activity = [{"Name": "tiled_gemm", "Time(%)": 99.7}]
            write(
                pathlib.Path(temp_dir) / "baseline_musa_gpu_kern_sum.json",
                json.dumps(activity),
            )

            valid, evidence, reason = module.check_msys(temp_dir)

        self.assertTrue(valid, reason)
        self.assertTrue(evidence.endswith("baseline_musa_gpu_kern_sum.json"))

    def test_rejects_mcu_environment_failure_and_raw_without_metric_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            write(pathlib.Path(temp_dir) / "kernel.mcu-rep", "x" * 128)
            write(
                pathlib.Path(temp_dir) / "details_kernel.txt",
                "mcu cannot be used in the current environment\n",
            )
            write(pathlib.Path(temp_dir) / "raw_kernel.csv", "metric,value\n,\n")

            result = module.evaluate(temp_dir)

        self.assertFalse(result["mcu"]["valid"])
        self.assertIn("tool failure", result["mcu"]["reason"])

    def test_ready_only_when_both_reports_are_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            write(pathlib.Path(temp_dir) / "baseline.msys-rep", "x" * 128)
            write(
                pathlib.Path(temp_dir) / "baseline_musa_api_sum.json",
                json.dumps([{"Name": "musaMemcpy", "Calls": 8}]),
            )
            write(pathlib.Path(temp_dir) / "gemm.mcu-rep", "x" * 128)
            write(
                pathlib.Path(temp_dir) / "details_gemm.txt",
                "Kernel: tiled_gemm\nSection: Memory Workload Analysis\n",
            )
            write(
                pathlib.Path(temp_dir) / "raw_gemm.csv",
                "kernel,metric,value,unit\n"
                "tiled_gemm,dram_throughput,0.21,%\n",
            )

            result = module.evaluate(temp_dir)

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["optimization_allowed"])
        self.assertEqual(result["required_action"], "")
        self.assertTrue(result["mcu"]["evidence"].endswith("raw_gemm.csv"))

    def test_snapshot_blocks_any_change_to_original_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = pathlib.Path(temp_dir) / "bound_demo.mu"
            run_dir = pathlib.Path(temp_dir) / "run"
            write(source, "original\n")

            self.assertEqual(
                module.main([
                    "--snapshot-source", str(source), str(run_dir),
                ]),
                2,
            )
            write(source, "optimized\n")
            self.assertEqual(module.main([str(run_dir)]), 2)

            result = module.evaluate(str(run_dir))
            unchanged, _current, reason = module.check_sources(str(run_dir))

        self.assertFalse(result["optimization_allowed"])
        self.assertFalse(unchanged)
        self.assertIn("content changed", reason)

    def test_snapshot_is_immutable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = pathlib.Path(temp_dir) / "bound_demo.mu"
            write(source, "original\n")

            module.snapshot_sources(temp_dir, [str(source)])
            with self.assertRaises(FileExistsError):
                module.snapshot_sources(temp_dir, [str(source)])


if __name__ == "__main__":
    unittest.main()
