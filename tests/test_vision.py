"""Unit tests for ComputerVision (core version)."""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import cv2

from core.computer_vision import ComputerVision, BLUE_HSV_LOWER, BLUE_HSV_UPPER, MIN_TABLE_AREA


class TestComputerVision(unittest.TestCase):

    def setUp(self):
        self.cv = ComputerVision()

    def _make_blue_frame(self, w=800, h=600) -> np.ndarray:
        """BGR (255, 0, 0) = pure blue, maps to H=120 in OpenCV HSV (within [100,140])."""
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.ellipse(frame, (w//2, h//2), (w//3, h//3), 0, 0, 360, (255, 0, 0), -1)
        return frame

    def test_detect_poker_table_blue(self):
        frame = self._make_blue_frame()
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER)
        blue_pixels = np.sum(mask > 0)
        self.assertGreater(blue_pixels, MIN_TABLE_AREA,
                           f"Synthetic frame has {blue_pixels} blue pixels, need {MIN_TABLE_AREA}")
        bbox = self.cv.detect_poker_table(frame)
        self.assertIsNotNone(bbox, "Expected table detection on blue frame")
        x, y, w, h = bbox
        self.assertGreater(w * h, 0)

    def test_detect_poker_table_no_table(self):
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        bbox = self.cv.detect_poker_table(frame)
        self.assertIsNone(bbox)

    def test_detect_poker_table_with_confidence(self):
        frame = self._make_blue_frame()
        bbox, confidence, shape = self.cv.detect_poker_table_with_confidence(frame)
        self.assertIsNotNone(bbox)
        self.assertIsInstance(confidence, float)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)
        self.assertIn(shape, ["round", "octagonal", "elongated_round", "error"])

    def test_detect_cards(self):
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        result = self.cv.detect_cards(frame)
        self.assertIsInstance(result, list)

    def test_nms(self):
        detections = [
            {"bbox": (10, 10, 50, 50), "confidence": 0.9, "type": "card"},
            {"bbox": (12, 12, 50, 50), "confidence": 0.7, "type": "card"},
            {"bbox": (200, 200, 50, 50), "confidence": 0.8, "type": "card"},
        ]
        result = ComputerVision._nms(detections, iou_threshold=0.5)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["confidence"], 0.9)

    def test_confidence_scoring(self):
        frame = self._make_blue_frame()
        _, conf, _ = self.cv.detect_poker_table_with_confidence(frame)
        self.assertIsInstance(conf, float)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_empty_frame(self):
        frame = np.array([])
        bbox, conf, reason = self.cv.detect_poker_table_with_confidence(frame)
        self.assertIsNone(bbox)
        self.assertEqual(conf, 0.0)
        self.assertEqual(reason, "empty_frame")


if __name__ == "__main__":
    unittest.main()
