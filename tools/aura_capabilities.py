"""Hermes capabilities the Aura owner can switch on for new conversations.

Aura's base surface is its own adapters plus ``todo`` (scripts/reveta/aura_config.py).
Each entry below is an existing Hermes toolset. Enabling one writes it into
``platform_toolsets`` for the surfaces Aura serves; an agent snapshots its toolsets
when a conversation starts, so a change applies to the NEXT conversation and never
rewrites a running conversation's cached prompt prefix.

Nothing here touches approvals: every tool outside the dispatch policy's read list
still needs a single-use manual approval (tools/aura_dispatch_policy.py).
"""

from __future__ import annotations

from typing import Iterable

# Surfaces whose toolsets Aura's generated config owns.
AURA_PLATFORMS = ("cli", "api_server")
BASE_TOOLSETS = ("aura", "todo")

# toolset -> (label, what it does for the user). Order is display order.
CAPABILITIES: dict[str, tuple[str, str]] = {
    "session_search": ("Search past chats", "Aura can look up what you discussed in earlier conversations."),
    "memory": ("Memory", "Aura keeps short notes about you and your work across conversations."),
    "skills": ("Skills", "Aura can read and follow its skill guides, and draft new ones with your approval."),
    "clarify": ("Clarifying questions", "Aura can ask you a multiple-choice question before acting."),
    "browser": ("Full browser", "Aura can click, type and fill forms in a real browser. Every action asks first. "
                "Needs Commands and background tasks on, because it runs code on the server."),
    "file": ("Workspace files", "Aura can read, write and edit files in its workspace."),
    "code_execution": ("Run code", "Aura can run short Python scripts for calculations and data work."),
    "terminal": ("Commands and background tasks", "Aura can run shell commands and long background processes."),
    "delegation": ("Subagents", "Aura can hand a subtask to a helper agent with its own context."),
    "cronjob": ("Scheduled jobs", "Aura can create jobs that run on a schedule."),
    "vision": ("Image understanding", "Aura can look at images you attach, if the model supports it."),
    "web": ("Web search", "Aura can search the web and read result pages."),
    "image_gen": ("Image generation", "Aura can create images."),
}

# Preset bundles for the composer's mode picker. "Focused" is Aura's base surface.
MODES: dict[str, tuple[str, ...]] = {
    "Focused": (),
    "Research": ("session_search", "memory", "clarify", "web"),
    "Agent": tuple(CAPABILITIES),
}

# Hermes offers browser_exec only alongside the terminal surface (model_tools._rewrite_browser_exec):
# it runs host Python. Switching the browser on without commands would show a switch that does nothing.
REQUIRES = {"browser": "terminal"}

# Toolsets whose tools the model may be offered inside Aura once their toolset is on.
UNLOCKABLE = frozenset(CAPABILITIES)


def _availability() -> dict[str, dict]:
    """Per-toolset readiness from the tool registry's own checks (a missing key reads as unavailable)."""
    import model_tools  # imports register every built-in tool
    from tools.registry import registry

    requirements = registry.get_toolset_requirements()
    result = {}
    for name in CAPABILITIES:
        info = requirements.get(name) or {}
        env = [str(item) for item in info.get("env_vars") or [] if isinstance(item, str)]
        result[name] = {"available": registry.is_toolset_available(name), "requires_env": env}
    return result


def _enabled(config: dict) -> set[str]:
    platform = (config.get("platform_toolsets") or {}).get("cli") or []
    return {str(name) for name in platform if str(name) in UNLOCKABLE} if isinstance(platform, list) else set()


def _mode_of(enabled: set[str], available: set[str]) -> str | None:
    for mode, toolsets in MODES.items():
        if enabled == set(toolsets) & available:
            return mode
    return None


def status() -> dict:
    from hermes_cli.config import load_config

    config = load_config()
    enabled = _enabled(config)
    ready = _availability()
    available = {name for name, info in ready.items() if info["available"]}
    return {
        "applies_to": "new conversations",
        "mode": _mode_of(enabled, available),
        "modes": {mode: [name for name in toolsets if name in available] for mode, toolsets in MODES.items()},
        "capabilities": [
            {"id": name, "label": label, "description": description, "enabled": name in enabled,
             "available": ready[name]["available"],
             # A capability without its key stays switched off; the owner adds the key outside the chat.
             "blocked": None if ready[name]["available"] else "Needs a service key or package that is not set up.",
             "requires_env": ready[name]["requires_env"], "requires": REQUIRES.get(name)}
            for name, (label, description) in CAPABILITIES.items()
        ],
    }


def configure(enabled: Iterable[str]) -> dict:
    """Replace the unlocked set; unknown or unavailable toolsets are refused, MCP entries are kept."""
    from hermes_cli.config import load_config, save_config

    wanted = [str(name) for name in enabled]
    unknown = sorted(set(wanted) - UNLOCKABLE)
    if unknown:
        raise ValueError(f"Unknown capability: {', '.join(unknown)}")
    ready = _availability()
    blocked = sorted(name for name in set(wanted) if not ready[name]["available"])
    if blocked:
        raise ValueError(f"Not available until it is set up: {', '.join(blocked)}")
    for name, needed in REQUIRES.items():
        if name in wanted and needed not in wanted:
            raise ValueError(f"{CAPABILITIES[name][0]} needs {CAPABILITIES[needed][0]} switched on too.")
    config = load_config()
    toolsets = config.setdefault("platform_toolsets", {})
    for platform in AURA_PLATFORMS:
        current = toolsets.get(platform) if isinstance(toolsets.get(platform), list) else []
        # Anything that is neither base nor unlockable (MCP server names such as composio) is preserved.
        kept = [name for name in current if name not in UNLOCKABLE and name not in BASE_TOOLSETS]
        toolsets[platform] = [*BASE_TOOLSETS, *[name for name in CAPABILITIES if name in wanted], *kept]
    save_config(config)
    return status()


def set_mode(mode: str) -> dict:
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    ready = _availability()
    return configure(name for name in MODES[mode] if ready[name]["available"])


def unlockable_tools() -> frozenset[str]:
    """Tool names inside the unlockable toolsets, resolved as ``platform_toolsets`` resolves them."""
    from toolsets import resolve_toolset

    return frozenset(tool for name in CAPABILITIES for tool in resolve_toolset(name))
