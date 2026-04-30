# Project context for new Claude chats

> **Use this:** copy the block inside the triple-backticks below into the first
> message of any new chat (claude.ai or otherwise). It gives the model full
> context on this project so you can immediately ask for help with packaging,
> writing, debugging, planning, etc. without re-explaining.
>
> If something changes (new feature, new metric, deployment URL moves), update
> this file and re-paste.

---

```
# Context: my portfolio project — Technical Research Agent

I'm Roman Shcherbin. I built a production-grade AI agent as my main
portfolio piece for fulltime remote AI Agent Engineer roles.

## What it does

Give it a technical research query. It runs a multi-step pipeline and
returns a structured Markdown brief where every claim ends with a
verifiable citation. A typical run: 60-120s, 6-10 citations, ~$0.10-0.30.

## Live links

- Code:        https://github.com/Shcherbin96/ai-research-agent
- Live UI:     https://romanserbin96--ai-research-agent-research.modal.run
- Public trace: https://cloud.langfuse.com/public/traces/bc2b23ae0e1e0a525a0cf69e1bb02d00
- CI:          https://github.com/Shcherbin96/ai-research-agent/actions
- Release:     https://github.com/Shcherbin96/ai-research-agent/releases/tag/v0.1.0
- LICENSE:     MIT

## Architecture and stack

**Pipeline (LangGraph state machine):** plan → search → rank → read → synthesize → verify, with a self-correction loop back to synthesize on low support.

- **Plan** (Sonnet 4.6): decomposes the user query into 3-6 focused subqueries.
- **Search**: parallel fan-out across three adapters — arXiv API (`arxiv` lib + `pypdf` for full-paper text), GitHub `/search/repositories` REST, Anthropic server-side `web_search` tool. Plus an optional Browserbase + Playwright Google Scholar adapter.
- **Rank** (Haiku 4.5): reranks ~50 candidates down to top 6-10 with source diversity.
- **Read** (Haiku 4.5 in "fast" mode, Sonnet in "quality" mode, concurrency=1, 5-min ephemeral prompt cache on the system message): extracts a structured `ExtractedFact` with verbatim quotes from each source.
- **Synthesize** (Sonnet 4.6): assembles executive summary, key findings (each ending with `[n]` citation marker), comparison matrix, open questions.
- **Verify** (Haiku 4.5): scores claim grounding. If support_rate < 0.7 and we've used < 2 attempts, conditional edge sends control back to synthesize with a feedback string listing unsupported claims; otherwise END.

**Production-grade infrastructure:**

- **Eval framework:** `eval/tasks.json` — 50 hand-curated tasks (25 synthetic with arXiv/GitHub ground-truth URLs, 25 real research questions from r/MachineLearning, HN, eng blogs). CLI: `research-agent eval`.
- **Metrics:** support rate (LLM-as-judge with Haiku per claim) + recall (URL coverage with prefix-match) + **pass^k** (each task run k times, pass only if all k clear gates ≥3 findings, support ≥50%, recall ≥50%) + **pairwise usefulness** (Sonnet-as-judge with MT-Bench position-bias mitigation: each pair judged twice with A/B swapped, only counted as a win if same side wins both orderings).
- **CI/CD** (GitHub Actions): every PR runs ruff + 54 pytest tests + an eval subset (5 tasks, ~$3, ~10 min). Full 50-task sweep available via `workflow_dispatch` or `full-eval` PR label. **Regression gate**: blocks merge if support_rate or recall drops > 5pp vs the committed `eval/baseline.json`. PR comments are posted by the workflow whether the gate passes or fails (header reflects status), with a collapsible per-task table from the markdown report.
- **Observability:** every node and LLM call wrapped in Langfuse `@observe` (no-op if env vars missing). Per-call usage + a hierarchical trace tree are visible in the dashboard.
- **Cost tracking:** module-level accumulator parses `response.usage` (input, output, cache_creation, cache_read tokens) on every Anthropic call, multiplies by April-2026 pricing, exposes per-run total + per-node breakdown in the API response and the UI.
- **Anthropic prompt caching:** `read_node`'s system prompt is sent with `cache_control: ephemeral` so the second-through-Nth read pay 0.1× input price on the system portion (5-minute TTL). Typical 60-80% input-cost reduction at this stage.
- **Long-term memory:** Mem0 cloud — completed briefs are stored, and the planner recalls top-3 semantically-similar past briefs as warm context for new queries (opt-in via `MEM0_API_KEY`).
- **Deploy:** Modal serverless function as a single ASGI app with three routes — `GET /` interactive web UI (Tailwind via CDN + Alpine.js + marked.js, mobile-friendly with horizontal scroll on the comparison matrix), `POST /api/research` JSON, **`POST /api/research/stream`** SSE endpoint that emits `stage` / `chunk` / `verify` / `result` events so the UI shows a live 6-cell stage timeline plus word-by-word synthesize text.
- **Shareable briefs:** every successful brief is persisted to a `modal.Dict` keyed by an 8-byte URL-safe id; `GET /brief/<id>` renders the same UI shell with the saved brief hydrated client-side. The "Share link" button on the result card copies the URL to the clipboard.
- 54 unit tests, ruff-clean, MIT-licensed, v0.1.0 tagged.

## Hiring signals the project closes

For AI Agent Engineer / ML Engineer / Backend-with-AI roles:

- LangGraph multi-step orchestration with conditional edges (self-correction)
- Tool use (search, read, browse) with verifiable grounding
- Long-term memory (Mem0)
- Production observability (Langfuse traces, public-shareable)
- Eval-driven development: LLM-as-judge, pass^k, pairwise comparison with bias mitigation
- Anthropic prompt caching mastery (specific to Claude API)
- Per-query cost tracking with per-node breakdown
- Streaming UX (SSE, async generator orchestration)
- CI/CD with regression gate for non-deterministic systems
- Production deployment (Modal serverless, public HTTPS endpoint)
- Open source, MIT-licensed, public live demo

## What I want from you in this chat

[REPLACE THIS LINE WITH WHAT YOU WANT.]

Common asks:
- Help write a 1-page resume / CV
- Write 3-5 resume bullets specifically about this project
- Write a 80-120 word bio for GitHub profile / hh.ru / dev.to
- Write a GitHub profile README that showcases this project
- Write 3 cold-email templates for different company types
- Outline / draft a dev.to or Habr post about how I built this
- Help me prepare for an interview that referenced this project
- Brainstorm new features or improvements
- Critique my README / proposed cover letter / Loom script

Ask me whatever you need (years of experience, target salary, target geography, current employment status) before drafting anything substantive.
```

