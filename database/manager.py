"""
Occhi di Falco – PokerDatabaseManager
Provides high-level access to the SQLite tournament database with pre-built
queries for VPIP, aggression factor, fish detection, bubble analysis, and more.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from database.models import (
    Base,
    BubbleTracking,
    Hand,
    HandAction,
    PlayerInTournament,
    PlayerStatistics,
    SessionMetadata,
    Tournament,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DATETIME_FIELDS = {
    "start_time", "end_time", "timestamp", "session_start", "session_end",
    "created_at", "updated_at",
}


def _coerce_datetimes(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of *data* with ISO-string datetime values replaced by
    :class:`datetime` objects.  Columns in :data:`_DATETIME_FIELDS` that
    carry a ``str`` value are parsed with :func:`datetime.fromisoformat`.
    """
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key in _DATETIME_FIELDS and isinstance(value, str):
            try:
                out[key] = datetime.fromisoformat(value)
            except ValueError:
                out[key] = value
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Pre-built SQL queries
# ---------------------------------------------------------------------------

_QUERY_VPIP = text("""
    SELECT
        player_id,
        ROUND(
            100.0 * COUNT(CASE WHEN action_type NOT IN ('fold', 'check') THEN 1 END)
            / NULLIF(COUNT(*), 0),
            2
        ) AS vpip_percentage
    FROM hand_actions
    WHERE hand_id IN (
        SELECT hand_id FROM hands WHERE tournament_id = :tid
    )
    GROUP BY player_id
""")

_QUERY_AGGRESSION_FACTOR = text("""
    SELECT
        player_id,
        COUNT(CASE WHEN action_type IN ('bet', 'raise', 'allin') THEN 1 END)
            AS aggressive_actions,
        COUNT(CASE WHEN action_type = 'call' THEN 1 END)
            AS calls,
        ROUND(
            CAST(
                COUNT(CASE WHEN action_type IN ('bet', 'raise', 'allin') THEN 1 END)
                AS REAL
            ) / NULLIF(
                COUNT(CASE WHEN action_type = 'call' THEN 1 END), 0
            ),
            2
        ) AS aggression_factor
    FROM hand_actions
    WHERE hand_id IN (
        SELECT hand_id FROM hands WHERE tournament_id = :tid
    )
    GROUP BY player_id
""")

_QUERY_SHOWDOWN_PCT = text("""
    SELECT
        player_id,
        ROUND(
            100.0 * COUNT(*) / NULLIF(
                (SELECT COUNT(*) FROM hands WHERE tournament_id = :tid), 0
            ),
            2
        ) AS showdown_percentage
    FROM hand_actions
    WHERE hand_id IN (
        SELECT hand_id FROM hands
        WHERE tournament_id = :tid
          AND hand_stage IN ('river', 'showdown')
    )
    GROUP BY player_id
""")

_QUERY_FISH_SCORES = text("""
    SELECT
        ps.player_id,
        ps.vpip,
        ps.aggression_factor,
        CASE
            WHEN ps.vpip > 50 AND ps.aggression_factor < 1.5 THEN 90
            WHEN ps.vpip > 40 AND ps.aggression_factor < 1.2 THEN 75
            WHEN ps.vpip > 35 AND ps.aggression_factor < 1.0 THEN 60
            WHEN ps.vpip > 30 AND ps.aggression_factor < 0.8 THEN 45
            ELSE 20
        END AS fish_score
    FROM player_statistics ps
    WHERE ps.tournament_id = :tid
    ORDER BY fish_score DESC
""")

_QUERY_WIN_RATE_BY_POSITION = text("""
    SELECT
        COALESCE(h.button_position, 'Unknown') AS position,
        COUNT(*) AS hands_played,
        SUM(CASE WHEN h.hero_result = 'win' THEN 1 ELSE 0 END) AS hands_won,
        ROUND(
            100.0 * SUM(CASE WHEN h.hero_result = 'win' THEN 1 ELSE 0 END)
            / NULLIF(COUNT(*), 0),
            2
        ) AS win_percentage,
        ROUND(SUM(COALESCE(h.hero_profit, 0)), 2) AS total_profit
    FROM hands h
    WHERE h.tournament_id = :tid
      AND h.hero_seat IS NOT NULL
    GROUP BY h.button_position
    ORDER BY hands_played DESC
""")

_QUERY_BUBBLE_PROGRESSION = text("""
    SELECT
        bt.timestamp,
        bt.remaining_players,
        bt.players_to_cash,
        bt.bubble_factor,
        bt.your_chip_position,
        ROUND(bt.your_chip_percentage * 100, 2) AS chip_percentage,
        ROUND(bt.icm_equity, 2) AS icm_value,
        COUNT(h.hand_id) AS hands_played_this_stage
    FROM bubble_tracking bt
    LEFT JOIN hands h
        ON h.tournament_id = bt.tournament_id
       AND h.hand_number >= bt.hand_number
    WHERE bt.tournament_id = :tid
    GROUP BY bt.hand_number
    ORDER BY bt.hand_number
""")

