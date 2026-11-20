"""The Aura owner and the owner's preview switches.

Aura on Render has one sign-in: the dashboard's basic-auth account. That account is the owner.
``AURA_COMPANION_ADMINS`` (Hermes user id or email, comma separated) adds admins where the
deployment sets it; testers (``AURA_COMPANION_TESTERS``) are never owners.

Preview switches live in ``config.yaml`` so the owner can flip them in Settings without a deploy
environment edit, and ``scripts/reveta/aura_config.py`` keeps them across boots:

* ``aura.companion.enabled``: the browser companion for the owner only. Without
  ``AURA_COMPANION_SECRET`` the key-signing secret is generated once and kept in ``HERMES_HOME``.
* ``aura.companion.handoff``: chat-to-browser handoff (``aura_companion_handoff.py``).
* ``plugins.enabled`` containing ``venus-evidence``: the run-evidence plugin, through the same
  enable path as the dashboard's plugin page.

Shortcut: on a host whose disk is wiped (Render free spins down after 15 idle minutes), the
switches and the generated secret go with the disk; the owner switches them on again.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

VENUS_PLUGIN = "venus-evidence"
_SECRET_FILE = "aura-companion.secret"


def _names(var: str) -> set[str]:
    return {v.strip().lower() for v in os.environ.get(var, "").split(",") if v.strip()}


def _basic_auth_username() -> str:
    from plugins.dashboard_auth._shared import resolve_env_or_cfg
    from plugins.dashboard_auth.basic import _load_config_basic_auth_section

    return str(resolve_env_or_cfg("HERMES_DASHBOARD_BASIC_AUTH_USERNAME",
                                  _load_config_basic_auth_section().get("username", "")) or "").strip()


def is_owner(user_id: str, email: str = "") -> bool:
    """The basic-auth account or a listed admin. Testers and every other identity: False."""
    who = {str(user_id or "").strip().lower(), str(email or "").strip().lower()} - {""}
    if not who:
        return False
    if who & _names("AURA_COMPANION_ADMINS"):
        return True
    owner = _basic_auth_username().lower()
    return bool(owner) and owner in who


def caller_is_owner(auth_required: bool, user_id: str = "", email: str = "") -> bool:
    """Owner check for a caller that already passed the sign-in gate. Without the gate (the local
    loopback desktop) the only caller is the machine's owner."""
    return not auth_required or is_owner(user_id, email)


def _companion() -> dict:
    from hermes_cli.config import load_config_readonly

    aura = load_config_readonly().get("aura")
    companion = aura.get("companion") if isinstance(aura, dict) else None
    return companion if isinstance(companion, dict) else {}


def companion_switched_on() -> bool:
    """Only the literal ``true`` switches it on."""
    return _companion().get("enabled") is True


def generated_secret(home: Optional[Path] = None) -> str:
    """A key-signing secret made once per ``HERMES_HOME`` and readable only by this user."""
    from hermes_constants import get_hermes_home

    path = (home or get_hermes_home()) / _SECRET_FILE
    if not path.exists():
        value = secrets.token_urlsafe(48)
        tmp = path.with_name(f".{_SECRET_FILE}.{secrets.token_hex(8)}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
        try:
            # A hard link never replaces: two first requests racing agree on whichever landed first.
            os.link(tmp, path)
        except FileExistsError:
            pass
        finally:
            tmp.unlink()
    stored = path.read_text(encoding="utf-8-sig").strip()
    if len(stored) < 32:
        raise ValueError(f"{path} holds no usable companion secret; delete it to make a new one")
    return stored


def _plugin_enabled(name: str) -> bool:
    from hermes_cli.config import load_config_readonly

    plugins = load_config_readonly().get("plugins")
    if not isinstance(plugins, dict):
        return False
    enabled = plugins.get("enabled") if isinstance(plugins.get("enabled"), list) else []
    disabled = plugins.get("disabled") if isinstance(plugins.get("disabled"), list) else []
    return name in enabled and name not in disabled


def preview_status() -> dict:
    companion = _companion()
    return {"companion": companion.get("enabled") is True, "handoff": companion.get("handoff") is True,
            "venus_evidence": _plugin_enabled(VENUS_PLUGIN),
            "companion_secret_from_env": len(os.environ.get("AURA_COMPANION_SECRET", "").strip()) >= 32}


def set_preview(companion: Optional[bool] = None, handoff: Optional[bool] = None,
                venus_evidence: Optional[bool] = None) -> dict:
    """Owner-only switches; the caller checks :func:`is_owner`. ``None`` leaves a switch as it is."""
    from hermes_cli.config import load_config, save_config

    if companion is not None or handoff is not None:
        config = load_config()
        aura = dict(config.get("aura") or {})
        current = dict(aura.get("companion") or {}) if isinstance(aura.get("companion"), dict) else {}
        if companion is not None:
            current["enabled"] = bool(companion)
        if handoff is not None:
            current["handoff"] = bool(handoff)
        aura["companion"] = current
        config["aura"] = aura
        save_config(config)
    result = {}
    if venus_evidence is not None:
        result["restart_required"] = _switch_venus(bool(venus_evidence))
    return {**preview_status(), **result}


def _switch_venus(on: bool) -> bool:
    """Write the bundled evidence plugin into ``plugins.enabled`` and load it in this process.

    Like ``ensure_basic_auth_plugin_enabled_in_config`` this edits the list directly instead of the PM
    admission transaction: the plugin is bundled and has no dependencies, and admission republishes
    the dependency environment, which can mean a Python download on a 512 MB host. Returns whether a
    restart is needed (switching off: its hooks stay wired until the process restarts)."""
    from hermes_cli.config import load_config, save_config

    config = load_config()
    plugins = dict(config.get("plugins") or {}) if isinstance(config.get("plugins"), dict) else {}
    enabled = [n for n in (plugins.get("enabled") or []) if n != VENUS_PLUGIN]
    disabled = [n for n in (plugins.get("disabled") or []) if n != VENUS_PLUGIN]
    (enabled if on else disabled).append(VENUS_PLUGIN)
    was_on = _plugin_enabled(VENUS_PLUGIN)
    config["plugins"] = {**plugins, "enabled": enabled, "disabled": disabled}
    save_config(config)
    if on and not was_on:
        from hermes_cli.plugins_activation import activate_plugin_now

        activate_plugin_now(VENUS_PLUGIN)
    return was_on and not on
