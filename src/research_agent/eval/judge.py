"""LLM-as-judge for the support metric.

We send (claim, supporting source body, optional verbatim quote) to Sonnet and ask
a yes/no question: "Does the source actually support this claim?". Returns a
``ClaimVerdict`` per claim.

Claims are extracted from the ``key_findings`` list — each bullet is one claim.
The ``[n]`` markers at the end identify which citations were used; we resolve those
to source bodies via the ``Brief.citations`` list.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel

from research_agent.adapters import arxiv as arxiv_adapter
from research_agent.adapters import github as github_adapter
from research_agent.llm import call_haiku, extract_json_tag
from research_agent.models import Brief, Citation

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")
_JUDGE_SYSTEM = """You are a strict fact-checker. You decide whether a source supports a specific claim.

You will see:
- ONE claim (a short statement).
- ONE source body (the only evidence available).

Decide: does the source body explicitly support the claim, or not? Be conservative.
- "supported": the source explicitly states (or directly implies) the claim.
- "unsupported": the source does not contain the claim, or only weakly relates to it.
- "contradicted": the source contradicts the claim.

Output a single `<json>` block:

<json>
{"verdict": "supported|unsupported|contradicted", "reason": "<10 words>"}
</json>
"""


class ClaimVerdict(BaseModel):
    claim: str
    citation_indices: list[int]
    verdict: Literal["supported", "unsupported", "contradicted", "no_citation"]
    reason: str = ""


def _claims_from_findings(findings: list[str]) -> list[tuple[str, list[int]]]:
    out: list[tuple[str, list[int]]] = []
    for line in findings:
        indices = [int(m) for m in _CITATION_RE.findall(line)]
        clean = _CITATION_RE.sub("", line).strip(" .,;").strip()
        if clean:
            out.append((clean, indices))
    return out


async def _source_body_for(citation: Citation) -> str:
    """Re-fetch the source body for a citation, mirroring read_node logic."""
    url = str(citation.candidate_url)
    if "arxiv.org" in url:
        # Best-effort: fetch the PDF via arxiv ID embedded in the URL.
        # If the citation already carries a quote, that's the strongest evidence
        # and the judge will see it as part of the body.
        m = re.search(r"abs/([\w.\-]+)", url)
        if m:
            pdf_url = f"https://arxiv.org/pdf/{m.group(1)}.pdf"
            text = await arxiv_adapter.fetch_paper_text(pdf_url, fallback_abstract="")
            if text:
                return text
    if "github.com" in url:
        m = re.match(r"https?://github.com/([^/]+/[^/]+)", url)
        if m:
            full_name = m.group(1).rstrip("/")
            text = await github_adapter.fetch_readme(full_name)
            if text:
                return text
    if citation.quote:
        return citation.quote
    return ""


async def judge_brief(brief: Brief) -> list[ClaimVerdict]:
    """Run the judge over every key_findings claim."""
    citations_by_index = {c.index: c for c in brief.citations}
    verdicts: list[ClaimVerdict] = []

    for claim, indices in _claims_from_findings(brief.key_findings):
        if not indices:
            verdicts.append(
                ClaimVerdict(claim=claim, citation_indices=[], verdict="no_citation")
            )
            continue

        bodies: list[str] = []
        for idx in indices:
            cit = citations_by_index.get(idx)
            if not cit:
                continue
            body = await _source_body_for(cit)
            if body:
                bodies.append(f"[{idx}] {cit.title}\n{body[:6000]}")

        if not bodies:
            verdicts.append(
                ClaimVerdict(
                    claim=claim,
                    citation_indices=indices,
                    verdict="unsupported",
                    reason="could not fetch any source body",
                )
            )
            continue

        user = (
            f"Claim:\n{claim}\n\n"
            f"Source body (concatenated from cited references):\n\n"
            + "\n\n---\n\n".join(bodies)
        )
        try:
            raw = call_haiku(system=_JUDGE_SYSTEM, user=user, max_tokens=200, temperature=0.0)
            payload = extract_json_tag(raw)
            verdict = payload.get("verdict", "unsupported")
            if verdict not in ("supported", "unsupported", "contradicted"):
                verdict = "unsupported"
            verdicts.append(
                ClaimVerdict(
                    claim=claim,
                    citation_indices=indices,
                    verdict=verdict,
                    reason=payload.get("reason", "")[:200],
                )
            )
        except Exception as exc:
            logger.warning("judge failed for claim %r: %s", claim[:60], exc)
            verdicts.append(
                ClaimVerdict(
                    claim=claim,
                    citation_indices=indices,
                    verdict="unsupported",
                    reason=f"judge error: {exc}",
                )
            )

    return verdicts


def support_rate(verdicts: list[ClaimVerdict]) -> float:
    """Fraction of claims judged 'supported'."""
    if not verdicts:
        return 0.0
    supported = sum(1 for v in verdicts if v.verdict == "supported")
    return supported / len(verdicts)
