"""
Occhi di Falco - Database Module (v2.1)
SQLite persistence for poker hand history and player statistics.

Tables
------
sessions      – one row per capture session
hands         – one row per parsed frame snapshot
players       – per-seat data for each hand snapshot
actions       – individual action events per hand
player_stats  – running aggregated statistics per player per session
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,
    platform    TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS hands (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id            INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp             TEXT    NOT NULL,
    table_name            TEXT,
    platform              TEXT,
    game_format           TEXT,
    hand_stage            TEXT,
    pot                   REAL,
    small_blind           REAL,
    big_blind             REAL,
    ante                  REAL,
    community_cards_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id    INTEGER NOT NULL REFERENCES hands(id) ON DELETE CASCADE,
    seat       INTEGER,
    position   TEXT,
    stack      REAL,
    status     TEXT,
    action     TEXT,
    bet        REAL,
    is_dealer  INTEGER DEFAULT 0,
    is_fish    INTEGER
);

CREATE TABLE IF NOT EXISTS actions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id   INTEGER NOT NULL REFERENCES hands(id) ON DELETE CASCADE,
    timestamp TEXT,
    stage     TEXT,
    action    TEXT,
    amount    REAL,
    raw_text  TEXT
);

CREATE TABLE IF NOT EXISTS player_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seat            INTEGER NOT NULL,
    hands_seen      INTEGER DEFAULT 0,
    vpip_count      INTEGER DEFAULT 0,
    aggr_actions    INTEGER DEFAULT 0,
    passive_actions INTEGER DEFAULT 0,
    showdown_count  INTEGER DEFAULT 0,
    UNIQUE(session_id, seat)
);

CREATE INDEX IF NOT EXISTS idx_hands_session  ON hands(session_id);
CREATE INDEX IF NOT EXISTS idx_players_hand   ON players(hand_id);
CREATE INDEX IF NOT EXISTS idx_actions_hand   ON actions(hand_id);
CREATE INDEX IF NOT EXISTS idx_stats_session  ON player_stats(session_id);
"""

# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------


