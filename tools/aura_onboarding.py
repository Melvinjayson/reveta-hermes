"""First-run onboarding state for Aura, kept in the profile's ``HERMES_HOME`` (one per account).

``status`` also says whether this server keeps data across restarts, so the welcome never promises
durability the host does not give: storage counts as durable only when ``HERMES_HOME`` is a mounted
volume (a Render persistent disk, a Docker volume), not the container's own throwaway filesystem.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os

from hermes_constants import get_hermes_home

_FILE = "aura-onboarding.json"


def storage_durable() -> bool:
    home = get_hermes_home().resolve()
    return any(os.path.ismount(path) for path in (home, *home.parents) if path != path.parent)


def status() -> dict:
    try:
        saved = json.loads((get_hermes_home() / _FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        saved = {}
    completed_at = saved.get("completed_at") if isinstance(saved, dict) else None
    return {"completed": isinstance(completed_at, str), "completed_at": completed_at,
            "storage_durable": storage_durable()}


def complete() -> dict:
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / _FILE).write_text(json.dumps({"completed_at": datetime.now(UTC).isoformat(timespec="seconds")}),
                              encoding="utf-8")
    return status()
