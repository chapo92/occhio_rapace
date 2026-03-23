"""
Occhi di Falco - Poker Parser Module
Converts raw OCR text and CV detections into structured poker hand data.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from ocr_processor import OCRProcessor
from computer_vision import ComputerVision

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSITIONS_ORDER = ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "CO"]
HAND_STAGES = ["preflop", "flop", "turn", "river", "showdown"]

# Keywords that signal poker actions in OCR text
_ACTION_PATTERNS = {
    "fold": re.compile(r"\bfold(s)?\b", re.I),
    "check": re.compile(r"\bcheck(s)?\b", re.I),
    "call": re.compile(r"\bcall(s)?\b", re.I),
    "raise": re.compile(r"\braise(s|d)?\b", re.I),
    "bet": re.compile(r"\bbet(s)?\b", re.I),
    "all-in": re.compile(r"\ball[\s-]in\b", re.I),
    "post": re.compile(r"\bpost(s|ed)?\b", re.I),
}

# Stage detection keywords
_STAGE_PATTERNS = {
    "flop": re.compile(r"\bflop\b", re.I),
    "turn": re.compile(r"\bturn\b", re.I),
    "river": re.compile(r"\briver\b", re.I),
    "showdown": re.compile(r"\bshow(down|cards?)?\b", re.I),
}

# Table format detection
_FORMAT_PATTERNS = {
    "2-max": re.compile(r"\b2[\s-]?max\b|\bheads[\s-]?up\b", re.I),
    "6-max": re.compile(r"\b6[\s-]?max\b", re.I),
    "9-max": re.compile(r"\b9[\s-]?max\b|\bfull[\s-]ring\b", re.I),
}

# ---------------------------------------------------------------------------
# Data classes (plain dicts for JSON-serialisable output)
# ---------------------------------------------------------------------------


def _make_player(
    seat: int,
    position: str = "unknown",
    stack: Optional[float] = None,
    status: str = "active",
    action: Optional[str] = None,
    bet: Optional[float] = None,
    is_dealer: bool = False,
    is_fish: Optional[bool] = None,
) -> Dict[str, Any]:
    return {
        "seat": seat,
        "position": position,
        "stack": stack,
        "status": status,
        "action": action,
        "bet": bet,
        "is_dealer": is_dealer,
        "is_fish": is_fish,
    }


def _make_hand_data(
    table_name: str = "Unknown",
    platform: str = "unknown",
    game_format: str = "unknown",
    game_type: str = "NLHE",
    small_blind: Optional[float] = None,
    big_blind: Optional[float] = None,
    ante: float = 0.0,
    pot: Optional[float] = None,
    hand_stage: str = "preflop",
    players: Optional[List] = None,
    actions_history: Optional[List] = None,
    community_cards_count: int = 0,
) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "table_info": {
            "name": table_name,
            "platform": platform,
            "format": game_format,
            "game_type": game_type,
        },
        "blinds": {
            "small_blind": small_blind,
            "big_blind": big_blind,
            "ante": ante,
        },
        "pot": pot,
        "hand_stage": hand_stage,
        "players": players or [],
        "player_count": len(players) if players else 0,
        "actions_history": actions_history or [],
        "community_cards_count": community_cards_count,
    }


# ---------------------------------------------------------------------------
# PokerParser
# ---------------------------------------------------------------------------


class PokerParser:
    """
    Parses a screen frame into a structured poker hand dictionary.

    Parameters
    ----------
    ocr : OCRProcessor
        OCR engine instance.
    cv : ComputerVision
        Computer vision engine instance.
    platform : str
        Target platform ("pokerstars" or "888poker").
    """

    def __init__(
        self,
        ocr: OCRProcessor,
        cv: ComputerVision,
        platform: str = "pokerstars",
    ):
        self.ocr = ocr
        self.cv = cv
        self.platform = platform.lower()
        self._actions_history: List[Dict[str, Any]] = []
        self._prev_stage: str = "preflop"
        self._vpip_counts: Dict[int, int] = {}  # seat → VPIP hand count
        self._hand_counts: Dict[int, int] = {}   # seat → total hand count

    # ------------------------------------------------------------------
    # Main parse entry-point
    # ------------------------------------------------------------------

    def parse_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Extract all poker data from a single BGR frame.

        Parameters
        ----------
        frame : np.ndarray
            Full-screen BGR image.

        Returns
        -------
        dict
            Structured hand data (JSON-serialisable).
        """
        full_text = self.ocr.read_text(frame)

        # Structural detections
        table_box = self.cv.detect_poker_table(frame)
        cards = self.cv.detect_cards(frame)

        # Extract individual fields
        platform = self._detect_platform(full_text)
        game_format = self._detect_format(full_text)
        table_name = self._extract_table_name(full_text, platform)
        hand_stage = self._detect_hand_stage(full_text, cards)
        sb, bb, ante = self._extract_blinds(full_text)
        pot = self._extract_pot(full_text)
        players = self._extract_players(frame, full_text)
        self._update_fish_tags(players)
        self._update_actions_history(full_text, players, hand_stage)

        hand_data = _make_hand_data(
            table_name=table_name,
            platform=platform,
            game_format=game_format,
            small_blind=sb,
            big_blind=bb,
            ante=ante,
            pot=pot,
            hand_stage=hand_stage,
            players=players,
            actions_history=list(self._actions_history),
            community_cards_count=len(cards),
        )

        if table_box:
            hand_data["table_box"] = list(table_box)

        self._prev_stage = hand_stage
        return hand_data

    # ------------------------------------------------------------------
    # Platform & format detection
    # ------------------------------------------------------------------

    def _detect_platform(self, text: str) -> str:
        t = text.lower()
        if "pokerstars" in t or "stars" in t:
            return "pokerstars"
        if "888" in t or "pacific" in t:
            return "888poker"
        return self.platform

    def _detect_format(self, text: str) -> str:
        for fmt, pat in _FORMAT_PATTERNS.items():
            if pat.search(text):
                return fmt
        return "unknown"

    # ------------------------------------------------------------------
    # Table name
    # ------------------------------------------------------------------

    def _extract_table_name(self, text: str, platform: str) -> str:
        if platform == "pokerstars":
            m = re.search(r"Table\s+'?([^'\n]+)'?", text, re.I)
            if m:
                return m.group(1).strip()
        elif platform == "888poker":
            m = re.search(r"Table\s+#?(\d+)", text, re.I)
            if m:
                return f"888 Table #{m.group(1)}"
        return "Unknown Table"

    # ------------------------------------------------------------------
    # Blinds & ante
    # ------------------------------------------------------------------

    def _extract_blinds(self, text: str) -> tuple:
        """
        Return (small_blind, big_blind, ante).
        Looks for patterns like "0.5/1", "$0.50/$1", "SB 0.50", etc.
        """
        sb = bb = ante = None

        # Pattern: "0.5/1" or "$0.50/$1.00"
        m = re.search(
            r"[$€£]?(\d+(?:[.,]\d+)?)\s*/\s*[$€£]?(\d+(?:[.,]\d+)?)",
            text,
        )
        if m:
            sb = float(m.group(1).replace(",", "."))
            bb = float(m.group(2).replace(",", "."))

        # Ante: "Ante 0.10" or "ante: 0.10"
        m_ante = re.search(r"\bante\b\s*:?\s*[$€£]?(\d+(?:[.,]\d+)?)", text, re.I)
        if m_ante:
            ante = float(m_ante.group(1).replace(",", "."))

        return sb, bb, (ante or 0.0)

    # ------------------------------------------------------------------
    # Pot
    # ------------------------------------------------------------------

    def _extract_pot(self, text: str) -> Optional[float]:
        """Extract total pot size from OCR text."""
        m = re.search(
            r"\bpot\b\s*:?\s*[$€£]?(\d+(?:[.,]\d+)?)",
            text,
            re.I,
        )
        if m:
            return float(m.group(1).replace(",", "."))

        # Total pot line (PokerStars format)
        m = re.search(r"Total\s+pot\s+[$€£]?(\d+(?:[.,]\d+)?)", text, re.I)
        if m:
            return float(m.group(1).replace(",", "."))

        return None

    # ------------------------------------------------------------------
    # Hand stage
    # ------------------------------------------------------------------

    def _detect_hand_stage(self, text: str, cards: list) -> str:
        for stage, pat in _STAGE_PATTERNS.items():
            if pat.search(text):
                return stage

        # Infer from number of community cards
        n_cards = len(cards)
        if n_cards == 0:
            return "preflop"
        if n_cards == 3:
            return "flop"
        if n_cards == 4:
            return "turn"
        if n_cards >= 5:
            return "river"

        return self._prev_stage

    # ------------------------------------------------------------------
    # Player extraction
    # ------------------------------------------------------------------

    def _extract_players(self, frame: np.ndarray, text: str) -> List[Dict[str, Any]]:
        """
        Build a list of player dictionaries from OCR text.

        Looks for patterns like "Seat 1: PlayerName ($145.30 in chips)"
        or simple stack indications near player name regions.
        """
        players: List[Dict[str, Any]] = []

        # PokerStars-style: "Seat N: <name> ($<stack> in chips)"
        seat_pattern = re.compile(
            r"Seat\s+(\d+):\s+(\S+)\s+\([$€£]?(\d+(?:[.,]\d+)?)\s+in\s+chips\)",
            re.I,
        )
        for m in seat_pattern.finditer(text):
            seat = int(m.group(1))
            stack = float(m.group(3).replace(",", "."))
            players.append(_make_player(seat=seat, stack=stack))

        # 888 Poker style: "Player 1: $145.30"
        if not players:
            p888 = re.compile(
                r"Player\s+(\d+)\s*:?\s*[$€£]?(\d+(?:[.,]\d+)?)",
                re.I,
            )
            for m in p888.finditer(text):
                seat = int(m.group(1))
                stack = float(m.group(2).replace(",", "."))
                players.append(_make_player(seat=seat, stack=stack))

        # Assign positions cyclically if we found players
        if players:
            players = self._assign_positions(players, text)

        return players

    def _assign_positions(
        self,
        players: List[Dict[str, Any]],
        text: str,
    ) -> List[Dict[str, Any]]:
        """Assign BTN/SB/BB/etc. positions to players."""
        n = len(players)
        if n == 0:
            return players

        # Try to find the dealer seat from OCR (e.g. "Seat 3 is the button")
        btn_seat = None
        m = re.search(r"Seat\s+(\d+)\s+is\s+the\s+button", text, re.I)
        if m:
            btn_seat = int(m.group(1))

        # Find seat index of dealer
        seats = [p["seat"] for p in players]
        btn_idx = 0
        if btn_seat and btn_seat in seats:
            btn_idx = seats.index(btn_seat)

        pos_cycle = ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "CO"]
        for i, player in enumerate(players):
            pos_idx = (i - btn_idx) % n
            player["position"] = pos_cycle[pos_idx] if pos_idx < len(pos_cycle) else f"P{pos_idx}"
            player["is_dealer"] = (i == btn_idx)

        return players

    # ------------------------------------------------------------------
    # Fish (loose/passive) detection
    # ------------------------------------------------------------------

    def _update_fish_tags(self, players: List[Dict[str, Any]]) -> None:
        """
        Tag loose/passive players as 'fish' based on VPIP heuristics.

        A player is considered a fish if their observed VPIP (voluntarily
        put money in pot) rate exceeds 40% over ≥10 hands.
        """
        for p in players:
            seat = p["seat"]
            hands = self._hand_counts.get(seat, 0)
            vpip = self._vpip_counts.get(seat, 0)
            if hands >= 10:
                p["is_fish"] = (vpip / hands) > 0.40
            else:
                p["is_fish"] = None  # Not enough data

    # ------------------------------------------------------------------
    # Actions history
    # ------------------------------------------------------------------

    def _update_actions_history(
        self,
        text: str,
        players: List[Dict[str, Any]],
        stage: str,
    ) -> None:
        """
        Detect player actions in *text* and append new entries to the
        running actions history.
        """
        # Clear history on new hand (detect "New hand" or stage resets to preflop)
        if stage == "preflop" and self._prev_stage in ("river", "showdown"):
            self._actions_history.clear()
            logger.info("New hand detected – actions history cleared")

        ts = datetime.now(timezone.utc).isoformat()

        for action_name, pat in _ACTION_PATTERNS.items():
            for m in pat.finditer(text):
                # Try to find an associated amount (e.g. "raises to 12.50")
                amount = None
                amount_m = re.search(
                    r"(?:raises?|bets?|calls?)\s+(?:to\s+)?[$€£]?(\d+(?:[.,]\d+)?)",
                    m.string[max(0, m.start() - 20): m.end() + 30],
                    re.I,
                )
                if amount_m:
                    amount = float(amount_m.group(1).replace(",", "."))

                entry = {
                    "timestamp": ts,
                    "stage": stage,
                    "action": action_name,
                    "amount": amount,
                    "raw_text": m.string[max(0, m.start() - 20): m.end() + 30].strip(),
                }
                # Avoid duplicating the very same entry
                if entry not in self._actions_history[-5:]:
                    self._actions_history.append(entry)

        # Update VPIP counters for players who bet/raise/call (not fold/check)
        for p in players:
            action = p.get("action")
            seat = p["seat"]
            if action in ("raise", "bet", "call"):
                self._vpip_counts[seat] = self._vpip_counts.get(seat, 0) + 1
            if action in ("fold", "check", "call", "raise", "bet"):
                self._hand_counts[seat] = self._hand_counts.get(seat, 0) + 1

    def reset_session(self) -> None:
        """Reset all session state (actions history, VPIP counters)."""
        self._actions_history.clear()
        self._vpip_counts.clear()
        self._hand_counts.clear()
        self._prev_stage = "preflop"
        logger.info("Session state reset")
