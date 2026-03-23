from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import numpy as np

from .ocr_processor import OCRProcessor
from .computer_vision import ComputerVision
from .card_recognizer import CardRecognizer

logger = logging.getLogger(__name__)

POSITIONS_ORDER = ["BTN", "SB", "BB", "UTG", "UTG+1", "CO", "HJ"]
HAND_STAGES = ["preflop", "flop", "turn", "river", "showdown"]

# 9-max seat positions in standard 888 layout order (seat index 0–8)
# Starting from BTN and going clockwise: BTN, SB, BB, UTG, UTG+1, MP, MP+1, HJ, CO
SEAT_POSITIONS_9MAX = ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "HJ", "CO"]

_ROIS_CFG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "rois_888.json"
)


def _load_rois_cfg() -> Dict:
    try:
        with open(_ROIS_CFG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("Could not load rois_888.json: %s", exc)
        return {}


def _safe_crop(
    frame: np.ndarray, roi: Tuple[int, int, int, int]
) -> Optional[np.ndarray]:
    """Crop *roi* (x, y, w, h) from *frame* with bounds clamping. Returns None if empty."""
    if frame is None or frame.size == 0:
        return None
    fh, fw = frame.shape[:2]
    x, y, w, h = roi
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(1, min(w, fw - x))
    h = max(1, min(h, fh - y))
    crop = frame[y: y + h, x: x + w]
    if crop.size == 0:
        return None
    return crop


class PokerParser:
    def __init__(self):
        self.ocr = OCRProcessor()
        self.cv = ComputerVision()
        self._rois = _load_rois_cfg()
        self._card_recognizer = self._init_card_recognizer()
        self.session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._vpip_tracker: Dict[int, Dict] = {}
        self._hand_count = 0

    def _init_card_recognizer(self) -> CardRecognizer:
        cr_cfg = self._rois.get("card_recognizer", {})
        return CardRecognizer(
            rank_threshold=cr_cfg.get("rank_threshold", 0.50),
            suit_threshold=cr_cfg.get("suit_threshold", 0.45),
        )

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
                sb, bb, ante = self._extract_blinds_structured(full_text, frame)
                result["small_blind"] = sb
                result["big_blind"] = bb
                result["blinds"] = {"small_blind": sb, "big_blind": bb, "ante": ante}
                result["board_cards"] = self._extract_board_cards(frame)
                result["hero_cards"] = self._extract_hero_cards(frame)
                result["hero_stack"] = self._extract_hero_stack(frame)
                result["players"] = self.extract_players(table_region, bbox, frame)
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
            "blinds": {"small_blind": None, "big_blind": None, "ante": None},
            "player_count": 0,
            "players": [],
            "cards": [],
            "board_cards": [],
            "hero_cards": [],
            "hero_stack": None,
        }

    # ------------------------------------------------------------------
    # Blinds
    # ------------------------------------------------------------------

    def extract_blinds(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        """Legacy two-value extraction kept for backward compatibility."""
        sb, bb, _ = self._extract_blinds_structured(text, None)
        return sb, bb

    def _extract_blinds_structured(
        self,
        text: str,
        frame: Optional[np.ndarray],
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Return (small_blind, big_blind, ante) parsed from text or OCR ROI."""
        sb, bb = self._parse_blinds_from_text(text)
        ante: Optional[float] = None

        # Try OCR on dedicated blinds ROI if text parse failed
        if (sb is None or bb is None) and frame is not None:
            roi_data = self._rois.get("blinds", {}).get("roi")
            if roi_data:
                crop = _safe_crop(frame, tuple(roi_data))
                if crop is not None:
                    roi_text = self.ocr.read_text(crop)
                    sb2, bb2 = self._parse_blinds_from_text(roi_text)
                    if sb is None:
                        sb = sb2
                    if bb is None:
                        bb = bb2

        # Try to extract ante (pattern: "ante X.XX")
        ante_m = re.search(r'[Aa]nte\s*:?\s*\$?([\d,.]+)', text)
        if ante_m:
            try:
                ante = float(ante_m.group(1).replace(',', ''))
            except ValueError:
                pass

        return sb, bb, ante

    @staticmethod
    def _parse_blinds_from_text(
        text: str,
    ) -> Tuple[Optional[float], Optional[float]]:
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

    # ------------------------------------------------------------------
    # Pot
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Card extraction (board + hero)
    # ------------------------------------------------------------------

    def _extract_cards_from_rois(
        self, frame: np.ndarray, roi_list: List[List[int]]
    ) -> List[str]:
        cards: List[str] = []
        for roi in roi_list:
            crop = _safe_crop(frame, tuple(roi))
            if crop is None:
                continue
            rec = self._card_recognizer.recognize_corner(crop)
            if rec.get("card"):
                cards.append(rec["card"])
        return cards

    def _extract_board_cards(self, frame: np.ndarray) -> List[str]:
        roi_list = self._rois.get("board_corners", [])
        if not roi_list:
            return []
        return self._extract_cards_from_rois(frame, roi_list)

    def _extract_hero_cards(self, frame: np.ndarray) -> List[str]:
        roi_list = self._rois.get("hero_corners", [])
        if not roi_list:
            return []
        return self._extract_cards_from_rois(frame, roi_list)

    # ------------------------------------------------------------------
    # Hero stack
    # ------------------------------------------------------------------

    def _extract_hero_stack(self, frame: np.ndarray) -> Optional[float]:
        roi_data = self._rois.get("hero_stack")
        if not roi_data:
            return None
        crop = _safe_crop(frame, tuple(roi_data))
        if crop is None:
            return None
        return self.ocr.read_number(crop)

    # ------------------------------------------------------------------
    # Stage / hand-stage
    # ------------------------------------------------------------------

    def detect_hand_stage(self, text: str) -> str:
        text_lower = text.lower()
        for stage in reversed(HAND_STAGES):
            if stage in text_lower:
                return stage
        return "preflop"

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------

    def extract_players(
        self,
        region: np.ndarray,
        bbox: Tuple,
        full_frame: Optional[np.ndarray] = None,
    ) -> List[Dict]:
        """
        Extract player info from seat ROIs defined in rois_888.json.

        Each entry in the returned list has:
            seat     : int  (1-based)
            name     : str | None
            stack    : float | None
            position : str | None
        """
        seats_cfg = self._rois.get("seats_9max", {})
        name_rois = seats_cfg.get("name_rois", [])
        stack_rois = seats_cfg.get("stack_rois", [])

        if not name_rois and not stack_rois:
            return []

        frame = full_frame if full_frame is not None else region
        n_seats = max(len(name_rois), len(stack_rois))
        positions = self.assign_positions(n_seats)
        players: List[Dict] = []

        for i in range(n_seats):
            seat_num = i + 1
            name: Optional[str] = None
            stack: Optional[float] = None

            if i < len(name_rois):
                crop = _safe_crop(frame, tuple(name_rois[i]))
                if crop is not None:
                    raw = self.ocr.read_text(crop).strip()
                    name = raw if raw else None

            if i < len(stack_rois):
                crop = _safe_crop(frame, tuple(stack_rois[i]))
                if crop is not None:
                    stack = self.ocr.read_number(crop)

            players.append({
                "seat": seat_num,
                "name": name,
                "stack": stack,
                "position": positions[i] if i < len(positions) else None,
            })

        return players

    def assign_positions(self, player_count: int) -> List[str]:
        if player_count <= 0:
            return []
        base = SEAT_POSITIONS_9MAX if player_count <= 9 else POSITIONS_ORDER
        positions = list(base[:player_count])
        while len(positions) < player_count:
            positions.append(f"P{len(positions)+1}")
        return positions

    # ------------------------------------------------------------------
    # Utility / stats
    # ------------------------------------------------------------------

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
