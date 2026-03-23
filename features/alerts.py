"""Alert system for poker events."""
from __future__ import annotations
import logging
import queue
import shutil
import subprocess
import sys
import threading
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AlertType(Enum):
    STAGE_CHANGE = "stage_change"
    OCR_UNCERTAIN = "ocr_uncertain"
    TABLE_LOST = "table_lost"
    ACTION_TIMEOUT = "action_timeout"
    NEW_HAND = "new_hand"


class AlertSystem:
    def __init__(self, sound_enabled: bool = True, confidence_threshold: float = 0.7):
        self.sound_enabled = sound_enabled
        self.confidence_threshold = confidence_threshold
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._handlers: list = []

    def trigger(self, alert_type: AlertType, message: str = "", data: dict = None):
        self._queue.put({"type": alert_type, "message": message, "data": data or {}})

    def add_handler(self, handler: Callable):
        self._handlers.append(handler)

    def _play_beep(self):
        try:
            if sys.platform == "win32":
                try:
                    import winsound
                    winsound.Beep(800, 200)
                except Exception as e:
                    logger.debug("winsound.Beep failed: %s", e)
                    print('\a', end='', flush=True)
            else:
                try:
                    beep_cmd = shutil.which('beep')
                    if beep_cmd:
                        subprocess.run([beep_cmd], timeout=1, capture_output=True)
                    else:
                        raise FileNotFoundError("beep not found")
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    print('\a', end='', flush=True)
        except Exception:
            print('\a', end='', flush=True)

    def _process_loop(self):
        while self._running:
            try:
                alert = self._queue.get(timeout=0.5)
                logger.info("ALERT [%s]: %s", alert["type"].value, alert["message"])
                for handler in self._handlers:
                    try:
                        handler(alert)
                    except Exception as e:
                        logger.warning("Alert handler error: %s", e)
                if self.sound_enabled:
                    self._play_beep()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("Alert processing error: %s", e)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
