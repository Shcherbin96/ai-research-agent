import asyncio

from research_agent.adapters import google_scholar
from research_agent.adapters.google_scholar import _parse_year


def _clear(monkeypatch):
    for k in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"):
        monkeypatch.delenv(k, raising=False)


def test_disabled_without_keys(monkeypatch):
    _clear(monkeypatch)
    assert google_scholar.is_enabled() is False


def test_enabled_with_both_keys(monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb-fake")
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", "proj-fake")
    assert google_scholar.is_enabled() is True


def test_one_key_alone_does_not_enable(monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb-only")
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    assert google_scholar.is_enabled() is False


def test_search_returns_empty_when_disabled(monkeypatch):
    _clear(monkeypatch)
    out = asyncio.run(google_scholar.search("agent memory", limit=5))
    assert out == []


def test_parse_year_extracts_first_match():
    assert _parse_year("Smith, J — 2023 — arxiv.org") == 2023
    assert _parse_year("no year here") is None
    assert _parse_year("M. Doe, 1999, J. Mach. Learn.") == 1999