_QUERY_HAND_HISTORY = text("""
    SELECT
        h.hand_number,
        h.timestamp,
        h.button_position,
        h.small_blind,
        h.big_blind,
        h.hero_cards,
        h.community_cards,
        h.hand_stage,
        h.final_pot,
        h.hero_result,
        ROUND(h.hero_profit, 2) AS profit_loss
    FROM hands h
    WHERE h.tournament_id = :tid
      AND h.hero_seat IS NOT NULL
    ORDER BY h.hand_number
""")

_QUERY_TOURNAMENT_SUMMARY = text("""
    SELECT
        t.tournament_id,
        t.buy_in,
        t.final_stack,
        ROUND((t.final_stack - t.buy_in), 2) AS profit_loss,
        ROUND(((t.final_stack - t.buy_in) / t.buy_in) * 100, 2) AS roi_percentage,
        t.final_position,
        (
            SELECT COUNT(*)
            FROM players_in_tournament
            WHERE tournament_id = t.tournament_id
        ) AS total_players,
        t.total_hands_played,
        t.duration_minutes,
        ROUND(
            t.total_hands_played / NULLIF(t.duration_minutes, 0) * 60, 1
        ) AS hands_per_hour
    FROM tournaments t
    WHERE t.tournament_id = :tid
""")


# ---------------------------------------------------------------------------
# Manager class
# ---------------------------------------------------------------------------

