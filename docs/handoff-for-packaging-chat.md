# Handoff для упаковки в claude.ai

Скопируй текст ниже в первое сообщение нового чата с Claude. Можно дополнить ответами на вопросы про опыт/таргет/зарплату.

---

```
Привет. Помоги мне упаковать себя для job applications. Я ищу удалённую позицию AI Agent Engineer.

# Контекст: я только что построил production-grade portfolio проект

**Technical Research Agent** — AI-агент, который проводит технический research по запросу и возвращает структурированный brief с inline-цитатами на источники.

## Live ссылки
- 📦 Code (public): https://github.com/Shcherbin96/ai-research-agent
- 🌐 Live UI на Modal (можно потрогать): https://romanserbin96--ai-research-agent-research.modal.run
- 🔍 Public Langfuse trace одного из run'ов: https://cloud.langfuse.com/public/traces/bc2b23ae0e1e0a525a0cf69e1bb02d00
- ✅ CI: https://github.com/Shcherbin96/ai-research-agent/actions
- 🏷️ Release v0.1.0: https://github.com/Shcherbin96/ai-research-agent/releases/tag/v0.1.0

## Архитектура и стек
- LangGraph multi-step pipeline: Plan → Search → Rank → Read → Synthesize
- Три search-адаптера в parallel: arXiv API (с PDF-парсингом через pypdf), GitHub REST, Anthropic web_search server-side tool
- Опциональный Browserbase + Playwright адаптер для Google Scholar
- Claude Sonnet 4.6 для plan/read/synthesize, Haiku 4.5 для ранжирования
- Каждое утверждение в final brief заканчивается `[n]` цитатой, привязанной к verbatim quote из источника

## Production-инфраструктура
- **Eval framework**: 50 hand-curated tasks (25 синтетических с known ground-truth URLs + 25 real research questions)
- **Метрики**: support rate (LLM-as-judge per claim) + recall + pass^k reliability + pairwise usefulness comparison с MT-Bench position-bias mitigation
- **CI/CD**: GitHub Actions runs tests on every PR + eval subset (5 tasks, ~$3) on every PR + full sweep (50 tasks) on label/manual dispatch. Regression gate блокирует merge если support_rate или recall дропают >5pp vs committed `eval/baseline.json`
- **Observability**: Langfuse traces для каждого узла графа и LLM-вызова (token usage, full prompts, hierarchical span tree)
- **Long-term memory**: Mem0 — completed briefs сохраняются и подтягиваются как warm context для похожих будущих запросов
- **Deploy**: Modal serverless function с public HTTPS endpoint + interactive web UI (Tailwind + Alpine.js + marked.js, mobile-friendly)
- 49 unit tests, ruff-clean, MIT license

## Hiring signals которые проект закрывает (под job descriptions для AI Agent Engineer)
- LangGraph + multi-step agent orchestration
- Tool use (search/read/browse) с верифицируемым grounding
- Long-term memory (Mem0)
- Observability и production traces (Langfuse)
- Eval-driven development: LLM-as-judge, pass^k, pairwise comparison
- CI/CD для non-deterministic systems
- Production deployment (Modal)
- Open source с public live demo

## Что мне нужно от тебя

Помоги мне упаковать себя по очереди:

1. **Resume / CV на 1 страницу** — main документ. Я могу скинуть мой текущий опыт когда спросишь.
2. **3-5 resume bullets** именно про этот проект (achievements-style, с цифрами)
3. **Mini bio / "About"** на 80-120 слов для GitHub profile README, hh.ru, dev.to
4. **GitHub profile README** который светит этим проектом
5. **3 шаблона cold-email** под разные типы компаний (early-stage стартап / Series A-B / AI-консалтинг)
6. **Список 20-30 целевых компаний** с указанием как искать email'ы hiring manager'ов (не нужно искать конкретные адреса — просто скажи где смотреть)

Начнём с резюме. Сначала задай мне 4-5 вопросов про мой опыт, годы, прошлые роли, образование, чтобы написать резюме под меня.
```

---

После того как Claude в новом чате задаст вопросы и ты ответишь — он напишет тебе:

1. Резюме (Markdown)
2. Bullets под этот проект
3. Bio
4. README для https://github.com/Shcherbin96
5. Cold-email шаблоны
6. Target company list

Когда все артефакты готовы — возвращайся сюда (или нет — это всё уже про текст, удобнее в обычном чате).

Если в обычном чате потребуется **что-то поправить в коде/деплое** — приходи назад, мы тут продолжим.
