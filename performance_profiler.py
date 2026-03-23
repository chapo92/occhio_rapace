"""
FASE 6 - Performance Profiler
Real-time performance monitoring for the Occhi di Falco pipeline.

Profiles:
- FPS counter (capture thread)
- CPU usage (psutil optional)
- Memory footprint
- Latency: capture → parse → insert → stats
- Queue depth monitoring
- Thread health check
- Network latency (if database is remote)

Outputs:
- profiling_report.html  (real-time dashboard snapshot)
- performance_metrics.json  (timestamped records)
- bottleneck_analysis.txt  (recommendations)
"""

from __future__ import annotations

import json
import logging
import os
import queue
import statistics
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Benchmark targets
# ---------------------------------------------------------------------------
TARGET_FPS_MIN = 5.0
TARGET_FPS_GOAL = 8.0
TARGET_CPU_MAX = 15.0
TARGET_MEMORY_MB_MAX = 300.0
TARGET_LATENCY_MS_MAX = 500.0
TARGET_QUEUE_FILL_MAX = 0.80  # 80%

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LatencyRecord:
    capture_ms: float = 0.0
    parse_ms: float = 0.0
    insert_ms: float = 0.0
    stats_ms: float = 0.0
    total_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if self.total_ms == 0.0:
            self.total_ms = (
                self.capture_ms + self.parse_ms + self.insert_ms + self.stats_ms
            )


@dataclass
class PerformanceSnapshot:
    timestamp: str = ""
    fps: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    thread_count: int = 0
    queue_depth: int = 0
    queue_maxsize: int = 50
    queue_fill_pct: float = 0.0
    latency: LatencyRecord = field(default_factory=LatencyRecord)
    uptime_seconds: float = 0.0
    # benchmark verdict
    fps_ok: bool = False
    cpu_ok: bool = True
    memory_ok: bool = True
    latency_ok: bool = True
    queue_ok: bool = True

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Core profiler
# ---------------------------------------------------------------------------


