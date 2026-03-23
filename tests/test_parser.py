"""Unit tests for PokerParser (core version)."""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np

from core.poker_parser import PokerParser


class TestPokerParser(unittest.TestCase):

    def setUp(self):
        with patch('core.poker_parser.OCRProcessor'), \
             patch('core.poker_parser.ComputerVision'):
            self.parser = PokerParser()
            self.parser.ocr = MagicMock()
            self.parser.cv = MagicMock()

    def test_extract_blinds_slash(self):
        sb, bb = self.parser.extract_blinds("0.5/1.0")
        self.assertAlmostEqual(sb, 0.5)
        self.assertAlmostEqual(bb, 1.0)

    def test_extract_blinds_dollar(self):
        sb, bb = self.parser.extract_blinds("$0.25/$0.50")
        self.assertAlmostEqual(sb, 0.25)
        self.assertAlmostEqual(bb, 0.50)

    def test_extract_blinds_no_match(self):
        sb, bb = self.parser.extract_blinds("no blinds here")
        self.assertIsNone(sb)
        self.assertIsNone(bb)

    def test_extract_pot_colon(self):
        pot = self.parser.extract_pot("Pot: $45.50")
        self.assertAlmostEqual(pot, 45.50)

    def test_extract_pot_total(self):
        pot = self.parser.extract_pot("Total pot $100")
        self.assertAlmostEqual(pot, 100.0)

    def test_extract_pot_no_match(self):
        pot = self.parser.extract_pot("no pot here")
        self.assertIsNone(pot)

    def test_detect_hand_stage_flop(self):
        stage = self.parser.detect_hand_stage("Community cards - flop")
        self.assertEqual(stage, "flop")

    def test_detect_hand_stage_turn(self):
        stage = self.parser.detect_hand_stage("The turn card")
        self.assertEqual(stage, "turn")

    def test_detect_hand_stage_river(self):
        stage = self.parser.detect_hand_stage("River bet")
        self.assertEqual(stage, "river")

    def test_detect_hand_stage_default(self):
        stage = self.parser.detect_hand_stage("nothing")
        self.assertEqual(stage, "preflop")

    def test_assign_positions_4_players(self):
        positions = self.parser.assign_positions(4)
        self.assertEqual(len(positions), 4)
        self.assertIn("BTN", positions)
        self.assertIn("SB", positions)
        self.assertIn("BB", positions)

    def test_assign_positions_zero(self):
        positions = self.parser.assign_positions(0)
        self.assertEqual(positions, [])

    def test_fish_detection_high_vpip(self):
        self.assertTrue(self.parser.detect_fish(50.0))
        self.assertTrue(self.parser.detect_fish(40.0))

    def test_fish_detection_low_vpip(self):
        self.assertFalse(self.parser.detect_fish(20.0))
        self.assertFalse(self.parser.detect_fish(39.9))

    def test_session_id_generated(self):
        self.assertIsNotNone(self.parser.session_id)
        self.assertTrue(self.parser.session_id.startswith("sess_"))

    def test_session_id_in_output(self):
        self.parser.cv.detect_poker_table_with_confidence.return_value = (None, 0.0, "no_table")
        result = self.parser.parse_frame(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertIn("session_id", result)
        self.assertEqual(result["session_id"], self.parser.session_id)


if __name__ == "__main__":
    unittest.main()
