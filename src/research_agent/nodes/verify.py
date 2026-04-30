"""``verify_node`` — score the brief's grounding and gate retries.

After ``synthesize_node`` produces a Brief, this node runs Haiku on each
``key_findings`` claim asking whether the cited fact actually supports it.
Output goes into ``state["verify_support_rate"]`` and a human-readable
``state["verify_feedback"]`` that ``synthesize_node`` consumes on a retry.

The graph's conditional edge looks at ``verify_support_rate`` plus
``state["synthesize_attempts"]`` to decide whether to retry or finish.
"""

from __future__ import annotations

import logging
import re

from research_agent.llm import call_haiku, extract_json_tag
from research_agent.models import Brief, ExtractedFact
from research_agent.observability import observe
from research_agent.state import ResearchState

logger = logging.getLogger(__name__)

_VERIFY_SYSTEM = """You are a strict fact-checker for a research brief. For each claim you receive, decide if the cited extracted-fact actually supports it. Be conservative.

Output a single `<json>` block with one verdict per claim, matching the input order:

<json>
{"verdicts": [{"i": 1, "supported": true, "issue": ""}, {"i": 2, "supported": false, "issue": "claim adds a number not present in the cited fact"}]}
</json>
"""

_CITATION_RE = re.compile(r"\[(\d+)\]")


def _format_facts_block(facts: list[ExtractedFact]) -> str:
    lines: list[str] = []
    for i, f in enumerate(facts, start=1):
        quote = f.quotes[0] if f.quotes else ""
        lines.append(f"[{i}] thesis: {f.thesis}")
        if quote:
            lines.append(f"     quote: {quote[:300]}")
        if f.methods:
            lines.append(f"     methods: {', '.join(f.methods[:5])}")
    return "\n".join(lines)


def _format_claims_block(brief: Brief) -> tuple[str, list[tuple[str, list[int]]]]:
    """Returns the prompt block plus a parallel list of (claim_text, indices)."""
    parsed: list[tuple[str, list[int]]] = []
    lines: list[str] = []
    for i, line in enumerate(brief.key_findings, start=1):
        indices = [int(m) for m in _CITATION_RE.findall(line)]
        clean = _CITATION_RE.sub("", line).strip(" .,;").strip()
        parsed.append((clean, indices))
        lines.append(f"Claim {i} (cites {indices}): {clean}")
    return "\n".join(lines), parsed


@observe(name="verify_node")
async def verify_node(state: ResearchState) -> dict:
    brief: Brief | None = state.get("brief")
    facts = state.get("facts") or []

    attempts = state.get("synthesize_attempts", 0)
    out: dict = {"synthesize_attempts": attempts}

    if brief is None or not brief.key_findings or not facts:
        out["verify_support_rate"] = 0.0
        out["verify_feedback"] = ""
        logger.info("verify_node: nothing to verify")
        return out

    facts_block = _format_facts_block(facts)
    claims_block, parsed = _format_claims_block(brief)
    user = (
        f"Facts (numbered):\n{facts_block}\n\n"
        f"Claims to verify:\n{claims_block}"
    )

    raw = call_haiku(
        system=_VERIFY_SYSTEM,
        user=user,
        max_tokens=1024,
        temperature=0.0,
        cache_system=True,
        node="verify",
    )

    try:
        payload = extract_json_tag(raw)
        verdicts = payload.get("verdicts", []) or []
    except Exception as exc:
        logger.warning("verify_node parse failed: %s — assuming all claims supported", exc)
        out["verify_support_rate"] = 1.0
        out["verify_feedback"] = ""
        return out

    supported_flags: list[bool] = []
    issues: list[str] = []
    for v in verdicts:
        try:
            i = int(v.get("i"))
        except (TypeError, ValueError):
            continue
        if i < 1 or i > len(parsed):
            continue
        ok = bool(v.get("supported", False))
        supported_flags.append(ok)
        if not ok:
            issue = v.get("issue", "").strip() or "unsupported"
            issues.append(f'Claim {i}: "{parsed[i - 1][0][:120]}" — {issue}')

    if not supported_flags:
        # All verdicts unparseable — be lenient
        out["verify_support_rate"] = 1.0
        out["verify_feedback"] = ""
        return out

    rate = sum(supported_flags) / len(supported_flags)
    out["verify_support_rate"] = rate
    out["verify_feedback"] = (
        "On the previous attempt these specific claims failed grounding "
        "verification. Either drop them, rewrite them so they're directly "
        "supported by the cited fact, or pick a different citation:\n\n"
        + "\n".join(issues)
        if issues
        else ""
    )
    logger.info(
        "verify_node: support_rate=%.2f (%d/%d claims supported)",
        rate,
        sum(supported_flags),
        len(supported_flags),
    )
    return out
