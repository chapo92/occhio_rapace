"""
Occhi di Falco - Pipeline Integration Script (v2.0 + v2.1)
Connects screen capture → OCR → parsing → database → statistics.

Architecture
------------
  Producer thread  : capture frame → parse → enqueue PokerHandData
  Consumer thread  : dequeue → DB insert (with transaction rollback) →
                     update stats cache
  Main thread      : CLI dashboard loop + graceful shutdown

Usage
-----
    python pipeline.py [--fps 2] [--platform 888poker] [--db poker.db]
                       [--output output/] [--region left,top,width,height]
                       [--max-frames N] [--debug]
"""

from __future__ import annotations

import argparse
import logging
import queue
import signal
import sys
import threading
import time
from typing import Any, Dict, Optional

from config import load_config
from screen_capture import ScreenCapture
from ocr_processor import OCRProcessor
from computer_vision import ComputerVision
from poker_parser import PokerParser
from data_exporter import DataExporter
from database import DatabaseManager


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(cfg: dict) -> None:
    """Configure root logger from *cfg*."""
    logging.basicConfig(
        level=cfg["log_level"],
        format=cfg["log_format"],
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg["log_file"], encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Occhi di Falco – integrated pipeline (capture + DB)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument(
        "--platform",
        choices=["pokerstars", "888poker"],
        default=None,
    )
    parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    parser.add_argument("--output", type=str, default=None, help="JSON output directory")
    parser.add_argument("--region", type=str, default=None, help="left,top,width,height")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--queue-size",
        type=int,
        default=None,
        help="Max items in the inter-thread queue",
    )
    return parser.parse_args()


