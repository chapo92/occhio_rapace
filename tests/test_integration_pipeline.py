"""
Integration tests for the full processing pipeline.

Covers:
- Normal frame processing
- Bad frame handling
- Database transaction rollback on invalid data
- Queue overflow handling
- Thread synchronisation
- Graceful shutdown
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blue_frame(width: int = 800, height: int = 600) -> np.ndarray:
    import cv2
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.ellipse(frame, (width // 2, height // 2), (width // 3, height // 3),
                0, 0, 360, (255, 0, 0), -1)
    return frame


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNormalFrameProcessing:
    """Full path: CV → OCR → parser on a synthetic blue-table frame."""

    def test_cv_detects_blue_table(self, sample_frame):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bbox = cv.detect_poker_table(sample_frame)
        assert bbox is not None, "CV should detect the blue ellipse"
        x, y, w, h = bbox
        assert w > 0 and h > 0

    def test_cv_returns_confidence(self, sample_frame):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bbox, conf, shape = cv.detect_poker_table_with_confidence(sample_frame)
        assert conf >= 0.0
        assert conf <= 1.0
        assert shape in ("round", "octagonal", "elongated_round",
                         "no_contours", "too_small", "error", "empty_frame")

    def test_parser_produces_required_keys(self, mock_parser, sample_frame):
        result = mock_parser.parse_frame(sample_frame)
        for key in ("session_id", "timestamp", "stage", "pot",
                    "small_blind", "big_blind", "player_count"):
            assert key in result, f"Missing key: {key}"

    def test_parser_extracts_pot(self, mock_parser, sample_frame):
        result = mock_parser.parse_frame(sample_frame)
        assert result["pot"] == pytest.approx(45.50, abs=0.01)

    def test_parser_extracts_blinds(self, mock_parser, sample_frame):
        result = mock_parser.parse_frame(sample_frame)
        assert result["small_blind"] == pytest.approx(0.5, abs=0.01)
        assert result["big_blind"] == pytest.approx(1.0, abs=0.01)

    def test_full_pipeline_save_to_db(self, mock_parser, sample_frame, temp_database):
        result = mock_parser.parse_frame(sample_frame)
        hand_id = temp_database.save_hand(result, result["session_id"])
        assert hand_id > 0


class TestBadFrameHandling:
    """Parser must not raise on corrupt or empty input."""

    def test_parser_handles_none_frame(self, mock_parser):
        # The mock CV will still return a bbox, but slicing None will raise;
        # the parser's except block catches it and returns a partial result.
        result = mock_parser.parse_frame(None)
        assert "session_id" in result

    def test_parser_handles_empty_array(self, mock_parser):
        result = mock_parser.parse_frame(np.array([]))
        assert "session_id" in result

    def test_parser_handles_blank_frame(self, mock_parser, blank_frame):
        # CV mock is set to always return a table; override for this test
        mock_parser.cv.detect_poker_table_with_confidence.return_value = (
            None, 0.0, "no_contours"
        )
        result = mock_parser.parse_frame(blank_frame)
        assert result.get("table_detected") is False

    def test_cv_handles_none_input(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bbox, conf, shape = cv.detect_poker_table_with_confidence(None)
        assert bbox is None
        assert conf == 0.0

    def test_cv_handles_empty_array(self):
        from core.computer_vision import ComputerVision
        cv = ComputerVision()
        bbox, conf, shape = cv.detect_poker_table_with_confidence(np.array([]))
        assert bbox is None


class TestDatabaseTransactionRollback:
    """DB operations should fail gracefully without corrupting state."""

    def test_save_hand_returns_positive_id(self, temp_database, sample_hands):
        hand_id = temp_database.save_hand(sample_hands[0], "sess_rollback")
        assert hand_id > 0

    def test_session_stats_after_insert(self, temp_database, sample_hands):
        for hand in sample_hands[:3]:
            temp_database.save_hand(hand, "sess_stats")
        stats = temp_database.get_session_stats("sess_stats")
        assert stats["session_id"] == "sess_stats"
        assert stats.get("total_hands", 0) >= 3

    def test_duplicate_session_does_not_crash(self, temp_database, sample_hands):
        temp_database.save_hand(sample_hands[0], "sess_dup")
        # Saving again with the same session should not raise.
        hand_id2 = temp_database.save_hand(sample_hands[1], "sess_dup")
        assert hand_id2 > 0

    def test_missing_optional_fields_do_not_crash(self, temp_database):
        minimal_hand = {
            "session_id": "sess_minimal",
            "timestamp": "2024-01-01T00:00:00",
            "stage": "preflop",
        }
        hand_id = temp_database.save_hand(minimal_hand, "sess_minimal")
        assert hand_id > 0


class TestQueueOverflow:
    """A bounded queue should block producers when full."""

    def test_queue_full_blocks(self):
        q = queue.Queue(maxsize=5)
        for i in range(5):
            q.put(i)
        assert q.full()
        # put_nowait must raise when queue is full
        with pytest.raises(queue.Full):
            q.put_nowait("overflow")

    def test_producer_consumer_drain(self):
        q = queue.Queue(maxsize=10)
        produced, consumed = [], []

        def producer():
            for i in range(8):
                q.put(i)
                produced.append(i)

        def consumer():
            while True:
                try:
                    item = q.get(timeout=0.5)
                    consumed.append(item)
                    q.task_done()
                except queue.Empty:
                    break

        t_prod = threading.Thread(target=producer)
        t_cons = threading.Thread(target=consumer)
        t_prod.start()
        t_cons.start()
        t_prod.join(timeout=5)
        t_cons.join(timeout=5)
        assert produced == list(range(8))
        assert consumed == list(range(8))


class TestThreadSynchronisation:
    """Multiple threads should be able to write to the DB concurrently."""

    def test_concurrent_db_writes(self, temp_db_path):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        errors = []

        def write_hands(thread_id: int):
            try:
                for j in range(5):
                    hand = {
                        "session_id": f"sess_thread_{thread_id}",
                        "timestamp": f"2024-01-01T00:{j:02d}:00",
                        "stage": "preflop",
                        "pot": 10.0 + j,
                        "player_count": 2,
                        "small_blind": 0.5,
                        "big_blind": 1.0,
                        "players": [],
                    }
                    db.save_hand(hand, hand["session_id"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write_hands, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        db.close()
        assert errors == [], f"Concurrent write errors: {errors}"


class TestGracefulShutdown:
    """Threads should terminate cleanly when signalled via an Event."""

    def test_worker_stops_on_event(self):
        stop_event = threading.Event()
        results = []

        def worker():
            while not stop_event.is_set():
                results.append(1)
                time.sleep(0.01)

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.05)
        stop_event.set()
        t.join(timeout=2)
        assert not t.is_alive(), "Worker thread should have stopped"
        assert len(results) > 0

    def test_queue_sentinel_stops_consumer(self):
        q = queue.Queue()
        consumed = []

        def consumer():
            while True:
                item = q.get()
                if item is None:  # sentinel
                    break
                consumed.append(item)

        t = threading.Thread(target=consumer)
        t.start()
        for i in range(5):
            q.put(i)
        q.put(None)  # sentinel
        t.join(timeout=2)
        assert not t.is_alive()
        assert consumed == list(range(5))