class PerformanceProfiler:
    """
    Thread-safe real-time profiler.  Attach to the pipeline and call:

    - ``record_frame()``          – after every captured frame
    - ``record_latency(...)``     – with per-stage times
    - ``set_queue_state(...)``    – with current queue depth + maxsize
    - ``get_snapshot()``          – to retrieve current metrics
    - ``save_report()``           – to write HTML + JSON + TXT outputs
    """

    def __init__(
        self,
        fps_window: int = 30,
        history_size: int = 300,
        output_dir: str = "output",
    ):
        self._fps_window = fps_window
        self._history_size = history_size
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self._frame_times: Deque[float] = deque(maxlen=fps_window)
        self._latency_history: Deque[LatencyRecord] = deque(maxlen=history_size)
        self._snapshots: List[PerformanceSnapshot] = []

        self._queue_depth = 0
        self._queue_maxsize = 50

        self._start_time = time.time()
        self._lock = threading.Lock()

        self._process: Optional[object] = None
        if PSUTIL_AVAILABLE:
            try:
                self._process = psutil.Process()
                # warm-up so first call doesn't return 0.0
                self._process.cpu_percent(interval=None)
            except Exception as exc:
                logger.warning("psutil.Process() init failed: %s", exc)

    # ------------------------------------------------------------------
    # Recording API
    # ------------------------------------------------------------------

    def record_frame(self) -> None:
        """Call once per captured frame."""
        with self._lock:
            self._frame_times.append(time.time())

    def record_latency(
        self,
        capture_ms: float = 0.0,
        parse_ms: float = 0.0,
        insert_ms: float = 0.0,
        stats_ms: float = 0.0,
    ) -> None:
        """Record per-stage latency for one processed frame."""
        rec = LatencyRecord(
            capture_ms=capture_ms,
            parse_ms=parse_ms,
            insert_ms=insert_ms,
            stats_ms=stats_ms,
        )
        with self._lock:
            self._latency_history.append(rec)

    def set_queue_state(self, depth: int, maxsize: int = 50) -> None:
        """Update current queue depth and capacity."""
        self._queue_depth = max(0, depth)
        self._queue_maxsize = max(1, maxsize)

    # ------------------------------------------------------------------
    # Metrics API
    # ------------------------------------------------------------------

    def _compute_fps(self) -> float:
        with self._lock:
            times = list(self._frame_times)
        if len(times) < 2:
            return 0.0
        elapsed = times[-1] - times[0]
        return round((len(times) - 1) / elapsed, 2) if elapsed > 0 else 0.0

    def _get_system_stats(self):
        cpu = 0.0
        mem_mb = 0.0
        if self._process and PSUTIL_AVAILABLE:
            try:
                cpu = self._process.cpu_percent(interval=None)
                mem_mb = self._process.memory_info().rss / 1024 / 1024
            except Exception:
                pass
        return round(cpu, 1), round(mem_mb, 1)

    def _latest_latency(self) -> LatencyRecord:
        with self._lock:
            if self._latency_history:
                return self._latency_history[-1]
        return LatencyRecord()

    def get_snapshot(self) -> PerformanceSnapshot:
        """Return a *PerformanceSnapshot* with current metrics."""
        fps = self._compute_fps()
        cpu, mem_mb = self._get_system_stats()
        lat = self._latest_latency()
        qd = self._queue_depth
        qm = self._queue_maxsize
        fill_pct = round(qd / qm, 4) if qm > 0 else 0.0

        snap = PerformanceSnapshot(
            timestamp=datetime.now().isoformat(),
            fps=fps,
            cpu_percent=cpu,
            memory_mb=mem_mb,
            thread_count=threading.active_count(),
            queue_depth=qd,
            queue_maxsize=qm,
            queue_fill_pct=round(fill_pct * 100, 1),
            latency=lat,
            uptime_seconds=round(time.time() - self._start_time, 1),
            fps_ok=fps >= TARGET_FPS_MIN,
            cpu_ok=cpu <= TARGET_CPU_MAX or cpu == 0.0,
            memory_ok=mem_mb <= TARGET_MEMORY_MB_MAX or mem_mb == 0.0,
            latency_ok=lat.total_ms <= TARGET_LATENCY_MS_MAX,
            queue_ok=fill_pct <= TARGET_QUEUE_FILL_MAX,
        )
        self._snapshots.append(snap)
        return snap

    # ------------------------------------------------------------------
    # Latency percentiles
    # ------------------------------------------------------------------

    def latency_percentiles(self) -> Dict[str, float]:
        """Return P50/P95/P99 for total latency across recorded history."""
        with self._lock:
            totals = [r.total_ms for r in self._latency_history if r.total_ms > 0]
        if not totals:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
        totals_sorted = sorted(totals)
        n = len(totals_sorted)
        return {
            "p50": round(totals_sorted[int(n * 0.50)], 2),
            "p95": round(totals_sorted[min(int(n * 0.95), n - 1)], 2),
            "p99": round(totals_sorted[min(int(n * 0.99), n - 1)], 2),
            "mean": round(statistics.mean(totals), 2),
        }

    def stage_averages(self) -> Dict[str, float]:
        """Return mean latency per pipeline stage."""
        with self._lock:
            records = list(self._latency_history)
        if not records:
            return {"capture": 0.0, "parse": 0.0, "insert": 0.0, "stats": 0.0}
        return {
            "capture": round(statistics.mean(r.capture_ms for r in records), 2),
            "parse": round(statistics.mean(r.parse_ms for r in records), 2),
            "insert": round(statistics.mean(r.insert_ms for r in records), 2),
            "stats": round(statistics.mean(r.stats_ms for r in records), 2),
        }

    # ------------------------------------------------------------------
    # Thread health
    # ------------------------------------------------------------------

    def thread_health(self) -> Dict[str, object]:
        """Return a summary of live threads."""
        threads = threading.enumerate()
        return {
            "active_count": len(threads),
            "names": [t.name for t in threads],
            "daemon_count": sum(1 for t in threads if t.daemon),
        }

    # ------------------------------------------------------------------
    # Bottleneck recommendations (also used by bottleneck_analyzer)
    # ------------------------------------------------------------------

    def bottleneck_recommendations(self) -> List[str]:
        """Analyse collected data and return a list of recommendation strings."""
        recs: List[str] = []
        snap = self.get_snapshot()
        stages = self.stage_averages()
        percs = self.latency_percentiles()

        if snap.fps < TARGET_FPS_MIN:
            recs.append(
                f"[CAPTURE] FPS {snap.fps:.1f} < target {TARGET_FPS_MIN}. "
                "Consider reducing capture resolution, using a faster grab backend "
                "(mss), or lowering --fps target."
            )

        slowest = max(stages, key=lambda k: stages[k])
        if stages[slowest] > 0:
            recs.append(
                f"[BOTTLENECK] Slowest stage: '{slowest}' "
                f"(avg {stages[slowest]:.1f} ms)."
            )
            if slowest == "capture":
                recs.append(
                    "[CAPTURE] Optimise screen grab: use mss with a tight bounding "
                    "box, avoid full-screen capture."
                )
            elif slowest == "parse":
                recs.append(
                    "[PARSE] Optimise OCR/CV: reduce image scale, use grayscale "
                    "for tesseract, pre-filter ROI regions."
                )
            elif slowest == "insert":
                recs.append(
                    "[INSERT] Optimise DB: use WAL mode, batch inserts, or "
                    "increase cache_size pragma."
                )
            elif slowest == "stats":
                recs.append(
                    "[STATS] Optimise statistics update: debounce or cache "
                    "aggregated queries."
                )

        if snap.cpu_percent > TARGET_CPU_MAX:
            recs.append(
                f"[CPU] Usage {snap.cpu_percent:.1f}% exceeds {TARGET_CPU_MAX}%. "
                "Profile heavy loops; consider numpy vectorisation or frame skipping."
            )

        if snap.memory_mb > TARGET_MEMORY_MB_MAX:
            recs.append(
                f"[MEMORY] {snap.memory_mb:.0f} MB exceeds target "
                f"{TARGET_MEMORY_MB_MAX:.0f} MB. Check for growing caches or "
                "unbounded queues."
            )

        if percs["p99"] > TARGET_LATENCY_MS_MAX:
            recs.append(
                f"[LATENCY] P99 {percs['p99']:.0f} ms exceeds "
                f"{TARGET_LATENCY_MS_MAX:.0f} ms. Investigate outlier frames."
            )

        if snap.queue_fill_pct > TARGET_QUEUE_FILL_MAX * 100:
            recs.append(
                f"[QUEUE] {snap.queue_fill_pct:.0f}% full. "
                "Consumer (DB insert) is slower than producer; consider "
                "increasing queue maxsize or speeding up inserts."
            )

        if not recs:
            recs.append("✅ All metrics within target thresholds. System healthy.")

        return recs

    # ------------------------------------------------------------------
    # Output generation
    # ------------------------------------------------------------------

    def save_metrics_json(self, path: Optional[str] = None) -> str:
        """Write *performance_metrics.json* and return the path."""
        if path is None:
            path = os.path.join(self._output_dir, "performance_metrics.json")
        snap = self.get_snapshot()
        data = {
            "generated_at": datetime.now().isoformat(),
            "snapshot": asdict(snap),
            "latency_percentiles": self.latency_percentiles(),
            "stage_averages": self.stage_averages(),
            "thread_health": self.thread_health(),
            "targets": {
                "fps_min": TARGET_FPS_MIN,
                "fps_goal": TARGET_FPS_GOAL,
                "cpu_max_pct": TARGET_CPU_MAX,
                "memory_max_mb": TARGET_MEMORY_MB_MAX,
                "latency_max_ms": TARGET_LATENCY_MS_MAX,
                "queue_fill_max_pct": TARGET_QUEUE_FILL_MAX * 100,
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Metrics saved to %s", path)
        return path

    def save_bottleneck_txt(self, path: Optional[str] = None) -> str:
        """Write *bottleneck_analysis.txt* and return the path."""
        if path is None:
            path = os.path.join(self._output_dir, "bottleneck_analysis.txt")
        recs = self.bottleneck_recommendations()
        lines = [
            "=" * 60,
            "BOTTLENECK ANALYSIS",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "=" * 60,
            "",
        ]
        stages = self.stage_averages()
        percs = self.latency_percentiles()
        lines += [
            "Stage averages (ms):",
            f"  capture : {stages['capture']:.2f}",
            f"  parse   : {stages['parse']:.2f}",
            f"  insert  : {stages['insert']:.2f}",
            f"  stats   : {stages['stats']:.2f}",
            "",
            "Latency percentiles (ms):",
            f"  P50 : {percs['p50']:.2f}",
            f"  P95 : {percs['p95']:.2f}",
            f"  P99 : {percs['p99']:.2f}",
            f"  Mean: {percs['mean']:.2f}",
            "",
            "Recommendations:",
        ]
        for rec in recs:
            lines.append(f"  • {rec}")
        lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("Bottleneck analysis saved to %s", path)
        return path

    def save_html_report(self, path: Optional[str] = None) -> str:
        """Write *profiling_report.html* and return the path."""
        if path is None:
            path = os.path.join(self._output_dir, "profiling_report.html")
        snap = self.get_snapshot()
        stages = self.stage_averages()
        percs = self.latency_percentiles()
        recs = self.bottleneck_recommendations()
        threads = self.thread_health()

        def badge(ok: bool) -> str:
            colour = "#27ae60" if ok else "#e74c3c"
            symbol = "✔" if ok else "✘"
            return f'<span style="color:{colour};font-weight:bold">{symbol}</span>'

        recs_html = "".join(f"<li>{r}</li>" for r in recs)
        threads_html = "".join(
            f"<li>{n}</li>" for n in threads.get("names", [])
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Occhi di Falco – Performance Report</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
  h1 {{ color: #e94560; }}
  h2 {{ color: #0f3460; background:#16213e; padding:8px; border-radius:4px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin:16px 0; }}
  .card {{ background:#16213e; border-radius:8px; padding:16px; text-align:center; }}
  .card .value {{ font-size:2em; font-weight:bold; color:#e94560; }}
  .card .label {{ font-size:0.85em; color:#aaa; margin-top:4px; }}
  .ok {{ color:#27ae60!important; }}
  .fail {{ color:#e74c3c!important; }}
  table {{ border-collapse:collapse; width:100%; margin:12px 0; }}
  th,td {{ border:1px solid #0f3460; padding:8px; text-align:left; }}
  th {{ background:#0f3460; }}
  ul {{ line-height:1.8; }}
  .footer {{ color:#555; font-size:0.8em; margin-top:30px; }}
</style>
</head>
<body>
<h1>🎯 Occhi di Falco – Performance Profiling Report</h1>
<p>Generated: {snap.timestamp} | Uptime: {snap.uptime_seconds}s</p>

<h2>📊 Live Metrics</h2>
<div class="grid">
  <div class="card">
    <div class="value {'ok' if snap.fps_ok else 'fail'}">{snap.fps:.1f}</div>
    <div class="label">FPS {badge(snap.fps_ok)} (min {TARGET_FPS_MIN})</div>
  </div>
  <div class="card">
    <div class="value {'ok' if snap.cpu_ok else 'fail'}">{snap.cpu_percent:.1f}%</div>
    <div class="label">CPU {badge(snap.cpu_ok)} (max {TARGET_CPU_MAX}%)</div>
  </div>
  <div class="card">
    <div class="value {'ok' if snap.memory_ok else 'fail'}">{snap.memory_mb:.0f} MB</div>
    <div class="label">Memory {badge(snap.memory_ok)} (max {TARGET_MEMORY_MB_MAX:.0f} MB)</div>
  </div>
  <div class="card">
    <div class="value {'ok' if snap.latency_ok else 'fail'}">{snap.latency.total_ms:.0f} ms</div>
    <div class="label">Latency {badge(snap.latency_ok)} (max {TARGET_LATENCY_MS_MAX:.0f} ms)</div>
  </div>
  <div class="card">
    <div class="value {'ok' if snap.queue_ok else 'fail'}">{snap.queue_fill_pct:.0f}%</div>
    <div class="label">Queue Fill {badge(snap.queue_ok)} (max {int(TARGET_QUEUE_FILL_MAX*100)}%)</div>
  </div>
  <div class="card">
    <div class="value">{snap.thread_count}</div>
    <div class="label">Active Threads</div>
  </div>
</div>

<h2>⏱ Pipeline Stage Latency (avg ms)</h2>
<table>
  <tr><th>Stage</th><th>Average (ms)</th></tr>
  <tr><td>Capture</td><td>{stages['capture']:.2f}</td></tr>
  <tr><td>Parse (OCR/CV)</td><td>{stages['parse']:.2f}</td></tr>
  <tr><td>DB Insert</td><td>{stages['insert']:.2f}</td></tr>
  <tr><td>Stats Update</td><td>{stages['stats']:.2f}</td></tr>
</table>

<h2>📈 Latency Percentiles (ms)</h2>
<table>
  <tr><th>P50</th><th>P95</th><th>P99</th><th>Mean</th></tr>
  <tr>
    <td>{percs['p50']:.2f}</td>
    <td>{percs['p95']:.2f}</td>
    <td>{percs['p99']:.2f}</td>
    <td>{percs['mean']:.2f}</td>
  </tr>
</table>

<h2>🧵 Thread Health</h2>
<p>Active: {threads['active_count']} | Daemon: {threads['daemon_count']}</p>
<ul>{threads_html}</ul>

<h2>🔍 Bottleneck Recommendations</h2>
<ul>{recs_html}</ul>

<p class="footer">Occhi di Falco Performance Profiler – FASE 6</p>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("HTML report saved to %s", path)
        return path

    def save_report(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        Write all three output files and return a dict of paths.

        Returns:
            {
                "html": "<path>/profiling_report.html",
                "json": "<path>/performance_metrics.json",
                "txt":  "<path>/bottleneck_analysis.txt",
            }
        """
        d = output_dir or self._output_dir
        return {
            "html": self.save_html_report(os.path.join(d, "profiling_report.html")),
            "json": self.save_metrics_json(
                os.path.join(d, "performance_metrics.json")
            ),
            "txt": self.save_bottleneck_txt(
                os.path.join(d, "bottleneck_analysis.txt")
            ),
        }


# ---------------------------------------------------------------------------
# Background monitoring loop (optional helper)
# ---------------------------------------------------------------------------


class ProfilerDaemon:
    """
    Lightweight daemon that periodically calls ``profiler.get_snapshot()``
    and optionally saves JSON metrics.

    Usage::

        daemon = ProfilerDaemon(profiler, interval=5, auto_save=True)
        daemon.start()
        ...
        daemon.stop()
    """

    def __init__(
        self,
        profiler: PerformanceProfiler,
        interval: float = 5.0,
        auto_save: bool = False,
    ):
        self._profiler = profiler
        self._interval = interval
        self._auto_save = auto_save
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="ProfilerDaemon", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snap = self._profiler.get_snapshot()
                logger.debug(
                    "Profiler: fps=%.1f cpu=%.1f%% mem=%.0fMB latency=%.0fms queue=%d%%",
                    snap.fps,
                    snap.cpu_percent,
                    snap.memory_mb,
                    snap.latency.total_ms,
                    snap.queue_fill_pct,
                )
                if self._auto_save:
                    self._profiler.save_metrics_json()
            except Exception as exc:
                logger.warning("ProfilerDaemon error: %s", exc)
            self._stop_event.wait(self._interval)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Occhi di Falco – Performance Profiler")
    ap.add_argument("--output", default="output", help="Output directory")
    ap.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="How long to sample (seconds)",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Sampling interval (seconds)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    profiler = PerformanceProfiler(output_dir=args.output)
    daemon = ProfilerDaemon(profiler, interval=args.interval)
    daemon.start()

    print(f"Sampling for {args.duration}s …")
    time.sleep(args.duration)
    daemon.stop()

    paths = profiler.save_report(args.output)
    print("Reports written:")
    for key, p in paths.items():
        print(f"  [{key}] {p}")
