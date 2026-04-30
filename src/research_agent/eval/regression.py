"""Regression detection for the eval CI workflow.

Compares the latest eval report against the committed baseline (``eval/baseline.json``)
and exits non-zero when a metric drops by more than the configured threshold.

Used by ``.github/workflows/eval.yml`` to block merges that regress agent quality.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Drop tolerance: a 5pp absolute drop in either metric fails CI.
SUPPORT_RATE_TOLERANCE = 0.05
RECALL_TOLERANCE = 0.05


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _diff(label: str, baseline: float | None, latest: float | None, tol: float) -> tuple[bool, str]:
    if baseline is None and latest is None:
        return True, f"{label}: not measured"
    if baseline is None:
        return True, f"{label}: no baseline (latest = {latest:.2%})"
    if latest is None:
        return False, f"{label}: missing in latest report (baseline = {baseline:.2%})"
    delta = latest - baseline
    sign = "+" if delta >= 0 else ""
    line = f"{label}: {latest:.2%} (baseline {baseline:.2%}, Δ {sign}{delta:+.2%})"
    return delta >= -tol, line


def compare(baseline_path: Path, latest_path: Path) -> tuple[bool, list[str]]:
    baseline = _read_json(baseline_path)
    latest = _read_json(latest_path)

    lines: list[str] = []
    ok = True

    sup_ok, sup_line = _diff(
        "Avg support rate",
        baseline.get("avg_support_rate"),
        latest.get("avg_support_rate"),
        SUPPORT_RATE_TOLERANCE,
    )
    lines.append(sup_line)
    ok = ok and sup_ok

    rec_ok, rec_line = _diff(
        "Avg recall (synthetic)",
        baseline.get("avg_recall"),
        latest.get("avg_recall"),
        RECALL_TOLERANCE,
    )
    lines.append(rec_line)
    ok = ok and rec_ok

    return ok, lines


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python -m research_agent.eval.regression <baseline.json> <latest.json>")
        return 2

    baseline_path = Path(sys.argv[1])
    latest_path = Path(sys.argv[2])

    if not baseline_path.is_file():
        print(f"⚠️  No baseline at {baseline_path} — skipping regression check.")
        return 0
    if not latest_path.is_file():
        print(f"❌ Latest report not found at {latest_path}")
        return 2

    ok, lines = compare(baseline_path, latest_path)
    print("Regression check:")
    for line in lines:
        print(f"  - {line}")
    if not ok:
        print(
            f"\n❌ Regression: drop > {SUPPORT_RATE_TOLERANCE:.0%} in at least one metric. "
            "Investigate before merging, or update eval/baseline.json if intentional."
        )
        return 1
    print("\n✅ No regression detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
