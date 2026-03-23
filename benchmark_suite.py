"""
FASE 6 - Benchmark Suite
Controlled benchmarks for the Occhi di Falco pipeline.

Benchmarks:
- 100-frame benchmark
- 1000-frame benchmark
- Stress test (max CPU within limit)
- Memory leak test (configurable duration)
- Queue overflow test
- Database transaction stress

Metrics:
- Throughput (frames/second)
- P50/P95/P99 latency
- Memory growth over time
- CPU stability
- Queue behaviour

Outputs:
- benchmark_results.json
- benchmark_charts.html  (bar/line charts rendered with inline SVG/Canvas)
"""

from __future__ import annotations

import json
import logging
import os
import queue
import random
import statistics
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    name: str
    frames: int
    duration_s: float
    throughput_fps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    memory_start_mb: float
    memory_end_mb: float
    memory_growth_mb: float
    cpu_mean_pct: float
    cpu_max_pct: float
    queue_max_depth: int
    queue_overflows: int
    db_transactions: int
    db_errors: int
    passed: bool
    notes: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_mb() -> float:
    if PSUTIL_AVAILABLE:
        try:
            return psutil.Process().memory_info().rss / 1024 / 1024
        except Exception:
            pass
    return 0.0


def _cpu_pct() -> float:
    if PSUTIL_AVAILABLE:
        try:
            return psutil.Process().cpu_percent(interval=0.1)
        except Exception:
            pass
    return 0.0


