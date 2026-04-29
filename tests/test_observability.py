from research_agent.observability import (
    is_enabled,
    observe,
    reset_for_tests,
)


def _clear_keys(monkeypatch):
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(k, raising=False)


def test_observe_is_noop_when_keys_absent(monkeypatch):
    _clear_keys(monkeypatch)
    reset_for_tests()
    assert is_enabled() is False

    calls: list[int] = []

    @observe(name="x")
    def fn(n: int) -> int:
        calls.append(n)
        return n + 1

    assert fn(3) == 4
    assert calls == [3]


def test_is_enabled_with_both_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-fake")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-fake")
    reset_for_tests()
    assert is_enabled() is True

    # Reset so we don't pollute other tests.
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY")
    reset_for_tests()


def test_one_key_alone_does_not_enable(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-only")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    reset_for_tests()
    assert is_enabled() is False
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY")
    reset_for_tests()
