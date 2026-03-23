"""System performance monitoring."""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class SystemStatus:
    fps: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    thread_count: int = 0
    uptime_seconds: float = 0.0
    queue_size: int = 0
    timestamp: str = ""


class PerformanceMonitor:
    def __init__(self, fps_window: int = 30):
        self._fps_window = fps_window
        self._frame_times: List[float] = []
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._queue_size = 0
        self._process = None
        if PSUTIL_AVAILABLE:
            try:
                self._process = psutil.Process()
            except Exception as e:
                logger.warning("psutil.Process() init failed: %s", e)

    def record_frame(self):
        with self._lock:
            self._frame_times.append(time.time())
            if len(self._frame_times) > self._fps_window:
                self._frame_times = self._frame_times[-self._fps_window:]

    def set_queue_size(self, size: int):
        self._queue_size = size

    def get_status(self) -> SystemStatus:
        with self._lock:
            times = list(self._frame_times)
        fps = 0.0
        if len(times) >= 2:
            elapsed = times[-1] - times[0]
            if elapsed > 0:
                fps = (len(times) - 1) / elapsed
        cpu = 0.0
        mem_mb = 0.0
        thread_count = threading.active_count()
        if self._process and PSUTIL_AVAILABLE:
            try:
                cpu = self._process.cpu_percent(interval=None)
                mem_mb = self._process.memory_info().rss / 1024 / 1024
            except Exception:
                pass
        return SystemStatus(
            fps=round(fps, 2),
            cpu_percent=round(cpu, 1),
            memory_mb=round(mem_mb, 1),
            thread_count=thread_count,
            uptime_seconds=round(time.time() - self._start_time, 1),
            queue_size=self._queue_size,
            timestamp=datetime.now().isoformat(),
        )

    def get_status_dict(self) -> dict:
        s = self.get_status()
        return {
            "fps": s.fps,
            "cpu_percent": s.cpu_percent,
            "memory_mb": s.memory_mb,
            "thread_count": s.thread_count,
            "uptime_seconds": s.uptime_seconds,
            "queue_size": s.queue_size,
            "timestamp": s.timestamp,
        }
