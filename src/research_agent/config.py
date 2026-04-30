import os
from dataclasses import dataclass

from dotenv import load_dotenv

# override=True so the project's .env wins over any pre-set environment
# variables (e.g. when running inside an IDE/agent shell that injects its own).
load_dotenv(override=True)

SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

WEB_SEARCH_TOOL_TYPE = "web_search_20250305"

DEFAULT_LIMIT_PER_SOURCE = 10
DEFAULT_TOP_N_SELECTED = 10
DEFAULT_SUBQUERY_COUNT_RANGE = (3, 6)

GITHUB_README_TRUNCATE = 4000

# arXiv PDFs after pypdf extraction. Roughly ~1.5x chars-to-token, so 12k chars
# ≈ 8k input tokens — fits comfortably under Tier-1 30k/min with concurrency=2.
ARXIV_PDF_TRUNCATE = 12000

# Max concurrent calls in read_node. Reduced to 1 because cloud IPs (Modal,
# GitHub Actions) ALSO compete for the org-wide Anthropic Tier-1 budget, so
# even concurrency=2 routinely blew past 30k tokens/min when 5-6 reads landed
# in the same minute. Concurrency=1 + 5s arxiv-PDF fetches between calls
# spaces requests enough that the SDK's max_retries=6 reliably recovers.
READ_NODE_CONCURRENCY = 1


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    github_token: str | None


def load_settings() -> Settings:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return Settings(
        anthropic_api_key=api_key,
        github_token=os.environ.get("GITHUB_TOKEN", "").strip() or None,
    )
