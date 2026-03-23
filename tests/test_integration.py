"""Integration tests for Occhi di Falco."""
import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import cv2


class TestConfigLoading(unittest.TestCase):
    def test_config_loading(self):
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        self.assertTrue(os.path.exists(config_path), "config.json not found")
        with open(config_path) as f:
            cfg = json.load(f)
        for key in ["platform", "capture", "table_detection", "ocr", "output"]:
            self.assertIn(key, cfg, f"Missing key: {key}")
        self.assertEqual(cfg["platform"], "888poker")


class TestValidators(unittest.TestCase):
    def setUp(self):
        from utils.validators import validate_hand_data, validate_stack, validate_pot
        self.validate_hand_data = validate_hand_data
        self.validate_stack = validate_stack
        self.validate_pot = validate_pot

    def test_validate_hand_data_valid(self):
        hand_data = {
            "pot": 45.50,
            "small_blind": 0.5,
            "big_blind": 1.0,
            "player_count": 4,
            "players": [],
        }
        ok, errors = self.validate_hand_data(hand_data)
        self.assertTrue(ok, f"Expected valid but got errors: {errors}")

    def test_validate_hand_data_invalid_pot(self):
        hand_data = {"pot": -10.0}
        ok, errors = self.validate_hand_data(hand_data)
        self.assertFalse(ok)
        self.assertTrue(len(errors) > 0)

    def test_validate_stack_valid(self):
        ok, errors = self.validate_stack(500.0)
        self.assertTrue(ok)

    def test_validate_stack_invalid(self):
        ok, errors = self.validate_stack(-1)
        self.assertFalse(ok)

    def test_validate_pot_valid(self):
        ok, errors = self.validate_pot(0.0)
        self.assertTrue(ok)

    def test_validate_pot_invalid(self):
        ok, errors = self.validate_pot(999999)
        self.assertFalse(ok)


class TestDatabaseSaveRetrieve(unittest.TestCase):
    def test_database_save_retrieve(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            from features.database_manager import DatabaseManager
            db = DatabaseManager(db_path)
            hand_data = {
                "timestamp": "2024-01-01T00:00:00",
                "stage": "flop",
                "pot": 45.50,
                "player_count": 4,
                "small_blind": 0.5,
                "big_blind": 1.0,
                "players": [],
            }
            hand_id = db.save_hand(hand_data, "sess_test")
            self.assertGreater(hand_id, 0)
            stats = db.get_session_stats("sess_test")
            self.assertIn("session_id", stats)
            self.assertEqual(stats["session_id"], "sess_test")
            db.close()
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass


class TestFullPipelineSynthetic(unittest.TestCase):
    def _make_blue_frame(self, w=800, h=600):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.ellipse(frame, (w//2, h//2), (w//3, h//3), 0, 0, 360, (255, 0, 0), -1)
        return frame

    def test_full_pipeline_synthetic(self):
        from core.computer_vision import ComputerVision
        from core.poker_parser import PokerParser

        frame = self._make_blue_frame()

        cv_module = ComputerVision()
        bbox = cv_module.detect_poker_table(frame)
        self.assertIsNotNone(bbox, "CV should detect blue table")

        with patch('core.poker_parser.OCRProcessor') as mock_ocr_cls, \
             patch('core.poker_parser.ComputerVision') as mock_cv_cls:
            mock_ocr = MagicMock()
            mock_ocr.read_text.return_value = "Pot: $45.50 0.5/1.0 flop"
            mock_ocr_cls.return_value = mock_ocr

            mock_cv = MagicMock()
            mock_cv.detect_poker_table_with_confidence.return_value = (
                (100, 100, 600, 400), 0.85, "round")
            mock_cv.detect_cards.return_value = []
            mock_cv_cls.return_value = mock_cv

            parser = PokerParser()
            result = parser.parse_frame(frame)

        self.assertIn("session_id", result)
        self.assertIn("timestamp", result)
        self.assertIn("stage", result)


if __name__ == "__main__":
    unittest.main()