class PokerDatabaseManager:
    """
    High-level interface for the Occhi di Falco SQLite tournament database.

    Parameters
    ----------
    db_path : str
        File path for the SQLite database (created if absent).
    """

    def __init__(self, db_path: str = "poker_data.db") -> None:
        self.db_path = db_path
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        self._Session = sessionmaker(bind=self.engine)
        logger.info("PokerDatabaseManager initialised – db: %s", db_path)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def init_database(self) -> None:
        """Create all tables (idempotent – safe to call multiple times)."""
        Base.metadata.create_all(self.engine)
        logger.info("Database schema created/verified at %s", self.db_path)

    # ------------------------------------------------------------------
    # Context-manager helper
    # ------------------------------------------------------------------

    def _session(self) -> Session:
        return self._Session()

    # ------------------------------------------------------------------
    # Insert helpers
    # ------------------------------------------------------------------

    def insert_tournament(self, tournament_data: Dict[str, Any]) -> str:
        """
        Insert a new tournament record.

        Parameters
        ----------
        tournament_data : dict
            Keys matching :class:`~database.models.Tournament` columns.

        Returns
        -------
        str
            The ``tournament_id`` of the inserted record.
        """
        with self._session() as session:
            tournament = Tournament(**_coerce_datetimes(tournament_data))
            session.add(tournament)
            session.commit()
            logger.debug("Inserted tournament %s", tournament.tournament_id)
            return tournament.tournament_id

    def insert_player(self, player_data: Dict[str, Any]) -> str:
        """Insert a player record; returns ``player_id``."""
        with self._session() as session:
            player = PlayerInTournament(**_coerce_datetimes(player_data))
            session.add(player)
            session.commit()
            return player.player_id

    def insert_hand(self, hand_data: Dict[str, Any]) -> str:
        """Insert a hand record; returns ``hand_id``."""
        with self._session() as session:
            hand = Hand(**_coerce_datetimes(hand_data))
            session.add(hand)
            session.commit()
            return hand.hand_id

    def insert_hand_action(self, action_data: Dict[str, Any]) -> int:
        """Insert a hand action; returns ``action_id``."""
        with self._session() as session:
            action = HandAction(**_coerce_datetimes(action_data))
            session.add(action)
            session.commit()
            return action.action_id

    def upsert_player_statistics(self, stats_data: Dict[str, Any]) -> None:
        """
        Insert or update player statistics for a tournament.

        If a row for ``(tournament_id, player_id)`` already exists it is
        updated; otherwise a new row is inserted.
        """
        coerced = _coerce_datetimes(stats_data)
        with self._session() as session:
            existing = (
                session.query(PlayerStatistics)
                .filter_by(
                    tournament_id=coerced["tournament_id"],
                    player_id=coerced["player_id"],
                )
                .first()
            )
            if existing:
                for key, value in coerced.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(PlayerStatistics(**coerced))
            session.commit()

    def insert_bubble_snapshot(self, bubble_data: Dict[str, Any]) -> int:
        """Insert a bubble tracking snapshot; returns ``bubble_id``."""
        with self._session() as session:
            snapshot = BubbleTracking(**_coerce_datetimes(bubble_data))
            session.add(snapshot)
            session.commit()
            return snapshot.bubble_id

    def insert_session_metadata(self, metadata: Dict[str, Any]) -> str:
        """Insert session metadata; returns ``session_id``."""
        with self._session() as session:
            record = SessionMetadata(**_coerce_datetimes(metadata))
            session.add(record)
            session.commit()
            return record.session_id

    # ------------------------------------------------------------------
    # Pre-built analytics queries
    # ------------------------------------------------------------------

    def get_vpip(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Calculate VPIP (Voluntarily Put In Pot %) for every player.

        Returns
        -------
        list of dict with keys ``player_id``, ``vpip_percentage``.
        """
        with self._session() as session:
            rows = session.execute(_QUERY_VPIP, {"tid": tournament_id})
            return [dict(r._mapping) for r in rows]

    def get_aggression_factors(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Return aggression factor (Bets+Raises / Calls) per player.

        Returns
        -------
        list of dict with keys ``player_id``, ``aggressive_actions``,
        ``calls``, ``aggression_factor``.
        """
        with self._session() as session:
            rows = session.execute(
                _QUERY_AGGRESSION_FACTOR, {"tid": tournament_id}
            )
            return [dict(r._mapping) for r in rows]

    def get_showdown_percentages(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Return showdown percentage per player.

        Returns
        -------
        list of dict with keys ``player_id``, ``showdown_percentage``.
        """
        with self._session() as session:
            rows = session.execute(_QUERY_SHOWDOWN_PCT, {"tid": tournament_id})
            return [dict(r._mapping) for r in rows]

    def get_fish_scores(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Return fish detection scores for all players, highest first.

        Score is derived from pre-stored ``vpip`` and ``aggression_factor``
        in :table:`player_statistics`.

        Returns
        -------
        list of dict with keys ``player_id``, ``vpip``,
        ``aggression_factor``, ``fish_score``.
        """
        with self._session() as session:
            rows = session.execute(_QUERY_FISH_SCORES, {"tid": tournament_id})
            return [dict(r._mapping) for r in rows]

    def get_win_rate_by_position(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Return hero win-rate statistics broken down by table position.

        Returns
        -------
        list of dict with keys ``position``, ``hands_played``,
        ``hands_won``, ``win_percentage``, ``total_profit``.
        """
        with self._session() as session:
            rows = session.execute(
                _QUERY_WIN_RATE_BY_POSITION, {"tid": tournament_id}
            )
            return [dict(r._mapping) for r in rows]

    def get_bubble_progression(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Return bubble tracking snapshots ordered by hand number.

        Returns
        -------
        list of dict with bubble metrics per snapshot.
        """
        with self._session() as session:
            rows = session.execute(
                _QUERY_BUBBLE_PROGRESSION, {"tid": tournament_id}
            )
            return [dict(r._mapping) for r in rows]

    def get_hand_history(self, tournament_id: str) -> List[Dict[str, Any]]:
        """
        Return the hero's hand history for a tournament.

        Returns
        -------
        list of dict with hand details ordered by hand_number.
        """
        with self._session() as session:
            rows = session.execute(_QUERY_HAND_HISTORY, {"tid": tournament_id})
            return [dict(r._mapping) for r in rows]

    def get_tournament_summary(self, tournament_id: str) -> Optional[Dict[str, Any]]:
        """
        Return a summary of the tournament including ROI, position, and pace.

        Returns
        -------
        dict or None if the tournament is not found.
        """
        with self._session() as session:
            rows = session.execute(
                _QUERY_TOURNAMENT_SUMMARY, {"tid": tournament_id}
            )
            row = rows.fetchone()
            return dict(row._mapping) if row else None

    # ------------------------------------------------------------------
    # Export utilities
    # ------------------------------------------------------------------

    def export_hand_history_to_csv(
        self, tournament_id: str, output_file: str
    ) -> str:
        """
        Export the hero's hand history to a CSV file.

        Parameters
        ----------
        tournament_id : str
        output_file : str
            Destination file path (created or overwritten).

        Returns
        -------
        str
            Absolute path of the written file.
        """
        rows = self.get_hand_history(tournament_id)
        if not rows:
            logger.warning(
                "No hand history found for tournament %s", tournament_id
            )
            return output_file

        output_file = os.path.abspath(output_file)
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

        with open(output_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        logger.info(
            "Exported %d hands to %s", len(rows), output_file
        )
        return output_file

    def export_player_stats_to_csv(
        self, tournament_id: str, output_file: str
    ) -> str:
        """
        Export player statistics (with fish scores) to a CSV file.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        rows = self.get_fish_scores(tournament_id)
        if not rows:
            logger.warning(
                "No player stats found for tournament %s", tournament_id
            )
            return output_file

        output_file = os.path.abspath(output_file)
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

        with open(output_file, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        logger.info("Exported player stats to %s", output_file)
        return output_file
