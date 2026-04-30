import json
from pathlib import Path

from research_agent.eval.regression import compare


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_no_regression_when_metrics_match(tmp_path):
    base = _write(tmp_path, "base.json", {"avg_support_rate": 0.8, "avg_recall": 0.6})
    latest = _write(tmp_path, "latest.json", {"avg_support_rate": 0.8, "avg_recall": 0.6})
    ok, _ = compare(base, latest)
    assert ok


def test_no_regression_within_tolerance(tmp_path):
    base = _write(tmp_path, "base.json", {"avg_support_rate": 0.80, "avg_recall": 0.60})
    latest = _write(tmp_path, "latest.json", {"avg_support_rate": 0.77, "avg_recall": 0.58})
    ok, lines = compare(base, latest)
    assert ok, "3pp / 2pp drops are within the 5pp tolerance"
    assert any("support rate" in line.lower() for line in lines)


def test_regression_when_support_drops_more_than_tolerance(tmp_path):
    base = _write(tmp_path, "base.json", {"avg_support_rate": 0.90, "avg_recall": 0.60})
    latest = _write(tmp_path, "latest.json", {"avg_support_rate": 0.70, "avg_recall": 0.60})
    ok, _ = compare(base, latest)
    assert not ok


def test_regression_when_recall_drops(tmp_path):
    base = _write(tmp_path, "base.json", {"avg_support_rate": 0.80, "avg_recall": 0.70})
    latest = _write(tmp_path, "latest.json", {"avg_support_rate": 0.80, "avg_recall": 0.50})
    ok, _ = compare(base, latest)
    assert not ok


def test_no_baseline_recall_passes(tmp_path):
    base = _write(tmp_path, "base.json", {"avg_support_rate": 0.80, "avg_recall": None})
    latest = _write(tmp_path, "latest.json", {"avg_support_rate": 0.80, "avg_recall": 0.60})
    ok, _ = compare(base, latest)
    assert ok


def test_improvement_is_not_a_regression(tmp_path):
    base = _write(tmp_path, "base.json", {"avg_support_rate": 0.50, "avg_recall": 0.30})
    latest = _write(tmp_path, "latest.json", {"avg_support_rate": 0.95, "avg_recall": 0.80})
    ok, lines = compare(base, latest)
    assert ok
    assert any("+" in line for line in lines)
