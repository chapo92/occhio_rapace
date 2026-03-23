"""
Occhi di Falco - Computer Vision Module
Detects poker table elements using OpenCV template matching and contour analysis.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Colours (BGR) used in poker UI detection
_GREEN_FELT_LOWER = np.array([30, 80, 20], dtype=np.uint8)
_GREEN_FELT_UPPER = np.array([90, 255, 100], dtype=np.uint8)

_CARD_WHITE_LOWER = np.array([200, 200, 200], dtype=np.uint8)
_CARD_WHITE_UPPER = np.array([255, 255, 255], dtype=np.uint8)

# Chip colour ranges (yellow/gold)
_CHIP_LOWER = np.array([10, 100, 100], dtype=np.uint8)
_CHIP_UPPER = np.array([40, 255, 255], dtype=np.uint8)


class ComputerVision:
    """
    Uses OpenCV for detecting poker table regions of interest.

    Parameters
    ----------
    template_dir : str
        Path to folder containing template PNG images.
    match_threshold : float
        Minimum normalised cross-correlation score for template matches.
    """

    def __init__(self, template_dir: str = "templates", match_threshold: float = 0.75):
        self.template_dir = template_dir
        self.match_threshold = match_threshold
        self._templates: Dict[str, np.ndarray] = {}
        self._load_templates()

    # ------------------------------------------------------------------
    # Template management
    # ------------------------------------------------------------------

    def _load_templates(self) -> None:
        """Load all PNG templates from *template_dir*."""
        if not os.path.isdir(self.template_dir):
            logger.debug("Template directory not found: %s", self.template_dir)
            return

        for fname in os.listdir(self.template_dir):
            if fname.lower().endswith(".png"):
                path = os.path.join(self.template_dir, fname)
                tpl = cv2.imread(path, cv2.IMREAD_COLOR)
                if tpl is not None:
                    key = os.path.splitext(fname)[0]
                    self._templates[key] = tpl
                    logger.debug("Loaded template: %s", key)

        logger.info("Loaded %d templates from %s", len(self._templates), self.template_dir)

    # ------------------------------------------------------------------
    # Table detection
    # ------------------------------------------------------------------

    def detect_poker_table(self, frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the poker table felt region in *frame*.

        Uses colour segmentation on the green felt colour.

        Parameters
        ----------
        frame : np.ndarray
            Full BGR screen frame.

        Returns
        -------
        tuple or None
            Bounding box (x, y, w, h) of the largest green region, or None.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # HSV range for green felt
        lower = np.array([35, 40, 30], dtype=np.uint8)
        upper = np.array([85, 255, 200], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)

        # Morphological clean-up
        kernel = np.ones((15, 15), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 10_000:
            return None

        return cv2.boundingRect(largest)

    # ------------------------------------------------------------------
    # Card / chip detection
    # ------------------------------------------------------------------

    def detect_cards(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detect white rectangular card shapes in *frame*.

        Returns
        -------
        list of (x, y, w, h)
            Bounding boxes of detected cards, sorted left-to-right.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)

        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        cards = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / max(h, 1)
            area = w * h
            # Cards are roughly portrait (aspect ~0.6–0.85) and at least 800 px²
            if 0.5 < aspect < 0.9 and 800 < area < 50_000:
                cards.append((x, y, w, h))

        # Sort left-to-right (community cards on board)
        cards.sort(key=lambda b: b[0])
        return cards

    def detect_chips(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detect chip stack areas (yellow/gold circles) in *frame*.

        Returns
        -------
        list of (x, y, w, h)
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, _CHIP_LOWER, _CHIP_UPPER)

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        chips = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 500:
                chips.append(cv2.boundingRect(cnt))

        return chips

    # ------------------------------------------------------------------
    # Template matching
    # ------------------------------------------------------------------

    def find_template(
        self,
        frame: np.ndarray,
        template_name: str,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Locate a named template in *frame*.

        Parameters
        ----------
        frame : np.ndarray
            BGR image to search in.
        template_name : str
            Key matching a loaded template (filename without extension).

        Returns
        -------
        tuple or None
            (x, y, w, h) bounding box of best match, or None.
        """
        tpl = self._templates.get(template_name)
        if tpl is None:
            logger.debug("Template not found: %s", template_name)
            return None

        result = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < self.match_threshold:
            return None

        h, w = tpl.shape[:2]
        x, y = max_loc
        return (x, y, w, h)

    def find_all_templates(
        self,
        frame: np.ndarray,
        template_name: str,
    ) -> List[Tuple[int, int, int, int]]:
        """
        Find all occurrences of a template in *frame*.

        Parameters
        ----------
        frame : np.ndarray
        template_name : str

        Returns
        -------
        list of (x, y, w, h)
        """
        tpl = self._templates.get(template_name)
        if tpl is None:
            return []

        result = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= self.match_threshold)

        h, w = tpl.shape[:2]
        boxes = []
        for pt in zip(*locations[::-1]):
            boxes.append((int(pt[0]), int(pt[1]), w, h))

        # Non-maximum suppression (remove overlapping detections)
        return self._nms(boxes, overlap_threshold=0.3)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _nms(
        boxes: List[Tuple[int, int, int, int]],
        overlap_threshold: float = 0.3,
    ) -> List[Tuple[int, int, int, int]]:
        """Simple non-maximum suppression for bounding boxes."""
        if not boxes:
            return []

        boxes_np = np.array([[x, y, x + w, y + h] for x, y, w, h in boxes], dtype=float)
        areas = (boxes_np[:, 2] - boxes_np[:, 0]) * (boxes_np[:, 3] - boxes_np[:, 1])
        order = np.argsort(areas)[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))

            xx1 = np.maximum(boxes_np[i, 0], boxes_np[order[1:], 0])
            yy1 = np.maximum(boxes_np[i, 1], boxes_np[order[1:], 1])
            xx2 = np.minimum(boxes_np[i, 2], boxes_np[order[1:], 2])
            yy2 = np.minimum(boxes_np[i, 3], boxes_np[order[1:], 3])

            inter_w = np.maximum(0.0, xx2 - xx1)
            inter_h = np.maximum(0.0, yy2 - yy1)
            inter = inter_w * inter_h
            union = areas[i] + areas[order[1:]] - inter
            iou = inter / np.maximum(union, 1e-6)

            order = order[np.where(iou <= overlap_threshold)[0] + 1]

        return [boxes[i] for i in keep]

    @staticmethod
    def draw_detections(
        frame: np.ndarray,
        detections: Dict[str, List[Tuple[int, int, int, int]]],
    ) -> np.ndarray:
        """
        Draw bounding boxes on a copy of *frame* for debugging.

        Parameters
        ----------
        frame : np.ndarray
        detections : dict
            Mapping from label to list of (x, y, w, h) boxes.

        Returns
        -------
        np.ndarray
            Annotated BGR image.
        """
        colours = {
            "table": (0, 200, 0),
            "card": (255, 200, 0),
            "chip": (0, 200, 255),
        }
        out = frame.copy()
        for label, boxes in detections.items():
            colour = colours.get(label, (200, 200, 200))
            for x, y, w, h in boxes:
                cv2.rectangle(out, (x, y), (x + w, y + h), colour, 2)
                cv2.putText(out, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
        return out
