from __future__ import annotations
import logging
import queue
import threading
import time
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)

class ScreenCapture:
    """
    Thread-safe screen capture with background capture thread and FPS monitoring.

    Captures desktop frames at a configurable FPS using mss (preferred) or pyautogui
    as fallback. Frames are stored in a thread-safe queue for consumption by
    processing threads.

    Usage::

        cap = ScreenCapture(fps=5)
        cap.start()
        frame = cap.get_frame(timeout=1.0)
        cap.stop()
    """
    def __init__(self, fps: int = 5, region=None, queue_size: int = 100):
        self.fps = fps
        self.region = region
        self.queue_size = queue_size
        self._frame_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_times = []
        self._lock = threading.Lock()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self.capture_continuous, daemon=True)
        self._thread.start()
        logger.info("ScreenCapture started at %d fps", self.fps)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("ScreenCapture stopped")

    def get_frame(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def capture_frame(self) -> Optional[np.ndarray]:
        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                if self.region:
                    monitor = {"left": self.region[0], "top": self.region[1],
                               "width": self.region[2], "height": self.region[3]}
                screenshot = sct.grab(monitor)
                frame = np.array(screenshot)
                frame = frame[:, :, :3]  # drop alpha
                return frame
        except Exception as e:
            logger.debug("mss failed: %s, trying pyautogui", e)
            try:
                import pyautogui
                screenshot = pyautogui.screenshot()
                return np.array(screenshot)
            except Exception as e2:
                logger.error("All capture backends failed: %s", e2)
                return None

    def capture_continuous(self):
        interval = 1.0 / self.fps
        while self._running:
            t0 = time.time()
            frame = self.capture_frame()
            if frame is not None:
                with self._lock:
                    self._frame_times.append(time.time())
                    self._frame_times = self._frame_times[-30:]
                if self._frame_queue.full():
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    self._frame_queue.put_nowait(frame)
                except queue.Full:
                    pass
            elapsed = time.time() - t0
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    def get_queue_size(self) -> int:
        return self._frame_queue.qsize()

    @property
    def actual_fps(self) -> float:
        with self._lock:
            if len(self._frame_times) < 2:
                return 0.0
            elapsed = self._frame_times[-1] - self._frame_times[0]
            if elapsed <= 0:
                return 0.0
            return (len(self._frame_times) - 1) / elapsed
