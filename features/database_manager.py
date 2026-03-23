"""SQLite database manager for poker session data."""
from __future__ import annotations
import csv
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    CREATE_SESSIONS = """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        platform TEXT DEFAULT '888poker',
        total_hands INTEGER DEFAULT 0
    )"""

    CREATE_HANDS = """
    CREATE TABLE IF NOT EXISTS hands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        stage TEXT,
        pot REAL,
        player_count INTEGER,
        sb REAL,
        bb REAL,
        ante REAL DEFAULT 0
    )"""

    CREATE_PLAYERS = """
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hand_id INTEGER NOT NULL,
        seat INTEGER,
        position TEXT,
        stack REAL,
        is_fish INTEGER,
        vpip_pct REAL,
        last_action TEXT,
        FOREIGN KEY (hand_id) REFERENCES hands(id)
    )"""

    CREATE_ACTIONS = """
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hand_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        stage TEXT,
        position TEXT,
        action TEXT,
        amount REAL,
        FOREIGN KEY (hand_id) REFERENCES hands(id)
    )"""

    def __init__(self, db_path: str = "output/poker_data.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.cursor()
            for stmt in [self.CREATE_SESSIONS, self.CREATE_HANDS, self.CREATE_PLAYERS, self.CREATE_ACTIONS]:
                cur.execute(stmt)
            self._conn.commit()
            logger.debug("Database initialized: %s", self.db_path)
        except Exception as e:
            logger.error("DB init error: %s", e)
            self._conn = None

    def _ensure_session(self, session_id: str):
        if not self._conn:
            return
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, start_time) VALUES (?, ?)",
            (session_id, datetime.now().isoformat()))
        self._conn.commit()

    def save_hand(self, hand_data: Dict[str, Any], session_id: str) -> int:
        if not self._conn:
            return -1
        try:
            with self._lock:
                self._ensure_session(session_id)
                cur = self._conn.cursor()
                cur.execute(
                    "INSERT INTO hands (session_id, timestamp, stage, pot, player_count, sb, bb) VALUES (?,?,?,?,?,?,?)",
                    (session_id,
                     hand_data.get("timestamp", datetime.now().isoformat()),
                     hand_data.get("stage", ""),
                     hand_data.get("pot"),
                     hand_data.get("player_count", 0),
                     hand_data.get("small_blind"),
                     hand_data.get("big_blind")))
                hand_id = cur.lastrowid
                for player in hand_data.get("players", []):
                    cur.execute(
                        "INSERT INTO players (hand_id, seat, position, stack, is_fish, vpip_pct, last_action) VALUES (?,?,?,?,?,?,?)",
                        (hand_id, player.get("seat"), player.get("position"), player.get("stack"),
                         int(player.get("is_fish", False)), player.get("vpip_pct"), player.get("last_action")))
                self._conn.execute(
                    "UPDATE sessions SET total_hands = total_hands + 1 WHERE session_id = ?", (session_id,))
                self._conn.commit()
                return hand_id
        except Exception as e:
            logger.error("save_hand error: %s", e)
            return -1

    def get_session_stats(self, session_id: str) -> Dict:
        if not self._conn:
            return {}
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.error("get_session_stats error: %s", e)
        return {}

    def get_player_vpip(self, seat: int, session_id: str = None) -> Optional[float]:
        if not self._conn:
            return None
        try:
            if session_id:
                row = self._conn.execute(
                    "SELECT AVG(vpip_pct) FROM players p JOIN hands h ON p.hand_id=h.id "
                    "WHERE p.seat=? AND h.session_id=?", (seat, session_id)).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT AVG(vpip_pct) FROM players WHERE seat=?", (seat,)).fetchone()
            return row[0] if row and row[0] is not None else None
        except Exception as e:
            logger.error("get_player_vpip error: %s", e)
            return None

    def export_csv(self, filename: str, session_id: str = None):
        if not self._conn:
            return
        try:
            query = "SELECT * FROM hands"
            params = []
            if session_id:
                query += " WHERE session_id = ?"
                params = [session_id]
            rows = self._conn.execute(query, params).fetchall()
            with open(filename, "w", newline="", encoding="utf-8") as f:
                if rows:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows([dict(r) for r in rows])
            logger.info("Exported %d rows to %s", len(rows), filename)
        except Exception as e:
            logger.error("export_csv error: %s", e)

    def backup(self, backup_dir: str = "output/backups"):
        if not self._conn:
            return
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"poker_data_{ts}.db")
        try:
            backup_conn = sqlite3.connect(dest)
            self._conn.backup(backup_conn)
            backup_conn.close()
            logger.info("Database backed up to %s", dest)
        except Exception as e:
            logger.error("backup error: %s", e)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
