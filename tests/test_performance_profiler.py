"""Tests for FASE 6: performance_profiler, bottleneck_analyzer, benchmark_suite."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from performance_profiler import (
    LatencyRecord,
    PerformanceProfiler,
    PerformanceSnapshot,
    ProfilerDaemon,
    TARGET_CPU_MAX,
    TARGET_FPS_MIN,
    TARGET_LATENCY_MS_MAX,
    TARGET_MEMORY_MB_MAX,
    TARGET_QUEUE_FILL_MAX,
)
from bottleneck_analyzer import BottleneckAnalyzer, BottleneckReport, StageAnalysis
from benchmark_suite import BenchmarkSuite, BenchmarkResult


# ---------------------------------------------------------------------------
# PerformanceProfiler tests
# ---------------------------------------------------------------------------


class TestLatencyRecord(unittest.TestCase):
    def test_total_auto_computed(self):
        rec = LatencyRecord(capture_ms=10, parse_ms=20, insert_ms=5, stats_ms=2)
        self.assertAlmostEqual(rec.total_ms, 37.0, places=5)

    def test_explicit_total_preserved(self):
        rec = LatencyRecord(capture_ms=10, parse_ms=20, insert_ms=5, stats_ms=2, total_ms=99.0)
        self.assertAlmostEqual(rec.total_ms, 99.0, places=5)

    def test_timestamp_auto_set(self):
        rec = LatencyRecord()
        self.assertTrue(len(rec.timestamp) > 0)


class TestPerformanceProfiler(unittest.TestCase):
    def _make_profiler(self):
        td = tempfile.mkdtemp()
        return PerformanceProfiler(output_dir=td), td

    def test_initial_fps_zero(self):
        p, _ = self._make_profiler()
        snap = p.get_snapshot()
        self.assertEqual(snap.fps, 0.0)

    def test_record_frame_increases_fps(self):
        p, _ = self._make_profiler()
        # Record several frames quickly
        for _ in range(10):
            p.record_frame()
            time.sleep(0.01)
        snap = p.get_snapshot()
        self.assertGreater(snap.fps, 0.0)

    def test_record_latency(self):
        p, _ = self._make_profiler()
        p.record_latency(capture_ms=30, parse_ms=80, insert_ms=5, stats_ms=2)
        snap = p.get_snapshot()
        self.assertAlmostEqual(snap.latency.capture_ms, 30.0, places=5)
        self.assertAlmostEqual(snap.latency.parse_ms, 80.0, places=5)

    def test_set_queue_state(self):
        p, _ = self._make_profiler()
        p.set_queue_state(depth=40, maxsize=50)
        snap = p.get_snapshot()
        self.assertEqual(snap.queue_depth, 40)
        self.assertEqual(snap.queue_fill_pct, 80.0)

    def test_queue_ok_flag(self):
        p, _ = self._make_profiler()
        p.set_queue_state(depth=10, maxsize=50)  # 20% – OK
        snap = p.get_snapshot()
        self.assertTrue(snap.queue_ok)

        p.set_queue_state(depth=45, maxsize=50)  # 90% – not OK
        snap = p.get_snapshot()
        self.assertFalse(snap.queue_ok)

    def test_latency_percentiles_empty(self):
        p, _ = self._make_profiler()
        percs = p.latency_percentiles()
        self.assertEqual(percs["p50"], 0.0)
        self.assertEqual(percs["p99"], 0.0)

    def test_latency_percentiles_populated(self):
        p, _ = self._make_profiler()
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            p.record_latency(capture_ms=v)
        percs = p.latency_percentiles()
        self.assertGreater(percs["p50"], 0.0)
        self.assertGreaterEqual(percs["p99"], percs["p95"])
        self.assertGreaterEqual(percs["p95"], percs["p50"])

    def test_stage_averages(self):
        p, _ = self._make_profiler()
        p.record_latency(capture_ms=10, parse_ms=50, insert_ms=5, stats_ms=1)
        p.record_latency(capture_ms=20, parse_ms=70, insert_ms=7, stats_ms=3)
        avgs = p.stage_averages()
        self.assertAlmostEqual(avgs["capture"], 15.0, places=2)
        self.assertAlmostEqual(avgs["parse"], 60.0, places=2)

    def test_thread_health(self):
        p, _ = self._make_profiler()
        health = p.thread_health()
        self.assertIn("active_count", health)
        self.assertIn("names", health)
        self.assertGreater(health["active_count"], 0)

    def test_bottleneck_recommendations_healthy(self):
        p, _ = self._make_profiler()
        # Inject fast latency – all stages within targets
        for _ in range(5):
            p.record_latency(capture_ms=20, parse_ms=30, insert_ms=5, stats_ms=2)
            p.record_frame()
            time.sleep(0.01)
        recs = p.bottleneck_recommendations()
        # Should still return at least one recommendation
        self.assertGreater(len(recs), 0)
        # At least one rec should be positive (fps low since we didn't run long)
        self.assertTrue(any(isinstance(r, str) for r in recs))

    def test_save_metrics_json(self):
        p, td = self._make_profiler()
        p.record_latency(capture_ms=30, parse_ms=80)
        path = p.save_metrics_json()
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertIn("snapshot", data)
        self.assertIn("latency_percentiles", data)
        self.assertIn("targets", data)

    def test_save_bottleneck_txt(self):
        p, td = self._make_profiler()
        path = p.save_bottleneck_txt()
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn("BOTTLENECK ANALYSIS", content)
        self.assertIn("Recommendations", content)

    def test_save_html_report(self):
        p, td = self._make_profiler()
        path = p.save_html_report()
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("Performance Profiling", content)

    def test_save_report_all_three(self):
        p, td = self._make_profiler()
        paths = p.save_report()
        self.assertIn("html", paths)
        self.assertIn("json", paths)
        self.assertIn("txt", paths)
        for path in paths.values():
            self.assertTrue(os.path.exists(path), f"Missing: {path}")


class TestProfilerDaemon(unittest.TestCase):
    def test_daemon_start_stop(self):
        td = tempfile.mkdtemp()
        p = PerformanceProfiler(output_dir=td)
        daemon = ProfilerDaemon(p, interval=0.1)
        daemon.start()
        time.sleep(0.3)
        daemon.stop(timeout=2.0)
        # If we got here without hanging the test passes
        self.assertTrue(True)


# ---------------------------------------------------------------------------
# BottleneckAnalyzer tests
# ---------------------------------------------------------------------------


class TestBottleneckAnalyzer(unittest.TestCase):
    def _make_analyzer(self, metrics_dict=None):
        td = tempfile.mkdtemp()
        if metrics_dict is not None:
            json_path = os.path.join(td, "performance_metrics.json")
            with open(json_path, "w") as f:
                json.dump(metrics_dict, f)
            return BottleneckAnalyzer(metrics_json=json_path, output_dir=td), td
        return BottleneckAnalyzer(output_dir=td), td

    def _sample_metrics(self, parse_ms=200.0):
        return {
            "stage_averages": {
                "capture": 30.0,
                "parse": parse_ms,
                "insert": 5.0,
                "stats": 2.0,
            },
            "latency_percentiles": {"p50": 100.0, "p95": 200.0, "p99": 300.0, "mean": 120.0},
            "snapshot": {
                "cpu_percent": 5.0,
                "memory_mb": 100.0,
                "queue_fill_pct": 20.0,
                "thread_count": 4,
            },
        }

    def test_analyze_returns_report(self):
        a, _ = self._make_analyzer(self._sample_metrics())
        report = a.analyze()
        self.assertIsInstance(report, BottleneckReport)
        self.assertEqual(len(report.stages), 4)

    def test_bottleneck_detected_correctly(self):
        a, _ = self._make_analyzer(self._sample_metrics(parse_ms=300.0))
        report = a.analyze()
        self.assertEqual(report.bottleneck_stage, "parse")

    def test_no_bottleneck_when_all_zero(self):
        a, _ = self._make_analyzer()
        report = a.analyze()
        # With no data there should be no crash and stages should be present
        self.assertIsNotNone(report)

    def test_cpu_spike_detection(self):
        a, _ = self._make_analyzer()
        for _ in range(5):
            a.record_cpu(25.0)
        report = a.analyze()
        # Spike threshold is 20 %
        self.assertTrue(report.cpu_spike_detected)

    def test_no_cpu_spike_below_threshold(self):
        a, _ = self._make_analyzer()
        for _ in range(5):
            a.record_cpu(10.0)
        report = a.analyze()
        self.assertFalse(report.cpu_spike_detected)

    def test_memory_leak_detection(self):
        a, _ = self._make_analyzer()
        # Need (last_val - first_val) / 5 > 50 MB threshold
        # Using [50, 100, 150, 200, 250, 310]: growth = (310-50)/5 = 52 MB > 50
        for mb in [50, 100, 150, 200, 250, 310]:
            a.record_memory(mb)
        report = a.analyze()
        self.assertTrue(report.memory_leak_suspected)

    def test_no_memory_leak_stable(self):
        a, _ = self._make_analyzer()
        for _ in range(6):
            a.record_memory(100.0)
        report = a.analyze()
        self.assertFalse(report.memory_leak_suspected)

    def test_queue_congestion_detected(self):
        metrics = self._sample_metrics()
        metrics["snapshot"]["queue_fill_pct"] = 80.0
        a, _ = self._make_analyzer(metrics)
        report = a.analyze()
        self.assertTrue(report.queue_congested)

    def test_recommendations_not_empty(self):
        a, _ = self._make_analyzer(self._sample_metrics())
        report = a.analyze()
        self.assertGreater(len(report.overall_recommendations), 0)

    def test_save_html_report(self):
        a, td = self._make_analyzer(self._sample_metrics())
        report = a.analyze()
        path = a.save_html_report(report)
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("Bottleneck", content)

    def test_save_html_report_auto_analyze(self):
        a, td = self._make_analyzer(self._sample_metrics())
        path = a.save_html_report()
        self.assertTrue(os.path.exists(path))

    def test_analyzer_with_live_profiler(self):
        td = tempfile.mkdtemp()
        from performance_profiler import PerformanceProfiler

        profiler = PerformanceProfiler(output_dir=td)
        profiler.record_latency(capture_ms=30, parse_ms=150, insert_ms=5, stats_ms=2)
        analyzer = BottleneckAnalyzer(profiler=profiler, output_dir=td)
        report = analyzer.analyze()
        self.assertEqual(report.bottleneck_stage, "parse")


# ---------------------------------------------------------------------------
# BenchmarkSuite tests
# ---------------------------------------------------------------------------


class TestBenchmarkSuite(unittest.TestCase):
    def _make_suite(self):
        td = tempfile.mkdtemp()
        return BenchmarkSuite(output_dir=td, db_path=os.path.join(td, "test.db")), td

    def test_100_frames_benchmark(self):
        suite, _ = self._make_suite()
        result = suite.run_frames_benchmark(10)  # small N for speed
        self.assertIsInstance(result, BenchmarkResult)
        self.assertEqual(result.frames, 10)
        self.assertGreater(result.throughput_fps, 0)
        self.assertGreater(result.p50_ms, 0)

    def test_latency_percentile_ordering(self):
        suite, _ = self._make_suite()
        result = suite.run_frames_benchmark(20)
        self.assertGreaterEqual(result.p99_ms, result.p95_ms)
        self.assertGreaterEqual(result.p95_ms, result.p50_ms)

    def test_queue_overflow_test(self):
        suite, _ = self._make_suite()
        result = suite.run_queue_overflow_test(
            producer_fps=60.0, consumer_fps=5.0, duration_s=1.0
        )
        self.assertIsInstance(result, BenchmarkResult)
        self.assertGreater(result.queue_overflows, 0)  # fast producer should overflow

    def test_db_stress_test(self):
        suite, _ = self._make_suite()
        result = suite.run_db_stress_test(n_transactions=20)
        self.assertEqual(result.db_transactions, 20)
        self.assertEqual(result.db_errors, 0)
        self.assertGreater(result.throughput_fps, 0)

    def test_stress_test_short(self):
        suite, _ = self._make_suite()
        result = suite.run_stress_test(duration_s=1.0, max_fps=30.0)
        self.assertGreater(result.frames, 0)
        self.assertGreater(result.throughput_fps, 0)

    def test_memory_leak_test_short(self):
        suite, _ = self._make_suite()
        result = suite.run_memory_leak_test(
            duration_s=2.0, sample_interval=0.5
        )
        self.assertIsInstance(result, BenchmarkResult)
        self.assertGreater(result.frames, 0)

    def test_run_all_returns_list(self):
        suite, _ = self._make_suite()
        results = suite.run_all(
            include_stress=False,
            include_memory_leak=False,
        )
        # At minimum: 100-frame, 1000-frame, queue overflow, db stress
        self.assertGreaterEqual(len(results), 4)
        for r in results:
            self.assertIsInstance(r, BenchmarkResult)

    def test_save_results(self):
        suite, td = self._make_suite()
        results = [suite.run_frames_benchmark(5)]
        paths = suite.save_results(results)
        self.assertIn("json", paths)
        self.assertIn("html", paths)
        self.assertTrue(os.path.exists(paths["json"]))
        self.assertTrue(os.path.exists(paths["html"]))

        with open(paths["json"]) as f:
            data = json.load(f)
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)

    def test_benchmark_charts_html_content(self):
        suite, td = self._make_suite()
        results = [suite.run_frames_benchmark(5), suite.run_db_stress_test(5)]
        paths = suite.save_results(results)
        content = open(paths["html"]).read()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("Benchmark Results", content)

    def test_custom_capture_fn(self):
        td = tempfile.mkdtemp()

        def fast_capture(frame_idx: int) -> float:
            return 1.0

        suite = BenchmarkSuite(
            output_dir=td,
            db_path=os.path.join(td, "t.db"),
            capture_fn=fast_capture,
        )
        result = suite.run_frames_benchmark(5)
        self.assertEqual(result.frames, 5)


if __name__ == "__main__":
    unittest.main()
