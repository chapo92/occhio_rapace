"""Interactive calibration wizard for 888 Poker table detection."""
from __future__ import annotations
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CalibrationWizard:
    CONFIG_FILE = "config.json"

    def __init__(self, interactive: bool = True):
        self.interactive = interactive
        self._captured_frames: List[np.ndarray] = []
        self._detected_ranges: List[Dict] = []

    def run(self) -> Dict[str, Any]:
        logger.info("Starting calibration wizard...")
        frames = self.capture_calibration_frames(n=3)
        if not frames:
            logger.warning("No frames captured, using defaults")
            config = self._default_config()
        else:
            blue_range = self.analyze_blue_range(frames)
            config = {"table_detection": {"blue_hsv_range": blue_range}}
        self.save_config(config)
        logger.info("Calibration complete: %s", config)
        return config

    def capture_calibration_frames(self, n: int = 3) -> List[np.ndarray]:
        frames = []
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                for i in range(n):
                    shot = sct.grab(monitor)
                    frame = np.array(shot)[:, :, :3]
                    frames.append(frame)
                    if i < n - 1:
                        time.sleep(0.5)
        except Exception as e:
            logger.warning("Frame capture failed: %s", e)
        self._captured_frames = frames
        return frames

    def analyze_blue_range(self, frames: List[np.ndarray]) -> Dict[str, Any]:
        blue_pixels = []
        for frame in frames:
            try:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                mask = cv2.inRange(hsv, np.array([90, 20, 20]), np.array([150, 255, 255]))
                pixels = hsv[mask > 0]
                if len(pixels) > 100:
                    blue_pixels.extend(pixels.tolist())
            except Exception as e:
                logger.debug("Frame analysis error: %s", e)
        if len(blue_pixels) < 50:
            return {"h_min": 100, "h_max": 140, "s_min": 30, "s_max": 255, "v_min": 30, "v_max": 255}
        arr = np.array(blue_pixels)
        return {
            "h_min": max(90, int(np.percentile(arr[:, 0], 5))),
            "h_max": min(150, int(np.percentile(arr[:, 0], 95))),
            "s_min": max(20, int(np.percentile(arr[:, 1], 5))),
            "s_max": 255,
            "v_min": max(20, int(np.percentile(arr[:, 2], 5))),
            "v_max": 255,
        }

    def _default_config(self) -> Dict[str, Any]:
        return {
            "table_detection": {
                "blue_hsv_range": {
                    "h_min": 100, "h_max": 140, "s_min": 30, "s_max": 255, "v_min": 30, "v_max": 255
                }
            }
        }

    def save_config(self, config_updates: Dict[str, Any]):
        from utils.constants import deep_merge
        existing = {}
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        merged = deep_merge(existing, config_updates)
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        logger.info("Config saved to %s", self.CONFIG_FILE)

    def _detect_blue_table_hsv(self, frame: np.ndarray) -> Optional[Dict]:
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([100, 30, 30]), np.array([140, 255, 255]))
            pixel_count = int(np.sum(mask > 0))
            if pixel_count < 1000:
                return None
            pixels = hsv[mask > 0]
            return {
                "pixel_count": pixel_count,
                "h_mean": float(np.mean(pixels[:, 0])),
                "s_mean": float(np.mean(pixels[:, 1])),
                "v_mean": float(np.mean(pixels[:, 2])),
            }
        except Exception as e:
            logger.debug("HSV detection error: %s", e)
            return None
