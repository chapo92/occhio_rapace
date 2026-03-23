"""
validate_dataset.py
===================
Process every PNG frame in a dataset directory through the Occhi di Falco
pipeline (ComputerVision + OCRProcessor) and produce:

* ``validation_report.csv``   – one row per frame with key metrics.
* ``detailed_report.json``    – full per-frame results including raw OCR text.
* ``validation_report.html``  – human-readable HTML summary with problem frames.

Usage
-----
    python utility/scripts/validate_dataset.py \\
        --dataset ./datasets/video_frames/ \\
        --output  ./output/validation/

Features
--------
* Batch processing (``--batch-size``) keeps memory usage bounded.
* Resume support: frames already in the output JSON are skipped.
* Identifies frames with confidence < ``--min-confidence`` threshold (default 0.75).
* Detailed logging to ``validation.log`` inside the output directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path so core modules are importable
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.computer_vision import ComputerVision  # noqa: E402
from core.ocr_processor import OCRProcessor       # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress bar helper (optional tqdm dependency)
# ---------------------------------------------------------------------------

def _try_import_tqdm():
    try:
        from tqdm import tqdm  # noqa: F401
        return True
    except ImportError:
        return False


class _PlainProgress:
    def __init__(self, total: int, desc: str = ""):
        self._total = total
        self._n = 0
        self._desc = desc
        print(f"{desc}: 0/{total}", end="\r", flush=True)

    def update(self, n: int = 1) -> None:
        self._n += n
        pct = 100.0 * self._n / self._total if self._total > 0 else 0.0
        print(f"{self._desc}: {self._n}/{self._total} ({pct:.1f}%)", end="\r", flush=True)

    def close(self) -> None:
        print()


# ---------------------------------------------------------------------------
# Frame processing
# ---------------------------------------------------------------------------

def _process_frame(
    frame_path: str,
    cv_module: ComputerVision,
    ocr_module: OCRProcessor,
    min_confidence: float,
) -> Dict[str, Any]:
    """
    Run table detection + OCR on a single frame image.

    Returns a dict with all measured metrics.
    """
    filename = os.path.basename(frame_path)
    result: Dict[str, Any] = {
        "filename": filename,
        "frame_path": frame_path,
        "processed_at": datetime.now().isoformat(),
        "load_error": False,
        "table_detected": False,
        "table_confidence": 0.0,
        "table_shape": "none",
        "ocr_text": "",
        "ocr_word_count": 0,
        "numbers_found": [],
        "number_count": 0,
        "cards_detected": 0,
        "is_problematic": False,
        "processing_ms": 0,
    }

    t0 = time.monotonic()

    try:
        frame = cv2.imread(frame_path, cv2.IMREAD_COLOR)
        if frame is None:
            result["load_error"] = True
            result["is_problematic"] = True
            logger.warning("Cannot load frame: %s", frame_path)
            return result

        # --- Table detection ---
        bbox, confidence, shape = cv_module.detect_poker_table_with_confidence(frame)
        result["table_detected"] = bbox is not None
        result["table_confidence"] = float(confidence)
        result["table_shape"] = shape

        # --- OCR on table region (or full frame if no table found) ---
        ocr_region = frame
        if bbox is not None:
            x, y, w, h = bbox
            ocr_region = frame[y: y + h, x: x + w]

        ocr_text = ocr_module.read_text(ocr_region)
        result["ocr_text"] = ocr_text
        result["ocr_word_count"] = len(ocr_text.split()) if ocr_text else 0

        numbers = ocr_module.read_all_numbers(ocr_region)
        result["numbers_found"] = numbers
        result["number_count"] = len(numbers)

        # --- Card detection ---
        cards = cv_module.detect_cards(frame)
        result["cards_detected"] = len(cards)

    except Exception as exc:
        logger.error("Error processing %s: %s", frame_path, exc)
        result["load_error"] = True
        result["is_problematic"] = True

    result["processing_ms"] = round((time.monotonic() - t0) * 1000, 1)
    result["is_problematic"] = (
        result["load_error"]
        or result["table_confidence"] < min_confidence
    )

    return result


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Occhi di Falco – Validation Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
    h1 {{ color: #2c3e50; }}
    h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 6px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }}
    .card {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
    .card .value {{ font-size: 2em; font-weight: bold; color: #2980b9; }}
    .card .label {{ color: #7f8c8d; font-size: 0.9em; margin-top: 4px; }}
    .card.warning .value {{ color: #e67e22; }}
    .card.danger  .value {{ color: #e74c3c; }}
    .card.success .value {{ color: #27ae60; }}
    table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    th {{ background: #2c3e50; color: white; padding: 10px; text-align: left; font-size: 0.85em; }}
    td {{ padding: 8px 10px; border-bottom: 1px solid #ecf0f1; font-size: 0.82em; }}
    tr:hover {{ background: #f8f9fa; }}
    .ok   {{ color: #27ae60; }}
    .warn {{ color: #e67e22; }}
    .bad  {{ color: #e74c3c; font-weight: bold; }}
    .generated {{ color: #95a5a6; font-size: 0.8em; margin-top: 20px; }}
  </style>
</head>
<body>
  <h1>🎯 Occhi di Falco – Validation Report</h1>
  <p>Dataset: <strong>{dataset_dir}</strong> &nbsp;|&nbsp; Generated: <strong>{generated_at}</strong></p>

  <h2>Summary</h2>
  <div class="summary-grid">
    <div class="card">
      <div class="value">{total_frames}</div>
      <div class="label">Total Frames</div>
    </div>
    <div class="card {detection_class}">
      <div class="value">{detection_rate:.1f}%</div>
      <div class="label">Table Detection Rate</div>
    </div>
    <div class="card {confidence_class}">
      <div class="value">{avg_confidence:.3f}</div>
      <div class="label">Avg Confidence</div>
    </div>
    <div class="card {problem_class}">
      <div class="value">{problematic_count}</div>
      <div class="label">Problematic Frames</div>
    </div>
    <div class="card">
      <div class="value">{avg_processing_ms:.0f}ms</div>
      <div class="label">Avg Processing Time</div>
    </div>
    <div class="card">
      <div class="value">{avg_numbers:.1f}</div>
      <div class="label">Avg Numbers / Frame</div>
    </div>
  </div>

  <h2>Problematic Frames (confidence &lt; {min_confidence})</h2>
  {problem_table}

  <h2>All Frames</h2>
  {all_table}

  <p class="generated">Report generated by validate_dataset.py on {generated_at}</p>
</body>
</html>
"""

