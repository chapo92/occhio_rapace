from __future__ import annotations
import logging
from typing import Optional, Tuple, List, Dict
import cv2
import numpy as np

logger = logging.getLogger(__name__)

BLUE_HSV_LOWER = np.array([100, 30, 30])
BLUE_HSV_UPPER = np.array([140, 255, 255])
MIN_TABLE_AREA = 50000
SHAPE_TOLERANCE = 0.05
TABLE_SHAPES = ["round", "octagonal", "elongated_round"]


class ComputerVision:
    def __init__(self):
        self._hsv_lower = BLUE_HSV_LOWER.copy()
        self._hsv_upper = BLUE_HSV_UPPER.copy()

    def detect_poker_table(self, frame: np.ndarray) -> Optional[Tuple[int,int,int,int]]:
        bbox, confidence, _ = self.detect_poker_table_with_confidence(frame)
        return bbox

    def detect_poker_table_with_confidence(self, frame: np.ndarray) -> Tuple[Optional[Tuple[int,int,int,int]], float, str]:
        if frame is None or frame.size == 0:
            return None, 0.0, "empty_frame"
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, self._hsv_lower, self._hsv_upper)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return None, 0.0, "no_contours"
            best_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(best_contour)
            if area < MIN_TABLE_AREA:
                return None, 0.0, "too_small"
            x, y, w, h = cv2.boundingRect(best_contour)
            shape, shape_conf = self._classify_shape(best_contour, w, h)
            color_coverage = float(np.sum(mask > 0)) / (frame.shape[0] * frame.shape[1])
            confidence = min(1.0, shape_conf * 0.5 + color_coverage * 2.0)
            confidence = round(max(0.0, min(1.0, confidence)), 3)
            return (x, y, w, h), confidence, shape
        except Exception as e:
            logger.error("Table detection error: %s", e)
            return None, 0.0, "error"

    def _classify_shape(self, contour: np.ndarray, w: int, h: int) -> Tuple[str, float]:
        aspect = w / h if h > 0 else 1.0
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        contour_area = cv2.contourArea(contour)
        solidity = contour_area / hull_area if hull_area > 0 else 0.0
        if 0.85 <= aspect <= 1.15 and solidity > 0.85:
            return "round", min(1.0, solidity)
        elif 1.3 <= aspect <= 2.5 and solidity > 0.80:
            return "elongated_round", min(1.0, solidity * 0.95)
        elif solidity > 0.80:
            return "octagonal", min(1.0, solidity * 0.90)
        return "round", solidity * 0.5

    def detect_cards(self, frame: np.ndarray, roi: Optional[Tuple] = None) -> List[Dict]:
        detections = []
        region = frame[roi[1]:roi[1]+roi[3], roi[0]:roi[0]+roi[2]] if roi else frame
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 1000 < area < 20000:
                x, y, w, h = cv2.boundingRect(cnt)
                ar = w / h if h > 0 else 0
                if 0.5 < ar < 0.9:
                    detections.append({"bbox": (x, y, w, h), "confidence": 0.7, "type": "card"})
        return self._nms(detections)

    def detect_chips(self, frame: np.ndarray, roi: Optional[Tuple] = None) -> List[Dict]:
        detections = []
        region = frame[roi[1]:roi[1]+roi[3], roi[0]:roi[0]+roi[2]] if roi else frame
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        for color_range in [
            (np.array([0, 120, 100]), np.array([10, 255, 255])),
            (np.array([20, 100, 100]), np.array([35, 255, 255])),
        ]:
            mask = cv2.inRange(hsv, color_range[0], color_range[1])
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 200 < area < 5000:
                    x, y, w, h = cv2.boundingRect(cnt)
                    detections.append({"bbox": (x, y, w, h), "confidence": 0.6, "type": "chip"})
        return self._nms(detections)

    @staticmethod
    def _nms(detections: List[Dict], iou_threshold: float = 0.5) -> List[Dict]:
        if not detections:
            return []
        detections = sorted(detections, key=lambda d: d.get("confidence", 0), reverse=True)
        kept = []
        while detections:
            best = detections.pop(0)
            kept.append(best)
            bx, by, bw, bh = best["bbox"]
            remaining = []
            for d in detections:
                dx, dy, dw, dh = d["bbox"]
                ix1 = max(bx, dx)
                iy1 = max(by, dy)
                ix2 = min(bx + bw, dx + dw)
                iy2 = min(by + bh, dy + dh)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                union = bw * bh + dw * dh - inter
                iou = inter / union if union > 0 else 0
                if iou < iou_threshold:
                    remaining.append(d)
            detections = remaining
        return kept

    def draw_detections(self, frame: np.ndarray, bbox: Optional[Tuple], detections: List[Dict] = None) -> np.ndarray:
        out = frame.copy()
        if bbox:
            x, y, w, h = bbox
            cv2.rectangle(out, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(out, "Table", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        for det in (detections or []):
            dx, dy, dw, dh = det["bbox"]
            color = (255, 0, 0) if det.get("type") == "card" else (0, 165, 255)
            cv2.rectangle(out, (dx, dy), (dx+dw, dy+dh), color, 1)
        return out

    def calibrate(self, frames: List[np.ndarray]) -> Dict:
        """Auto-calibrate HSV range from sample frames."""
        blue_pixels = []
        for frame in frames:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([90, 20, 20]), np.array([150, 255, 255]))
            pixels = hsv[mask > 0]
            if len(pixels) > 0:
                blue_pixels.extend(pixels.tolist())
        if not blue_pixels:
            return {"h_min": 100, "h_max": 140, "s_min": 30, "s_max": 255, "v_min": 30, "v_max": 255}
        arr = np.array(blue_pixels)
        h_min = max(90, int(np.percentile(arr[:, 0], 5)))
        h_max = min(150, int(np.percentile(arr[:, 0], 95)))
        s_min = max(20, int(np.percentile(arr[:, 1], 5)))
        v_min = max(20, int(np.percentile(arr[:, 2], 5)))
        self._hsv_lower = np.array([h_min, s_min, v_min])
        self._hsv_upper = np.array([h_max, 255, 255])
        return {"h_min": h_min, "h_max": h_max, "s_min": s_min, "s_max": 255, "v_min": v_min, "v_max": 255}
