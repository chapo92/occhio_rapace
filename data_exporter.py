"""
Occhi di Falco - Data Exporter Module
Saves structured poker hand data to JSON files in real-time.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DataExporter:
    """
    Exports poker hand data to JSON files.

    Each call to :meth:`export` writes or updates a session file
    ``<output_dir>/<prefix>_<date>.json`` that holds a list of hand
    snapshots for the current session.

    Parameters
    ----------
    output_dir : str
        Directory where JSON output files are written.
    file_prefix : str
        Prefix for output filenames.
    pretty : bool
        If True, write indented (human-readable) JSON.
    """

    def __init__(
        self,
        output_dir: str = "output",
        file_prefix: str = "hand_data",
        pretty: bool = True,
    ):
        self.output_dir = output_dir
        self.file_prefix = file_prefix
        self.pretty = pretty
        self._session_data: List[Dict[str, Any]] = []
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info("DataExporter ready – output dir: %s", self.output_dir)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def export(self, hand_data: Dict[str, Any]) -> str:
        """
        Append *hand_data* to the in-memory buffer and persist to disk.

        Parameters
        ----------
        hand_data : dict
            Structured hand snapshot (output of :class:`PokerParser`).

        Returns
        -------
        str
            Absolute path to the JSON file written.
        """
        self._session_data.append(hand_data)
        path = self._session_filepath()
        self._write_json(path, self._session_data)
        logger.debug("Exported snapshot to %s (%d entries)", path, len(self._session_data))
        return path

    def export_single(self, hand_data: Dict[str, Any]) -> str:
        """
        Write a single hand snapshot to its own timestamped JSON file.

        Parameters
        ----------
        hand_data : dict

        Returns
        -------
        str
            Absolute path to the written file.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        filename = f"{self.file_prefix}_{ts}.json"
        path = os.path.join(self.output_dir, filename)
        self._write_json(path, hand_data)
        logger.debug("Single export → %s", path)
        return path

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """
        Return the most recently exported hand snapshot, or None.
        """
        if not self._session_data:
            return None
        return self._session_data[-1]

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Return all hand snapshots captured in this session.
        """
        return list(self._session_data)

    def clear_session(self) -> None:
        """
        Clear the in-memory session buffer (does not delete files).
        """
        self._session_data.clear()
        logger.info("Session buffer cleared")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session_filepath(self) -> str:
        """Build today's session file path."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"{self.file_prefix}_{date_str}.json"
        return os.path.join(self.output_dir, filename)

    def _write_json(self, path: str, data: Any) -> None:
        """Write *data* to *path* as JSON, handling errors gracefully."""
        try:
            indent = 2 if self.pretty else None
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=indent, ensure_ascii=False, default=str)
        except OSError as exc:
            logger.error("Failed to write JSON to %s: %s", path, exc)
