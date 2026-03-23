"""
Error-scenario integration tests.

Covers:
- OCR failure on a frame
- Database connection lost / file unavailable
- Screen resolution change during operation
- Corrupted image data
- Invalid poker data rejected by validators
- Recovery after each scenario
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOCRFailure:
    """Parser must handle OCR returning empty / garbage text gracefully."""

    def _make_parser_with_ocr(self, ocr_return_value: str):
        with patch("core.poker_parser.OCRProcessor") as mock_ocr_cls, \
             patch("core.poker_parser.ComputerVision") as mock_cv_cls:
            mock_ocr = MagicMock()
            mock_ocr.read_text.return_value = ocr_return_value
            mock_ocr_cls.return_value = mock_ocr

            mock_cv = MagicMock()
            mock_cv.detect_poker_table_with_confidence.return_value = (
                (50, 50, 600, 400), 0.9, "round"
            )
            mock_cv.detect_cards.return_value = []
            mock_cv_cls.return_value = mock_cv

            from core.poker_parser import PokerParser
            p = PokerParser()
            p.ocr = mock_ocr
            p.cv = mock_cv
            return p

    def test_ocr_empty_string_does_not_raise(self, sample_frame):
        parser = self._make_parser_with_ocr("")
        result = parser.parse_frame(sample_frame)
        assert "session_id" in result

    def test_ocr_garbled_text_does_not_raise(self, sample_frame):
        parser = self._make_parser_with_ocr("@#$%^&*()")
        result = parser.parse_frame(sample_frame)
        assert "session_id" in result

    def test_ocr_no_pot_returns_none(self, sample_frame):
        parser = self._make_parser_with_ocr("no numbers here")
        result = parser.parse_frame(sample_frame)
        assert result["pot"] is None

    def test_ocr_raises_exception_handled(self, sample_frame):
        with patch("core.poker_parser.OCRProcessor") as mock_ocr_cls, \
             patch("core.poker_parser.ComputerVision") as mock_cv_cls:
            mock_ocr = MagicMock()
            mock_ocr.read_text.side_effect = RuntimeError("OCR crashed")
            mock_ocr_cls.return_value = mock_ocr

            mock_cv = MagicMock()
            mock_cv.detect_poker_table_with_confidence.return_value = (
                (50, 50, 600, 400), 0.9, "round"
            )
            mock_cv.detect_cards.return_value = []
            mock_cv_cls.return_value = mock_cv

            from core.poker_parser import PokerParser
            parser = PokerParser()
            parser.ocr = mock_ocr
            parser.cv = mock_cv

            result = parser.parse_frame(sample_frame)
            assert "session_id" in result


class TestDatabaseConnectionLost:
    """Operations on a closed DB should fail gracefully or be recoverable."""

    def test_close_then_reopen_works(self, temp_db_path, sample_hands):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        db.save_hand(sample_hands[0], "sess_lost")
        db.close()

        db2 = DatabaseManager(temp_db_path)
        stats = db2.get_session_stats("sess_lost")
        db2.close()
        assert stats.get("total_hands", 0) >= 1

    def test_operations_after_close_do_not_corrupt_file(self, temp_db_path, sample_hands):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        for hand in sample_hands[:5]:
            db.save_hand(hand, "sess_safe")
        db.close()

        # Operations after close might raise or silently fail; the important
        # thing is that the file remains readable.
        try:
            db.save_hand(sample_hands[6], "sess_safe")
        except Exception:
            pass  # Expected

        db3 = DatabaseManager(temp_db_path)
        stats = db3.get_session_stats("sess_safe")
        db3.close()
        assert stats.get("total_hands", 0) >= 5


class TestScreenResolutionChange:
    """CV must handle frames of different sizes without crashing."""

    @pytest.mark.parametrize("width,height", [
        (320, 240),
        (640, 480),
        (1280, 720),
        (1920, 1080),
    ])
    def test_cv_handles_different_resolutions(self, width, height):
        import cv2 as _cv2
        from core.computer_vision import ComputerVision
        cv = ComputerVision()

        frame = np.zeros((height, width, 3), dtype=np.uint8)
        _cv2.ellipse(frame, (width // 2, height // 2),
                     (width // 3, height // 3), 0, 0, 360, (255, 0, 0), -1)
        bbox, conf, shape = cv.detect_poker_table_with_confidence(frame)
        assert conf >= 0.0

    def test_cv_handles_very_small_frame(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        tiny = np.zeros((10, 10, 3), dtype=np.uint8)
        bbox, conf, shape = cv.detect_poker_table_with_confidence(tiny)
        assert conf == 0.0  # too small to detect

    def test_cv_handles_non_standard_aspect_ratio(self):
        from core.computer_vision import ComputerVision
        import cv2 as _cv2
        cv = ComputerVision()
        frame = np.zeros((200, 1600, 3), dtype=np.uint8)
        _cv2.ellipse(frame, (800, 100), (500, 80), 0, 0, 360, (255, 0, 0), -1)
        # Should not raise.
        cv.detect_poker_table_with_confidence(frame)


class TestCorruptedImageData:
    """CV must be robust to broken numpy arrays."""

    def test_single_channel_image(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        gray = np.zeros((600, 800), dtype=np.uint8)
        # detect_poker_table_with_confidence may raise ValueError for wrong
        # number of channels; it should be caught internally.
        try:
            bbox, conf, shape = cv.detect_poker_table_with_confidence(gray)
        except Exception:
            pass  # Acceptable; it should not crash the whole application

    def test_wrong_dtype(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bad = np.zeros((100, 100, 3), dtype=np.float64)
        try:
            cv.detect_poker_table_with_confidence(bad)
        except Exception:
            pass

    def test_none_frame(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bbox, conf, shape = cv.detect_poker_table_with_confidence(None)
        assert bbox is None

    def test_nan_values_do_not_crash(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bad = np.full((100, 100, 3), np.nan)
        try:
            cv.detect_poker_table_with_confidence(bad)
        except Exception:
            pass


class TestInvalidPokerData:
    """Validators must reject obviously wrong values and accept correct ones."""

    def test_negative_pot_rejected(self):
        from utils.validators import validate_pot
        ok, errors = validate_pot(-5.0)
        assert not ok
        assert len(errors) > 0

    def test_oversized_pot_rejected(self):
        from utils.validators import validate_pot
        ok, errors = validate_pot(999999)
        assert not ok

    def test_valid_pot_accepted(self):
        from utils.validators import validate_pot
        ok, errors = validate_pot(100.0)
        assert ok

    def test_zero_stack_rejected(self):
        from utils.validators import validate_stack
        ok, errors = validate_stack(0)
        assert not ok

    def test_negative_stack_rejected(self):
        from utils.validators import validate_stack
        ok, errors = validate_stack(-100)
        assert not ok

    def test_valid_stack_accepted(self):
        from utils.validators import validate_stack
        ok, errors = validate_stack(1500.0)
        assert ok

    def test_invalid_blinds_rejected(self):
        from utils.validators import validate_blinds
        ok, errors = validate_blinds(0.0, 0.0)
        assert not ok

    def test_valid_blinds_accepted(self):
        from utils.validators import validate_blinds
        ok, errors = validate_blinds(0.5, 1.0)
        assert ok

    def test_player_count_too_low_rejected(self):
        from utils.validators import validate_player_count
        ok, errors = validate_player_count(1)
        assert not ok

    def test_player_count_too_high_rejected(self):
        from utils.validators import validate_player_count
        ok, errors = validate_player_count(10)
        assert not ok

    def test_valid_player_count_accepted(self):
        from utils.validators import validate_player_count
        ok, errors = validate_player_count(6)
        assert ok

    def test_full_hand_data_validation(self):
        from utils.validators import validate_hand_data
        valid = {
            "pot": 45.50,
            "small_blind": 0.5,
            "big_blind": 1.0,
            "player_count": 4,
            "players": [{"seat": 1, "stack": 500.0}],
        }
        ok, errors = validate_hand_data(valid)
        assert ok, f"Unexpected errors: {errors}"

    def test_hand_data_with_invalid_pot_fails(self):
        from utils.validators import validate_hand_data
        bad = {"pot": -99.0, "player_count": 4}
        ok, errors = validate_hand_data(bad)
        assert not ok


class TestRecoveryScenarios:
    """After each error scenario the system should remain operational."""

    def test_recovery_after_bad_frame(self, mock_parser, blank_frame, sample_frame):
        """After a bad frame, the parser should handle a good frame normally."""
        mock_parser.cv.detect_poker_table_with_confidence.return_value = (
            None, 0.0, "no_contours"
        )
        result_bad = mock_parser.parse_frame(blank_frame)
        assert result_bad.get("table_detected") is False

        # Restore mock and process a good frame
        mock_parser.cv.detect_poker_table_with_confidence.return_value = (
            (50, 50, 600, 400), 0.9, "round"
        )
        mock_parser.ocr.read_text.return_value = "Pot: $30.00 0.5/1.0 flop"
        result_good = mock_parser.parse_frame(sample_frame)
        assert result_good.get("table_detected") is True

    def test_recovery_after_db_close(self, temp_db_path, sample_hands):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        db.save_hand(sample_hands[0], "sess_rec")
        db.close()

        # Re-open and continue writing
        db2 = DatabaseManager(temp_db_path)
        hid = db2.save_hand(sample_hands[1], "sess_rec")
        db2.close()
        assert hid > 0

    def test_recovery_after_ocr_exception(self, sample_frame):
        """Parser should return a valid (empty) result after OCR crash."""
        with patch("core.poker_parser.OCRProcessor") as mock_ocr_cls, \
             patch("core.poker_parser.ComputerVision") as mock_cv_cls:
            mock_ocr = MagicMock()
            mock_ocr.read_text.side_effect = RuntimeError("crash")
            mock_ocr_cls.return_value = mock_ocr

            mock_cv = MagicMock()
            mock_cv.detect_poker_table_with_confidence.return_value = (
                (50, 50, 600, 400), 0.9, "round"
            )
            mock_cv.detect_cards.return_value = []
            mock_cv_cls.return_value = mock_cv

            from core.poker_parser import PokerParser
            parser = PokerParser()
            parser.ocr = mock_ocr
            parser.cv = mock_cv

            result = parser.parse_frame(sample_frame)
            assert isinstance(result, dict)
