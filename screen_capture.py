"""
Occhi di Falco - Screen Capture Module
Real-time desktop screen capture using mss.
Falls back to pyautogui when mss is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class ScreenCapture:
    """
    Captures desktop frames at a configurable FPS.

    Parameters
    ----------
    fps : int
        Target capture rate (frames per second).
    region : tuple or None
        (left, top, width, height) in pixels, or None for full-screen.
    """

    def __init__(self, fps: int = 2, region: Optional[Tuple[int, int, int, int]] = None):
        self.fps = max(1, fps)
        self.region = region
        self._frame_interval = 1.0 / self.fps
        self._capture_func = self._init_capture_backend()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_capture_backend(self):
        """Try mss first, fall back to pyautogui."""
        try:
            import mss  # noqa: F401 – only imported to check availability
            logger.info("Screen capture backend: mss")
            return self._capture_mss
        except ImportError:
            pass

        try:
            import pyautogui  # noqa: F401
            logger.info("Screen capture backend: pyautogui")
            return self._capture_pyautogui
        except ImportError:
            pass

        raise RuntimeError(
            "No screen capture backend found. "
            "Install 'mss' or 'pyautogui': pip install mss pyautogui"
        )

    # ------------------------------------------------------------------
    # Capture back-ends
    # ------------------------------------------------------------------

    def _capture_mss(self) -> np.ndarray:
        import mss

        with mss.mss() as sct:
            if self.region:
                left, top, width, height = self.region
                monitor = {"left": left, "top": top, "width": width, "height": height}
            else:
                monitor = sct.monitors[1]  # primary monitor

            screenshot = sct.grab(monitor)
            # mss returns BGRA; convert to BGR (OpenCV standard)
            frame = np.array(screenshot)
            return frame[:, :, :3]  # drop alpha channel

    def _capture_pyautogui(self) -> np.ndarray:
        import pyautogui

        if self.region:
            left, top, width, height = self.region
            img = pyautogui.screenshot(region=(left, top, width, height))
        else:
            img = pyautogui.screenshot()

        return np.array(img)[:, :, ::-1]  # RGB → BGR

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a single frame.

        Returns
        -------
        np.ndarray or None
            BGR image array, or None on error.
        """
        try:
            return self._capture_func()
        except Exception as exc:
            logger.error("Frame capture failed: %s", exc)
            return None

    def capture_continuous(self):
        """
        Generator that yields frames at the configured FPS indefinitely.

        Yields
        ------
        np.ndarray
            BGR image array.
        """
        logger.info(
            "Starting continuous capture at %d FPS (region=%s)",
            self.fps,
            self.region or "full screen",
        )
        while True:
            t_start = time.monotonic()
            frame = self.capture_frame()
            if frame is not None:
                yield frame

            elapsed = time.monotonic() - t_start
            sleep_time = self._frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def capture_n_frames(self, n: int) -> list:
        """
        Capture exactly *n* frames and return them as a list.

        Parameters
        ----------
        n : int
            Number of frames to capture.

        Returns
        -------
        list[np.ndarray]
        """
        frames = []
        for frame in self.capture_continuous():
            frames.append(frame)
            if len(frames) >= n:
                break
        return frames
