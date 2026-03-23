"""
Tests for CardRecognizer, ROI crop safety, and output schema.

These tests do NOT require a live poker table, real card images, or a
display device. They validate:
  1. Template loading from card_templates/
  2. Robustness of _safe_crop (no out-of-bounds)
  3. Output schema from PokerParser contains the new keys
  4. Jones JSONL export contains required keys
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# CardRecognizer tests
# ---------------------------------------------------------------------------

class TestCardRecognizerTemplateLoading(unittest.TestCase):
    """Verify that CardRecognizer loads rank/suit templates without errors."""

    def setUp(self):
        from core.card_recognizer import CardRecognizer
        self.CardRecognizer = CardRecognizer

    def test_instantiation_does_not_raise(self):
        """Creating a CardRecognizer must not raise even if templates are missing."""
        # Default template dir may not exist in CI — that's fine; just no templates.
        try:
            recognizer = self.CardRecognizer()
        except Exception as exc:
            self.fail(f"CardRecognizer() raised unexpectedly: {exc}")

    def test_loaded_ranks_are_valid_chars(self):
        recognizer = self.CardRecognizer()
        for rank in recognizer.loaded_ranks:
            self.assertIn(
                rank, set("23456789TJQKA"),
                f"Unexpected rank key: {rank!r}",
            )

    def test_loaded_suits_are_valid_chars(self):
        recognizer = self.CardRecognizer()
        for suit in recognizer.loaded_suits:
            self.assertIn(
                suit, {"s", "h", "d", "c"},
                f"Unexpected suit key: {suit!r}",
            )

    def test_recognize_corner_returns_dict_on_empty_image(self):
        recognizer = self.CardRecognizer()
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        result = recognizer.recognize_corner(img)
        self.assertIsInstance(result, dict)
        for key in ("rank", "suit", "card", "rank_score", "suit_score"):
            self.assertIn(key, result)

    def test_recognize_corner_returns_dict_on_none(self):
        recognizer = self.CardRecognizer()
        result = recognizer.recognize_corner(None)  # type: ignore[arg-type]
        self.assertIsInstance(result, dict)
        self.assertIsNone(result["card"])

    def test_recognize_corner_gray_input(self):
        """Grayscale (2-D) input must not crash."""
        recognizer = self.CardRecognizer()
        gray_img = np.zeros((40, 30), dtype=np.uint8)
        result = recognizer.recognize_corner(gray_img)
        self.assertIsInstance(result, dict)

    def test_recognize_corner_with_real_templates(self):
        """If templates exist, recognize_corner on a white patch returns a result dict."""
        recognizer = self.CardRecognizer()
        if not recognizer.loaded_ranks and not recognizer.loaded_suits:
            self.skipTest("No templates loaded – skipping live matching test")
        img = np.ones((60, 50, 3), dtype=np.uint8) * 200
        result = recognizer.recognize_corner(img)
        self.assertIsInstance(result, dict)
        self.assertIsInstance(result["rank_score"], float)
        self.assertIsInstance(result["suit_score"], float)

    def test_custom_template_dir(self):
        """CardRecognizer with a nonexistent dir loads 0 templates gracefully."""
        recognizer = self.CardRecognizer(template_dir="/nonexistent/path/xyz")
        self.assertEqual(recognizer.loaded_ranks, [])
        self.assertEqual(recognizer.loaded_suits, [])

    def test_flat_template_naming(self):
        """Templates named rank_A.png / suit_spade.png in flat dir are discovered."""
        import cv2
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal rank_A and suit_spade templates
            r_img = np.ones((20, 15), dtype=np.uint8) * 200
            s_img = np.ones((15, 15), dtype=np.uint8) * 100
            cv2.imwrite(os.path.join(tmpdir, "rank_A.png"), r_img)
            cv2.imwrite(os.path.join(tmpdir, "suit_spade.png"), s_img)

            recognizer = self.CardRecognizer(template_dir=tmpdir)
            self.assertIn("A", recognizer.loaded_ranks)
            self.assertIn("s", recognizer.loaded_suits)

    def test_subdir_template_naming(self):
        """Templates in ranks/ and suits/ subdirs are discovered."""
        import cv2
        with tempfile.TemporaryDirectory() as tmpdir:
            ranks_dir = os.path.join(tmpdir, "ranks")
            suits_dir = os.path.join(tmpdir, "suits")
            os.makedirs(ranks_dir)
            os.makedirs(suits_dir)
            cv2.imwrite(os.path.join(ranks_dir, "K.png"),
                        np.ones((20, 15), dtype=np.uint8) * 200)
            cv2.imwrite(os.path.join(suits_dir, "heart.png"),
                        np.ones((15, 15), dtype=np.uint8) * 150)

            recognizer = self.CardRecognizer(template_dir=tmpdir)
            self.assertIn("K", recognizer.loaded_ranks)
            self.assertIn("h", recognizer.loaded_suits)


# ---------------------------------------------------------------------------
# _safe_crop tests
# ---------------------------------------------------------------------------

class TestSafeCrop(unittest.TestCase):
    """Verify that _safe_crop never raises and never returns out-of-bounds crops."""

    def setUp(self):
        from core.poker_parser import _safe_crop
        self._safe_crop = _safe_crop

    def _make_frame(self, h=100, w=120):
        return np.zeros((h, w, 3), dtype=np.uint8)

    def test_normal_crop(self):
        frame = self._make_frame()
        crop = self._safe_crop(frame, (10, 10, 30, 20))
        self.assertIsNotNone(crop)
        self.assertEqual(crop.shape[:2], (20, 30))

    def test_roi_beyond_right_edge(self):
        frame = self._make_frame(h=100, w=120)
        crop = self._safe_crop(frame, (100, 10, 100, 20))  # x+w > width
        self.assertIsNotNone(crop)
        self.assertGreater(crop.size, 0)

    def test_roi_beyond_bottom_edge(self):
        frame = self._make_frame(h=100, w=120)
        crop = self._safe_crop(frame, (10, 80, 30, 100))  # y+h > height
        self.assertIsNotNone(crop)
        self.assertGreater(crop.size, 0)

    def test_roi_negative_x(self):
        frame = self._make_frame()
        crop = self._safe_crop(frame, (-10, 0, 30, 20))
        self.assertIsNotNone(crop)
        self.assertGreater(crop.size, 0)

    def test_roi_entirely_outside(self):
        """An ROI with x starting at frame boundary returns a minimal crop (not None)."""
        frame = self._make_frame(h=100, w=120)
        # x = 119, w = 30 → clamped to w=1
        crop = self._safe_crop(frame, (119, 0, 30, 20))
        self.assertIsNotNone(crop)
        self.assertGreater(crop.size, 0)

    def test_none_frame(self):
        crop = self._safe_crop(None, (0, 0, 10, 10))  # type: ignore[arg-type]
        self.assertIsNone(crop)

    def test_empty_frame(self):
        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        crop = self._safe_crop(empty, (0, 0, 10, 10))
        self.assertIsNone(crop)


# ---------------------------------------------------------------------------
# PokerParser output schema tests
# ---------------------------------------------------------------------------

class TestPokerParserOutputSchema(unittest.TestCase):
    """Verify that parse_frame output contains the new required keys."""

    NEW_KEYS = [
        "hero_cards",
        "board_cards",
        "hero_stack",
        "blinds",
        "players",
        "player_count",
    ]

    BLINDS_KEYS = {"small_blind", "big_blind", "ante"}

    def setUp(self):
        with patch("core.poker_parser.OCRProcessor"), \
             patch("core.poker_parser.ComputerVision"), \
             patch("core.poker_parser.CardRecognizer"):
            from core.poker_parser import PokerParser
            self.parser = PokerParser()
            self.parser.ocr = MagicMock()
            self.parser.cv = MagicMock()
            self.parser._card_recognizer = MagicMock()
            self.parser._rois = {}

    def _parse_blank_frame(self):
        self.parser.cv.detect_poker_table_with_confidence.return_value = (
            None, 0.0, "no_table"
        )
        return self.parser.parse_frame(np.zeros((100, 100, 3), dtype=np.uint8))

    def test_new_keys_present(self):
        result = self._parse_blank_frame()
        for key in self.NEW_KEYS:
            self.assertIn(key, result, f"Missing key: {key!r}")

    def test_hero_cards_is_list(self):
        result = self._parse_blank_frame()
        self.assertIsInstance(result["hero_cards"], list)

    def test_board_cards_is_list(self):
        result = self._parse_blank_frame()
        self.assertIsInstance(result["board_cards"], list)

    def test_blinds_is_dict_with_expected_keys(self):
        result = self._parse_blank_frame()
        self.assertIsInstance(result["blinds"], dict)
        self.assertTrue(
            self.BLINDS_KEYS.issubset(result["blinds"].keys()),
            f"blinds dict missing keys: {self.BLINDS_KEYS - set(result['blinds'].keys())}",
        )

    def test_players_is_list(self):
        result = self._parse_blank_frame()
        self.assertIsInstance(result["players"], list)

    def test_player_count_matches_players_length(self):
        result = self._parse_blank_frame()
        self.assertEqual(result["player_count"], len(result["players"]))

    def test_hero_stack_is_none_or_float(self):
        result = self._parse_blank_frame()
        val = result["hero_stack"]
        self.assertTrue(val is None or isinstance(val, float))

    def test_existing_keys_still_present(self):
        """Ensure previously existing keys are not removed."""
        legacy_keys = [
            "session_id", "timestamp", "table_detected", "table_confidence",
            "table_shape", "stage", "pot", "small_blind", "big_blind",
            "player_count", "players", "cards",
        ]
        result = self._parse_blank_frame()
        for key in legacy_keys:
            self.assertIn(key, result, f"Legacy key removed: {key!r}")


# ---------------------------------------------------------------------------
# DataExporter Jones JSONL tests
# ---------------------------------------------------------------------------

class TestDataExporterJones(unittest.TestCase):
    """Verify that DataExporter writes valid Jones JSONL records."""

    JONES_MIN_KEYS = {
        "hand_id", "table_id", "timestamp", "blinds",
        "players", "board", "pot", "actions", "winners",
    }

    def _make_hand_data(self) -> dict:
        return {
            "session_id": "sess_test",
            "timestamp": "2026-01-01T12:00:00",
            "stage": "flop",
            "pot": 5.0,
            "small_blind": 0.5,
            "big_blind": 1.0,
            "blinds": {"small_blind": 0.5, "big_blind": 1.0, "ante": None},
            "board_cards": ["Ac", "7d", "Ts"],
            "hero_cards": ["Kh", "Qd"],
            "hero_stack": 95.5,
            "players": [
                {"seat": 1, "name": "villain", "stack": 120.0, "position": "BTN"},
            ],
            "player_count": 1,
            "cards": [],
            "table_detected": True,
            "table_confidence": 0.9,
            "table_shape": "round",
        }

    def test_jones_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("core.data_exporter.DB_AVAILABLE", False):
                from core.data_exporter import DataExporter
                exporter = DataExporter(output_dir=tmpdir)
            exporter._export_jones(self._make_hand_data())
            jones_path = os.path.join(tmpdir, "jones", "live.jsonl")
            self.assertTrue(os.path.exists(jones_path))

    def test_jones_record_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("core.data_exporter.DB_AVAILABLE", False):
                from core.data_exporter import DataExporter
                exporter = DataExporter(output_dir=tmpdir)
            exporter._export_jones(self._make_hand_data())
            jones_path = os.path.join(tmpdir, "jones", "live.jsonl")
            with open(jones_path, encoding="utf-8") as fh:
                record = json.loads(fh.readline())
            missing = self.JONES_MIN_KEYS - set(record.keys())
            self.assertFalse(missing, f"Jones record missing keys: {missing}")

    def test_jones_board_matches_hand_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("core.data_exporter.DB_AVAILABLE", False):
                from core.data_exporter import DataExporter
                exporter = DataExporter(output_dir=tmpdir)
            hand = self._make_hand_data()
            exporter._export_jones(hand)
            jones_path = os.path.join(tmpdir, "jones", "live.jsonl")
            with open(jones_path, encoding="utf-8") as fh:
                record = json.loads(fh.readline())
            self.assertEqual(record["board"], hand["board_cards"])

    def test_jones_hero_in_players(self):
        """Hero hole_cards should appear in the jones players list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("core.data_exporter.DB_AVAILABLE", False):
                from core.data_exporter import DataExporter
                exporter = DataExporter(output_dir=tmpdir)
            hand = self._make_hand_data()
            exporter._export_jones(hand)
            jones_path = os.path.join(tmpdir, "jones", "live.jsonl")
            with open(jones_path, encoding="utf-8") as fh:
                record = json.loads(fh.readline())
            hero_entries = [p for p in record["players"] if p.get("name") == "HERO"]
            self.assertEqual(len(hero_entries), 1)
            self.assertEqual(hero_entries[0]["hole_cards"], hand["hero_cards"])

    def test_jones_appends_multiple_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("core.data_exporter.DB_AVAILABLE", False):
                from core.data_exporter import DataExporter
                exporter = DataExporter(output_dir=tmpdir)
            hand = self._make_hand_data()
            exporter._export_jones(hand)
            exporter._export_jones(hand)
            jones_path = os.path.join(tmpdir, "jones", "live.jsonl")
            with open(jones_path, encoding="utf-8") as fh:
                lines = [l.strip() for l in fh if l.strip()]
            self.assertEqual(len(lines), 2)
            for line in lines:
                record = json.loads(line)
                self.assertIn("hand_id", record)

    def test_jones_actions_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("core.data_exporter.DB_AVAILABLE", False):
                from core.data_exporter import DataExporter
                exporter = DataExporter(output_dir=tmpdir)
            exporter._export_jones(self._make_hand_data())
            jones_path = os.path.join(tmpdir, "jones", "live.jsonl")
            with open(jones_path, encoding="utf-8") as fh:
                record = json.loads(fh.readline())
            self.assertEqual(record["actions"], [])
            self.assertEqual(record["winners"], [])


if __name__ == "__main__":
    unittest.main()
