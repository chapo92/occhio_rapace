"""
Occhi di Falco - Main Entry Point
Real-time 888 Poker data extraction.

Usage
-----
    python main.py [--fps 5] [--output output/] [--region left,top,width,height]
                   [--debug] [--calibrate] [--max-frames N] [--no-backup]
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Optional

from config import load_config
from core.screen_capture import ScreenCapture
from core.poker_parser import PokerParser
from core.data_exporter import DataExporter
from features.performance_monitor import PerformanceMonitor
from features.dashboard import Dashboard
from features.alerts import AlertSystem, AlertType
from features.error_recovery import ErrorRecovery
from utils.logger_setup import setup_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Occhi di Falco – real-time 888 Poker data extractor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--fps", type=int, default=None, help="Capture frames per second")
    parser.add_argument("--output", type=str, default=None, help="Output directory for JSON files")
    parser.add_argument(
        "--region", type=str, default=None,
        help="Screen region to capture: left,top,width,height",
    )
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    parser.add_argument("--calibrate", action="store_true", help="Run calibration wizard first")
    parser.add_argument(
        "--max-frames", type=int, default=0,
        help="Stop after N frames (0 = run forever)",
    )
    parser.add_argument("--no-dashboard", action="store_true", help="Disable rich dashboard")
    parser.add_argument("--no-backup", action="store_true", help="Disable automatic backup scheduler")
    return parser.parse_args()


def _parse_region(region_str: str) -> tuple:
    parts = [int(x.strip()) for x in region_str.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Invalid region string: {region_str!r}")
    return tuple(parts)


def run(cfg: dict, args: argparse.Namespace) -> None:
    logger = logging.getLogger(__name__)

    fps = args.fps or cfg.get("capture", {}).get("fps", 5)
    output_dir = args.output or cfg.get("output", {}).get("directory", "./output/")
    region = _parse_region(args.region) if args.region else cfg.get("capture", {}).get("region")
    queue_size = cfg.get("performance", {}).get("queue_size", 100)

    if args.calibrate:
        from calibration import CalibrationWizard
        CalibrationWizard().run()

    logger.info("=== Occhi di Falco ===")
    logger.info("Platform : 888poker")
    logger.info("FPS      : %d", fps)
    logger.info("Region   : %s", region or "full screen")
    logger.info("Output   : %s", output_dir)

    parser_obj = PokerParser()
    exporter = DataExporter(output_dir=output_dir, session_id=parser_obj.session_id)
    capture = ScreenCapture(fps=fps, region=region, queue_size=queue_size)
    perf = PerformanceMonitor()
    dashboard = Dashboard(session_id=parser_obj.session_id, use_rich=not args.no_dashboard)
    alerts = AlertSystem(sound_enabled=cfg.get("alerts", {}).get("sound", True))
    recovery = ErrorRecovery(checkpoint_dir="output/checkpoints")

    _running = [True]

    def _shutdown_handler(signum, _frame):
        logger.info("Shutdown signal received – stopping…")
        _running[0] = False

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    capture.start()
    alerts.start()
    dashboard.start()

    # Start automatic backup scheduler in background (unless disabled)
    auto_backup = cfg.get("database", {}).get("auto_backup", True)
    if auto_backup and not args.no_backup:
        try:
            from scripts.backup.backup_scheduler import BackupScheduler
            _backup_scheduler = BackupScheduler()
            _backup_scheduler.schedule_daily_backup(hour=0, minute=0)
            _backup_scheduler.run_async()
            logger.info("Auto-backup scheduler started (daily at midnight)")
        except Exception as _exc:
            logger.warning("Could not start backup scheduler: %s", _exc)

    frame_count = 0
    last_log = time.monotonic()

    try:
        while _running[0]:
            frame = capture.get_frame(timeout=1.0)
            if frame is None:
                continue

            try:
                hand_data = parser_obj.parse_frame(frame)
                perf.record_frame()
                perf.set_queue_size(capture.get_queue_size())
                recovery.save_checkpoint(hand_data)
                status = perf.get_status_dict()
                exporter.export(hand_data, status)
                dashboard.update(hand_data, status)
                frame_count += 1

                now = time.monotonic()
                if now - last_log >= 10:
                    logger.info(
                        "Frames: %d | FPS: %.1f | Table: %s | Stage: %s | Pot: %s",
                        frame_count, status["fps"],
                        hand_data.get("table_detected"),
                        hand_data.get("stage"),
                        hand_data.get("pot"),
                    )
                    last_log = now

            except Exception as exc:
                logger.exception("Error processing frame: %s", exc)
                hand_data = recovery.get_fallback(None, exc)

            if args.max_frames and frame_count >= args.max_frames:
                logger.info("Reached max-frames limit (%d) – stopping", args.max_frames)
                break
    finally:
        capture.stop()
        alerts.stop()
        dashboard.stop()
        logger.info("Session complete. Total frames: %d", frame_count)


def main() -> None:
    args = parse_args()
    cfg = load_config()

    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logger("occhi_di_falco", level=log_level, log_file="output/occhi_di_falco.log")

    run(cfg, args)


if __name__ == "__main__":
    main()
