from __future__ import annotations
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from features.database_manager import DatabaseManager
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class DataExporter:
    def __init__(self, output_dir: str = "output", session_id: str = ""):
        self.output_dir = output_dir
        self.session_id = session_id or f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_dir = os.path.join(output_dir, "sessions", self.session_id)
        os.makedirs(self.session_dir, exist_ok=True)
        self._history: List[Dict] = []
        self._db: Optional[Any] = None
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
        if self._db:
            try:
                self._db.save_hand(hand_data, self.session_id)
            except Exception as e:
                logger.debug("DB save failed: %s", e)
        return filename

    def get_latest(self) -> Optional[Dict]:
        return self._history[-1] if self._history else None

    def get_all(self) -> List[Dict]:
        return list(self._history)

    def clear_session(self):
        self._history.clear()
        logger.info("Session cleared")
