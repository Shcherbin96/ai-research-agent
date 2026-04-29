from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

SourceType = Literal["arxiv", "github", "web"]


class Candidate(BaseModel):
    source: SourceType
    url: HttpUrl
    title: str
    snippet: str = ""
    authors: list[str] = Field(default_factory=list)
    published: date | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    index: int
    candidate_url: HttpUrl
    title: str
    quote: str | None = None


class ExtractedFact(BaseModel):
    candidate_url: HttpUrl
    thesis: str
    methods: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)


class Brief(BaseModel):
    query: str
    executive_summary: str
    key_findings: list[str] = Field(default_factory=list)
    comparison_matrix: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
