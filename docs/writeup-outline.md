# Write-up outline: "How I built a production Claude agent with eval-driven CI"

> Target audience: AI engineers and hiring managers reading dev.to / Medium / personal blog.
> Goal: position as a senior AI Agent Engineer who thinks about reliability, not just demos.
> Length: 2,500-3,500 words. Reading time: ~12-15 min.
> Tone: technical, honest, opinionated. Show tradeoffs, not just wins.

---

## Hook (~150 words)

Open with a concrete problem framing, not a stack list.

- The "demo trap" in agents: shiny demos that fall apart on the second user.
- Position: a research agent that produces a brief in 2 minutes is interesting; one whose every claim is grounded in a verifiable source is hireable.
- Promise of the post: build it end-to-end (LangGraph → eval → CI → deploy), and own the tradeoffs.
- Live link: `romanserbin96--ai-research-agent-research.modal.run` — invite reader to try a curl before reading.

---

## Section 1: What it does and why it matters (~300 words)

- One paragraph use case: "find and compare modern approaches to X in 2025-2026."
- Pipeline overview: Plan → Search → Rank → Read → Synthesize.
- Sample output snippet (real brief excerpt with `[n]` citations).
- Why "every claim has a citation" is the hard part. Cite the 2024-2025 hallucination research.

**Take-away callout:** "Grounding isn't a feature flag — it's a property of every node in your graph."

---

## Section 2: LangGraph state design (~400 words)

- Why a flat `TypedDict` instead of accumulating reducers (simplicity).
- The state schema (Candidate / ExtractedFact / Brief pydantic models).
- Each node writes one field. No state coupling between nodes.
- **Code snippet:** the `ResearchState` definition.
- Why linear graph beats conditional edges in v1: less surface area to test.

**Take-away callout:** "If you can't draw your state schema on a napkin, your graph is too clever."

---

## Section 3: Search and the multi-source fan-out (~350 words)

- Three adapters: arXiv (free API), GitHub REST, Anthropic server-side `web_search` tool.
- Why I dropped Browserbase + Stagehand from the MVP: cost-per-session and a manageable trio without it.
- Real-world rate limits: arXiv 429s when running from cloud IPs (Modal). Show the semaphore + delay fix.
- **Code snippet:** the `_get_arxiv_semaphore` pattern.

**Take-away callout:** "Cloud IPs share fate. Plan for 429s as the default."

---

## Section 4: Grounding and the synthesize contract (~400 words)

- The `[n]` citation marker convention.
- Pydantic `Brief` schema with citations as first-class objects.
- Synthesize prompt: hard rule that every claim ends with `[n]`. Show the prompt.
- **Code snippet:** the `synthesize.md` system prompt.
- Verbatim quotes in `read.md`: "If you can't find an exact quote, return an empty list — do NOT paraphrase."

**Take-away callout:** "You can't grade reasoning if the model paraphrases. Make verbatim the only valid output."

---

## Section 5: Eval-driven development (~500 words)

The longest section — this is the hire-me bit.

- Three metrics from the spec: support / recall / usefulness.
- Why I shipped 2 of 3 in v1: usefulness (pairwise) needs a baseline version to compare against.
- Support rate via LLM-as-judge: send `(claim, source-body)` to Haiku, ask "supported / unsupported / contradicted."
- Recall on synthetic tasks: precomputed "must-have URLs" with prefix-match (`github.com/x/y` matches `github.com/x/y/tree/main`).
- 50-task dataset design: 25 synthetic with ground truth + 25 real questions from r/MachineLearning, HN, engineering blogs.
- **Code snippet:** the `judge_brief` function.
- Honest baseline: at Anthropic Tier 1 (30k tokens/min), back-to-back tasks fail mid-pipeline. Documented openly.

**Take-away callout:** "An eval that always passes is useless. An eval that never passes is broken. The interesting metric is your direction over time."

---

## Section 6: Eval-CI on every PR (~400 words)

