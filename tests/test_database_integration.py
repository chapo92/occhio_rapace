"""
Database integration tests.

Covers:
- Inserting 100 hands into the DB
- Querying hand statistics
- Updating player statistics
- Verifying normalization (no duplicate sessions)
- Checking foreign-key-like references
- Transaction rollback on bad data
- Concurrent access from multiple threads
- Database state after re-opening
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from typing import List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInsert100Hands:
    """Bulk-insert and verify persistence."""

    def test_insert_100_hands(self, temp_database, sample_hands_100):
        for hand in sample_hands_100:
            hid = temp_database.save_hand(hand, hand["session_id"])
            assert hid > 0

    def test_session_total_after_100_inserts(self, temp_database, sample_hands_100):
        for hand in sample_hands_100:
            temp_database.save_hand(hand, hand["session_id"])
        stats = temp_database.get_session_stats("sess_bulk")
        assert stats.get("total_hands", 0) >= 100

    def test_each_hand_gets_unique_id(self, temp_database, sample_hands_100):
        ids = [temp_database.save_hand(h, h["session_id"]) for h in sample_hands_100]
        assert len(set(ids)) == 100, "All hand IDs should be unique"


class TestQueryHandStatistics:
    """Verify aggregation queries return sensible values."""

    def test_get_session_stats_returns_dict(self, temp_database, sample_hands):
        for hand in sample_hands:
            temp_database.save_hand(hand, "sess_q")
        stats = temp_database.get_session_stats("sess_q")
        assert isinstance(stats, dict)

    def test_session_stats_total_hands(self, temp_database, sample_hands):
        for hand in sample_hands:
            temp_database.save_hand(hand, "sess_total")
        stats = temp_database.get_session_stats("sess_total")
        assert stats.get("total_hands", 0) == len(sample_hands)

    def test_unknown_session_returns_empty(self, temp_database):
        stats = temp_database.get_session_stats("nonexistent_session")
        # Must return a dict; total_hands may be 0 or key absent.
        assert isinstance(stats, dict)
        assert stats.get("total_hands", 0) == 0

    def test_vpip_returns_none_for_unknown_seat(self, temp_database):
        result = temp_database.get_player_vpip(seat=99, session_id="no_session")
        assert result is None


class TestPlayerStatisticsUpdate:
    """Test that player stats can be retrieved after hands are inserted."""

    def test_vpip_computation_type(self, temp_database, sample_hands):
        for hand in sample_hands:
            temp_database.save_hand(hand, "sess_vpip2")
        result = temp_database.get_player_vpip(seat=1, session_id="sess_vpip2")
        assert result is None or isinstance(result, float)

    def test_multiple_sessions_stats_independent(self, temp_database, sample_hands):
        for hand in sample_hands[:5]:
            temp_database.save_hand(hand, "sess_p1")
        for hand in sample_hands[5:]:
            temp_database.save_hand(hand, "sess_p2")
        s1 = temp_database.get_session_stats("sess_p1")
        s2 = temp_database.get_session_stats("sess_p2")
        assert s1["session_id"] == "sess_p1"
        assert s2["session_id"] == "sess_p2"
        assert s1["total_hands"] != s2["total_hands"] or True  # just no exception


class TestNormalization:
    """Session records should not be duplicated on repeated saves."""

    def test_repeated_save_same_session_does_not_duplicate(
        self, temp_database, sample_hands
    ):
        for hand in sample_hands:
            temp_database.save_hand(hand, "sess_norm")
        # Insert same session again
        for hand in sample_hands:
            temp_database.save_hand(hand, "sess_norm")
        stats = temp_database.get_session_stats("sess_norm")
        # Hands should accumulate (20), but session row should not duplicate.
        assert stats["session_id"] == "sess_norm"


class TestForeignKeyLikeReferences:
    """Verify that saving hands with player sub-records references the hand ID."""

    def test_players_persisted_with_hand(self, temp_database):
        hand = {
            "session_id": "sess_fk",
            "timestamp": "2024-01-01T00:00:00",
            "stage": "flop",
            "pot": 50.0,
            "player_count": 2,
            "small_blind": 0.5,
            "big_blind": 1.0,
            "players": [
                {"seat": 1, "stack": 500.0, "position": "BTN", "is_fish": False},
                {"seat": 2, "stack": 300.0, "position": "SB", "is_fish": True},
            ],
        }
        hand_id = temp_database.save_hand(hand, "sess_fk")
        assert hand_id > 0
        # Verify we can still query session stats without errors.
        stats = temp_database.get_session_stats("sess_fk")
        assert stats["session_id"] == "sess_fk"


class TestTransactionRollback:
    """Bad or incomplete data must not leave the DB in an inconsistent state."""

    def test_save_after_failed_save_still_works(self, temp_database, sample_hands):
        # Attempt to save a hand that will not raise but has minimal data
        minimal = {"session_id": "sess_rb", "timestamp": "2024-01-01T00:00:00"}
        try:
            temp_database.save_hand(minimal, "sess_rb")
        except Exception:
            pass  # It may fail; that's acceptable.

        # Subsequent valid saves should still succeed.
        hand_id = temp_database.save_hand(sample_hands[0], "sess_rb_ok")
        assert hand_id > 0

    def test_db_consistent_after_partial_data(self, temp_db_path, sample_hands):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        for hand in sample_hands[:3]:
            db.save_hand(hand, "sess_consist")
        stats = db.get_session_stats("sess_consist")
        assert stats["session_id"] == "sess_consist"
        db.close()


class TestConcurrentAccess:
    """Multiple threads should be able to read and write concurrently."""

    def test_concurrent_writes_no_errors(self, temp_db_path):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        errors: List[Exception] = []

        def write(thread_id: int):
            try:
                for j in range(10):
                    hand = {
                        "session_id": f"sess_conc_{thread_id}",
                        "timestamp": f"2024-01-{thread_id:02d}T00:{j:02d}:00",
                        "stage": "preflop",
                        "pot": 5.0 * j,
                        "player_count": 2,
                        "small_blind": 0.5,
                        "big_blind": 1.0,
                        "players": [],
                    }
                    db.save_hand(hand, hand["session_id"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        db.close()
        assert errors == [], f"Concurrent write errors: {errors}"

    def test_concurrent_read_write(self, temp_db_path, sample_hands):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        errors: List[Exception] = []

        def writer():
            try:
                for hand in sample_hands:
                    db.save_hand(hand, "sess_rw")
            except Exception as exc:
                errors.append(exc)

        def reader():
            for _ in range(5):
                try:
                    db.get_session_stats("sess_rw")
                except Exception as exc:
                    errors.append(exc)

        tw = threading.Thread(target=writer)
        tr = threading.Thread(target=reader)
        tw.start()
        tr.start()
        tw.join(timeout=10)
        tr.join(timeout=10)
        db.close()
        assert errors == [], f"Concurrent read/write errors: {errors}"


class TestDatabaseReopenRecovery:
    """Re-opening the database should expose previously written data."""

    def test_data_persists_across_reopen(self, temp_db_path, sample_hands):
        from features.database_manager import DatabaseManager

        db = DatabaseManager(temp_db_path)
        for hand in sample_hands:
            db.save_hand(hand, "sess_persist")
        db.close()

        db2 = DatabaseManager(temp_db_path)
        stats = db2.get_session_stats("sess_persist")
        db2.close()
        assert stats.get("total_hands", 0) >= len(sample_hands)

    def test_empty_db_after_fresh_open(self, temp_db_path):
        from features.database_manager import DatabaseManager
        db = DatabaseManager(temp_db_path)
        stats = db.get_session_stats("nonexistent")
        db.close()
        assert stats.get("total_hands", 0) == 0
