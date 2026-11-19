"""Evidence sinks. ``EvidenceSink`` is the seam a remote store can implement later; the only
shipped sink appends one JSON line per record to a per-day file under the plugin data dir."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol

from .evidence import PLUGIN_NAME


class EvidenceSink(Protocol):
    def write(self, record: dict) -> None:
        """Persist one record or raise; callers buffer on failure."""


class JsonlDailySink:
    """``<hermes home>/plugin-data/venus-evidence/evidence-YYYY-MM-DD.jsonl`` (UTC day).

    The directory is resolved on every write so the active profile's home is used."""

    def __init__(self, root: Optional[Callable[[], Path]] = None):
        self._root = root or _default_root
        self._lock = threading.Lock()

    def path_for(self, day: Optional[datetime] = None) -> Path:
        day = day or datetime.now(timezone.utc)
        return self._root() / f"evidence-{day:%Y-%m-%d}.jsonl"

    def write(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock, self.path_for().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _default_root() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir(PLUGIN_NAME)
