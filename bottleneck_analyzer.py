"""
FASE 6 - Bottleneck Analyzer
Identifies slow pipeline stages and provides targeted recommendations.

Inputs:  A populated PerformanceProfiler instance (or a saved
         performance_metrics.json file).

Outputs:
- bottleneck_report.html  (detailed visual analysis)
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_KEYS = ("capture", "parse", "insert", "stats")
STAGE_LABELS = {
    "capture": "Screen Capture",
    "parse": "OCR / CV Parse",
    "insert": "DB Insert",
    "stats": "Stats Update",
}


# ---------------------------------------------------------------------------
# Analysis result
# ---------------------------------------------------------------------------


@dataclass
class StageAnalysis:
    name: str
    label: str
    mean_ms: float
    p95_ms: float
    p99_ms: float
    share_pct: float          # percentage of total pipeline time
    is_bottleneck: bool
    recommendation: str


@dataclass
class BottleneckReport:
    generated_at: str
    bottleneck_stage: str
    total_mean_ms: float
    stages: List[StageAnalysis]
    cpu_spike_detected: bool
    memory_leak_suspected: bool
    queue_congested: bool
    thread_contention: bool
    overall_recommendations: List[str]


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class BottleneckAnalyzer:
    """
    Analyses pipeline performance data and identifies the primary bottleneck.

    Usage::

        from performance_profiler import PerformanceProfiler

        profiler = PerformanceProfiler()
        # … run pipeline …
        analyzer = BottleneckAnalyzer(profiler=profiler)
        report = analyzer.analyze()
        analyzer.save_html_report(report)
    """

    # CPU spike threshold (percentage)
    CPU_SPIKE_THRESHOLD = 20.0
    # Memory growth considered a leak (MB over recorded history)
    MEMORY_GROWTH_THRESHOLD_MB = 50.0
    # Queue congestion threshold (%)
    QUEUE_CONGESTION_THRESHOLD = 70.0

    def __init__(
        self,
        profiler: Optional[object] = None,
        metrics_json: Optional[str] = None,
        output_dir: str = "output",
    ):
        """
        Provide either a live ``PerformanceProfiler`` instance or the path to a
        previously saved ``performance_metrics.json`` file.
        """
        self._profiler = profiler
        self._metrics_json = metrics_json
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # internal history for memory-leak detection
        self._memory_history: Deque[float] = deque(maxlen=60)
        self._cpu_history: Deque[float] = deque(maxlen=60)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def record_memory(self, mb: float) -> None:
        """Feed a memory reading (MB) for leak detection."""
        self._memory_history.append(mb)

    def record_cpu(self, pct: float) -> None:
        """Feed a CPU reading (%) for spike detection."""
        self._cpu_history.append(pct)

    def _load_from_profiler(self) -> Dict[str, Any]:
        if self._profiler is None:
            return {}
        return {
            "stage_averages": self._profiler.stage_averages(),
            "latency_percentiles": self._profiler.latency_percentiles(),
            "snapshot": self._profiler.get_snapshot().__dict__,
        }

    def _load_from_json(self) -> Dict[str, Any]:
        if not self._metrics_json or not os.path.exists(self._metrics_json):
            return {}
        try:
            with open(self._metrics_json, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to load metrics JSON: %s", exc)
            return {}

    def _get_data(self) -> Dict[str, Any]:
        if self._profiler is not None:
            return self._load_from_profiler()
        return self._load_from_json()

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_cpu_spike(self, cpu_pct: float) -> bool:
        self._cpu_history.append(cpu_pct)
        if len(self._cpu_history) < 3:
            return cpu_pct > self.CPU_SPIKE_THRESHOLD
        mean_cpu = statistics.mean(self._cpu_history)
        return mean_cpu > self.CPU_SPIKE_THRESHOLD

    def _detect_memory_leak(self, memory_mb: float) -> bool:
        # If external readings have been seeded via record_memory(), use those.
        # Otherwise add the live snapshot value and evaluate.
        if len(self._memory_history) == 0:
            self._memory_history.append(memory_mb)
        if len(self._memory_history) < 5:
            return False
        first = list(self._memory_history)[:5]
        last = list(self._memory_history)[-5:]
        growth = statistics.mean(last) - statistics.mean(first)
        return growth > self.MEMORY_GROWTH_THRESHOLD_MB

    def _detect_queue_congestion(self, queue_fill_pct: float) -> bool:
        return queue_fill_pct > self.QUEUE_CONGESTION_THRESHOLD

    def _detect_thread_contention(self, thread_count: int) -> bool:
        # Flag if unusually high number of threads (heuristic)
        return thread_count > 20

    # ------------------------------------------------------------------
    # Per-stage recommendation
    # ------------------------------------------------------------------

    @staticmethod
    def _stage_recommendation(stage: str, mean_ms: float, is_bottleneck: bool) -> str:
        if not is_bottleneck:
            return f"Stage '{stage}' is within normal range ({mean_ms:.1f} ms)."
        tips = {
            "capture": (
                f"Screen capture is the bottleneck ({mean_ms:.1f} ms avg). "
                "Optimise: use mss with a tight bounding box, avoid full-screen "
                "grabs, reduce capture resolution, consider hardware acceleration."
            ),
            "parse": (
                f"OCR/CV parsing is the bottleneck ({mean_ms:.1f} ms avg). "
                "Optimise: convert to grayscale before tesseract, reduce image "
                "scale, restrict ROI regions, cache template matches."
            ),
            "insert": (
                f"Database insert is the bottleneck ({mean_ms:.1f} ms avg). "
                "Optimise: enable WAL journal mode, use batch inserts, add "
                "cache_size pragma, move DB to SSD or in-memory for testing."
            ),
            "stats": (
                f"Stats update is the bottleneck ({mean_ms:.1f} ms avg). "
                "Optimise: debounce aggregated queries, cache rolling averages, "
                "use indexed columns for aggregation."
            ),
        }
        return tips.get(stage, f"Stage '{stage}' is slow ({mean_ms:.1f} ms avg).")

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    def analyze(self) -> BottleneckReport:
        """
        Run the full bottleneck analysis and return a ``BottleneckReport``.
        """
        data = self._get_data()
        stage_avgs: Dict[str, float] = data.get(
            "stage_averages", {k: 0.0 for k in STAGE_KEYS}
        )
        snap: Dict[str, Any] = data.get("snapshot", {})

        cpu_pct = snap.get("cpu_percent", 0.0)
        memory_mb = snap.get("memory_mb", 0.0)
        queue_fill = snap.get("queue_fill_pct", 0.0)
        thread_count = snap.get("thread_count", threading_active_count())

        total_mean = sum(stage_avgs.get(k, 0.0) for k in STAGE_KEYS)
        bottleneck_stage = max(stage_avgs, key=lambda k: stage_avgs.get(k, 0.0)) if stage_avgs else "unknown"

        stages: List[StageAnalysis] = []
        for key in STAGE_KEYS:
            mean = stage_avgs.get(key, 0.0)
            share = round((mean / total_mean * 100) if total_mean > 0 else 0.0, 1)
            is_bn = key == bottleneck_stage and mean > 0
            stages.append(
                StageAnalysis(
                    name=key,
                    label=STAGE_LABELS[key],
                    mean_ms=round(mean, 2),
                    p95_ms=0.0,  # would need per-stage history for full percentiles
                    p99_ms=0.0,
                    share_pct=share,
                    is_bottleneck=is_bn,
                    recommendation=self._stage_recommendation(key, mean, is_bn),
                )
            )

        cpu_spike = self._detect_cpu_spike(cpu_pct)
        mem_leak = self._detect_memory_leak(memory_mb)
        queue_cong = self._detect_queue_congestion(queue_fill)
        thread_cont = self._detect_thread_contention(thread_count)

        overall: List[str] = []
        for s in stages:
            if s.is_bottleneck:
                overall.append(s.recommendation)
        if cpu_spike:
            overall.append(
                f"[CPU SPIKE] Average CPU {cpu_pct:.1f}% exceeds threshold. "
                "Profile hot loops with cProfile or py-spy."
            )
        if mem_leak:
            overall.append(
                "[MEMORY LEAK] Significant memory growth detected. "
                "Check for growing lists/dicts, unbounded caches, or circular refs. "
                "Use tracemalloc or memory_profiler to isolate the component."
            )
        if queue_cong:
            overall.append(
                f"[QUEUE] {queue_fill:.0f}% full – consumer is lagging. "
                "Speed up DB inserts or increase queue maxsize."
            )
        if thread_cont:
            overall.append(
                f"[THREADS] {thread_count} active threads – possible contention. "
                "Review locks and consider reducing thread count."
            )
        if not overall:
            overall.append("✅ No bottlenecks detected. Pipeline is healthy.")

        return BottleneckReport(
            generated_at=datetime.now().isoformat(),
            bottleneck_stage=bottleneck_stage if total_mean > 0 else "none",
            total_mean_ms=round(total_mean, 2),
            stages=stages,
            cpu_spike_detected=cpu_spike,
            memory_leak_suspected=mem_leak,
            queue_congested=queue_cong,
            thread_contention=thread_cont,
            overall_recommendations=overall,
        )

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    def save_html_report(
        self,
        report: Optional[BottleneckReport] = None,
        path: Optional[str] = None,
    ) -> str:
        """Generate *bottleneck_report.html* and return the path."""
        if report is None:
            report = self.analyze()
        if path is None:
            path = os.path.join(self._output_dir, "bottleneck_report.html")

        def bar(share: float, is_bn: bool) -> str:
            colour = "#e74c3c" if is_bn else "#3498db"
            return (
                f'<div style="background:{colour};height:20px;'
                f'width:{max(share, 1):.0f}%;border-radius:4px;'
                f'display:inline-block"></div> {share:.1f}%'
            )

        def status_badge(ok: bool, label: str) -> str:
            colour = "#27ae60" if ok else "#e74c3c"
            symbol = "✔" if ok else "✘"
            return (
                f'<span style="background:{colour};color:#fff;'
                f'padding:2px 8px;border-radius:12px;font-size:0.85em">'
                f"{symbol} {label}</span>"
            )

        stages_rows = "".join(
            f"<tr>"
            f"<td>{s.label}</td>"
            f"<td>{s.mean_ms:.2f}</td>"
            f"<td>{bar(s.share_pct, s.is_bottleneck)}</td>"
            f"<td>{'🔴 Bottleneck' if s.is_bottleneck else '🟢 OK'}</td>"
            f"</tr>"
            for s in report.stages
        )

        recs_html = "".join(
            f"<li>{r}</li>" for r in report.overall_recommendations
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Occhi di Falco – Bottleneck Report</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
  h1 {{ color: #e94560; }}
  h2 {{ color: #eee; background: #16213e; padding: 8px; border-radius: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #0f3460; padding: 10px; text-align: left; }}
  th {{ background: #0f3460; }}
  .badges {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }}
  ul {{ line-height: 1.9; }}
  .footer {{ color: #555; font-size: 0.8em; margin-top: 30px; }}
</style>
</head>
<body>
<h1>🔍 Occhi di Falco – Bottleneck Analysis Report</h1>
<p>Generated: {report.generated_at}</p>
<p>Primary bottleneck: <strong>{report.bottleneck_stage}</strong> |
   Total pipeline mean: <strong>{report.total_mean_ms:.1f} ms</strong></p>

<h2>📊 Stage Comparison</h2>
<table>
  <tr><th>Stage</th><th>Avg (ms)</th><th>Share</th><th>Status</th></tr>
  {stages_rows}
</table>

<h2>🚦 System Status</h2>
<div class="badges">
  {status_badge(not report.cpu_spike_detected, "CPU")}
  {status_badge(not report.memory_leak_suspected, "Memory")}
  {status_badge(not report.queue_congested, "Queue")}
  {status_badge(not report.thread_contention, "Threads")}
</div>

<h2>💡 Recommendations</h2>
<ul>{recs_html}</ul>

<p class="footer">Occhi di Falco Bottleneck Analyzer – FASE 6</p>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Bottleneck report saved to %s", path)
        return path


# ---------------------------------------------------------------------------
# Helper – avoid importing threading just for one call
# ---------------------------------------------------------------------------

def threading_active_count() -> int:
    import threading
    return threading.active_count()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Occhi di Falco – Bottleneck Analyzer"
    )
    ap.add_argument(
        "--metrics",
        default="output/performance_metrics.json",
        help="Path to performance_metrics.json produced by performance_profiler.py",
    )
    ap.add_argument("--output", default="output", help="Output directory")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    analyzer = BottleneckAnalyzer(metrics_json=args.metrics, output_dir=args.output)
    report = analyzer.analyze()
    html_path = analyzer.save_html_report(report)
    print(f"Primary bottleneck: {report.bottleneck_stage}")
    print(f"Report: {html_path}")
    for rec in report.overall_recommendations:
        print(f"  • {rec}")