_TABLE_HEADER = """
<table>
  <tr>
    <th>#</th><th>Filename</th><th>Table Detected</th>
    <th>Confidence</th><th>Shape</th>
    <th>OCR Words</th><th>Numbers</th><th>Cards</th>
    <th>Processing (ms)</th><th>Status</th>
  </tr>
"""


def _row_class(confidence: float, detected: bool) -> str:
    if not detected:
        return "bad"
    if confidence >= 0.75:
        return "ok"
    if confidence >= 0.50:
        return "warn"
    return "bad"


def _build_table(records: List[Dict]) -> str:
    if not records:
        return "<p><em>None</em></p>"
    rows = [_TABLE_HEADER]
    for i, r in enumerate(records, 1):
        cls = _row_class(r["table_confidence"], r["table_detected"])
        detected_str = "✅" if r["table_detected"] else "❌"
        rows.append(
            f"<tr>"
            f"<td>{i}</td>"
            f"<td>{r['filename']}</td>"
            f"<td>{detected_str}</td>"
            f"<td class='{cls}'>{r['table_confidence']:.3f}</td>"
            f"<td>{r['table_shape']}</td>"
            f"<td>{r['ocr_word_count']}</td>"
            f"<td>{r['number_count']}</td>"
            f"<td>{r['cards_detected']}</td>"
            f"<td>{r['processing_ms']}</td>"
            f"<td class='{cls}'>{'⚠ Problem' if r['is_problematic'] else 'OK'}</td>"
            f"</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _generate_html(
    results: List[Dict],
    dataset_dir: str,
    min_confidence: float,
) -> str:
    total = len(results)
    detected_count = sum(1 for r in results if r["table_detected"])
    detection_rate = 100.0 * detected_count / total if total > 0 else 0.0
    avg_conf = (
        sum(r["table_confidence"] for r in results) / total if total > 0 else 0.0
    )
    problematic = [r for r in results if r["is_problematic"]]
    avg_proc = (
        sum(r["processing_ms"] for r in results) / total if total > 0 else 0.0
    )
    avg_nums = (
        sum(r["number_count"] for r in results) / total if total > 0 else 0.0
    )

    def _rate_class(rate: float) -> str:
        if rate >= 75:
            return "success"
        if rate >= 50:
            return "warning"
        return "danger"

    return _HTML_TEMPLATE.format(
        dataset_dir=dataset_dir,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_frames=total,
        detection_rate=detection_rate,
        detection_class=_rate_class(detection_rate),
        avg_confidence=avg_conf,
        confidence_class=_rate_class(avg_conf * 100),
        problematic_count=len(problematic),
        problem_class="danger" if problematic else "success",
        avg_processing_ms=avg_proc,
        avg_numbers=avg_nums,
        min_confidence=min_confidence,
        problem_table=_build_table(problematic),
        all_table=_build_table(results),
    )


# ---------------------------------------------------------------------------
# Main validation loop
# ---------------------------------------------------------------------------

