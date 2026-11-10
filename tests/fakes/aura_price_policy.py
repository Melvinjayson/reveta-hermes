"""Explicit zero-cost attestations for synthetic fixtures only; not runtime pricing."""

import hashlib
import json
from pathlib import Path
from threading import Lock
import uuid

from ruamel.yaml import YAML

_lock = Lock()


def attest_tool(home: Path, name: str, args: dict):
    with _lock:
        yaml = YAML()
        config = (
            yaml.load((home / "config.yaml").read_text())
            if (home / "config.yaml").exists()
            else {}
        )
        aura = config.setdefault("aura", {})
        digest = hashlib.sha256(
            json.dumps(
                args,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        entries = aura.setdefault("free_tools", [])
        if not any(
            entry.get("name") == name and entry.get("arguments_sha256") == digest
            for entry in entries
        ):
            entries.append(
                {
                    "name": name,
                    "arguments_sha256": digest,
                    "confirmed_free": True,
                    "cost_usd": 0,
                    "evidence": "synthetic fixture only",
                }
            )
        staged = home / f"config-{uuid.uuid4().hex}.tmp"
        with staged.open("w") as output:
            yaml.dump(config, output)
        staged.replace(home / "config.yaml")
