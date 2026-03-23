from __future__ import annotations
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import itertools

logger = logging.getLogger(__name__)
_hand_id_counter = itertools.count(1)

try:
    from features.database_manager import DatabaseManager
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


def _build_jones_record(hand_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a *hand_data* dict produced by PokerParser into a Jones-compatible record.

    Minimum required fields for the cervellone project:
        hand_id, table_id, timestamp, blinds, players, board, pot,
        actions (empty), winners (empty).
    """
    blinds = hand_data.get("blinds") or {
        "small_blind": hand_data.get("small_blind"),
        "big_blind": hand_data.get("big_blind"),
        "ante": None,
    }

    # Build player list in Jones format
    players_out = []
    for p in hand_data.get("players", []):
        players_out.append({
            "seat": p.get("seat"),
            "name": p.get("name"),
            "stack": p.get("stack"),
            "position": p.get("position"),
            "hole_cards": [],  # opponents not visible
        })

    # Inject hero hole_cards into the player list if present (seat 0 = hero placeholder)
    hero_cards = hand_data.get("hero_cards", [])
    if hero_cards:
        hero_stack = hand_data.get("hero_stack")
        players_out.insert(0, {
            "seat": 0,
            "name": "HERO",
            "stack": hero_stack,
            "position": None,
            "hole_cards": hero_cards,
        })

    return {
        "hand_id": f"AUTO-{next(_hand_id_counter):08d}-{hand_data.get('timestamp', datetime.now().isoformat())}",
        "table_id": f"888-{hand_data.get('session_id', 'unknown')}",
        "timestamp": hand_data.get("timestamp", datetime.now().isoformat()),
        "blinds": blinds,
        "players": players_out,
        "board": hand_data.get("board_cards", []),
        "pot": hand_data.get("pot"),
        "stage": hand_data.get("stage", "preflop"),
        "actions": [],
        "winners": [],
    }


class DataExporter:
    def __init__(self, output_dir: str = "output", session_id: str = "", jones_dir: Optional[str] = None):
        self.output_dir = output_dir
        self.session_id = session_id or f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_dir = os.path.join(output_dir, "sessions", self.session_id)
        os.makedirs(self.session_dir, exist_ok=True)
        self._history: List[Dict] = []
        self._db: Optional[Any] = None

        # Jones JSONL export
        self._jones_dir = jones_dir or os.path.join(output_dir, "jones")
        os.makedirs(self._jones_dir, exist_ok=True)
        self._jones_path = os.path.join(self._jones_dir, "live.jsonl")

        if DB_AVAILABLE:
            try:
                self._db = DatabaseManager(os.path.join(output_dir, "poker_data.db"))
            except Exception as e:
                logger.warning("DB init failed: %s", e)

    def export(self, hand_data: Dict[str, Any], system_status: Optional[Dict] = None) -> str:
        record = dict(hand_data)
        record["export_timestamp"] = datetime.now().isoformat()
        if system_status:
            record["system_status"] = system_status
        self._history.append(record)
        filename = os.path.join(self.session_dir, f"hand_{len(self._history):06d}.json")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, default=str)
        except Exception as e:
            logger.error("Export failed: %s", e)
        latest_path = os.path.join(self.output_dir, "latest.json")
        try:
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, default=str)
        except Exception as e:
            logger.warning("latest.json write failed: %s", e)
        self._export_jones(hand_data)
        if self._db:
            try:
                self._db.save_hand(hand_data, self.session_id)
            except Exception as e:
                logger.debug("DB save failed: %s", e)
        return filename

    def _export_jones(self, hand_data: Dict[str, Any]) -> None:
        """Append one Jones record to output/jones/live.jsonl."""
        try:
            jones_record = _build_jones_record(hand_data)
            with open(self._jones_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(jones_record, default=str) + "\n")
        except Exception as exc:
            logger.warning("Jones JSONL export failed: %s", exc)

    def get_latest(self) -> Optional[Dict]:
        return self._history[-1] if self._history else None

    def get_all(self) -> List[Dict]:
        return list(self._history)

    def clear_session(self):
        self._history.clear()
        logger.info("Session cleared")
