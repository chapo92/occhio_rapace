"""Automatic recovery manager for incomplete or crashed pipeline sessions."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from features.checkpoint_system import CheckpointSystem

logger = logging.getLogger(__name__)

_LOCK_FILENAME = "session.lock"
_RECOVERY_LOG = "output/recovery.log"


class RecoveryManager:
    """Detect, log, and recover from abnormal pipeline terminations.

    On startup the manager checks whether a *session lock file* was left behind
    by a previous run.  If it was, the previous session ended abnormally and
    the manager will attempt to load the last valid checkpoint and resume
    processing from there.

    Parameters
    ----------
    checkpoint_dir:
        Directory shared with :class:`~features.checkpoint_system.CheckpointSystem`.
    session_id:
        Identifier for the current session.
    output_dir:
        Root output directory; used for the recovery log and temp-file cleanup.
    """

    def __init__(
        self,
        checkpoint_dir: str = "output/checkpoints",
        session_id: str = "default",
        output_dir: str = "output",
    ) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.session_id = session_id
        self.output_dir = output_dir
        self._lock_path = os.path.join(checkpoint_dir, _LOCK_FILENAME)
        self._recovery_log = os.path.join(output_dir, "recovery.log")
        self._checkpoint_system = CheckpointSystem(
            checkpoint_dir=checkpoint_dir, session_id=session_id
        )
        os.makedirs(checkpoint_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Session lock helpers
    # ------------------------------------------------------------------

    def acquire_lock(self) -> None:
        """Write a session lock file indicating the pipeline is running."""
        try:
            with open(self._lock_path, "w", encoding="utf-8") as f:
                f.write(
                    f"session_id={self.session_id}\n"
                    f"pid={os.getpid()}\n"
                    f"started={datetime.now().isoformat()}\n"
                )
            logger.debug("Session lock acquired: %s", self._lock_path)
        except OSError as exc:
            logger.warning("Could not acquire session lock: %s", exc)

    def release_lock(self) -> None:
        """Remove the session lock file on clean shutdown."""
        try:
            if os.path.exists(self._lock_path):
                os.unlink(self._lock_path)
                logger.debug("Session lock released")
        except OSError as exc:
            logger.warning("Could not release session lock: %s", exc)

    def is_previous_session_incomplete(self) -> bool:
        """Return ``True`` if the lock file from a previous session exists."""
        return os.path.exists(self._lock_path)

    # ------------------------------------------------------------------
    # Recovery entry point
    # ------------------------------------------------------------------

    def detect_and_recover(self) -> Optional[Dict[str, Any]]:
        """Check for an incomplete previous session and recover if needed.

        Returns the recovered checkpoint data dict when recovery succeeds, or
        ``None`` if there is nothing to recover.
        """
        if not self.is_previous_session_incomplete():
            return None

        self._log_recovery_event("incomplete_session_detected", {})
        logger.warning(
            "Incomplete session detected (lock file present: %s)", self._lock_path
        )

        checkpoint = self._checkpoint_system.load_checkpoint()
        if checkpoint is None:
            self._log_recovery_event(
                "recovery_failed", {"reason": "no_valid_checkpoint"}
            )
            logger.error("Recovery failed: no valid checkpoint found")
            self._cleanup_lock()
            return None

        if not self._verify_data_consistency(checkpoint):
            self._log_recovery_event(
                "recovery_failed", {"reason": "data_inconsistency"}
            )
            logger.error("Recovery failed: checkpoint data is inconsistent")
            self._cleanup_lock()
            return None

        self._cleanup_temp_files()
        self._cleanup_lock()

        self._log_recovery_event(
            "recovery_success",
            {
                "session_id": checkpoint.get("session_id"),
                "last_frame_id": checkpoint.get("last_frame_id"),
                "checkpoint_timestamp": checkpoint.get("timestamp"),
            },
        )
        logger.info(
            "Recovery successful: resuming from frame %d (session %s)",
            checkpoint.get("last_frame_id", 0),
            checkpoint.get("session_id", "?"),
        )
        return checkpoint

    # ------------------------------------------------------------------
    # Consistency verification
    # ------------------------------------------------------------------

    def _verify_data_consistency(self, checkpoint: Dict[str, Any]) -> bool:
        """Perform lightweight consistency checks on *checkpoint*.

        Returns ``True`` if the data looks usable.
        """
        required_fields = {"session_id", "last_frame_id", "timestamp"}
        missing = required_fields - checkpoint.keys()
        if missing:
            logger.warning("Checkpoint missing fields: %s", missing)
            return False

        last_frame_id = checkpoint.get("last_frame_id")
        if not isinstance(last_frame_id, int) or last_frame_id < 0:
            logger.warning("Checkpoint has invalid last_frame_id: %s", last_frame_id)
            return False

        return True

    # ------------------------------------------------------------------
    # Temp-file cleanup
    # ------------------------------------------------------------------

    def _cleanup_temp_files(self) -> int:
        """Remove ``*.tmp`` files from *output_dir* left by a crashed run.

        Returns the number of files removed.
        """
        removed = 0
        try:
            for root, _dirs, files in os.walk(self.output_dir):
                for name in files:
                    if name.endswith(".tmp"):
                        path = os.path.join(root, name)
                        try:
                            os.unlink(path)
                            removed += 1
                            logger.debug("Removed temp file: %s", path)
                        except OSError as exc:
                            logger.warning("Could not remove %s: %s", path, exc)
        except OSError as exc:
            logger.warning("_cleanup_temp_files walk error: %s", exc)
        if removed:
            logger.info("Cleaned up %d temp file(s)", removed)
        return removed

    def _cleanup_lock(self) -> None:
        try:
            if os.path.exists(self._lock_path):
                os.unlink(self._lock_path)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Recovery logging
    # ------------------------------------------------------------------

    def _log_recovery_event(self, event: str, details: Dict[str, Any]) -> None:
        """Append a structured recovery event to the recovery log."""
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "session_id": self.session_id,
        }
        entry.update(details)
        try:
            with open(self._recovery_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.warning("Could not write recovery log: %s", exc)

    def get_recovery_log(self) -> List[Dict[str, Any]]:
        """Return all recovery log entries as a list of dicts."""
        entries: List[Dict[str, Any]] = []
        if not os.path.exists(self._recovery_log):
            return entries
        try:
            with open(self._recovery_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except ValueError:
                            pass
        except OSError as exc:
            logger.warning("Could not read recovery log: %s", exc)
        return entries
