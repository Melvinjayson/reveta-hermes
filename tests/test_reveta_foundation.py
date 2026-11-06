"""Pure boundary tests; no network or secret-bearing service is required."""
import json

from reveta_ecosystem import foundation


def test_no_registry_is_unconnected(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    foundation._cache = None
    result = foundation.overview()
    assert result["registry_state"] == "not_configured"
    assert result["systems"] == []
    assert result["brain"]["state"] == "not_connected"


def test_invalid_registry_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    d = tmp_path / "reveta"
    d.mkdir()
    (d / "registry.json").write_text(json.dumps({
        "schema_version": 1,
        "systems": [{"id": "test", "name": "Test", "repository": "bad/url/extra"}],
    }))
    assert foundation.read_registry() == ([], "invalid_registry")


def test_allowlisted_metadata_only(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    d = tmp_path / "reveta"
    d.mkdir()
    (d / "registry.json").write_text(json.dumps({
        "schema_version": 1,
        "systems": [{"id": "aura", "name": "Aura", "repository": "owner/aura", "portfolio_status": "unknown"}],
    }))
    monkeypatch.setattr(foundation, "_github_revision", lambda repo: {
        "connection": "unknown", "revision": None, "checked_at": None,
    })
    foundation._cache = None
    data = foundation.overview()
    assert data["systems"][0]["deployment"] == "unknown"
    assert "token" not in json.dumps(data).lower()


def test_governance_fail_closed():
    assert foundation.action_posture("research")["posture"] == "read_only"
    assert foundation.action_posture("deploy")["posture"] == "founder_approval_required"
    assert foundation.action_posture("new_unknown_action")["posture"] == "unclassified_hold"
    assert all(foundation.action_posture(x)["authority"] == "none_granted"
               for x in ("research", "deploy", "new_unknown_action"))
