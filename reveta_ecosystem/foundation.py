"""Read-only, provenance-aware Reveta registry and approval advisory.

The public Hermes derivative contains no proprietary Reveta OS document bodies.
Only explicitly listed repositories are queried; no general URL fetching,
memory ingestion, migrations, telemetry uploads or write operations exist.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MAX_REGISTRY_BYTES = 64 * 1024
MAX_SYSTEMS = 16
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
ALLOWED_STATUS = frozenset({"unknown", "discovery", "paused", "active", "archived"})
READ_ONLY = frozenset({"inspect", "summarise", "research", "review", "draft"})
REQUIRES_APPROVAL = frozenset({
    "merge", "deploy", "publish", "send", "purchase", "delete", "migrate",
    "change_access", "change_permissions", "create_cloud_resource", "run_external_action",
})


def action_posture(action: str) -> dict[str, str]:
    """Advice only. The action executor must independently enforce authority."""
    if action in READ_ONLY:
        return {"action": action, "posture": "read_only", "authority": "none_granted"}
    if action in REQUIRES_APPROVAL:
        return {
            "action": action, "posture": "founder_approval_required",
            "authority": "none_granted",
        }
    return {"action": action, "posture": "unclassified_hold", "authority": "none_granted"}


def _valid_system(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    system_id, name, repo = item.get("id"), item.get("name"), item.get("repository")
    status = item.get("portfolio_status", "unknown")
    if (not isinstance(system_id, str) or not SAFE_ID_RE.fullmatch(system_id)
        or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
        or not isinstance(repo, str) or not REPO_RE.fullmatch(repo)
        or status not in ALLOWED_STATUS):
        return None
    return {
        "id": system_id, "name": name.strip(), "repository": repo,
        "portfolio_status": status,
    }


def _registry_path() -> Path:
    # Explicit machine-local configuration, not the public source checkout.
    root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).resolve()
    return root / "reveta" / "registry.json"


def read_registry() -> tuple[list[dict[str, str]], str]:
    """Load an operator-curated metadata allowlist; fail closed on bad input."""
    raw_env = os.environ.get("REVETA_REGISTRY_JSON", "")
    try:
        if raw_env:
            if len(raw_env.encode("utf-8")) > MAX_REGISTRY_BYTES:
                return [], "invalid_registry"
            data = json.loads(raw_env)
        else:
            path = _registry_path()
            if path.is_symlink() or not path.is_file():
                return [], "not_configured"
            if path.stat().st_size > MAX_REGISTRY_BYTES:
                return [], "invalid_registry"
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return [], "invalid_registry" if raw_env else "not_configured"
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return [], "invalid_registry"
    raw = data.get("systems")
    if not isinstance(raw, list) or len(raw) > MAX_SYSTEMS:
        return [], "invalid_registry"
    results, seen = [], set()
    for candidate in raw:
        item = _valid_system(candidate)
        if item is None or item["id"] in seen:
            return [], "invalid_registry"
        seen.add(item["id"])
        results.append(item)
    return results, "configured"


def _github_revision(repo: str) -> dict[str, Any]:
    """One bounded metadata GET to GitHub. No arbitrary URLs or contents."""
    url = f"https://api.github.com/repos/{repo}/commits?per_page=1"
    token = os.environ.get("REVETA_GITHUB_READ_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "reveta-hermes-readonly/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            # Refuse oversized or unexpected payloads; never return raw response.
            data = json.loads(response.read(16 * 1024))
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return {"connection": "unknown", "revision": None, "checked_at": None}
        sha = data[0].get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            return {"connection": "unknown", "revision": None, "checked_at": None}
        return {
            "connection": "observed", "revision": sha,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return {"connection": "unknown", "revision": None, "checked_at": None}


_cache: tuple[float, dict[str, Any]] | None = None


def overview(*, refresh: bool = False) -> dict[str, Any]:
    """Advisory registry with evidence-grounded code revision, not health claims."""
    global _cache
    now = time.monotonic()
    if not refresh and _cache is not None and now - _cache[0] < 60:
        return _cache[1]
    entries, status = read_registry()
    rows = []
    for entry in entries:
        # Repository reachability is not proof of running service or passed CI.
        rows.append({
            **entry,
            **_github_revision(entry["repository"]),
            "deployment": "unknown",
            "governance_gate": "not_evaluated",
        })
    result = {
        "schema_version": 1, "mode": "read_only",
        "registry_state": status, "source_of_truth": "Reveta OS and owner systems",
        "brain": {
            "state": "not_connected",
            "authority": "advisory_only",
            "hosted_ingestion": False,
            "automatic_writeback": False,
        },
        "systems": rows,
        "action_policy": {
            "default": "hold",
            "production": "founder_approval_required",
            "external_actions": "founder_approval_required",
        },
        "limitations": [
            "A GitHub commit check does not verify CI, releases or runtime health.",
            "Portfolio status is manually curated and must be checked against Reveta OS.",
            "No hosted Aura Brain or GBrain has been connected.",
            "No enforcement hook is installed on Hermes' tool executor.",
        ],
    }
    _cache = (now, result)
    return result
