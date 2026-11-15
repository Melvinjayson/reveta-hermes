"""The Aura workspace that aura_config.py creates as root must be handed to hermes on boot.

Live phone test (Nov 14): every Aura tool failed with
``PermissionError: [Errno 13] Permission denied: '/opt/data/aura-workspace/<hash>'`` because the Render start
command runs ``scripts/reveta/aura_config.py --write`` as root, leaving ``aura-workspace`` root-owned for the
unprivileged runtime. This runs the hook's own repair functions and block (no image build needed) with
``chown``/``find`` shims standing in for a root-owned tree.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "docker" / "stage2-hook.sh"


def _hook_parts() -> tuple[str, str]:
    text = HOOK.read_text(encoding="utf-8")
    functions = re.search(r"^path_has_symlink_component\(\) \{.*?^tree_has_non_hermes_owner\(\) \{.*?^\}\n",
                          text, re.S | re.M)
    block = re.search(r'^if \[ -d "\$HERMES_HOME/aura-workspace" \].*?^fi\n', text, re.S | re.M)
    assert functions and block, "stage2 hook lost the aura-workspace ownership repair"
    return functions.group(0), block.group(0)


def _run(tmp_path: Path, home: Path) -> str:
    functions, block = _hook_parts()
    shims = tmp_path / "bin"
    shims.mkdir(exist_ok=True)
    log = tmp_path / "chown.log"
    log.unlink(missing_ok=True)
    (shims / "chown").write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    # Every path counts as root-owned, which is what the root-run aura_config.py leaves behind.
    (shims / "find").write_text('#!/bin/sh\n[ -e "$1" ] && echo "$1"\n')
    for shim in shims.iterdir():
        shim.chmod(0o755)
    script = f'HERMES_HOME="{home}"\n{functions}\n{block}'
    subprocess.run(["sh", "-c", script], check=True, env={**os.environ, "PATH": f"{shims}:{os.environ['PATH']}"})
    return log.read_text() if log.exists() else ""


def test_root_owned_aura_workspace_is_chowned_to_hermes(tmp_path):
    home = tmp_path / "data"
    (home / "aura-workspace" / "d1db6f028dd8504962ba61a6").mkdir(parents=True)
    assert _run(tmp_path, home).split() == ["-R", "hermes:hermes", str(home / "aura-workspace")]


def test_missing_or_symlinked_workspace_is_left_alone(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    assert _run(tmp_path, home) == ""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (home / "aura-workspace").symlink_to(outside)
    assert _run(tmp_path, home) == ""


def test_workspace_is_also_precreated_as_hermes():
    text = HOOK.read_text(encoding="utf-8")
    mkdir_block = text[text.index("as_hermes mkdir -p \\"):]
    mkdir_block = mkdir_block[: mkdir_block.index("\n\n")]
    assert '"$HERMES_HOME/aura-workspace"' in mkdir_block
