"""Render adapter static safety checks (not a full Docker integration test)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "docker" / "entrypoint-dispatch.sh"
BOOT = ROOT / "docker" / "render-preview-boot.sh"


def test_shell_syntax():
    for script in (ENTRYPOINT, BOOT):
        subprocess.run(["sh", "-n", str(script)], check=True, timeout=5)


def test_render_preview_is_explicit_opt_in():
    text = ENTRYPOINT.read_text()
    assert 'if [ "${REVETA_RENDER_PREVIEW_BOOT:-}" = "1" ]; then' in text
    assert "exec /init /opt/hermes/docker/main-wrapper.sh" in text


def test_render_preview_never_disables_dashboard_auth():
    text = BOOT.read_text()
    for key in (
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME",
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH",
        "HERMES_DASHBOARD_BASIC_AUTH_SECRET",
    ):
        assert "${" + key + ":?" in text
    assert "exec /command/s6-setuidgid hermes" in text
    assert "--host 0.0.0.0" in text
    assert "--skip-build" in text
    assert "HERMES_DASHBOARD_INSECURE" not in text