- GitHub Actions workflow: `eval.yml` with subset (5 tasks, $3) by default, full sweep (50 tasks, $30) on `full-eval` label.
- Why subset for routine PRs: cost control. Why full for releases: confidence.
- Regression gate: 5pp tolerance on support_rate + recall vs `eval/baseline.json`.
- **Code snippet:** the `regression.py` compare function.
- PR comment with metrics auto-posted via `actions/github-script`.
- **Screenshot:** real PR comment from `Shcherbin96/ai-research-agent#1`.

**Take-away callout:** "Eval CI is the only honest signal that your prompt change didn't quietly break the agent."

---

## Section 7: Observability with Langfuse (~250 words)

- Why traces matter for non-deterministic systems: you can't `print` your way out.
- Optional integration: env-var-gated `@observe` decorator that's a no-op without keys.
- Hierarchical span tree: top-level run → 5 nodes → 8+ LLM calls with token usage.
- **Public trace link:** `cloud.langfuse.com/public/traces/<id>` — invite reader to inspect.
- Trade-off: vendor dependency vs build-it-yourself. I chose vendor for v1.

**Take-away callout:** "If you can't share a trace publicly, you don't have observability — you have logs."

---

## Section 8: Long-term memory and Mem0 (~200 words)

- Use case: cache findings between research sessions so a follow-up query benefits from past work.
- Two hooks: `synthesize_node` writes briefs to memory; `plan_node` recalls top-3 similar past briefs as warm context.
- Honest scope: in v1, I haven't measured the win quantitatively. Memory is interesting plumbing, not a proven quality gain (yet).

**Take-away callout:** "Adding long-term memory is easy. Proving it improves your eval is the hard part."

---

## Section 9: Deploy and the public endpoint (~200 words)

- Modal serverless: build image with `uv_pip_install`, declare secret, expose `@modal.fastapi_endpoint`.
- Cold start ~10-30s. Per-call cost dominated by Anthropic, not Modal compute.
- Why not Railway/Fly: this is a per-request job, not a long-running service. FaaS is a better fit.
- **Code snippet:** the 60-line `modal_app.py`.

**Take-away callout:** "Pick the platform that matches your workload shape. CLI tools belong on FaaS."

---

## Section 10: What I'd do next (~250 words)

The honest backlog. Don't pretend it's done.

1. **pass^k metric:** every task run 4 times, only counts if all 4 pass. The current eval is single-run — passes that fail 1-in-4 times look identical to bulletproof passes.
2. **Pairwise usefulness:** ship a baseline version, compare each PR's brief side-by-side via LLM-as-judge.
3. **Tier-2 Anthropic:** the rate-limit failures in baseline are real signal that Tier 1 is the wrong tier for back-to-back research.
4. **Browser-based Google Scholar:** the source diversity is fine without it, but academic queries miss recent unpublished preprints.
5. **PDF tables / formula extraction:** `pypdf` extracts text but loses structure. For physics/ML, equations matter.

---

## Closing (~150 words)

- The hireable signal isn't "I built an agent." It's "I built an agent and I have eval/observability/CI to prove it works."
- Project is open and live; encourage forks, issues, screenshots of broken tasks.
- Brief biographical line: who you are, what role you're looking for, contact link.

---

## Distribution checklist

- [ ] Cross-post to dev.to + Medium + personal blog
- [ ] Submit to: r/MachineLearning (Self Promotion Saturday), HN Show, AI Engineer newsletter
- [ ] LinkedIn post with key screenshot + 1 paragraph hook
- [ ] Twitter/X thread: 8-10 tweets, one per section, ending with the live URL
- [ ] Add link to GitHub README (top of file, "Read the build log")

---

## Visual assets to prepare

1. **Architecture mermaid** — already in README, lift for the post.
2. **Sample brief screenshot** — render one of the `briefs/*.md` files as styled HTML.
3. **Langfuse trace screenshot** — the hierarchical span tree.
4. **PR comment screenshot** — eval CI metrics comment.
5. **Eval report markdown screenshot** — the per-task table.

Loom 2-3 min as "video version" for those who don't read.
