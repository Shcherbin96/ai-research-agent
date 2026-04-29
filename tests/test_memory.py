from research_agent.memory import is_enabled, recall, reset_for_tests, store_brief
from research_agent.models import Brief


def _clear(monkeypatch):
    for k in ("MEM0_API_KEY", "MEM0_USER_ID"):
        monkeypatch.delenv(k, raising=False)


def test_disabled_without_key(monkeypatch):
    _clear(monkeypatch)
    reset_for_tests()
    assert is_enabled() is False


def test_recall_returns_empty_when_disabled(monkeypatch):
    _clear(monkeypatch)
    reset_for_tests()
    assert recall("agent memory") == []


def test_store_brief_is_safe_when_disabled(monkeypatch):
    _clear(monkeypatch)
    reset_for_tests()
    brief = Brief(query="x", executive_summary="y")
    # Should not raise even though Mem0 is disabled.
    store_brief("x", brief)


def test_enabled_with_key(monkeypatch):
    monkeypatch.setenv("MEM0_API_KEY", "m0-fake")
    reset_for_tests()
    assert is_enabled() is True
    monkeypatch.delenv("MEM0_API_KEY")
    reset_for_tests()
