"""
generate_accuracy_report.py
============================
Read ``detailed_report.json`` produced by ``validate_dataset.py`` and generate:

* ``accuracy_report.html``  – full interactive HTML report with charts.
* ``summary.txt``           – plain-text human-readable summary.
* ``accuracy_export.csv``   – CSV export of all per-frame metrics.

Usage
-----
    python utility/scripts/generate_accuracy_report.py \\
        --input  ./output/validation/detailed_report.json \\
        --output ./output/reports/

Features
--------
* Confidence trend chart (Chart.js via CDN – no extra Python dependency).
* Table detection rate chart.
* Top-10 problematic frames highlighted.
* Fine-tuning recommendations based on aggregate statistics.
* Pure-Python HTML generation – no additional template engine required.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_report(json_path: str) -> List[Dict[str, Any]]:
    """Load and validate the detailed_report.json produced by validate_dataset.py."""
    path = Path(json_path)
    if not path.is_file():
        raise FileNotFoundError(f"Input report not found: {json_path!r}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("detailed_report.json must contain a JSON array")
    return data


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _compute_stats(records: List[Dict]) -> Dict[str, Any]:
    """Compute aggregate statistics from the record list."""
    total = len(records)
    if total == 0:
        return {}

    detected = sum(1 for r in records if r.get("table_detected"))
    problematic = [r for r in records if r.get("is_problematic")]
    confidences = [r.get("table_confidence", 0.0) for r in records]
    word_counts = [r.get("ocr_word_count", 0) for r in records]
    number_counts = [r.get("number_count", 0) for r in records]
    proc_times = [r.get("processing_ms", 0) for r in records]

    load_errors = sum(1 for r in records if r.get("load_error"))

    shapes: Dict[str, int] = {}
    for r in records:
        s = r.get("table_shape", "unknown")
        shapes[s] = shapes.get(s, 0) + 1

    top_problematic = sorted(
        problematic, key=lambda r: r.get("table_confidence", 0.0)
    )[:10]

    def avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    def pct(n):
        return round(100.0 * n / total, 2)

    return {
        "total_frames": total,
        "frames_with_table": detected,
        "detection_rate_pct": pct(detected),
        "avg_confidence": round(avg(confidences), 4),
        "min_confidence": round(min(confidences), 4),
        "max_confidence": round(max(confidences), 4),
        "problematic_count": len(problematic),
        "problematic_rate_pct": pct(len(problematic)),
        "load_errors": load_errors,
        "avg_ocr_word_count": round(avg(word_counts), 2),
        "avg_number_count": round(avg(number_counts), 2),
        "avg_processing_ms": round(avg(proc_times), 1),
        "shapes": shapes,
        "top_problematic": top_problematic,
    }


# ---------------------------------------------------------------------------
# Fine-tuning recommendations
# ---------------------------------------------------------------------------

def _build_recommendations(stats: Dict) -> List[str]:
    recs: List[str] = []
    detection_rate = stats.get("detection_rate_pct", 0.0)
    avg_conf = stats.get("avg_confidence", 0.0)
    prob_rate = stats.get("problematic_rate_pct", 0.0)
    avg_words = stats.get("avg_ocr_word_count", 0)

    if detection_rate < 50.0:
        recs.append(
            "⚠️  Table detection rate is very low (<50%). "
            "Recalibrate the HSV colour range for the blue felt using "
            "calibration.py or cv_module.calibrate() with sample frames."
        )
    elif detection_rate < 75.0:
        recs.append(
            "🔧 Table detection rate is below 75%. "
            "Consider widening the BLUE_HSV_LOWER/UPPER range in "
            "core/computer_vision.py (current: H 100-140)."
        )

    if avg_conf < 0.5:
        recs.append(
            "⚠️  Average confidence is very low (<0.50). "
            "The poker table colour may differ from the expected HSV range. "
            "Run calibration on a sample of frames from this video."
        )
    elif avg_conf < 0.75:
        recs.append(
            "🔧 Average confidence is below 0.75. "
            "Fine-tune MIN_TABLE_AREA in core/computer_vision.py "
            "if the table appears small in the video."
        )

    if prob_rate > 30.0:
        recs.append(
            "🔧 More than 30% of frames are problematic. "
            "Review the top-10 problematic frames in this report "
            "and check for lighting changes, overlays, or HUD elements "
            "that may occlude the table."
        )

    if avg_words < 2:
        recs.append(
            "🔧 OCR is extracting very few words per frame on average. "
            "Verify that pytesseract/EasyOCR is correctly installed and "
            "that the table region ROI is not too small."
        )

    if not recs:
        recs.append(
            "✅ All metrics look good. "
            "Table detection and OCR appear to be working correctly for this video."
        )

    return recs


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_EXPORT_FIELDS = [
    "filename", "processed_at", "table_detected", "table_confidence",
    "table_shape", "ocr_word_count", "number_count", "cards_detected",
    "is_problematic", "processing_ms",
]


def _write_csv(records: List[Dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _build_html_report(
    records: List[Dict],
    stats: Dict,
    recs: List[str],
    input_path: str,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Prepare chart data (first 500 records for readability)
    chart_records = records[:500]
    labels_js = json.dumps([r.get("filename", "") for r in chart_records])
    confidences_js = json.dumps([round(r.get("table_confidence", 0.0), 3) for r in chart_records])
    detected_js = json.dumps([1 if r.get("table_detected") else 0 for r in chart_records])

    # Shapes pie data
    shapes = stats.get("shapes", {})
    shape_labels_js = json.dumps(list(shapes.keys()))
    shape_values_js = json.dumps(list(shapes.values()))

    # Problematic frames table
    top_problematic = stats.get("top_problematic", [])

    prob_rows = "\n".join(
        f"<tr>"
        f"<td>{i + 1}</td>"
        f"<td>{r.get('filename', '')}</td>"
        f"<td class='bad'>{r.get('table_confidence', 0.0):.3f}</td>"
        f"<td>{'✅' if r.get('table_detected') else '❌'}</td>"
        f"<td>{r.get('table_shape', '-')}</td>"
        f"<td>{r.get('ocr_word_count', 0)}</td>"
        f"<td>{r.get('processing_ms', 0):.0f}ms</td>"
        f"</tr>"
        for i, r in enumerate(top_problematic)
    ) or "<tr><td colspan='7'><em>None</em></td></tr>"

    recs_html = "\n".join(f"<li>{rec}</li>" for rec in recs)

    detection_class = (
        "success" if stats.get("detection_rate_pct", 0) >= 75
        else "warning" if stats.get("detection_rate_pct", 0) >= 50
        else "danger"
    )
    confidence_class = (
        "success" if stats.get("avg_confidence", 0) >= 0.75
        else "warning" if stats.get("avg_confidence", 0) >= 0.50
        else "danger"
    )
    problem_class = "success" if stats.get("problematic_count", 0) == 0 else "danger"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Occhi di Falco – Accuracy Report</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; color: #2c3e50; }}
    h1   {{ color: #2c3e50; }}
    h2   {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 6px; margin-top: 32px; }}
    .summary-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 20px 0;
    }}
    .card {{
      background: white; border-radius: 8px; padding: 16px;
      box-shadow: 0 2px 4px rgba(0,0,0,.1); text-align: center;
    }}
    .card .value {{ font-size: 2em; font-weight: bold; color: #2980b9; }}
    .card .label {{ color: #7f8c8d; font-size: .9em; margin-top: 4px; }}
    .card.warning .value {{ color: #e67e22; }}
    .card.danger  .value {{ color: #e74c3c; }}
    .card.success .value {{ color: #27ae60; }}
    .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 20px 0; }}
    .chart-box {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
    .chart-box-full {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,.1); margin: 20px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,.1); margin-top: 12px; }}
    th {{ background: #2c3e50; color: white; padding: 10px; text-align: left; font-size: .85em; }}
    td {{ padding: 8px 10px; border-bottom: 1px solid #ecf0f1; font-size: .82em; }}
    tr:hover {{ background: #f8f9fa; }}
    .ok   {{ color: #27ae60; }}
    .warn {{ color: #e67e22; }}
    .bad  {{ color: #e74c3c; font-weight: bold; }}
    .recs {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
    .recs li {{ margin: 8px 0; line-height: 1.5; }}
    .generated {{ color: #95a5a6; font-size: .8em; margin-top: 20px; }}
    @media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>🎯 Occhi di Falco – Accuracy Report</h1>
  <p>
    Input: <strong>{os.path.basename(input_path)}</strong>
    &nbsp;|&nbsp;
    Generated: <strong>{generated_at}</strong>
  </p>

  <h2>Summary Statistics</h2>
  <div class="summary-grid">
    <div class="card">
      <div class="value">{stats.get('total_frames', 0)}</div>
      <div class="label">Total Frames</div>
    </div>
    <div class="card {detection_class}">
      <div class="value">{stats.get('detection_rate_pct', 0):.1f}%</div>
      <div class="label">Table Detection Rate</div>
    </div>
    <div class="card {confidence_class}">
      <div class="value">{stats.get('avg_confidence', 0):.3f}</div>
      <div class="label">Avg Confidence</div>
    </div>
    <div class="card {problem_class}">
      <div class="value">{stats.get('problematic_count', 0)}</div>
      <div class="label">Problematic Frames</div>
    </div>
    <div class="card">
      <div class="value">{stats.get('avg_processing_ms', 0):.0f}ms</div>
      <div class="label">Avg Processing Time</div>
    </div>
    <div class="card">
      <div class="value">{stats.get('avg_number_count', 0):.1f}</div>
      <div class="label">Avg Numbers / Frame</div>
    </div>
    <div class="card">
      <div class="value">{stats.get('min_confidence', 0):.3f}</div>
      <div class="label">Min Confidence</div>
    </div>
    <div class="card">
      <div class="value">{stats.get('max_confidence', 0):.3f}</div>
      <div class="label">Max Confidence</div>
    </div>
  </div>

  <h2>Charts</h2>
  <div class="chart-box-full">
    <canvas id="confidenceChart" height="80"></canvas>
  </div>
  <div class="charts">
    <div class="chart-box">
      <canvas id="detectionChart"></canvas>
    </div>
    <div class="chart-box">
      <canvas id="shapesChart"></canvas>
    </div>
  </div>

  <h2>Top 10 Problematic Frames</h2>
  <table>
    <tr>
      <th>#</th><th>Filename</th><th>Confidence</th>
      <th>Detected</th><th>Shape</th><th>OCR Words</th><th>Processing</th>
    </tr>
    {prob_rows}
  </table>

  <h2>Recommendations for Fine-Tuning</h2>
  <div class="recs">
    <ul>
      {recs_html}
    </ul>
  </div>

  <p class="generated">Report generated by generate_accuracy_report.py on {generated_at}</p>

  <script>
  // Confidence trend chart
  const labels = {labels_js};
  const confidences = {confidences_js};
  const detected = {detected_js};

  // Sample for readability if too many points
  const step = Math.max(1, Math.floor(labels.length / 200));
  const sampledLabels = labels.filter((_, i) => i % step === 0);
  const sampledConf   = confidences.filter((_, i) => i % step === 0);

  new Chart(document.getElementById('confidenceChart'), {{
    type: 'line',
    data: {{
      labels: sampledLabels,
      datasets: [{{
        label: 'Table Confidence',
        data: sampledConf,
        borderColor: '#3498db',
        backgroundColor: 'rgba(52,152,219,.1)',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.2,
        fill: true,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{
        title: {{ display: true, text: 'Confidence Trend Over Frames' }},
        legend: {{ display: false }},
      }},
      scales: {{
        y: {{ min: 0, max: 1.05, title: {{ display: true, text: 'Confidence' }} }},
        x: {{ ticks: {{ maxTicksLimit: 20 }} }},
      }},
    }}
  }});

  // Detection rate doughnut
  const detectedCount = detected.reduce((a, b) => a + b, 0);
  const notDetected = detected.length - detectedCount;
  new Chart(document.getElementById('detectionChart'), {{
    type: 'doughnut',
    data: {{
      labels: ['Table Detected', 'Not Detected'],
      datasets: [{{
        data: [detectedCount, notDetected],
        backgroundColor: ['#27ae60', '#e74c3c'],
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ title: {{ display: true, text: 'Table Detection Result' }} }},
    }}
  }});

  // Table shapes pie
  const shapeLabels = {shape_labels_js};
  const shapeValues = {shape_values_js};
  new Chart(document.getElementById('shapesChart'), {{
    type: 'pie',
    data: {{
      labels: shapeLabels,
      datasets: [{{
        data: shapeValues,
        backgroundColor: ['#3498db','#e67e22','#9b59b6','#1abc9c','#95a5a6'],
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ title: {{ display: true, text: 'Detected Table Shapes' }} }},
    }}
  }});
  </script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# Summary text
# ---------------------------------------------------------------------------

def _build_summary_txt(stats: Dict, recs: List[str], input_path: str) -> str:
    lines = [
        "=" * 60,
        "  OCCHI DI FALCO – ACCURACY REPORT SUMMARY",
        "=" * 60,
        f"  Input : {input_path}",
        f"  Date  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "  METRICS",
        f"  Total frames          : {stats.get('total_frames', 0)}",
        f"  Table detected        : {stats.get('frames_with_table', 0)} ({stats.get('detection_rate_pct', 0):.1f}%)",
        f"  Avg confidence        : {stats.get('avg_confidence', 0):.4f}",
        f"  Min / Max confidence  : {stats.get('min_confidence', 0):.4f} / {stats.get('max_confidence', 0):.4f}",
        f"  Problematic frames    : {stats.get('problematic_count', 0)} ({stats.get('problematic_rate_pct', 0):.1f}%)",
        f"  Avg processing time   : {stats.get('avg_processing_ms', 0):.1f}ms",
        f"  Avg OCR word count    : {stats.get('avg_ocr_word_count', 0):.2f}",
        f"  Avg number count      : {stats.get('avg_number_count', 0):.2f}",
        "",
        "  TABLE SHAPES",
    ]
    for shape, count in stats.get("shapes", {}).items():
        pct = 100.0 * count / stats.get("total_frames", 1)
        lines.append(f"    {shape:<20s}: {count} ({pct:.1f}%)")

    lines += ["", "  TOP 10 PROBLEMATIC FRAMES"]
    for i, r in enumerate(stats.get("top_problematic", []), 1):
        lines.append(
            f"    {i:2d}. {r.get('filename', ''):<40s} conf={r.get('table_confidence', 0):.3f}"
        )

    lines += ["", "  RECOMMENDATIONS"]
    for rec in recs:
        # Strip emoji for plain text
        clean = rec.encode("ascii", errors="ignore").decode("ascii").strip()
        lines.append(f"  - {clean}")

    lines += ["", "=" * 60]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_accuracy_report(
    input_path: str,
    output_dir: str,
) -> Dict:
    """
    Read *input_path* (detailed_report.json) and write accuracy reports to
    *output_dir*.

    Returns
    -------
    dict
        Paths to all generated output files.
    """
    records = _load_report(input_path)
    stats = _compute_stats(records)
    recs = _build_recommendations(stats)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    html_path = output_path / "accuracy_report.html"
    summary_path = output_path / "summary.txt"
    csv_path = output_path / "accuracy_export.csv"

    html_content = _build_html_report(records, stats, recs, input_path)
    html_path.write_text(html_content, encoding="utf-8")

    summary_txt = _build_summary_txt(stats, recs, input_path)
    summary_path.write_text(summary_txt, encoding="utf-8")

    _write_csv(records, csv_path)

    result = {
        "html_report": str(html_path.resolve()),
        "summary_txt": str(summary_path.resolve()),
        "csv_export": str(csv_path.resolve()),
        "stats": stats,
    }

    print(f"\n{'='*60}")
    print(f"  ✅ Accuracy report generated!")
    print(f"  HTML  : {html_path}")
    print(f"  TXT   : {summary_path}")
    print(f"  CSV   : {csv_path}")
    print(f"\n  Detection rate : {stats.get('detection_rate_pct', 0):.1f}%")
    print(f"  Avg confidence : {stats.get('avg_confidence', 0):.4f}")
    print(f"  Problematic    : {stats.get('problematic_count', 0)} frames")
    print(f"{'='*60}\n")

    for rec in recs:
        print(f"  {rec}")

    return result


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------

_CSV_EXPORT_FIELDS = [
    "filename", "processed_at", "table_detected", "table_confidence",
    "table_shape", "ocr_word_count", "number_count", "cards_detected",
    "is_problematic", "processing_ms",
]


def _write_csv(records: List[Dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate accuracy report from detailed_report.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", required=True, help="Path to detailed_report.json")
    p.add_argument(
        "--output",
        default="./output/reports/",
        help="Output directory for reports",
    )
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        result = generate_accuracy_report(
            input_path=args.input,
            output_dir=args.output,
        )
        print(json.dumps({k: v for k, v in result.items() if k != "stats"}, indent=2))
        return 0
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