def validate_dataset(
    dataset_dir: str,
    output_dir: str,
    min_confidence: float = 0.75,
    batch_size: int = 50,
) -> Dict:
    """
    Process all PNG frames in *dataset_dir* and write reports to *output_dir*.

    Parameters
    ----------
    dataset_dir : str
        Directory containing PNG frames (produced by extract_frames_from_video.py).
    output_dir : str
        Where reports will be written.
    min_confidence : float
        Frames below this table-detection confidence are flagged as problematic.
    batch_size : int
        Number of frames per processing batch (memory efficiency).

    Returns
    -------
    dict
        Validation summary.
    """
    dataset_path = Path(dataset_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Configure file-based logging
    log_file = output_path / "validation.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(fh)

    json_report_path = output_path / "detailed_report.json"
    csv_report_path = output_path / "validation_report.csv"
    html_report_path = output_path / "validation_report.html"

    # Collect frame files
    frame_files = sorted(
        p for p in dataset_path.iterdir()
        if p.suffix.lower() == ".png"
    )
    if not frame_files:
        raise FileNotFoundError(f"No PNG frames found in: {dataset_dir}")

    logger.info("Found %d PNG frames in %s", len(frame_files), dataset_dir)

    # Resume support: load already-processed results
    existing_results: Dict[str, Dict] = {}
    if json_report_path.exists():
        try:
            with open(json_report_path, "r", encoding="utf-8") as f:
                for r in json.load(f):
                    existing_results[r["filename"]] = r
            logger.info("Resuming: %d frames already processed", len(existing_results))
        except (json.JSONDecodeError, KeyError):
            existing_results = {}

    pending = [f for f in frame_files if f.name not in existing_results]
    logger.info("Frames to process: %d (skipping %d)", len(pending), len(existing_results))

    print(f"\n{'='*60}")
    print(f"  Validating dataset: {dataset_dir}")
    print(f"  Total frames  : {len(frame_files)}")
    print(f"  Pending       : {len(pending)}")
    print(f"  Batch size    : {batch_size}")
    print(f"  Min confidence: {min_confidence}")
    print(f"  Output dir    : {output_dir}")
    print(f"{'='*60}\n")

    cv_module = ComputerVision()
    ocr_module = OCRProcessor()

    all_results: List[Dict] = list(existing_results.values())

    use_tqdm = _try_import_tqdm()
    if use_tqdm:
        from tqdm import tqdm
        progress = tqdm(total=len(pending), unit="frame", desc="Validating")
    else:
        progress = _PlainProgress(total=len(pending), desc="Validating")

    # Process in batches for memory efficiency
    for batch_start in range(0, len(pending), batch_size):
        batch = pending[batch_start: batch_start + batch_size]
        for frame_path in batch:
            result = _process_frame(
                str(frame_path), cv_module, ocr_module, min_confidence
            )
            all_results.append(result)
            progress.update(1)

        # Persist after each batch (partial results on interruption)
        _write_json(all_results, json_report_path)

    progress.close()

    # Final writes
    _write_json(all_results, json_report_path)
    _write_csv(all_results, csv_report_path)
    html_content = _generate_html(all_results, dataset_dir, min_confidence)
    html_report_path.write_text(html_content, encoding="utf-8")

    # Summary statistics
    total = len(all_results)
    detected = sum(1 for r in all_results if r["table_detected"])
    problematic = sum(1 for r in all_results if r["is_problematic"])
    avg_conf = sum(r["table_confidence"] for r in all_results) / total if total > 0 else 0.0

    summary = {
        "total_frames": total,
        "frames_with_table": detected,
        "detection_rate_pct": round(100.0 * detected / total, 2) if total > 0 else 0.0,
        "avg_confidence": round(avg_conf, 4),
        "problematic_frames": problematic,
        "problematic_rate_pct": round(100.0 * problematic / total, 2) if total > 0 else 0.0,
        "min_confidence_threshold": min_confidence,
        "json_report": str(json_report_path.resolve()),
        "csv_report": str(csv_report_path.resolve()),
        "html_report": str(html_report_path.resolve()),
    }

    print(f"\n{'='*60}")
    print(f"  ✅ Validation complete!")
    print(f"  Total frames      : {total}")
    print(f"  Table detected    : {detected} ({summary['detection_rate_pct']:.1f}%)")
    print(f"  Avg confidence    : {avg_conf:.3f}")
    print(f"  Problematic frames: {problematic} ({summary['problematic_rate_pct']:.1f}%)")
    print(f"  Reports written to: {output_dir}")
    print(f"{'='*60}\n")

    logger.info("Validation summary: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# CSV helper
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "filename", "processed_at", "load_error",
    "table_detected", "table_confidence", "table_shape",
    "ocr_word_count", "number_count", "cards_detected",
    "is_problematic", "processing_ms",
]


def _write_json(records: List[Dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)


def _write_csv(records: List[Dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate a dataset of PNG frames through the Occhi di Falco pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--dataset",
        required=True,
        help="Directory containing PNG frames",
    )
    p.add_argument(
        "--output",
        default="./output/validation/",
        help="Output directory for reports",
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=0.75,
        help="Frames below this confidence are flagged as problematic",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of frames per processing batch",
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
        summary = validate_dataset(
            dataset_dir=args.dataset,
            output_dir=args.output,
            min_confidence=args.min_confidence,
            batch_size=args.batch_size,
        )
        print(json.dumps(summary, indent=2))
        return 0
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
