"""Behavioural checks for the container entrypoint used by the Render Preview.

The Preview deliberately uses upstream Hermes' own dispatcher (no fork-specific
boot path). These tests execute the real script against stub targets so a
syntactically valid but broken condition — e.g. ``[ "$" -eq 1 ]`` instead of
``[ "$$" -eq 1 ]`` — fails CI instead of silently skipping s6 supervision.

Render note (verified 2026-11-06): a Render "Docker Command" REPLACES the
image ENTRYPOINT, so the Preview service must name the dispatcher explicitly:
  /opt/hermes/docker/entrypoint-dispatch.sh dashboard --host 0.0.0.0 --port 10000 --no-open --skip-build
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "docker" / "entrypoint-dispatch.sh"


def _stubbed_dispatch(tmp_path: Path) -> Path:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in {
        "stage2-hook.sh": 'echo "STAGE2"',
        "main-wrapper.sh": 'echo "MAIN-WRAPPER $*"',
        "init": 'echo "S6-INIT $*"',
    }.items():
        path = stubs / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    text = DISPATCH.read_text()
    text = text.replace("/opt/hermes/docker/", f"{stubs}/").replace("exec /init ", f"exec {stubs}/init ")
    script = tmp_path / "entrypoint-dispatch.sh"
    script.write_text(text)
    return script


def test_shell_syntax():
    subprocess.run(["sh", "-n", str(DISPATCH)], check=True, timeout=5)


def test_pid1_check_uses_the_shell_pid():
    assert 'if [ "$$" -eq 1 ]; then' in DISPATCH.read_text()


def test_wrapped_runtime_fallback_runs_bootstrap_then_dashboard(tmp_path):
    """Not PID 1 (e.g. a platform init wraps the container): stage2 bootstrap must still
    run, then the requested dashboard command, with no shell errors on stderr."""
    script = _stubbed_dispatch(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "REVETA_RENDER_PREVIEW_BOOT"}
    proc = subprocess.run(
        ["sh", str(script), "dashboard", "--host", "0.0.0.0", "--port", "10000"],
        capture_output=True, text=True, timeout=10, env=env, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        "STAGE2", "MAIN-WRAPPER dashboard --host 0.0.0.0 --port 10000",
    ]
    stderr = [line for line in proc.stderr.splitlines() if line.strip()]
    assert len(stderr) == 1 and stderr[0].startswith("[hermes] WARNING: container entrypoint is not PID 1")


def test_pid1_runs_s6_init(tmp_path):
    """As PID 1 the dispatcher must hand over to s6-overlay's /init (full supervision)."""
    unshare = shutil.which("unshare")
    if not unshare:
        pytest.skip("unshare not available")
    script = _stubbed_dispatch(tmp_path)
    probe = subprocess.run([unshare, "--user", "--map-root-user", "--pid", "--fork", "true"],
                           capture_output=True, timeout=10, check=False)
    if probe.returncode != 0:
        pytest.skip("unprivileged PID namespaces unavailable in this runner")
    proc = subprocess.run(
        [unshare, "--user", "--map-root-user", "--pid", "--fork", "sh", str(script), "dashboard"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("dashboard")
    assert proc.stdout.startswith("S6-INIT "), proc.stdout
    assert proc.stderr.strip() == ""


def test_no_fork_specific_boot_path_remains():
    """The Preview uses upstream's dispatcher; a bespoke boot script that skips stage2
    (config migration, skills sync, install-tree protection) must not come back silently."""
    assert "REVETA_RENDER_PREVIEW_BOOT" not in DISPATCH.read_text()
    assert not (ROOT / "docker" / "render-preview-boot.sh").exists()
