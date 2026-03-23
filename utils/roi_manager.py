"""Region of Interest management for 888 Poker table layouts."""
import math
from typing import Dict, List, Optional, Tuple
import numpy as np


class ROIManager:
    """
    Manages dynamic Region-of-Interest (ROI) calculations for 888 Poker table layouts.

    Divides the detected table bounding box into named zones (pot_area, blinds_area,
    community_area, player_areas) based on the table shape. Results are cached by
    (bbox, shape) key so repeated calls within the same frame are free.

    Parameters
    ----------
    table_shape : str
        One of "round", "octagonal", or "elongated_round".
    """
    ZONES = ["pot_area", "blinds_area", "community_area"]

    def __init__(self, table_shape: str = "round"):
        self.table_shape = table_shape
        self._cache: Dict = {}

    def compute_rois(self, bbox: Tuple[int, int, int, int]) -> Dict[str, Tuple[int, int, int, int]]:
        cache_key = (bbox, self.table_shape)
        if cache_key in self._cache:
            return self._cache[cache_key]
        x, y, w, h = bbox
        rois = {
            "pot_area": (x + w // 3, y + h // 3, w // 3, h // 6),
            "blinds_area": (x + w // 4, y + h * 3 // 4, w // 2, h // 8),
            "community_area": (x + w // 6, y + h * 2 // 5, w * 2 // 3, h // 5),
        }
        self._cache[cache_key] = rois
        return rois

    def get_player_areas(self, bbox: Tuple[int, int, int, int], player_count: int) -> List[Tuple[int, int, int, int]]:
        x, y, w, h = bbox
        areas = []
        cx, cy = x + w // 2, y + h // 2
        rx, ry = w * 0.42, h * 0.42
        seat_w, seat_h = max(80, w // 8), max(40, h // 8)
        for i in range(player_count):
            angle = (2 * math.pi * i / player_count) - math.pi / 2
            sx = int(cx + rx * math.cos(angle)) - seat_w // 2
            sy = int(cy + ry * math.sin(angle)) - seat_h // 2
            sx = max(x, min(sx, x + w - seat_w))
            sy = max(y, min(sy, y + h - seat_h))
            areas.append((sx, sy, seat_w, seat_h))
        return areas

    def invalidate_cache(self):
        self._cache.clear()
