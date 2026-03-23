"""Automatic checkpoint system for saving and restoring pipeline state."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHECKPOINT_VERSION = 1
_MAX_CHECKPOINTS = 5
_FRAMES_PER_CHECKPOINT = 100


class CheckpointSystem:
    """Persist pipeline state to disk and recover after unexpected termination.

    Checkpoints are saved as JSON files in *checkpoint_dir*.  Each checkpoint
    includes a SHA-256 integrity hash so corrupted files can be detected and
    skipped automatically.  At most ``max_checkpoints`` files are kept on disk;
    older ones are pruned by :meth:`cleanup_old_checkpoints`.

    Parameters
    ----------
    checkpoint_dir:
        Directory where checkpoint files are stored.
    session_id:
        Identifier for the current capture session.
    max_checkpoints:
        Number of checkpoint files to retain (default 5).
    frames_per_checkpoint:
        How often (in frames) to auto-save a checkpoint (default 100).
    """

    def __init__(
        self,
        checkpoint_dir: str = "output/checkpoints",
        session_id: str = "default",
        max_checkpoints: int = _MAX_CHECKPOINTS,
        frames_per_checkpoint: int = _FRAMES_PER_CHECKPOINT,
    ) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.session_id = session_id
        self.max_checkpoints = max_checkpoints
        self.frames_per_checkpoint = frames_per_checkpoint
        self._frame_counter: int = 0
        os.makedirs(checkpoint_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _checkpoint_path(self, name: str) -> str:
        return os.path.join(self.checkpoint_dir, name)

    @staticmethod
    def _compute_hash(data: Dict[str, Any]) -> str:
        payload = json.dumps(data, sort_keys=True, default=str).encode()
        return hashlib.sha256(payload).hexdigest()

    def _latest_path(self) -> str:
        return self._checkpoint_path(f"checkpoint_{self.session_id}_latest.json")

    def _backup_path(self) -> str:
        return self._checkpoint_path(f"checkpoint_{self.session_id}_backup.json")

    def _timestamped_path(self, ts: str) -> str:
        safe_ts = ts.replace(":", "-").replace(".", "-")
        return self._checkpoint_path(
            f"checkpoint_{self.session_id}_{safe_ts}.json"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_checkpoint(
        self,
        last_frame_id: int,
        queue_state: Optional[List[Any]] = None,
        db_state: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist current pipeline state to disk.

        Parameters
        ----------
        last_frame_id:
            Index of the most recently processed frame.
        queue_state:
            Snapshot of the in-memory processing queue (serialisable items).
        db_state:
            Lightweight summary of the database state (e.g. last hand id).
        extra:
            Any additional metadata to include in the checkpoint.

        Returns
        -------
        bool
            ``True`` on success, ``False`` on failure.
        """
        ts = datetime.now().isoformat()
        payload: Dict[str, Any] = {
            "_version": _CHECKPOINT_VERSION,
            "session_id": self.session_id,
            "timestamp": ts,
            "last_frame_id": last_frame_id,
            "queue_state": queue_state or [],
            "db_state": db_state or {},
        }
        if extra:
            payload.update(extra)

        payload["_hash"] = self._compute_hash(
            {k: v for k, v in payload.items() if k != "_hash"}
        )

        latest = self._latest_path()
        backup = self._backup_path()
        timestamped = self._timestamped_path(ts)

        try:
            # Write to a temporary file then rename for atomicity.
            tmp = latest + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            os.replace(tmp, latest)

            # Maintain a backup copy.
            shutil.copy2(latest, backup)

            # Keep a timestamped snapshot for history.
            shutil.copy2(latest, timestamped)

            logger.debug(
                "Checkpoint saved: frame=%d session=%s", last_frame_id, self.session_id
            )
            self.cleanup_old_checkpoints()
            return True
        except Exception as exc:
            logger.error("save_checkpoint failed: %s", exc)
            return False

    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Load the most recent valid checkpoint for *session_id*.

        Tries the *latest* file first, then the *backup* copy.  Returns
        ``None`` if no valid checkpoint is found.
        """
        for path in (self._latest_path(), self._backup_path()):
            if os.path.exists(path):
                data = self._load_and_verify(path)
                if data is not None:
                    logger.info("Checkpoint loaded from %s", path)
                    return data
                logger.warning("Checkpoint at %s failed integrity check", path)
        return None

    def verify_checkpoint_integrity(self, path: Optional[str] = None) -> bool:
        """Return ``True`` if the checkpoint file at *path* is intact.

        If *path* is ``None`` the *latest* checkpoint for the current session
        is checked.
        """
        target = path or self._latest_path()
        return self._load_and_verify(target) is not None

    def _load_and_verify(self, path: str) -> Optional[Dict[str, Any]]:
        """Load *path* and verify its integrity hash.

        Returns the checkpoint dict on success, ``None`` on any failure.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
        except Exception as exc:
            logger.debug("Cannot read checkpoint %s: %s", path, exc)
            return None

        stored_hash = data.pop("_hash", None)
        if stored_hash is None:
            logger.debug("Checkpoint %s missing integrity hash", path)
            return None

        expected = self._compute_hash(data)
        if stored_hash != expected:
            logger.warning(
                "Checkpoint integrity mismatch in %s (expected %s, got %s)",
                path, expected, stored_hash,
            )
            return None

        # Restore hash field so callers receive the full object.
        data["_hash"] = stored_hash
        return data

    def _is_timestamped_checkpoint(self, filename: str, excluded: set) -> bool:
        """Return True if *filename* is a timestamped checkpoint for this session."""
        prefix = f"checkpoint_{self.session_id}_"
        return (
            filename.startswith(prefix)
            and filename.endswith(".json")
            and filename not in excluded
        )

    def cleanup_old_checkpoints(self) -> int:
        """Delete timestamped checkpoint files beyond *max_checkpoints*.

        Only files matching the ``checkpoint_{session_id}_*.json`` pattern
        (excluding *latest* and *backup*) are considered.

        Returns
        -------
        int
            Number of files deleted.
        """
        excluded = {
            os.path.basename(self._latest_path()),
            os.path.basename(self._backup_path()),
        }
        candidates: List[str] = []
        try:
            for name in os.listdir(self.checkpoint_dir):
                if self._is_timestamped_checkpoint(name, excluded):
                    candidates.append(os.path.join(self.checkpoint_dir, name))
        except OSError as exc:
            logger.warning("cleanup_old_checkpoints: cannot list dir: %s", exc)
            return 0

        candidates.sort(key=lambda p: os.path.getmtime(p))
        to_delete = candidates[: max(0, len(candidates) - self.max_checkpoints)]
        deleted = 0
        for path in to_delete:
            try:
                os.unlink(path)
                deleted += 1
                logger.debug("Deleted old checkpoint: %s", path)
            except OSError as exc:
                logger.warning("Could not delete checkpoint %s: %s", path, exc)
        return deleted

    def maybe_checkpoint(
        self,
        last_frame_id: int,
        queue_state: Optional[List[Any]] = None,
        db_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Save a checkpoint if *frames_per_checkpoint* frames have elapsed.

        Call this once per processed frame.  Returns ``True`` if a checkpoint
        was actually written.
        """
        self._frame_counter += 1
        if self._frame_counter % self.frames_per_checkpoint == 0:
            return self.save_checkpoint(last_frame_id, queue_state, db_state)
        return False

    def list_checkpoints(self) -> List[str]:
        """Return paths of all checkpoint files for this session, newest first."""
        prefix = f"checkpoint_{self.session_id}_"
        paths: List[str] = []
        try:
            for name in os.listdir(self.checkpoint_dir):
                if name.startswith(prefix) and name.endswith(".json"):
                    paths.append(os.path.join(self.checkpoint_dir, name))
        except OSError:
            pass
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return paths