class DatabaseManager:
    """
    Thread-safe SQLite database manager.

    Parameters
    ----------
    db_path : str
        Path to the SQLite file.  Use ``:memory:`` for in-memory testing.
    """

    def __init__(self, db_path: str = "poker.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_schema()
        logger.info("DatabaseManager ready – db: %s", db_path)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Return a per-thread cached connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit off; we manage transactions
            )
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager that wraps statements in a single transaction."""
        conn = self._get_connection()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not yet exist."""
        with self._lock:
            conn = self._get_connection()
            conn.executescript(_DDL)
            logger.debug("Database schema initialised")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self, platform: str = "", notes: str = "") -> int:
        """
        Insert a new session row.

        Returns
        -------
        int
            The new session ``id``.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at, platform, notes) VALUES (?, ?, ?)",
                (started_at, platform, notes),
            )
            session_id = cur.lastrowid
        logger.info("Session created: id=%d platform=%s", session_id, platform)
        return session_id

    # ------------------------------------------------------------------
    # Hand data insertion
    # ------------------------------------------------------------------

    def insert_hand_data(self, session_id: int, hand_data: Dict[str, Any]) -> Optional[int]:
        """
        Persist a full hand snapshot (including players and actions).

        Runs inside a single transaction; rolls back on any error.

        Parameters
        ----------
        session_id : int
            ID of the current session.
        hand_data : dict
            Structured hand snapshot as returned by :class:`PokerParser`.

        Returns
        -------
        int or None
            The new ``hand_id``, or *None* on failure.
        """
        try:
            with self._lock, self._transaction() as conn:
                hand_id = self._insert_hand(conn, session_id, hand_data)
                self._insert_players(conn, hand_id, hand_data.get("players", []))
                self._insert_actions(conn, hand_id, hand_data.get("actions_history", []))
                self._upsert_player_stats(conn, session_id, hand_data.get("players", []))
            logger.debug("Inserted hand_id=%d session=%d", hand_id, session_id)
            return hand_id
        except Exception as exc:
            logger.error("insert_hand_data failed (rolled back): %s", exc)
            return None

    def _insert_hand(
        self, conn: sqlite3.Connection, session_id: int, hand_data: Dict[str, Any]
    ) -> int:
        table_info = hand_data.get("table_info", {})
        blinds = hand_data.get("blinds", {})
        cur = conn.execute(
            """
            INSERT INTO hands
                (session_id, timestamp, table_name, platform, game_format,
                 hand_stage, pot, small_blind, big_blind, ante, community_cards_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                hand_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                table_info.get("name"),
                table_info.get("platform"),
                table_info.get("format"),
                hand_data.get("hand_stage"),
                hand_data.get("pot"),
                blinds.get("small_blind"),
                blinds.get("big_blind"),
                blinds.get("ante", 0.0),
                hand_data.get("community_cards_count", 0),
            ),
        )
        return cur.lastrowid

    def _insert_players(
        self, conn: sqlite3.Connection, hand_id: int, players: List[Dict[str, Any]]
    ) -> None:
        rows = [
            (
                hand_id,
                p.get("seat"),
                p.get("position"),
                p.get("stack"),
                p.get("status"),
                p.get("action"),
                p.get("bet"),
                int(bool(p.get("is_dealer", False))),
                None if p.get("is_fish") is None else int(bool(p["is_fish"])),
            )
            for p in players
        ]
        conn.executemany(
            """
            INSERT INTO players
                (hand_id, seat, position, stack, status, action, bet, is_dealer, is_fish)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _insert_actions(
        self, conn: sqlite3.Connection, hand_id: int, actions: List[Dict[str, Any]]
    ) -> None:
        rows = [
            (
                hand_id,
                a.get("timestamp"),
                a.get("stage"),
                a.get("action"),
                a.get("amount"),
                a.get("raw_text"),
            )
            for a in actions
        ]
        conn.executemany(
            """
            INSERT INTO actions (hand_id, timestamp, stage, action, amount, raw_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _upsert_player_stats(
        self,
        conn: sqlite3.Connection,
        session_id: int,
        players: List[Dict[str, Any]],
    ) -> None:
        """Increment running stats counters for each player in this snapshot."""
        for p in players:
            seat = p.get("seat")
            if seat is None:
                continue
            action = p.get("action") or ""
            vpip_delta = 1 if action in ("raise", "bet", "call") else 0
            aggr_delta = 1 if action in ("raise", "bet") else 0
            passive_delta = 1 if action in ("call", "check") else 0
            conn.execute(
                """
                INSERT INTO player_stats (session_id, seat, hands_seen, vpip_count,
                                          aggr_actions, passive_actions)
                VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT(session_id, seat) DO UPDATE SET
                    hands_seen      = hands_seen + 1,
                    vpip_count      = vpip_count + excluded.vpip_count,
                    aggr_actions    = aggr_actions + excluded.aggr_actions,
                    passive_actions = passive_actions + excluded.passive_actions
                """,
                (session_id, seat, vpip_delta, aggr_delta, passive_delta),
            )

    # ------------------------------------------------------------------
    # Query library
    # ------------------------------------------------------------------

    def query_fish_scores(self, session_id: int) -> List[Dict[str, Any]]:
        """
        Return player fish-score rankings for *session_id*.

        A **fish score** is 0–100 based on:
        - VPIP % (weight 60 %)
        - Passivity ratio: passive / (aggr + passive) (weight 40 %)

        Higher score → more fish-like behaviour.

        Returns
        -------
        list[dict]
            Rows sorted by fish_score descending.
        """
        query = """
            SELECT
                seat,
                hands_seen,
                vpip_count,
                aggr_actions,
                passive_actions,
                CASE
                    WHEN hands_seen > 0
                    THEN ROUND(100.0 * vpip_count / hands_seen, 1)
                    ELSE 0
                END AS vpip_pct,
                CASE
                    WHEN (aggr_actions + passive_actions) > 0
                    THEN ROUND(
                        60.0 * (MIN(vpip_count, hands_seen) * 1.0 / MAX(hands_seen, 1))
                        + 40.0 * (passive_actions * 1.0 /
                            (aggr_actions + passive_actions)),
                        1
                    )
                    ELSE 0
                END AS fish_score
            FROM player_stats
            WHERE session_id = ?
            ORDER BY fish_score DESC
        """
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(query, (session_id,)).fetchall()
        return [dict(r) for r in rows]

    def query_session_summary(self, session_id: int) -> Dict[str, Any]:
        """
        Return a summary dict for *session_id*:
        hands captured, distinct players, total actions.
        """
        with self._lock:
            conn = self._get_connection()
            hands_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM hands WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            players_row = conn.execute(
                """
                SELECT COUNT(DISTINCT p.seat) AS cnt
                FROM players p
                JOIN hands h ON h.id = p.hand_id
                WHERE h.session_id = ?
                """,
                (session_id,),
            ).fetchone()
            actions_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM actions a
                JOIN hands h ON h.id = a.hand_id
                WHERE h.session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return {
            "session_id": session_id,
            "hands_captured": hands_row["cnt"] if hands_row else 0,
            "distinct_players": players_row["cnt"] if players_row else 0,
            "total_actions": actions_row["cnt"] if actions_row else 0,
        }

    def query_recent_hands(
        self, session_id: int, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Return the *limit* most recent hand rows for *session_id*."""
        with self._lock:
            conn = self._get_connection()
            rows = conn.execute(
                """
                SELECT id, timestamp, table_name, platform, hand_stage, pot,
                       small_blind, big_blind
                FROM hands
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def query_player_vpip(self, session_id: int, seat: int) -> Optional[float]:
        """Return VPIP % for *seat* in *session_id*, or None if no data."""
        with self._lock:
            conn = self._get_connection()
            row = conn.execute(
                """
                SELECT vpip_count, hands_seen
                FROM player_stats
                WHERE session_id = ? AND seat = ?
                """,
                (session_id, seat),
            ).fetchone()
        if row and row["hands_seen"] > 0:
            return round(100.0 * row["vpip_count"] / row["hands_seen"], 1)
        return None

    def close(self) -> None:
        """Close the per-thread connection (call from the owning thread)."""
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None
            logger.debug("Database connection closed")
