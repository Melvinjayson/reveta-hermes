"""Reveta skill boundary smoke tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/productivity/reveta-ecosystem/SKILL.md"


def test_skill_declares_ownership_and_limits():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    for section in ("When to Use", "Prerequisites", "How to Run", "Quick Reference", "Procedure", "Pitfalls", "Verification"):
        assert f"## {section}" in text
    assert "not install an execution guard" in text
    assert "founder" in text.lower()
