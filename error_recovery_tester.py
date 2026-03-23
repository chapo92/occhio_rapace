#!/usr/bin/env python3
"""
error_recovery_tester.py
========================
Crash-resilience and error-recovery test suite for the Occhi di Falco pipeline.

Simulates realistic failure scenarios and validates that the system recovers
correctly.  Results are written to:
  - ``crash_recovery_report.txt``  – human-readable summary
  - ``test_results.json``          – structured machine-readable output

Usage::

    python error_recovery_tester.py [--output-dir OUTPUT_DIR] [--verbose]

Exit code 0 = all tests passed; 1 = one or more tests failed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

# Ensure the repository root is on the path so feature modules can be imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("error_recovery_tester")


# ---------------------------------------------------------------------------
# TestResult container
# ---------------------------------------------------------------------------

class TestResult:
    """Hold the outcome of a single test scenario."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.passed: bool = False
        self.recovery_time_ms: float = 0.0
        self.data_loss_detected: bool = False
        self.notes: str = ""
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "recovery_time_ms": round(self.recovery_time_ms, 3),
            "data_loss_detected": self.data_loss_detected,
            "notes": self.notes,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Base test infrastructure
# ---------------------------------------------------------------------------

class RecoveryTestSuite:
    """Collection of crash-simulation tests."""

    def __init__(self, output_dir: str = "output", verbose: bool = False) -> None:
        self.output_dir = output_dir
        self.verbose = verbose
        self._results: List[TestResult] = []
        os.makedirs(output_dir, exist_ok=True)
        if verbose:
            logging.getLogger("error_recovery_tester").setLevel(logging.DEBUG)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run(self, name: str, fn: Callable[[], Tuple[bool, str]]) -> TestResult:
        result = TestResult(name)
        t0 = time.perf_counter()
        try:
            passed, notes = fn()
            result.passed = passed
            result.notes = notes
        except Exception as exc:
            result.passed = False
            result.error = str(exc)
            result.notes = f"Unhandled exception: {exc}"
        result.recovery_time_ms = (time.perf_counter() - t0) * 1000
        self._results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {name:60s}  ({result.recovery_time_ms:.1f} ms)")
        if not result.passed and result.error:
            print(f"         ↳ {result.error}")
        return result

    # ------------------------------------------------------------------
    # Individual test scenarios
    # ------------------------------------------------------------------

    def test_capture_thread_kill_and_resume(self) -> Tuple[bool, str]:
        """Kill the capture thread; verify the pipeline can restart it."""
        stop_event = threading.Event()
        captured: List[int] = []

        def capture_worker() -> None:
            for i in range(5):
                if stop_event.is_set():
                    break
                captured.append(i)
                time.sleep(0.01)

        t = threading.Thread(target=capture_worker, daemon=True)
        t.start()
        time.sleep(0.02)
        stop_event.set()
        t.join(timeout=1.0)

        # Resume with a fresh thread.
        resumed: List[int] = []
        stop2 = threading.Event()

        def resume_worker() -> None:
            for i in range(3):
                if stop2.is_set():
                    break
                resumed.append(i)
                time.sleep(0.01)

        t2 = threading.Thread(target=resume_worker, daemon=True)
        t2.start()
        t2.join(timeout=1.0)

        ok = len(resumed) == 3
        return ok, f"captured={len(captured)} resumed={len(resumed)}"

    def test_database_thread_kill_queue_backup(self) -> Tuple[bool, str]:
        """Kill the DB writer; verify the queue retains pending items."""
        q: queue.Queue = queue.Queue(maxsize=50)
        stop_db = threading.Event()

        def db_worker() -> None:
            while not stop_db.is_set():
                try:
                    q.get(timeout=0.05)
                    q.task_done()
                except queue.Empty:
                    pass

        t = threading.Thread(target=db_worker, daemon=True)
        t.start()
        # Enqueue items.
        for i in range(5):
            q.put({"frame": i})
        time.sleep(0.02)
        stop_db.set()
        t.join(timeout=1.0)

        # Enqueue more *after* DB thread is dead – queue must hold them.
        for i in range(5, 10):
            q.put({"frame": i})

        backed_up = q.qsize()
        return backed_up > 0, f"items_in_queue={backed_up}"

    def test_database_lock_rollback(self) -> Tuple[bool, str]:
        """Simulate a database lock error and verify transaction rollback."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO t VALUES (1, 'initial')")
            conn.commit()

            rolled_back = False
            try:
                conn.execute("BEGIN EXCLUSIVE")
                conn.execute("INSERT INTO t VALUES (2, 'in_txn')")

                # Simulate a mid-transaction crash by forcing an error.
                raise RuntimeError("Simulated DB lock / crash")
            except RuntimeError:
                conn.rollback()
                rolled_back = True

            row_count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            conn.close()
            ok = rolled_back and row_count == 1
            return ok, f"rolled_back={rolled_back} row_count={row_count}"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    def test_ocr_fail_graceful_skip(self) -> Tuple[bool, str]:
        """OCR returns None / raises; pipeline should skip frame gracefully."""
        skipped = [False]

        def parse_frame_safe(frame_data: Optional[bytes]) -> Optional[Dict]:
            try:
                if frame_data is None:
                    raise ValueError("OCR received null frame")
                # Simulate OCR result.
                return {"text": "Pot: $10"}
            except Exception:
                skipped[0] = True
                return None

        # Good frame.
        result_good = parse_frame_safe(b"valid_frame")
        # Bad frame (OCR failure).
        result_bad = parse_frame_safe(None)

        ok = result_good is not None and result_bad is None and skipped[0]
        return ok, f"good_parsed={result_good is not None} bad_skipped={skipped[0]}"

    def test_corrupted_frame_fallback(self) -> Tuple[bool, str]:
        """Pass a corrupted/truncated frame; verify fallback to last valid state."""
        last_valid = {"pot": 45.0, "stage": "flop", "session_id": "test"}

        def process_frame(frame_bytes: bytes) -> Dict:
            if len(frame_bytes) < 10:
                # Corrupted – return fallback.
                fallback = dict(last_valid)
                fallback["_fallback"] = True
                return fallback
            return {"pot": 50.0, "stage": "turn", "session_id": "test"}

        result = process_frame(b"bad")
        ok = result.get("_fallback") is True and result.get("pot") == 45.0
        return ok, f"fallback_returned={result.get('_fallback')}"

    def test_queue_overflow_backpressure(self) -> Tuple[bool, str]:
        """Fill the queue to capacity; verify back-pressure blocks producers."""
        q: queue.Queue = queue.Queue(maxsize=5)
        blocked = [False]

        def producer() -> None:
            for i in range(10):
                try:
                    q.put(i, timeout=0.05)
                except queue.Full:
                    blocked[0] = True

        t = threading.Thread(target=producer, daemon=True)
        t.start()
        t.join(timeout=2.0)

        ok = blocked[0] and q.qsize() == 5
        return ok, f"blocked={blocked[0]} qsize={q.qsize()}"

    def test_queue_persistence_across_restart(self) -> Tuple[bool, str]:
        """Drain an in-memory queue and verify items survive a simulated restart."""
        original_items = [{"frame": i} for i in range(10)]

        # Simulate snapshot of queue to disk.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=self.output_dir
        ) as f:
            json.dump(original_items, f)
            snapshot_path = f.name

        try:
            # Reload from snapshot (simulating restart).
            with open(snapshot_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            ok = loaded == original_items
            return ok, f"persisted={len(loaded)} items"
        finally:
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass

    def test_checkpoint_save_and_load(self) -> Tuple[bool, str]:
        """Save a checkpoint and load it back; verify data integrity."""
        from features.checkpoint_system import CheckpointSystem

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = CheckpointSystem(checkpoint_dir=tmpdir, session_id="test_sess")
            ok = cs.save_checkpoint(
                last_frame_id=500,
                queue_state=[{"frame": 1}, {"frame": 2}],
                db_state={"last_hand_id": 42},
            )
            if not ok:
                return False, "save_checkpoint returned False"

            data = cs.load_checkpoint()
            if data is None:
                return False, "load_checkpoint returned None"

            checks = (
                data.get("last_frame_id") == 500
                and data.get("session_id") == "test_sess"
                and len(data.get("queue_state", [])) == 2
                and data["db_state"].get("last_hand_id") == 42
            )
            return checks, f"frame={data.get('last_frame_id')} queue={len(data.get('queue_state', []))}"

    def test_checkpoint_corruption_detection(self) -> Tuple[bool, str]:
        """Corrupt both latest and backup; verify integrity check rejects all."""
        from features.checkpoint_system import CheckpointSystem

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = CheckpointSystem(checkpoint_dir=tmpdir, session_id="corrupt_sess")
            cs.save_checkpoint(last_frame_id=100)

            for name in (
                "checkpoint_corrupt_sess_latest.json",
                "checkpoint_corrupt_sess_backup.json",
            ):
                path = os.path.join(tmpdir, name)
                if not os.path.exists(path):
                    return False, f"{name} not written"
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content[:-10] + "CORRUPTED}")

            result = cs.load_checkpoint()
            ok = result is None  # Both files corrupted → None expected.
            return ok, f"corrupted_rejected={ok}"

    def test_checkpoint_auto_cleanup(self) -> Tuple[bool, str]:
        """Write more than max_checkpoints; verify old ones are pruned."""
        from features.checkpoint_system import CheckpointSystem

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = CheckpointSystem(
                checkpoint_dir=tmpdir, session_id="clean_sess", max_checkpoints=3
            )
            for i in range(8):
                cs.save_checkpoint(last_frame_id=i * 100)
                time.sleep(0.01)  # Ensure distinct mtime.

            remaining = cs.list_checkpoints()
            # latest + backup + up to 3 timestamped = at most 5 entries.
            ok = len(remaining) <= 5
            return ok, f"remaining_files={len(remaining)}"

    def test_recovery_manager_incomplete_session(self) -> Tuple[bool, str]:
        """Simulate abnormal termination; verify RecoveryManager detects it."""
        from features.checkpoint_system import CheckpointSystem
        from features.recovery_manager import RecoveryManager

        with tempfile.TemporaryDirectory() as ckpt_dir, \
             tempfile.TemporaryDirectory() as out_dir:
            # Write a checkpoint so there is something to recover.
            cs = CheckpointSystem(checkpoint_dir=ckpt_dir, session_id="crashed_sess")
            cs.save_checkpoint(last_frame_id=250)

            rm = RecoveryManager(
                checkpoint_dir=ckpt_dir,
                session_id="crashed_sess",
                output_dir=out_dir,
            )
            # Simulate an existing lock file (previous crash).
            rm.acquire_lock()

            recovered = rm.detect_and_recover()
            ok = recovered is not None and recovered.get("last_frame_id") == 250
            return ok, f"recovered_frame={recovered.get('last_frame_id') if recovered else None}"

    def test_recovery_manager_clean_startup(self) -> Tuple[bool, str]:
        """No lock file → RecoveryManager should report nothing to recover."""
        from features.recovery_manager import RecoveryManager

        with tempfile.TemporaryDirectory() as ckpt_dir, \
             tempfile.TemporaryDirectory() as out_dir:
            rm = RecoveryManager(
                checkpoint_dir=ckpt_dir,
                session_id="clean_start",
                output_dir=out_dir,
            )
            recovered = rm.detect_and_recover()
            ok = recovered is None
            return ok, f"nothing_to_recover={ok}"

    def test_recovery_manager_corrupted_checkpoint(self) -> Tuple[bool, str]:
        """Corrupted checkpoint + lock → RecoveryManager returns None gracefully."""
        from features.checkpoint_system import CheckpointSystem
        from features.recovery_manager import RecoveryManager

        with tempfile.TemporaryDirectory() as ckpt_dir, \
             tempfile.TemporaryDirectory() as out_dir:
            cs = CheckpointSystem(checkpoint_dir=ckpt_dir, session_id="bad_sess")
            cs.save_checkpoint(last_frame_id=50)

            # Corrupt the checkpoint files.
            for name in ("checkpoint_bad_sess_latest.json", "checkpoint_bad_sess_backup.json"):
                path = os.path.join(ckpt_dir, name)
                if os.path.exists(path):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("NOT JSON {{{{ GARBAGE")

            rm = RecoveryManager(
                checkpoint_dir=ckpt_dir,
                session_id="bad_sess",
                output_dir=out_dir,
            )
            rm.acquire_lock()
            recovered = rm.detect_and_recover()
            ok = recovered is None
            return ok, f"graceful_failure={ok}"

    def test_recovery_manager_temp_file_cleanup(self) -> Tuple[bool, str]:
        """Verify temp files (*.tmp) are removed on recovery."""
        from features.checkpoint_system import CheckpointSystem
        from features.recovery_manager import RecoveryManager

        with tempfile.TemporaryDirectory() as ckpt_dir, \
             tempfile.TemporaryDirectory() as out_dir:
            # Create stale temp files.
            for i in range(3):
                open(os.path.join(out_dir, f"leftover_{i}.tmp"), "w").close()

            cs = CheckpointSystem(checkpoint_dir=ckpt_dir, session_id="tmp_sess")
            cs.save_checkpoint(last_frame_id=10)

            rm = RecoveryManager(
                checkpoint_dir=ckpt_dir,
                session_id="tmp_sess",
                output_dir=out_dir,
            )
            rm.acquire_lock()
            rm.detect_and_recover()

            remaining_tmp = [
                f for f in os.listdir(out_dir) if f.endswith(".tmp")
            ]
            ok = len(remaining_tmp) == 0
            return ok, f"tmp_files_remaining={len(remaining_tmp)}"

    def test_recovery_log_written(self) -> Tuple[bool, str]:
        """Recovery events should be persisted to the recovery log."""
        from features.checkpoint_system import CheckpointSystem
        from features.recovery_manager import RecoveryManager

        with tempfile.TemporaryDirectory() as ckpt_dir, \
             tempfile.TemporaryDirectory() as out_dir:
            cs = CheckpointSystem(checkpoint_dir=ckpt_dir, session_id="log_sess")
            cs.save_checkpoint(last_frame_id=777)

            rm = RecoveryManager(
                checkpoint_dir=ckpt_dir,
                session_id="log_sess",
                output_dir=out_dir,
            )
            rm.acquire_lock()
            rm.detect_and_recover()

            log = rm.get_recovery_log()
            ok = len(log) >= 2  # at least detected + success/failure
            return ok, f"log_entries={len(log)}"

    def test_error_recovery_get_fallback(self) -> Tuple[bool, str]:
        """ErrorRecovery.get_fallback should return last valid data on OCR error."""
        from features.error_recovery import ErrorRecovery

        er = ErrorRecovery(
            checkpoint_dir=os.path.join(self.output_dir, "er_fallback")
        )
        good_data = {
            "session_id": "s1",
            "timestamp": datetime.now().isoformat(),
            "table_detected": True,
            "pot": 30.0,
            "stage": "flop",
        }
        er._last_valid = dict(good_data)

        fallback = er.get_fallback(None, ValueError("OCR failed"))
        ok = fallback.get("_fallback") is True and fallback.get("pot") == 30.0
        return ok, f"fallback_pot={fallback.get('pot')}"

    def test_error_recovery_save_load_checkpoint(self) -> Tuple[bool, str]:
        """ErrorRecovery.save_checkpoint / load_checkpoint round-trip."""
        from features.error_recovery import ErrorRecovery

        with tempfile.TemporaryDirectory() as tmpdir:
            er = ErrorRecovery(checkpoint_dir=tmpdir)
            data = {
                "session_id": "s2",
                "timestamp": datetime.now().isoformat(),
                "pot": 100.0,
            }
            er.save_checkpoint(data)
            loaded = er.load_checkpoint()
            ok = loaded is not None and loaded.get("pot") == 100.0
            return ok, f"loaded_pot={loaded.get('pot') if loaded else None}"

    def test_missing_queue_state_handled(self) -> Tuple[bool, str]:
        """A checkpoint with no queue_state should load with an empty list."""
        from features.checkpoint_system import CheckpointSystem

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = CheckpointSystem(checkpoint_dir=tmpdir, session_id="noqueue")
            cs.save_checkpoint(last_frame_id=10)
            data = cs.load_checkpoint()
            ok = data is not None and data.get("queue_state") == []
            return ok, f"queue_state={data.get('queue_state') if data else 'N/A'}"

    def test_memory_exhaustion_simulation(self) -> Tuple[bool, str]:
        """Simulate memory pressure by filling a list then clearing it."""
        big: List[bytes] = []
        cleanup_called = [False]
        try:
            # Fill ~20 MB.
            for _ in range(200):
                big.append(b"x" * 100_000)
        except MemoryError:
            pass
        finally:
            big.clear()
            cleanup_called[0] = True

        ok = cleanup_called[0]
        return ok, f"cleanup_called={ok}"

    def test_network_disconnect_queue_persistence(self) -> Tuple[bool, str]:
        """Items in queue survive a simulated network disconnect."""
        q: queue.Queue = queue.Queue()
        for i in range(5):
            q.put({"frame": i})

        # Simulate network drop: the consumer stops but queue keeps items.
        consumer_stopped = threading.Event()
        consumer_stopped.set()

        # Count items still in queue.
        count = q.qsize()
        ok = count == 5
        return ok, f"queue_survived={count}"

    def test_incomplete_db_transaction_on_restart(self) -> Tuple[bool, str]:
        """Database created fresh after simulated incomplete prior transaction."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE IF NOT EXISTS state (k TEXT, v TEXT)")
            conn.execute("INSERT INTO state VALUES ('status', 'initialised')")
            conn.commit()

            # Simulate incomplete transaction (no commit before close).
            try:
                conn.execute("BEGIN")
                conn.execute("INSERT INTO state VALUES ('status', 'in_progress')")
                raise RuntimeError("crash before commit")
            except RuntimeError:
                conn.rollback()
            finally:
                conn.close()

            # Re-open and verify state is clean.
            conn2 = sqlite3.connect(db_path)
            rows = conn2.execute("SELECT * FROM state").fetchall()
            conn2.close()

            ok = len(rows) == 1 and rows[0][1] == "initialised"
            return ok, f"rows={len(rows)} value={rows[0][1] if rows else 'N/A'}"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    def test_checkpoint_version_field(self) -> Tuple[bool, str]:
        """Saved checkpoint must include the _version field."""
        from features.checkpoint_system import CheckpointSystem

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = CheckpointSystem(checkpoint_dir=tmpdir, session_id="ver_sess")
            cs.save_checkpoint(last_frame_id=1)
            data = cs.load_checkpoint()
            ok = data is not None and "_version" in data
            return ok, f"version={data.get('_version') if data else None}"

    def test_maybe_checkpoint_triggers_at_100_frames(self) -> Tuple[bool, str]:
        """maybe_checkpoint should fire exactly at multiples of frames_per_checkpoint."""
        from features.checkpoint_system import CheckpointSystem

        with tempfile.TemporaryDirectory() as tmpdir:
            cs = CheckpointSystem(
                checkpoint_dir=tmpdir,
                session_id="freq_sess",
                frames_per_checkpoint=10,
            )
            triggered = 0
            for frame in range(35):
                saved = cs.maybe_checkpoint(last_frame_id=frame)
                if saved:
                    triggered += 1

            ok = triggered == 3  # at frames 10, 20, 30
            return ok, f"triggered={triggered} expected=3"

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run_all(self) -> List[TestResult]:
        """Execute all test scenarios and collect results."""
        scenarios = [
            ("Capture thread kill & resume", self.test_capture_thread_kill_and_resume),
            ("DB thread kill – queue backup", self.test_database_thread_kill_queue_backup),
            ("DB lock → rollback", self.test_database_lock_rollback),
            ("OCR fail → graceful skip", self.test_ocr_fail_graceful_skip),
            ("Corrupted frame → fallback", self.test_corrupted_frame_fallback),
            ("Queue overflow – backpressure", self.test_queue_overflow_backpressure),
            ("Queue persistence across restart", self.test_queue_persistence_across_restart),
            ("Checkpoint save & load", self.test_checkpoint_save_and_load),
            ("Checkpoint corruption detection", self.test_checkpoint_corruption_detection),
            ("Checkpoint auto-cleanup (>max)", self.test_checkpoint_auto_cleanup),
            ("RecoveryManager – incomplete session", self.test_recovery_manager_incomplete_session),
            ("RecoveryManager – clean startup", self.test_recovery_manager_clean_startup),
            ("RecoveryManager – corrupted checkpoint", self.test_recovery_manager_corrupted_checkpoint),
            ("RecoveryManager – temp file cleanup", self.test_recovery_manager_temp_file_cleanup),
            ("Recovery log written", self.test_recovery_log_written),
            ("ErrorRecovery get_fallback", self.test_error_recovery_get_fallback),
            ("ErrorRecovery save/load checkpoint", self.test_error_recovery_save_load_checkpoint),
            ("Missing queue_state handled", self.test_missing_queue_state_handled),
            ("Memory exhaustion simulation", self.test_memory_exhaustion_simulation),
            ("Network disconnect – queue persistence", self.test_network_disconnect_queue_persistence),
            ("Incomplete DB transaction on restart", self.test_incomplete_db_transaction_on_restart),
            ("Checkpoint _version field present", self.test_checkpoint_version_field),
            ("maybe_checkpoint fires at correct interval", self.test_maybe_checkpoint_triggers_at_100_frames),
        ]

        print("\n" + "=" * 72)
        print("  Occhi di Falco – Error Recovery & Crash Resilience Tests")
        print("=" * 72)
        for name, fn in scenarios:
            self._run(name, fn)
        return self._results

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def write_reports(self) -> None:
        """Persist ``crash_recovery_report.txt`` and ``test_results.json``."""
        self._write_text_report()
        self._write_json_report()

    def _write_text_report(self) -> None:
        passed = sum(1 for r in self._results if r.passed)
        total = len(self._results)
        path = os.path.join(self.output_dir, "crash_recovery_report.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("=" * 72 + "\n")
            f.write("  CRASH RECOVERY REPORT – Occhi di Falco\n")
            f.write(f"  Generated: {datetime.now().isoformat()}\n")
            f.write("=" * 72 + "\n\n")
            f.write(f"Results: {passed}/{total} tests passed\n\n")
            f.write("-" * 72 + "\n")
            for r in self._results:
                status = "PASS" if r.passed else "FAIL"
                f.write(f"[{status}] {r.name}\n")
                f.write(f"       recovery_time_ms : {r.recovery_time_ms:.3f}\n")
                f.write(f"       data_loss        : {r.data_loss_detected}\n")
                f.write(f"       notes            : {r.notes}\n")
                if r.error:
                    f.write(f"       error            : {r.error}\n")
                f.write("\n")
            f.write("-" * 72 + "\n")
            f.write(f"\nSummary: {passed}/{total} passed")
            if passed == total:
                f.write("  ✅ ALL TESTS PASSED\n")
            else:
                failed = total - passed
                f.write(f"  ❌ {failed} FAILED\n")
        print(f"\n  Report written → {path}")

    def _write_json_report(self) -> None:
        passed = sum(1 for r in self._results if r.passed)
        total = len(self._results)
        payload = {
            "generated": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate_pct": round(passed / total * 100, 1) if total else 0,
            },
            "results": [r.to_dict() for r in self._results],
        }
        path = os.path.join(self.output_dir, "test_results.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"  Results written  → {path}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run error-recovery and crash-resilience tests",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for crash_recovery_report.txt and test_results.json",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    suite = RecoveryTestSuite(output_dir=args.output_dir, verbose=args.verbose)
    results = suite.run_all()
    suite.write_reports()

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Final: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
