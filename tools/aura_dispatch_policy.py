"""Aura dispatch approval policy. This is not OS-level containment.

Every dispatch uses this gate, including profiles and helper processes. There is
no mode, YOLO or missing-configuration bypass. No provider routing or price
classification is implemented here.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from hermes_constants import get_hermes_home

APPROVAL_TTL = 120
_READ = frozenset(
    {
        "read_file",
        "search_files",
        "list_files",
        "skills_list",
        "skill_view",
        "session_search",
        "session_search_recall",
        "web_extract",
        "tool_search",
        "tool_describe",
    }
)
_INTERNAL = frozenset({"todo", "todo_list"})


def _config():
    from hermes_cli.config_backend import read_config_doc_readonly

    home = get_hermes_home()
    try:
        config = read_config_doc_readonly(home / "config.yaml") or {}
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("Invalid configuration")
    return config


def _classification(name, args, config):
    if name in _READ:
        return "read"
    if name in _INTERNAL:
        return "internal"
    # File mutations also ask: profile-level local settings do not attest a
    # session's actual backend, nor all targets within a multi-file patch.
    # No shell allowlist: aliases, startup files and interpreters make even
    # apparently read-only shell text unprovable without OS isolation.
    return "consequential"


def _refused(reason):
    return json.dumps({"error": reason, "status": "refused", "aura_policy": True})


def _canonical(args):
    return json.dumps(
        args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _approve(name, snapshot, digest):
    from agent.redact import redact_sensitive_text
    from tools import approval, approval_context
    from tools.approval_gateway_wait import _await_gateway_decision

    if approval_context._no_user_can_answer():
        return False
    key = approval_context.get_current_session_key(default="")
    if not key:
        return False
    notify = approval._gateway_notify_cb(key)
    if notify is None:
        return False  # never use delegation auto-approval or a model callback
    expires = time.monotonic() + APPROVAL_TTL
    nonce = uuid.uuid4().hex
    decision = _await_gateway_decision(
        key,
        notify,
        {
            "command": redact_sensitive_text(
                f"{name} {_canonical(snapshot)}", force=True
            ),
            "description": "One exact action. Cost is not verified. Change refuses execution.",
            "pattern_key": f"aura:{digest}:{nonce}",
            "pattern_keys": [f"aura:{digest}:{nonce}"],
            "allow_permanent": False,
            "choices": ["once", "deny"],
            "single_use": True,
            "action_hash": digest,
            "expires_at_monotonic": expires,
        },
    )
    return (
        decision.get("choice") == "once"
        and decision.get("resolved")
        and time.monotonic() < expires
    )


def guarded_call(name, args, execute):
    """Authorize the final argument snapshot and execute it once; no reusable grant.

    Called at concrete dispatch boundaries, after middleware. Any policy, config,
    parsing or approval exception refuses before the handler is invoked.
    """
    try:
        config = _config()
        home = str(get_hermes_home().resolve())
        canonical = _canonical(args)
        if len(canonical.encode("utf-8")) > 16384:
            return _refused(
                "Action arguments are too large to approve. Reduce the action and try again."
            )
        snapshot = json.loads(canonical)
        classification = _classification(name, snapshot, config)
        if classification == "consequential":
            digest = hashlib.sha256(
                (home + "\0" + name + "\0" + canonical).encode()
            ).hexdigest()
            if not _approve(name, snapshot, digest):
                return _refused(
                    "This action did not receive a valid single-use approval, so it did not run."
                )
            if (
                _canonical(args) != canonical
                or str(get_hermes_home().resolve()) != home
            ):
                return _refused(
                    "The action changed after approval. Ask again for the changed action."
                )
    except Exception:
        return _refused(
            "The safety check could not complete, so the action did not run."
        )
    return execute(snapshot)


def guard_executor(name, execute):
    return lambda args: guarded_call(name, args, execute)
