from research_agent.graph import (
    MAX_SYNTHESIZE_ATTEMPTS,
    VERIFY_SUPPORT_THRESHOLD,
    _after_verify,
)


def test_after_verify_retries_on_low_support_first_attempt():
    state = {"verify_support_rate": 0.4, "synthesize_attempts": 1}
    assert _after_verify(state) == "synthesize"


def test_after_verify_stops_when_attempts_exhausted():
    state = {"verify_support_rate": 0.0, "synthesize_attempts": MAX_SYNTHESIZE_ATTEMPTS}
    assert _after_verify(state) == "END"


def test_after_verify_finishes_when_supported():
    state = {"verify_support_rate": 0.9, "synthesize_attempts": 1}
    assert _after_verify(state) == "END"


def test_after_verify_threshold_inclusive():
    """Exactly at threshold counts as supported (>= threshold)."""
    state = {
        "verify_support_rate": VERIFY_SUPPORT_THRESHOLD,
        "synthesize_attempts": 1,
    }
    assert _after_verify(state) == "END"


def test_after_verify_default_state_finishes():
    """Empty state (no verifier yet) shouldn't loop forever."""
    assert _after_verify({}) == "END"