def _percentile(data: List[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = min(int(len(s) * pct), len(s) - 1)
    return round(s[idx], 2)


# ---------------------------------------------------------------------------
# Mock pipeline stages (used when no real pipeline is attached)
# ---------------------------------------------------------------------------


def _mock_capture(frame_idx: int) -> float:
    """Simulate screen capture latency (ms)."""
    base = 30.0 + random.gauss(0, 5)
    return max(5.0, base)


def _mock_parse(frame_idx: int) -> float:
    """Simulate OCR/CV parse latency (ms)."""
    base = 80.0 + random.gauss(0, 15)
    return max(10.0, base)


def _mock_insert(db_conn: Any, frame_idx: int) -> float:
    """Simulate DB insert latency (ms)."""
    base = 5.0 + random.gauss(0, 2)
    if db_conn is not None:
        t0 = time.perf_counter()
        try:
            db_conn.execute(
                "INSERT INTO bench_frames (frame_idx, ts) VALUES (?,?)",
                (frame_idx, datetime.now().isoformat()),
            )
            db_conn.commit()
        except Exception:
            pass
        return (time.perf_counter() - t0) * 1000
    return max(1.0, base)


def _mock_stats(frame_idx: int) -> float:
    """Simulate stats update latency (ms)."""
    base = 2.0 + random.gauss(0, 0.5)
    return max(0.5, base)


# ---------------------------------------------------------------------------
# Core benchmark runner
# ---------------------------------------------------------------------------


class BenchmarkSuite:
    """
    Run controlled benchmarks against the pipeline or mock stages.

    Usage::

        suite = BenchmarkSuite(output_dir="output")
        results = suite.run_all()
        suite.save_results(results)
    """

    def __init__(
        self,
        output_dir: str = "output",
        db_path: Optional[str] = None,
        capture_fn: Optional[Callable[[int], float]] = None,
        parse_fn: Optional[Callable[[int], float]] = None,
        insert_fn: Optional[Callable[[Any, int], float]] = None,
        stats_fn: Optional[Callable[[int], float]] = None,
    ):
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self._db_path = db_path or os.path.join(output_dir, "benchmark_test.db")
        self._db_conn: Optional[Any] = None

        # Allow injection of real pipeline functions; fall back to mocks
        self._capture = capture_fn or _mock_capture
        self._parse = parse_fn or _mock_parse
        self._insert = insert_fn or _mock_insert
        self._stats = stats_fn or _mock_stats

        if PSUTIL_AVAILABLE:
            try:
                psutil.Process().cpu_percent(interval=None)  # warm-up
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> Any:
        import sqlite3

        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bench_frames "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, frame_idx INTEGER, ts TEXT)"
        )
        conn.commit()
        return conn

    def _close_db(self, conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _drop_bench_table(self, conn: Any) -> None:
        try:
            conn.execute("DROP TABLE IF EXISTS bench_frames")
            conn.commit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Single frame simulation
    # ------------------------------------------------------------------

    def _run_frame(self, frame_idx: int, conn: Any) -> Dict[str, float]:
        t_cap = self._capture(frame_idx)
        t_parse = self._parse(frame_idx)
        t_insert = self._insert(conn, frame_idx)
        t_stats = self._stats(frame_idx)
        total = t_cap + t_parse + t_insert + t_stats
        return {
            "capture": t_cap,
            "parse": t_parse,
            "insert": t_insert,
            "stats": t_stats,
            "total": total,
        }

    # ------------------------------------------------------------------
    # Individual benchmarks
    # ------------------------------------------------------------------

    def run_frames_benchmark(self, n_frames: int) -> BenchmarkResult:
        """Benchmark processing *n_frames* frames sequentially."""
        name = f"{n_frames}_frames"
        logger.info("Running benchmark: %s", name)

        conn = self._init_db()
        self._drop_bench_table(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bench_frames "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, frame_idx INTEGER, ts TEXT)"
        )
        conn.commit()

        latencies: List[float] = []
        cpu_samples: List[float] = []
        mem_start = _memory_mb()
        t_start = time.perf_counter()

        for i in range(n_frames):
            frame_data = self._run_frame(i, conn)
            latencies.append(frame_data["total"])
            if i % 10 == 0:
                cpu_samples.append(_cpu_pct())

        duration = time.perf_counter() - t_start
        mem_end = _memory_mb()
        self._drop_bench_table(conn)
        self._close_db(conn)

        throughput = n_frames / duration if duration > 0 else 0.0
        cpu_samples = cpu_samples or [0.0]

        return BenchmarkResult(
            name=name,
            frames=n_frames,
            duration_s=round(duration, 3),
            throughput_fps=round(throughput, 2),
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
            p99_ms=_percentile(latencies, 0.99),
            mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
            memory_start_mb=round(mem_start, 1),
            memory_end_mb=round(mem_end, 1),
            memory_growth_mb=round(mem_end - mem_start, 1),
            cpu_mean_pct=round(statistics.mean(cpu_samples), 1),
            cpu_max_pct=round(max(cpu_samples), 1),
            queue_max_depth=0,
            queue_overflows=0,
            db_transactions=n_frames,
            db_errors=0,
            passed=throughput >= 5.0 and _percentile(latencies, 0.99) <= 500.0,
            notes=f"Sequential {n_frames}-frame benchmark",
        )

    def run_stress_test(
        self, duration_s: float = 30.0, max_fps: float = 30.0
    ) -> BenchmarkResult:
        """
        Run as many frames as possible within *duration_s* seconds, capped at
        *max_fps* to stay within CPU budget.
        """
        name = "stress_test"
        logger.info("Running stress test for %.0fs", duration_s)

        conn = self._init_db()
        self._drop_bench_table(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bench_frames "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, frame_idx INTEGER, ts TEXT)"
        )
        conn.commit()

        latencies: List[float] = []
        cpu_samples: List[float] = []
        mem_start = _memory_mb()
        t_start = time.perf_counter()
        min_frame_time = 1.0 / max_fps
        frame_idx = 0

        while time.perf_counter() - t_start < duration_s:
            frame_t0 = time.perf_counter()
            frame_data = self._run_frame(frame_idx, conn)
            latencies.append(frame_data["total"])
            if frame_idx % 10 == 0:
                cpu_samples.append(_cpu_pct())
            elapsed = time.perf_counter() - frame_t0
            sleep_time = min_frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            frame_idx += 1

        duration = time.perf_counter() - t_start
        mem_end = _memory_mb()
        self._drop_bench_table(conn)
        self._close_db(conn)

        throughput = frame_idx / duration if duration > 0 else 0.0
        cpu_samples = cpu_samples or [0.0]

        return BenchmarkResult(
            name=name,
            frames=frame_idx,
            duration_s=round(duration, 3),
            throughput_fps=round(throughput, 2),
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
            p99_ms=_percentile(latencies, 0.99),
            mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
            memory_start_mb=round(mem_start, 1),
            memory_end_mb=round(mem_end, 1),
            memory_growth_mb=round(mem_end - mem_start, 1),
            cpu_mean_pct=round(statistics.mean(cpu_samples), 1),
            cpu_max_pct=round(max(cpu_samples), 1),
            queue_max_depth=0,
            queue_overflows=0,
            db_transactions=frame_idx,
            db_errors=0,
            passed=throughput >= 5.0,
            notes=f"Stress test {duration_s}s @ max {max_fps} FPS",
        )

    def run_memory_leak_test(
        self, duration_s: float = 60.0, sample_interval: float = 5.0
    ) -> BenchmarkResult:
        """
        Run the pipeline for *duration_s* seconds and monitor for memory growth.
        """
        name = "memory_leak_test"
        logger.info("Running memory leak test for %.0fs", duration_s)

        conn = self._init_db()
        self._drop_bench_table(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bench_frames "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, frame_idx INTEGER, ts TEXT)"
        )
        conn.commit()

        latencies: List[float] = []
        cpu_samples: List[float] = []
        mem_samples: List[float] = []
        mem_start = _memory_mb()
        mem_samples.append(mem_start)

        t_start = time.perf_counter()
        last_sample = t_start
        frame_idx = 0

        while time.perf_counter() - t_start < duration_s:
            frame_data = self._run_frame(frame_idx, conn)
            latencies.append(frame_data["total"])
            now = time.perf_counter()
            if now - last_sample >= sample_interval:
                mem_samples.append(_memory_mb())
                cpu_samples.append(_cpu_pct())
                last_sample = now
            frame_idx += 1
            # small sleep to avoid maxing CPU
            time.sleep(0.01)

        duration = time.perf_counter() - t_start
        mem_end = _memory_mb()
        mem_samples.append(mem_end)

        self._drop_bench_table(conn)
        self._close_db(conn)

        # Detect leak: is memory growing linearly?
        growth = mem_end - mem_start
        leaked = growth > 50.0  # MB threshold

        cpu_samples = cpu_samples or [0.0]
        throughput = frame_idx / duration if duration > 0 else 0.0

        return BenchmarkResult(
            name=name,
            frames=frame_idx,
            duration_s=round(duration, 3),
            throughput_fps=round(throughput, 2),
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
            p99_ms=_percentile(latencies, 0.99),
            mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
            memory_start_mb=round(mem_start, 1),
            memory_end_mb=round(mem_end, 1),
            memory_growth_mb=round(growth, 1),
            cpu_mean_pct=round(statistics.mean(cpu_samples), 1),
            cpu_max_pct=round(max(cpu_samples), 1),
            queue_max_depth=0,
            queue_overflows=0,
            db_transactions=frame_idx,
            db_errors=0,
            passed=not leaked,
            notes=(
                f"Memory leak test {duration_s}s. "
                f"Growth: {growth:.1f} MB. "
                f"{'⚠ Possible leak!' if leaked else '✅ No leak detected.'}"
            ),
        )

    def run_queue_overflow_test(
        self, producer_fps: float = 30.0, consumer_fps: float = 5.0, duration_s: float = 10.0
    ) -> BenchmarkResult:
        """
        Simulate a fast producer and slow consumer to test queue overflow handling.
        """
        name = "queue_overflow_test"
        logger.info(
            "Running queue overflow test: producer %.0f FPS, consumer %.0f FPS",
            producer_fps,
            consumer_fps,
        )

        q: queue.Queue = queue.Queue(maxsize=50)
        overflows = 0
        consumed = 0
        produced = 0
        latencies: List[float] = []
        stop_event = threading.Event()

        def producer():
            nonlocal produced, overflows
            interval = 1.0 / producer_fps
            while not stop_event.is_set():
                item = (produced, time.perf_counter())
                try:
                    q.put_nowait(item)
                    produced += 1
                except queue.Full:
                    overflows += 1
                time.sleep(interval)

        def consumer():
            nonlocal consumed
            interval = 1.0 / consumer_fps
            while not stop_event.is_set() or not q.empty():
                try:
                    item = q.get(timeout=0.5)
                    latency_ms = (time.perf_counter() - item[1]) * 1000
                    latencies.append(latency_ms)
                    consumed += 1
                    time.sleep(interval)
                except queue.Empty:
                    continue

        mem_start = _memory_mb()
        t_start = time.perf_counter()

        prod_thread = threading.Thread(target=producer, daemon=True)
        cons_thread = threading.Thread(target=consumer, daemon=True)
        prod_thread.start()
        cons_thread.start()

        time.sleep(duration_s)
        stop_event.set()
        prod_thread.join(timeout=5)
        cons_thread.join(timeout=5)

        duration = time.perf_counter() - t_start
        mem_end = _memory_mb()

        throughput = consumed / duration if duration > 0 else 0.0
        queue_max = min(produced - consumed, 50)  # bounded by maxsize

        return BenchmarkResult(
            name=name,
            frames=consumed,
            duration_s=round(duration, 3),
            throughput_fps=round(throughput, 2),
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
            p99_ms=_percentile(latencies, 0.99),
            mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
            memory_start_mb=round(mem_start, 1),
            memory_end_mb=round(mem_end, 1),
            memory_growth_mb=round(mem_end - mem_start, 1),
            cpu_mean_pct=0.0,
            cpu_max_pct=0.0,
            queue_max_depth=queue_max,
            queue_overflows=overflows,
            db_transactions=consumed,
            db_errors=0,
            passed=overflows < produced * 0.05,  # less than 5% overflow is OK
            notes=(
                f"Queue overflow test {duration_s}s. "
                f"Produced: {produced}, Consumed: {consumed}, Overflows: {overflows}."
            ),
        )

    def run_db_stress_test(self, n_transactions: int = 500) -> BenchmarkResult:
        """Stress-test DB with *n_transactions* rapid inserts."""
        name = "db_stress_test"
        logger.info("Running DB stress test: %d transactions", n_transactions)

        conn = self._init_db()
        self._drop_bench_table(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bench_frames "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, frame_idx INTEGER, ts TEXT)"
        )
        conn.commit()

        latencies: List[float] = []
        errors = 0
        mem_start = _memory_mb()
        t_start = time.perf_counter()

        for i in range(n_transactions):
            t0 = time.perf_counter()
            try:
                conn.execute(
                    "INSERT INTO bench_frames (frame_idx, ts) VALUES (?,?)",
                    (i, datetime.now().isoformat()),
                )
                conn.commit()
                latencies.append((time.perf_counter() - t0) * 1000)
            except Exception as exc:
                errors += 1
                logger.debug("DB error at tx %d: %s", i, exc)

        duration = time.perf_counter() - t_start
        mem_end = _memory_mb()
        self._drop_bench_table(conn)
        self._close_db(conn)

        throughput = n_transactions / duration if duration > 0 else 0.0

        return BenchmarkResult(
            name=name,
            frames=n_transactions,
            duration_s=round(duration, 3),
            throughput_fps=round(throughput, 2),
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
            p99_ms=_percentile(latencies, 0.99),
            mean_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
            memory_start_mb=round(mem_start, 1),
            memory_end_mb=round(mem_end, 1),
            memory_growth_mb=round(mem_end - mem_start, 1),
            cpu_mean_pct=0.0,
            cpu_max_pct=0.0,
            queue_max_depth=0,
            queue_overflows=0,
            db_transactions=n_transactions,
            db_errors=errors,
            passed=errors == 0 and throughput >= 50.0,
            notes=f"DB stress {n_transactions} transactions. Errors: {errors}.",
        )

    # ------------------------------------------------------------------
    # Run all benchmarks
    # ------------------------------------------------------------------

    def run_all(
        self,
        include_stress: bool = True,
        stress_duration_s: float = 15.0,
        include_memory_leak: bool = False,
        memory_leak_duration_s: float = 60.0,
    ) -> List[BenchmarkResult]:
        """
        Run the standard benchmark suite and return all results.

        ``include_memory_leak=True`` adds a longer-running test (default 60 s).
        """
        results = [
            self.run_frames_benchmark(100),
            self.run_frames_benchmark(1000),
            self.run_queue_overflow_test(duration_s=5.0),
            self.run_db_stress_test(n_transactions=200),
        ]
        if include_stress:
            results.append(self.run_stress_test(duration_s=stress_duration_s))
        if include_memory_leak:
            results.append(
                self.run_memory_leak_test(duration_s=memory_leak_duration_s)
            )
        return results

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def save_results(
        self,
        results: List[BenchmarkResult],
        json_path: Optional[str] = None,
        html_path: Optional[str] = None,
    ) -> Dict[str, str]:
        """Save *benchmark_results.json* and *benchmark_charts.html*."""
        if json_path is None:
            json_path = os.path.join(self._output_dir, "benchmark_results.json")
        if html_path is None:
            html_path = os.path.join(self._output_dir, "benchmark_charts.html")

        data = {
            "generated_at": datetime.now().isoformat(),
            "results": [asdict(r) for r in results],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Benchmark results saved to %s", json_path)

        self._save_html(results, html_path)
        logger.info("Benchmark charts saved to %s", html_path)

        return {"json": json_path, "html": html_path}

    # ------------------------------------------------------------------
    # HTML chart generation (pure inline SVG – no dependencies)
    # ------------------------------------------------------------------

    def _save_html(self, results: List[BenchmarkResult], path: str) -> None:
        def bar_chart(
            labels: List[str], values: List[float], title: str, unit: str
        ) -> str:
            if not values:
                return ""
            max_val = max(values) or 1
            bars = ""
            for label, val in zip(labels, values):
                pct = val / max_val * 100
                colour = "#e94560"
                bars += (
                    f'<div style="margin:4px 0">'
                    f'<span style="display:inline-block;width:160px;font-size:0.85em">{label}</span>'
                    f'<div style="display:inline-block;background:{colour};'
                    f'height:18px;width:{pct:.0f}%;max-width:400px;border-radius:3px;'
                    f'vertical-align:middle"></div>'
                    f'<span style="margin-left:6px;font-size:0.85em">{val:.1f} {unit}</span>'
                    f'</div>'
                )
            return f"<h3 style='color:#aaa'>{title}</h3>{bars}"

        names = [r.name for r in results]
        fps_vals = [r.throughput_fps for r in results]
        p95_vals = [r.p95_ms for r in results]
        mem_vals = [r.memory_growth_mb for r in results]

        rows = ""
        for r in results:
            status = "✅" if r.passed else "❌"
            rows += (
                f"<tr>"
                f"<td>{r.name}</td>"
                f"<td>{r.frames}</td>"
                f"<td>{r.throughput_fps:.1f}</td>"
                f"<td>{r.p50_ms:.1f}</td>"
                f"<td>{r.p95_ms:.1f}</td>"
                f"<td>{r.p99_ms:.1f}</td>"
                f"<td>{r.memory_growth_mb:.1f}</td>"
                f"<td>{r.db_errors}</td>"
                f"<td>{r.queue_overflows}</td>"
                f"<td>{status}</td>"
                f"</tr>"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Occhi di Falco – Benchmark Results</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
  h1 {{ color: #e94560; }}
  h2 {{ color: #eee; background: #16213e; padding: 8px; border-radius: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.9em; }}
  th, td {{ border: 1px solid #0f3460; padding: 8px; text-align: left; }}
  th {{ background: #0f3460; }}
  .footer {{ color: #555; font-size: 0.8em; margin-top: 30px; }}
</style>
</head>
<body>
<h1>🏁 Occhi di Falco – Benchmark Results</h1>
<p>Generated: {datetime.now().isoformat()}</p>

<h2>📊 Summary Table</h2>
<table>
  <tr>
    <th>Name</th><th>Frames</th><th>FPS</th>
    <th>P50 (ms)</th><th>P95 (ms)</th><th>P99 (ms)</th>
    <th>Mem Growth (MB)</th><th>DB Errors</th><th>Q Overflows</th><th>Pass</th>
  </tr>
  {rows}
</table>

<h2>📈 Charts</h2>
{bar_chart(names, fps_vals, "Throughput (FPS)", "fps")}
{bar_chart(names, p95_vals, "P95 Latency (ms)", "ms")}
{bar_chart(names, mem_vals, "Memory Growth (MB)", "MB")}

<p class="footer">Occhi di Falco Benchmark Suite – FASE 6</p>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Occhi di Falco – Benchmark Suite"
    )
    ap.add_argument("--output", default="output", help="Output directory")
    ap.add_argument(
        "--stress-duration",
        type=float,
        default=15.0,
        help="Stress test duration (seconds)",
    )
    ap.add_argument(
        "--memory-leak",
        action="store_true",
        help="Include memory leak test (runs for --leak-duration seconds)",
    )
    ap.add_argument(
        "--leak-duration",
        type=float,
        default=60.0,
        help="Memory leak test duration (seconds)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    suite = BenchmarkSuite(output_dir=args.output)
    results = suite.run_all(
        stress_duration_s=args.stress_duration,
        include_memory_leak=args.memory_leak,
        memory_leak_duration_s=args.leak_duration,
    )
    paths = suite.save_results(results)

    print("\n=== BENCHMARK SUMMARY ===")
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(
            f"  {status}  {r.name:<25}  "
            f"FPS={r.throughput_fps:.1f}  "
            f"P95={r.p95_ms:.0f}ms  "
            f"MemGrowth={r.memory_growth_mb:.1f}MB"
        )
    print(f"\nReports saved to: {args.output}/")
    print(f"  JSON: {paths['json']}")
    print(f"  HTML: {paths['html']}")
