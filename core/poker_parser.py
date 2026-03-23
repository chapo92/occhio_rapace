from __future__ import annotations
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import numpy as np

from .ocr_processor import OCRProcessor
from .computer_vision import ComputerVision

logger = logging.getLogger(__name__)

POSITIONS_ORDER = ["BTN", "SB", "BB", "UTG", "UTG+1", "CO", "HJ"]
HAND_STAGES = ["preflop", "flop", "turn", "river", "showdown"]


class PokerParser:
    def __init__(self):
        self.ocr = OCRProcessor()
        self.cv = ComputerVision()
        self.session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._vpip_tracker: Dict[int, Dict] = {}
        self._hand_count = 0

    def parse_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        result = self._empty_hand()
        try:
            bbox, confidence, shape = self.cv.detect_poker_table_with_confidence(frame)
            result["table_detected"] = bbox is not None
            result["table_confidence"] = confidence
            result["table_shape"] = shape
            if bbox:
                x, y, w, h = bbox
                table_region = frame[y:y+h, x:x+w]
                full_text = self.ocr.read_text(table_region)
                result["stage"] = self.detect_hand_stage(full_text)
                result["pot"] = self.extract_pot(full_text)
                sb, bb = self.extract_blinds(full_text)
                result["small_blind"] = sb
                result["big_blind"] = bb
                result["players"] = self.extract_players(table_region, bbox)
                result["player_count"] = len(result["players"])
                result["cards"] = self.cv.detect_cards(table_region)
        except Exception as e:
            logger.error("parse_frame error: %s", e)
        return result

    def _empty_hand(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "table_detected": False,
            "table_confidence": 0.0,
            "table_shape": "unknown",
            "stage": "preflop",
            "pot": None,
            "small_blind": None,
            "big_blind": None,
            "player_count": 0,
            "players": [],
            "cards": [],
        }

    def extract_blinds(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        patterns = [
            r'\$?([\d.]+)\s*/\s*\$?([\d.]+)',
            r'([\d.]+)\s*/\s*([\d.]+)',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                try:
                    return float(m.group(1)), float(m.group(2))
                except ValueError:
                    continue
        return None, None

    def extract_pot(self, text: str) -> Optional[float]:
        patterns = [
            r'[Pp]ot\s*:?\s*\$?([\d,.]+)',
            r'[Tt]otal\s+[Pp]ot\s+\$?([\d,.]+)',
            r'[Pp]ot\s+([\d,.]+)',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                try:
                    return float(m.group(1).replace(',', ''))
                except ValueError:
                    continue
        return None

    def detect_hand_stage(self, text: str) -> str:
        text_lower = text.lower()
        for stage in reversed(HAND_STAGES):
            if stage in text_lower:
                return stage
        return "preflop"

    def extract_players(self, region: np.ndarray, bbox: Tuple) -> List[Dict]:
        return []

    def assign_positions(self, player_count: int) -> List[str]:
        if player_count <= 0:
            return []
        positions = POSITIONS_ORDER[:player_count]
        while len(positions) < player_count:
            positions.append(f"P{len(positions)+1}")
        return positions

    def detect_fish(self, vpip: float, threshold: float = 40.0) -> bool:
        return vpip >= threshold

    def update_vpip(self, seat: int, voluntarily_put_in_preflop: bool):
        if seat not in self._vpip_tracker:
            self._vpip_tracker[seat] = {"hands": 0, "vpip_count": 0}
        self._vpip_tracker[seat]["hands"] += 1
        if voluntarily_put_in_preflop:
            self._vpip_tracker[seat]["vpip_count"] += 1

    def get_vpip(self, seat: int) -> float:
        if seat not in self._vpip_tracker or self._vpip_tracker[seat]["hands"] == 0:
            return 0.0
        d = self._vpip_tracker[seat]
        return (d["vpip_count"] / d["hands"]) * 100.0
