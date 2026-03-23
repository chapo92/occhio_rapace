"""
extract_frames_from_video.py
============================
Extract PNG frames from an MP4 video at a configurable rate (default 2 FPS).

Usage
-----
    python utility/scripts/extract_frames_from_video.py \\
        --input /path/to/video.mp4 \\
        --output ./datasets/video_frames/ \\
        --fps 2

Outputs
-------
* PNG frames named ``frame_NNNNNN_<timestamp_ms>.png`` in *output* directory.
* ``metadata.json`` alongside the frames with per-frame timestamp data.

Features
--------
* Live progress bar (via tqdm if available, plain counter otherwise).
* Metadata JSON with timestamp for every saved frame.
* Resume support: skips frames that already exist on disk.
* Robust error handling – a corrupted frame is logged and skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import cv2

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
    """Fallback progress indicator when tqdm is not installed."""

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
        print()  # newline after progress


# ---------------------------------------------------------------------------
# Core extraction logic
# ---------------------------------------------------------------------------

def extract_frames(
    input_path: str,
    output_dir: str,
    target_fps: float = 2.0,
) -> Dict:
    """
    Extract frames from *input_path* at *target_fps* and write them to
    *output_dir*.

    Parameters
    ----------
    input_path : str
        Path to the source MP4 (or any OpenCV-supported video).
    output_dir : str
        Directory where PNG frames and ``metadata.json`` will be written.
    target_fps : float
        How many frames per second to extract (default 2.0 → every 0.5 s).

    Returns
    -------
    dict
        Summary with keys: ``total_frames_extracted``, ``total_frames_skipped``,
        ``video_duration_s``, ``output_dir``, ``metadata_path``.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path!r}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    metadata_path = output_path / "metadata.json"

    # Load existing metadata for resume support
    existing_metadata: Dict[str, Dict] = {}
    if metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                existing_metadata = {m["filename"]: m for m in json.load(f)}
            logger.info("Loaded %d existing frame records (resume mode)", len(existing_metadata))
        except (json.JSONDecodeError, KeyError):
            existing_metadata = {}

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path!r}")

    source_fps: float = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_video_frames: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s: float = total_video_frames / source_fps

    # How many source frames to skip between saves
    frame_interval: int = max(1, round(source_fps / target_fps))
    expected_frames: int = max(1, total_video_frames // frame_interval)

    logger.info("Video : %s", input_path)
    logger.info("Source FPS   : %.2f | Duration: %.1f s | Total frames: %d", source_fps, duration_s, total_video_frames)
    logger.info("Target FPS   : %.2f | Frame interval: %d | Expected saves: ~%d", target_fps, frame_interval, expected_frames)
    logger.info("Output dir   : %s", output_dir)

    print(f"\n{'='*60}")
    print(f"  Extracting frames from: {os.path.basename(input_path)}")
    print(f"  Source FPS: {source_fps:.1f}  |  Target FPS: {target_fps}")
    print(f"  Duration: {duration_s:.1f}s  |  Expected frames: ~{expected_frames}")
    print(f"  Output: {output_dir}")
    print(f"{'='*60}\n")

    use_tqdm = _try_import_tqdm()
    if use_tqdm:
        from tqdm import tqdm
        progress = tqdm(total=expected_frames, unit="frame", desc="Extracting")
    else:
        progress = _PlainProgress(total=expected_frames, desc="Extracting")

    frame_records: List[Dict] = list(existing_metadata.values())
    extracted = 0
    skipped = 0
    errors = 0
    source_frame_idx = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if source_frame_idx % frame_interval == 0:
                timestamp_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                timestamp_s = timestamp_ms / 1000.0
                save_idx = source_frame_idx // frame_interval
                filename = f"frame_{save_idx:06d}_{timestamp_ms:08d}.png"
                filepath = output_path / filename

                if filename in existing_metadata:
                    # Frame already exists from a previous run
                    skipped += 1
                else:
                    try:
                        cv2.imwrite(str(filepath), frame)
                        record = {
                            "filename": filename,
                            "frame_index": save_idx,
                            "source_frame": source_frame_idx,
                            "timestamp_ms": timestamp_ms,
                            "timestamp_s": round(timestamp_s, 3),
                            "width": frame.shape[1],
                            "height": frame.shape[0],
                        }
                        frame_records.append(record)
                        extracted += 1
                    except Exception as exc:
                        logger.warning("Failed to save frame %d: %s", source_frame_idx, exc)
                        errors += 1

                progress.update(1)

            source_frame_idx += 1

    finally:
        cap.release()
        progress.close()

    # Persist metadata
    frame_records.sort(key=lambda r: r["frame_index"])
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(frame_records, f, indent=2)

    summary = {
        "total_frames_extracted": extracted,
        "total_frames_skipped": skipped,
        "total_frames_errors": errors,
        "total_frames_saved": len(frame_records),
        "video_duration_s": round(duration_s, 3),
        "source_fps": round(source_fps, 3),
        "target_fps": target_fps,
        "output_dir": str(output_path.resolve()),
        "metadata_path": str(metadata_path.resolve()),
    }

    print(f"\n{'='*60}")
    print(f"  ✅ Extraction complete!")
    print(f"  Frames extracted : {extracted}")
    print(f"  Frames skipped   : {skipped} (resume)")
    print(f"  Errors           : {errors}")
    print(f"  Total on disk    : {len(frame_records)}")
    print(f"  Metadata         : {metadata_path}")
    print(f"{'='*60}\n")

    logger.info("Extraction complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract PNG frames from a video at a target FPS.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", required=True, help="Path to input MP4 video")
    p.add_argument(
        "--output",
        default="./datasets/video_frames/",
        help="Output directory for PNG frames",
    )
    p.add_argument(
        "--fps",
        type=float,
        default=2.0,
        help="Target extraction rate in frames per second",
    )
    p.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        summary = extract_frames(
            input_path=args.input,
            output_dir=args.output,
            target_fps=args.fps,
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