---

## Tips for using this

1. **First message in claude.ai.** Paste the whole block above. Replace the `[REPLACE THIS LINE...]` placeholder with what you actually want. Claude has full context immediately.

2. **For long sessions** with multiple artifacts (resume + bio + emails + README), use claude.ai's **Projects** feature if you have it (Pro/Team plan): create a project with this context as the System prompt, then every chat in that project starts pre-loaded.

3. **For one-off questions**, you can also paste a *condensed* version: just the live links + 3-5 sentences of "what it does". Save tokens.

4. **For a different chat platform** (other LLM, Telegram bot with Claude, etc.) — same prompt works.

5. **For interview prep** specifically, ask Claude: "Drill me with 10 likely interview questions about this project, then give me model answers." That's worth doing 1-2 days before any interview.

## When to update this file

- New feature shipped → add a line under "Production-grade infrastructure" or "Hiring signals"
- Live URL changes
- New eval metric / score
- v0.2.0 / new release tagged

## Related docs in this repo

- `README.md` — main entry point for visitors of the repo
- `01-technical-research-agent.md` — original spec written before any code
- `docs/writeup-outline.md` — outline for a dev.to / Medium post
- `docs/handoff-for-packaging-chat.md` — older, slightly out-of-date version of this doc focused on packaging-for-jobs only (kept for backward compatibility)
