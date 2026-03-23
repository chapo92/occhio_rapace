"""CLI Dashboard using rich library with fallback."""
from __future__ import annotations
import time
from typing import Any, Dict, Optional

try:
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.console import Console
    from rich.layout import Layout
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def _fmt_uptime(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class Dashboard:
    def __init__(self, session_id: str = "", use_rich: bool = True):
        self.session_id = session_id
        self.use_rich = use_rich and RICH_AVAILABLE
        self._start_time = time.time()
        self._live: Optional[Any] = None
        self._console = Console() if RICH_AVAILABLE else None
        self._last_data: Optional[Dict] = None
        self._last_status: Optional[Dict] = None

    def start(self):
        if self.use_rich and self._console:
            self._live = Live(console=self._console, refresh_per_second=2, screen=False)
            self._live.start()

    def stop(self):
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    def update(self, hand_data: Dict, system_status: Optional[Dict] = None):
        self._last_data = hand_data
        self._last_status = system_status
        if self.use_rich:
            rendered = self._render_rich(hand_data, system_status)
            if self._live:
                self._live.update(rendered)
        else:
            self._render_plain(hand_data, system_status)

    def _render_rich(self, hand_data: Dict, system_status: Optional[Dict]) -> Any:
        uptime = _fmt_uptime(time.time() - self._start_time)
        table_status = "STABLE" if hand_data.get("table_detected") else "SEARCHING"
        pot = hand_data.get("pot") or 0.0
        sb = hand_data.get("small_blind") or 0.0
        bb = hand_data.get("big_blind") or 0.0
        stage = str(hand_data.get("stage", "preflop")).upper()
        player_count = hand_data.get("player_count", 0)
        session_id = hand_data.get("session_id", self.session_id)

        t = Table(show_header=False, box=box.DOUBLE, expand=True)
        t.add_column("Field", style="bold cyan")
        t.add_column("Value", style="green")
        t.add_row("Session", f"{session_id} | Uptime: {uptime}")
        t.add_row("Table", f"{table_status} | Players: {player_count}")
        t.add_row("Pot", f"${pot:.2f} | Blinds: {sb}/{bb} | Stage: {stage}")
        if system_status:
            fps = system_status.get("fps", 0.0)
            cpu = system_status.get("cpu_percent", 0.0)
            mem = system_status.get("memory_mb", 0.0)
            t.add_row("System", f"FPS: {fps:.1f} | CPU: {cpu:.1f}% | MEM: {mem:.0f}MB")
        return Panel(t, title="[bold yellow]OCCHI DI FALCO - 888 POKER LIVE DATA EXTRACTOR[/bold yellow]",
                     border_style="blue")

    def _render_plain(self, hand_data: Dict, system_status: Optional[Dict]):
        uptime = _fmt_uptime(time.time() - self._start_time)
        print("=" * 60)
        print("  OCCHI DI FALCO - 888 POKER LIVE DATA EXTRACTOR")
        print("=" * 60)
        session_id = hand_data.get("session_id", self.session_id)
        print(f"Session: {session_id} | Uptime: {uptime}")
        table_status = "STABLE" if hand_data.get("table_detected") else "SEARCHING"
        print(f"Table: {table_status} | Players: {hand_data.get('player_count', 0)}")
        pot = hand_data.get("pot") or 0.0
        sb = hand_data.get("small_blind") or 0.0
        bb = hand_data.get("big_blind") or 0.0
        stage = str(hand_data.get("stage", "preflop")).upper()
        print(f"Pot: ${pot:.2f} | Blinds: {sb}/{bb} | Stage: {stage}")
        if system_status:
            fps = system_status.get("fps", 0.0)
            cpu = system_status.get("cpu_percent", 0.0)
            print(f"FPS: {fps:.1f} | CPU: {cpu:.1f}%")
        print()
