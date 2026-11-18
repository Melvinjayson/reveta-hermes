"""aura.clarify_without_approval: built switched OFF, so a clarifying question still needs approval.
Only an explicit boolean true from the owner changes that; nothing else does. Config fixtures only."""

import pytest

from tools.aura_dispatch_policy import _classification


@pytest.mark.parametrize("config", [
    {},
    {"aura": {}},
    {"aura": {"enabled": True}},
    {"aura": {"clarify_without_approval": False}},
    {"aura": {"clarify_without_approval": "true"}},
    {"aura": {"clarify_without_approval": 1}},
    {"aura": "not-a-mapping"},
])
def test_default_and_anything_but_true_still_require_approval(config):
    assert _classification("clarify", {}, config) == "consequential"


def test_owner_opt_in_lets_only_clarify_skip_approval():
    config = {"aura": {"clarify_without_approval": True}}
    assert _classification("clarify", {}, config) == "internal"
    for tool in ("memory", "terminal", "browser_exec", "send_message", "delegate_task"):
        assert _classification(tool, {}, config) == "consequential", tool
