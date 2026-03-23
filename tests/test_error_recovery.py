"""Unit tests for CheckpointSystem and RecoveryManager."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from features.checkpoint_system import CheckpointSystem
from features.recovery_manager import RecoveryManager


class TestCheckpointSystemSaveLoad(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ckpt_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make(self, session_id="sess", **kwargs):
        return CheckpointSystem(
            checkpoint_dir=self.ckpt_dir, session_id=session_id, **kwargs
        )

    def test_save_and_load_round_trip(self):
        cs = self._make()
        ok = cs.save_checkpoint(
            last_frame_id=100,
            queue_state=[{"a": 1}],
            db_state={"last_hand_id": 5},
        )
        self.assertTrue(ok)
        data = cs.load_checkpoint()
        self.assertIsNotNone(data)
        self.assertEqual(data["last_frame_id"], 100)
        self.assertEqual(data["session_id"], "sess")
        self.assertEqual(data["queue_state"], [{"a": 1}])
        self.assertEqual(data["db_state"]["last_hand_id"], 5)

    def test_load_returns_none_when_no_checkpoint(self):
        cs = self._make(session_id="empty")
        self.assertIsNone(cs.load_checkpoint())

    def test_version_field_present(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=0)
        data = cs.load_checkpoint()
        self.assertIn("_version", data)
        self.assertIsInstance(data["_version"], int)

    def test_hash_field_present(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=0)
        latest = os.path.join(self.ckpt_dir, "checkpoint_sess_latest.json")
        with open(latest, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertIn("_hash", raw)

    def test_backup_file_created(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=1)
        backup = os.path.join(self.ckpt_dir, "checkpoint_sess_backup.json")
        self.assertTrue(os.path.exists(backup))

    def test_timestamped_file_created(self):
        cs = self._make()
        before = len(os.listdir(self.ckpt_dir))
        cs.save_checkpoint(last_frame_id=1)
        after = len(os.listdir(self.ckpt_dir))
        # latest + backup + timestamped = 3 new files
        self.assertEqual(after - before, 3)

    def test_empty_queue_state_default(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=5)
        data = cs.load_checkpoint()
        self.assertEqual(data["queue_state"], [])

    def test_extra_fields_stored(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=10, extra={"custom_key": "hello"})
        data = cs.load_checkpoint()
        self.assertEqual(data["custom_key"], "hello")


class TestCheckpointIntegrity(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ckpt_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make(self, session_id="isess"):
        return CheckpointSystem(checkpoint_dir=self.ckpt_dir, session_id=session_id)

    def test_verify_valid_checkpoint(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=10)
        self.assertTrue(cs.verify_checkpoint_integrity())

    def test_corrupted_checkpoint_rejected(self):
        """Both latest and backup corrupted → load_checkpoint returns None."""
        cs = self._make()
        cs.save_checkpoint(last_frame_id=10)
        for name in ("checkpoint_isess_latest.json", "checkpoint_isess_backup.json"):
            path = os.path.join(self.ckpt_dir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write("{GARBAGE{{{")
        self.assertIsNone(cs.load_checkpoint())

    def test_tampered_hash_rejected(self):
        """Tampered hash in both files → load_checkpoint returns None."""
        cs = self._make()
        cs.save_checkpoint(last_frame_id=20)
        for name in ("checkpoint_isess_latest.json", "checkpoint_isess_backup.json"):
            path = os.path.join(self.ckpt_dir, name)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["last_frame_id"] = 999  # tamper without updating hash
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        self.assertIsNone(cs.load_checkpoint())

    def test_missing_hash_rejected(self):
        """Missing _hash in both files → load_checkpoint returns None."""
        cs = self._make()
        cs.save_checkpoint(last_frame_id=5)
        for name in ("checkpoint_isess_latest.json", "checkpoint_isess_backup.json"):
            path = os.path.join(self.ckpt_dir, name)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            del data["_hash"]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        self.assertIsNone(cs.load_checkpoint())

    def test_falls_back_to_backup(self):
        cs = self._make()
        cs.save_checkpoint(last_frame_id=42)
        # Corrupt latest only.
        latest = os.path.join(self.ckpt_dir, "checkpoint_isess_latest.json")
        with open(latest, "w", encoding="utf-8") as f:
            f.write("INVALID")
        # Backup should still be loadable.
        data = cs.load_checkpoint()
        self.assertIsNotNone(data)
        self.assertEqual(data["last_frame_id"], 42)


class TestCheckpointCleanup(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ckpt_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_cleanup_keeps_max_timestamped(self):
        cs = CheckpointSystem(
            checkpoint_dir=self.ckpt_dir, session_id="cs", max_checkpoints=3
        )
        for i in range(7):
            cs.save_checkpoint(last_frame_id=i * 10)
            time.sleep(0.01)

        paths = cs.list_checkpoints()
        # latest + backup + ≤3 timestamped
        self.assertLessEqual(len(paths), 5)

    def test_cleanup_returns_delete_count(self):
        cs = CheckpointSystem(
            checkpoint_dir=self.ckpt_dir, session_id="del", max_checkpoints=2
        )
        for i in range(5):
            cs.save_checkpoint(last_frame_id=i)
            time.sleep(0.01)
        # After 5 saves with max=2, at least 3 files should have been deleted.
        remaining = len(cs.list_checkpoints())
        self.assertLessEqual(remaining, 4)  # 2 latest/backup + 2 timestamped

    def test_list_checkpoints_newest_first(self):
        cs = CheckpointSystem(
            checkpoint_dir=self.ckpt_dir, session_id="order", max_checkpoints=10
        )
        for i in range(3):
            cs.save_checkpoint(last_frame_id=i)
            time.sleep(0.02)
        paths = cs.list_checkpoints()
        mtimes = [os.path.getmtime(p) for p in paths]
        self.assertEqual(mtimes, sorted(mtimes, reverse=True))


class TestMaybeCheckpoint(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ckpt_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_triggers_at_correct_interval(self):
        cs = CheckpointSystem(
            checkpoint_dir=self.ckpt_dir,
            session_id="mc",
            frames_per_checkpoint=10,
        )
        triggered = sum(
            1 for i in range(35) if cs.maybe_checkpoint(last_frame_id=i)
        )
        self.assertEqual(triggered, 3)

    def test_does_not_trigger_before_interval(self):
        cs = CheckpointSystem(
            checkpoint_dir=self.ckpt_dir,
            session_id="nd",
            frames_per_checkpoint=100,
        )
        triggered = sum(
            1 for i in range(99) if cs.maybe_checkpoint(last_frame_id=i)
        )
        self.assertEqual(triggered, 0)


class TestRecoveryManagerLock(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._outdir = tempfile.TemporaryDirectory()
        self.ckpt_dir = self._tmpdir.name
        self.out_dir = self._outdir.name

    def tearDown(self):
        self._tmpdir.cleanup()
        self._outdir.cleanup()

    def _make(self, session_id="sess"):
        return RecoveryManager(
            checkpoint_dir=self.ckpt_dir,
            session_id=session_id,
            output_dir=self.out_dir,
        )

    def test_acquire_creates_lock_file(self):
        rm = self._make()
        rm.acquire_lock()
        self.assertTrue(os.path.exists(rm._lock_path))

    def test_release_removes_lock_file(self):
        rm = self._make()
        rm.acquire_lock()
        rm.release_lock()
        self.assertFalse(os.path.exists(rm._lock_path))

    def test_is_previous_session_incomplete_true(self):
        rm = self._make()
        rm.acquire_lock()
        self.assertTrue(rm.is_previous_session_incomplete())

    def test_is_previous_session_incomplete_false(self):
        rm = self._make()
        self.assertFalse(rm.is_previous_session_incomplete())


class TestRecoveryManagerDetectAndRecover(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._outdir = tempfile.TemporaryDirectory()
        self.ckpt_dir = self._tmpdir.name
        self.out_dir = self._outdir.name

    def tearDown(self):
        self._tmpdir.cleanup()
        self._outdir.cleanup()

    def _make(self, session_id="sess"):
        return RecoveryManager(
            checkpoint_dir=self.ckpt_dir,
            session_id=session_id,
            output_dir=self.out_dir,
        )

    def test_no_lock_returns_none(self):
        rm = self._make()
        self.assertIsNone(rm.detect_and_recover())

    def test_lock_with_valid_checkpoint_recovers(self):
        cs = CheckpointSystem(checkpoint_dir=self.ckpt_dir, session_id="sess")
        cs.save_checkpoint(last_frame_id=300)
        rm = self._make()
        rm.acquire_lock()
        result = rm.detect_and_recover()
        self.assertIsNotNone(result)
        self.assertEqual(result["last_frame_id"], 300)

    def test_lock_released_after_recovery(self):
        cs = CheckpointSystem(checkpoint_dir=self.ckpt_dir, session_id="sess")
        cs.save_checkpoint(last_frame_id=1)
        rm = self._make()
        rm.acquire_lock()
        rm.detect_and_recover()
        self.assertFalse(os.path.exists(rm._lock_path))

    def test_lock_with_no_checkpoint_returns_none(self):
        rm = self._make(session_id="nocp")
        rm.acquire_lock()
        result = rm.detect_and_recover()
        self.assertIsNone(result)
        # Lock should be cleaned up.
        self.assertFalse(os.path.exists(rm._lock_path))

    def test_corrupted_checkpoint_returns_none(self):
        cs = CheckpointSystem(checkpoint_dir=self.ckpt_dir, session_id="sess")
        cs.save_checkpoint(last_frame_id=10)
        for name in (
            "checkpoint_sess_latest.json",
            "checkpoint_sess_backup.json",
        ):
            path = os.path.join(self.ckpt_dir, name)
            if os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("GARBAGE")
        rm = self._make()
        rm.acquire_lock()
        result = rm.detect_and_recover()
        self.assertIsNone(result)

    def test_temp_files_cleaned_on_recovery(self):
        for i in range(3):
            open(os.path.join(self.out_dir, f"stale_{i}.tmp"), "w").close()
        cs = CheckpointSystem(checkpoint_dir=self.ckpt_dir, session_id="sess")
        cs.save_checkpoint(last_frame_id=5)
        rm = self._make()
        rm.acquire_lock()
        rm.detect_and_recover()
        tmp_files = [f for f in os.listdir(self.out_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_recovery_log_populated(self):
        cs = CheckpointSystem(checkpoint_dir=self.ckpt_dir, session_id="sess")
        cs.save_checkpoint(last_frame_id=50)
        rm = self._make()
        rm.acquire_lock()
        rm.detect_and_recover()
        log = rm.get_recovery_log()
        self.assertGreaterEqual(len(log), 2)
        events = {entry["event"] for entry in log}
        self.assertIn("incomplete_session_detected", events)

    def test_recovery_log_empty_when_no_recovery_needed(self):
        rm = self._make()
        log = rm.get_recovery_log()
        self.assertEqual(log, [])


if __name__ == "__main__":
    unittest.main()
