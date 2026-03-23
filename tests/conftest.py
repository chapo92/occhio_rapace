"""
Pytest fixtures shared across the integration test suite.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from typing import Generator
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure project root is on the path so all modules can be imported.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_database():
    """Create a temporary SQLite database; remove it after the test."""
    from features.database_manager import DatabaseManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
        db_path = fh.name

    db = DatabaseManager(db_path)
    yield db
    db.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def temp_db_path():
    """Yield a temporary file path for a database; remove it after the test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
        path = fh.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Screen / image helpers
# ---------------------------------------------------------------------------


def _make_blue_table_frame(width: int = 800, height: int = 600) -> np.ndarray:
    """Return a synthetic BGR frame that looks like a blue poker table."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    import cv2
    cv2.ellipse(
        frame,
        (width // 2, height // 2),
        (width // 3, height // 3),
        0, 0, 360,
        (255, 0, 0),  # BGR blue
        -1,
    )
    return frame


@pytest.fixture
def sample_frame() -> np.ndarray:
    """A synthetic BGR frame containing a blue ellipse (poker table)."""
    return _make_blue_table_frame()


@pytest.fixture
def blank_frame() -> np.ndarray:
    """A completely black (no-table) frame."""
    return np.zeros((600, 800, 3), dtype=np.uint8)


@pytest.fixture
def mock_screen():
    """Mock the ScreenCapture.capture() method to return a synthetic frame."""
    frame = _make_blue_table_frame()
    with patch("screen_capture.ScreenCapture.capture", return_value=frame):
        yield frame


# ---------------------------------------------------------------------------
# Parser / pipeline
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_parser():
    """A PokerParser with both OCR and CV dependencies mocked out."""
    with patch("core.poker_parser.OCRProcessor") as mock_ocr_cls, \
         patch("core.poker_parser.ComputerVision") as mock_cv_cls:
        mock_ocr = MagicMock()
        mock_ocr.read_text.return_value = "Pot: $45.50 0.5/1.0 flop"
        mock_ocr_cls.return_value = mock_ocr

        mock_cv = MagicMock()
        mock_cv.detect_poker_table_with_confidence.return_value = (
            (50, 50, 600, 400), 0.85, "round"
        )
        mock_cv.detect_cards.return_value = []
        mock_cv_cls.return_value = mock_cv

        from core.poker_parser import PokerParser
        parser = PokerParser()
        yield parser


# ---------------------------------------------------------------------------
# Pre-built hand data
# ---------------------------------------------------------------------------


def _make_hand(index: int = 0, session_id: str = "sess_test") -> dict:
    stages = ["preflop", "flop", "turn", "river", "showdown"]
    return {
        "session_id": session_id,
        "timestamp": f"2024-01-01T00:{index:02d}:00",
        "stage": stages[index % len(stages)],
        "pot": round(10.0 + index * 5.5, 2),
        "player_count": 4,
        "small_blind": 0.5,
        "big_blind": 1.0,
        "players": [
            {"seat": 1, "stack": 500.0 + index, "position": "BTN", "is_fish": False},
            {"seat": 2, "stack": 300.0 + index, "position": "SB", "is_fish": True},
        ],
    }


@pytest.fixture
def sample_hands():
    """10 pre-built hand data dicts for database testing."""
    return [_make_hand(i) for i in range(10)]


@pytest.fixture
def sample_hands_100():
    """100 pre-built hand data dicts for larger-scale database testing."""
    return [_make_hand(i, session_id="sess_bulk") for i in range(100)]
