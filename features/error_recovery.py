"""Error recovery and resilience for the extraction pipeline."""
from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ErrorRecovery:
    def __init__(self, checkpoint_dir: str = "output/checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        self._last_valid: Optional[Dict[str, Any]] = None
        self._error_count = 0
        self._error_window_start = time.time()
        self._last_error_time: Optional[float] = None
        os.makedirs(checkpoint_dir, exist_ok=True)

    def save_checkpoint(self, hand_data: Dict[str, Any]):
        if not hand_data:
            return
        self._last_valid = dict(hand_data)
        path = os.path.join(self.checkpoint_dir, "latest_checkpoint.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(hand_data, f, default=str)
        except Exception as e:
            logger.warning("Checkpoint save failed: %s", e)

    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.checkpoint_dir, "latest_checkpoint.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Checkpoint load failed: %s", e)
        return None

    def get_fallback(self, hand_data: Optional[Dict], error: Exception) -> Dict[str, Any]:
        self.record_error(error)
        if hand_data and hand_data.get("table_detected"):
            return hand_data
        if self._last_valid:
            fallback = dict(self._last_valid)
            fallback["_fallback"] = True
            fallback["_error"] = str(error)
            return fallback
        return {
            "session_id": "unknown",
            "timestamp": datetime.now().isoformat(),
            "table_detected": False,
            "table_confidence": 0.0,
            "stage": "preflop",
            "pot": None,
            "small_blind": None,
            "big_blind": None,
            "player_count": 0,
            "players": [],
            "_fallback": True,
            "_error": str(error),
        }

    def record_error(self, error: Exception):
        self._error_count += 1
        self._last_error_time = time.time()
        logger.debug("Error recorded (#%d): %s", self._error_count, error)

    def reset_error_count(self):
        self._error_count = 0
        self._error_window_start = time.time()

    @property
    def error_rate(self) -> float:
        elapsed = time.time() - self._error_window_start
        if elapsed <= 0:
            return 0.0
        return self._error_count / elapsed