def _parse_region(region_str: str) -> tuple:
    parts = [int(x.strip()) for x in region_str.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Invalid region string: {region_str!r}")
    return tuple(parts)


# ---------------------------------------------------------------------------
# Sentinel for queue shutdown
# ---------------------------------------------------------------------------

_STOP_SENTINEL = object()


# ---------------------------------------------------------------------------
# Producer thread – capture + parse
# ---------------------------------------------------------------------------


class ProducerThread(threading.Thread):
    """
    Continuously captures frames, parses them, and pushes results to *out_q*.

    Pushes ``_STOP_SENTINEL`` to the queue when done so the consumer can exit.

    Parameters
    ----------
    capture : ScreenCapture
    parser  : PokerParser
    exporter: DataExporter
    out_q   : queue.Queue
    max_frames : int
        Stop after this many successfully parsed frames (0 = run forever).
    stop_event : threading.Event
        Setting this event causes the producer to finish its current frame
        and then exit cleanly.
    """

    def __init__(
        self,
        capture: ScreenCapture,
        parser: PokerParser,
        exporter: DataExporter,
        out_q: "queue.Queue[Any]",
        max_frames: int = 0,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        super().__init__(name="producer", daemon=True)
        self.capture = capture
        self.parser = parser
        self.exporter = exporter
        self.out_q = out_q
        self.max_frames = max_frames
        self.stop_event = stop_event or threading.Event()
        self._logger = logging.getLogger(__name__ + ".producer")

    def run(self) -> None:
        self._logger.info("Producer started")
        frame_count = 0

        for frame in self.capture.capture_continuous():
            if self.stop_event.is_set():
                break

            # --- parse ---
            try:
                hand_data = self.parser.parse_frame(frame)
            except Exception as exc:
                self._logger.exception("Parse error (skipping frame): %s", exc)
                continue

            # --- export to JSON ---
            try:
                self.exporter.export(hand_data)
            except Exception as exc:
                self._logger.warning("JSON export error: %s", exc)

            # --- enqueue for DB consumer ---
            try:
                self.out_q.put(hand_data, timeout=5)
            except queue.Full:
                self._logger.warning("Queue full – dropping frame")

            frame_count += 1
            self._logger.debug("Produced frame %d", frame_count)

            if self.max_frames and frame_count >= self.max_frames:
                self._logger.info("Reached max-frames (%d) – stopping producer", self.max_frames)
                break

        # Signal consumer to stop
        self.out_q.put(_STOP_SENTINEL)
        self._logger.info("Producer finished after %d frames", frame_count)


# ---------------------------------------------------------------------------
# Consumer thread – DB insert
# ---------------------------------------------------------------------------


class ConsumerThread(threading.Thread):
    """
    Reads parsed hand data from *in_q* and persists it to the database.

    On database errors the transaction is automatically rolled back
    (handled inside :meth:`DatabaseManager.insert_hand_data`).

    Parameters
    ----------
    db          : DatabaseManager
    session_id  : int
    in_q        : queue.Queue
    stats_cache : dict
        Mutable dict updated after each successful insert so the main thread
        can display live statistics.
    """

    def __init__(
        self,
        db: DatabaseManager,
        session_id: int,
        in_q: "queue.Queue[Any]",
        stats_cache: Dict[str, Any],
    ) -> None:
        super().__init__(name="consumer", daemon=True)
        self.db = db
        self.session_id = session_id
        self.in_q = in_q
        self.stats_cache = stats_cache
        self._logger = logging.getLogger(__name__ + ".consumer")
        self._insert_count = 0
        self._error_count = 0

    def run(self) -> None:
        self._logger.info("Consumer started (session_id=%d)", self.session_id)

        while True:
            try:
                item = self.in_q.get(timeout=1)
            except queue.Empty:
                continue

            if item is _STOP_SENTINEL:
                self._logger.info("Consumer received stop sentinel – exiting")
                break

            # --- DB insert with automatic rollback on error ---
            try:
                hand_id = self.db.insert_hand_data(self.session_id, item)
                if hand_id is not None:
                    self._insert_count += 1
                    self._logger.debug(
                        "DB insert ok: hand_id=%d total=%d", hand_id, self._insert_count
                    )
                else:
                    self._error_count += 1
            except Exception as exc:
                self._error_count += 1
                self._logger.error("Unexpected consumer error: %s", exc)
            finally:
                self.in_q.task_done()

            # --- update stats cache for dashboard ---
            try:
                self._refresh_stats()
            except Exception as exc:
                self._logger.warning("Stats refresh error: %s", exc)

        self._logger.info(
            "Consumer done – inserts=%d errors=%d", self._insert_count, self._error_count
        )

    def _refresh_stats(self) -> None:
        """Refresh the shared stats_cache from the DB (non-blocking query)."""
        summary = self.db.query_session_summary(self.session_id)
        fish_scores = self.db.query_fish_scores(self.session_id)
        self.stats_cache.update(
            {
                "summary": summary,
                "fish_scores": fish_scores,
                "last_updated": time.time(),
                "db_inserts": self._insert_count,
                "db_errors": self._error_count,
            }
        )


# ---------------------------------------------------------------------------
# CLI Dashboard
# ---------------------------------------------------------------------------


def _render_dashboard(stats_cache: Dict[str, Any], frame_count: int) -> None:
    """Print a compact dashboard to stdout."""
    summary = stats_cache.get("summary", {})
    fish_scores = stats_cache.get("fish_scores", [])
    db_inserts = stats_cache.get("db_inserts", 0)
    db_errors = stats_cache.get("db_errors", 0)

    print("\033[2J\033[H", end="")  # clear screen + move cursor to top
    print("=" * 60)
    print("  Occhi di Falco – Live Dashboard")
    print("=" * 60)
    print(f"  Frames captured : {frame_count}")
    print(f"  DB inserts      : {db_inserts}  errors: {db_errors}")
    print(f"  Hands (DB)      : {summary.get('hands_captured', 0)}")
    print(f"  Distinct players: {summary.get('distinct_players', 0)}")
    print(f"  Total actions   : {summary.get('total_actions', 0)}")
    print("-" * 60)

    if fish_scores:
        print("  Fish Score Ranking (seat | VPIP% | score)")
        for row in fish_scores[:6]:
            flag = " 🐟" if (row.get("fish_score") or 0) >= 60 else ""
            print(
                f"    Seat {row['seat']:>2}  VPIP {row.get('vpip_pct', 0):>5.1f}%"
                f"  score {row.get('fish_score', 0):>5.1f}{flag}"
            )
    else:
        print("  (No player stats yet)")

    print("=" * 60)
    print("  Press Ctrl-C to stop")


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------


def run(cfg: dict, args: argparse.Namespace) -> None:
    """Initialise all components, start threads and run the dashboard loop."""
    logger = logging.getLogger(__name__)

    # --- resolve runtime values ---
    fps = args.fps or cfg.get("capture_fps", 2)
    platform = args.platform or cfg.get("platform", "pokerstars")
    output_dir = args.output or cfg.get("output_dir", "output")
    db_path = args.db or cfg.get("db_path", "poker.db")
    region = _parse_region(args.region) if args.region else cfg.get("capture_region")
    max_frames = args.max_frames
    queue_size = args.queue_size or cfg.get("pipeline_queue_size", 50)

    logger.info("=== Occhi di Falco Pipeline ===")
    logger.info("Platform : %s", platform)
    logger.info("FPS      : %d", fps)
    logger.info("DB       : %s", db_path)
    logger.info("Region   : %s", region or "full screen")

    # --- instantiate components ---
    capture = ScreenCapture(fps=fps, region=region)
    ocr = OCRProcessor(
        languages=cfg["ocr_languages"],
        use_gpu=cfg["ocr_gpu"],
        tesseract_config=cfg["tesseract_config"],
    )
    cv_engine = ComputerVision(
        template_dir=cfg["cv_template_dir"],
        match_threshold=cfg["cv_match_threshold"],
    )
    parser = PokerParser(ocr=ocr, cv=cv_engine, platform=platform)
    exporter = DataExporter(
        output_dir=output_dir,
        file_prefix=cfg["output_file_prefix"],
        pretty=cfg["export_pretty_json"],
    )
    db = DatabaseManager(db_path=db_path)
    session_id = db.create_session(platform=platform)
    logger.info("DB session_id=%d", session_id)

    # --- shared state ---
    data_queue: "queue.Queue[Any]" = queue.Queue(maxsize=queue_size)
    stats_cache: Dict[str, Any] = {}
    stop_event = threading.Event()

    # --- threads ---
    producer = ProducerThread(
        capture=capture,
        parser=parser,
        exporter=exporter,
        out_q=data_queue,
        max_frames=max_frames,
        stop_event=stop_event,
    )
    consumer = ConsumerThread(
        db=db,
        session_id=session_id,
        in_q=data_queue,
        stats_cache=stats_cache,
    )

    # --- graceful shutdown handler ---
    def _shutdown(signum, frame):  # noqa: ARG001
        logger.info("Shutdown signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # --- start ---
    producer.start()
    consumer.start()
    logger.info("Pipeline running (producer + consumer threads active)")

    # --- dashboard loop (main thread) ---
    dashboard_interval = cfg.get("dashboard_interval", 2.0)

    try:
        while producer.is_alive() or not data_queue.empty():
            time.sleep(dashboard_interval)
            # Frames in-flight = already inserted + still queued
            frames_in_flight = (
                stats_cache.get("db_inserts", 0) + data_queue.qsize()
            )
            _render_dashboard(stats_cache, frames_in_flight)

            if not producer.is_alive() and data_queue.empty():
                break

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt – stopping")
        stop_event.set()

    finally:
        # Wait for threads to finish
        stop_event.set()
        producer.join(timeout=10)
        consumer.join(timeout=10)
        db.close()

    # --- final report ---
    final_summary = db.query_session_summary(session_id)
    fish_scores = db.query_fish_scores(session_id)

    logger.info("=== Session Complete ===")
    logger.info("Hands captured : %d", final_summary.get("hands_captured", 0))
    logger.info("Distinct players: %d", final_summary.get("distinct_players", 0))
    logger.info("Total actions  : %d", final_summary.get("total_actions", 0))

    if fish_scores:
        logger.info("--- Fish Score Ranking ---")
        for row in fish_scores:
            logger.info(
                "  Seat %d | VPIP %.1f%% | Fish Score %.1f",
                row["seat"],
                row.get("vpip_pct", 0),
                row.get("fish_score", 0),
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    cfg = load_config()

    if args.debug:
        cfg["log_level"] = logging.DEBUG

    setup_logging(cfg)
    run(cfg, args)


if __name__ == "__main__":
    main()
