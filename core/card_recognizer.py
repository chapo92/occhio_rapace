"""
Card recognizer for 888 Poker using template matching (rank + suit separately).

Template directory layout (supported):
  card_templates/
    ranks/   ← one PNG/JPG per rank: A.png, K.png, Q.png, J.png, T.png, 9.png … 2.png
    suits/   ← one PNG/JPG per suit: spade.png, heart.png, diamond.png, club.png

Alternatively (flat naming with prefixes):
  card_templates/
    rank_A.png, rank_K.png … rank_2.png
    suit_spade.png, suit_heart.png, suit_diamond.png, suit_club.png

Suit file → single-char code mapping:
  spade/s → 's'
  heart/h → 'h'
  diamond/d → 'd'
  club/c   → 'c'

Usage
-----
    recognizer = CardRecognizer()
    result = recognizer.recognize_corner(corner_img)
    # result = {"rank": "A", "suit": "h", "card": "Ah",
    #           "rank_score": 0.92, "suit_score": 0.88}
    # or {"rank": None, "suit": None, "card": None, ...} on failure
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Default template directory (relative to repository root)
_DEFAULT_TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "card_templates"
)

# Suit filename stem → single-character code
_SUIT_MAP: Dict[str, str] = {
    "spade": "s",
    "spades": "s",
    "s": "s",
    "heart": "h",
    "hearts": "h",
    "h": "h",
    "diamond": "d",
    "diamonds": "d",
    "d": "d",
    "club": "c",
    "clubs": "c",
    "c": "c",
}

# Valid rank characters
_VALID_RANKS = set("23456789TJQKA")


class CardRecognizer:
    """
    Recognizes a single playing-card corner image by matching rank and suit
    templates separately with ``cv2.matchTemplate`` (TM_CCOEFF_NORMED).

    Parameters
    ----------
    template_dir : str, optional
        Root directory that contains ``ranks/`` and ``suits/`` subdirectories
        (or flat files with ``rank_``/``suit_`` prefixes).
    rank_threshold : float
        Minimum match score to accept a rank result (0–1).
    suit_threshold : float
        Minimum match score to accept a suit result (0–1).
    """

    def __init__(
        self,
        template_dir: Optional[str] = None,
        rank_threshold: float = 0.50,
        suit_threshold: float = 0.45,
    ) -> None:
        self.template_dir = os.path.abspath(
            template_dir if template_dir else _DEFAULT_TEMPLATE_DIR
        )
        self.rank_threshold = rank_threshold
        self.suit_threshold = suit_threshold

        self._rank_templates: Dict[str, np.ndarray] = {}
        self._suit_templates: Dict[str, np.ndarray] = {}
        self._load_templates()

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------

    def _load_templates(self) -> None:
        """Load all rank and suit templates from *template_dir*."""
        if not os.path.isdir(self.template_dir):
            logger.debug("CardRecognizer: template dir not found: %s", self.template_dir)
            return

        ranks_dir = os.path.join(self.template_dir, "ranks")
        suits_dir = os.path.join(self.template_dir, "suits")

        if os.path.isdir(ranks_dir) and os.path.isdir(suits_dir):
            self._rank_templates = self._load_from_dir(ranks_dir, "rank")
            self._suit_templates = self._load_from_dir(suits_dir, "suit")
        else:
            # Flat directory with prefix-named files
            all_files = [
                f for f in os.listdir(self.template_dir)
                if os.path.isfile(os.path.join(self.template_dir, f))
            ]
            for fname in all_files:
                stem, ext = os.path.splitext(fname)
                if ext.lower() not in {".png", ".jpg", ".jpeg"}:
                    continue
                path = os.path.join(self.template_dir, fname)
                img = self._load_gray(path)
                if img is None:
                    continue
                if stem.lower().startswith("rank_"):
                    key = stem[5:].upper()
                    if key in _VALID_RANKS:
                        self._rank_templates[key] = img
                elif stem.lower().startswith("suit_"):
                    code = _SUIT_MAP.get(stem[5:].lower())
                    if code:
                        self._suit_templates[code] = img

        logger.debug(
            "CardRecognizer: loaded %d rank templates %s, %d suit templates %s",
            len(self._rank_templates), sorted(self._rank_templates),
            len(self._suit_templates), sorted(self._suit_templates),
        )

    def _load_from_dir(
        self, directory: str, kind: str
    ) -> Dict[str, np.ndarray]:
        templates: Dict[str, np.ndarray] = {}
        for fname in os.listdir(directory):
            stem, ext = os.path.splitext(fname)
            if ext.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            path = os.path.join(directory, fname)
            img = self._load_gray(path)
            if img is None:
                continue
            if kind == "rank":
                key = stem.upper()
                if key in _VALID_RANKS:
                    templates[key] = img
            else:  # suit
                code = _SUIT_MAP.get(stem.lower())
                if code:
                    templates[code] = img
        return templates

    @staticmethod
    def _load_gray(path: str) -> Optional[np.ndarray]:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            logger.warning("Could not load template: %s", path)
        return img

    # ------------------------------------------------------------------
    # Template properties (for testing / introspection)
    # ------------------------------------------------------------------

    @property
    def loaded_ranks(self) -> List[str]:
        """Sorted list of rank keys that were successfully loaded."""
        return sorted(self._rank_templates)

    @property
    def loaded_suits(self) -> List[str]:
        """Sorted list of suit codes that were successfully loaded."""
        return sorted(self._suit_templates)

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------

    def recognize_corner(self, img: Optional[np.ndarray]) -> Dict:
        """
        Recognize a card from a corner-crop image.

        Parameters
        ----------
        img : np.ndarray
            BGR or grayscale image of the card corner (rank + suit visible).

        Returns
        -------
        dict with keys:
            rank        : str | None   (e.g. "A")
            suit        : str | None   (e.g. "h")
            card        : str | None   (e.g. "Ah")
            rank_score  : float
            suit_score  : float
        """
        result = {
            "rank": None,
            "suit": None,
            "card": None,
            "rank_score": 0.0,
            "suit_score": 0.0,
        }

        if img is None or img.size == 0:
            return result

        # Ensure grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        rank, rank_score = self._best_match(gray, self._rank_templates)
        suit, suit_score = self._best_match(gray, self._suit_templates)

        result["rank_score"] = round(rank_score, 4)
        result["suit_score"] = round(suit_score, 4)

        if rank is not None and rank_score >= self.rank_threshold:
            result["rank"] = rank
        if suit is not None and suit_score >= self.suit_threshold:
            result["suit"] = suit

        if result["rank"] and result["suit"]:
            result["card"] = result["rank"] + result["suit"]

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _best_match(
        gray: np.ndarray,
        templates: Dict[str, np.ndarray],
    ) -> Tuple[Optional[str], float]:
        """
        Run cv2.matchTemplate against every template; return (best_key, best_score).

        The image is tested at its original size and at a half-scale for
        robustness against slight resolution differences.
        """
        if not templates:
            return None, 0.0

        best_key: Optional[str] = None
        best_score: float = 0.0

        for key, tmpl in templates.items():
            score = CardRecognizer._match_score(gray, tmpl)
            if score > best_score:
                best_score = score
                best_key = key

        return best_key, best_score

    @staticmethod
    def _match_score(gray: np.ndarray, tmpl: np.ndarray) -> float:
        """
        Return the best TM_CCOEFF_NORMED match score for *tmpl* against *gray*.

        Handles the case where the template is larger than the image by
        downscaling the template.  Returns 0.0 on any error.
        """
        try:
            h_img, w_img = gray.shape[:2]
            h_tmpl, w_tmpl = tmpl.shape[:2]

        # Scale template down to fit inside the image, keeping a small margin (90%)
            # so the match result has at least 1 pixel to evaluate.
            if h_tmpl > h_img or w_tmpl > w_img:
                scale = min(h_img / h_tmpl, w_img / w_tmpl) * 0.9
                if scale <= 0:
                    return 0.0
                new_w = max(1, int(w_tmpl * scale))
                new_h = max(1, int(h_tmpl * scale))
                tmpl = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
                h_tmpl, w_tmpl = tmpl.shape[:2]

            if h_tmpl < 1 or w_tmpl < 1 or h_img < h_tmpl or w_img < w_tmpl:
                return 0.0

            res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return float(max_val)
        except Exception:
            return 0.0
