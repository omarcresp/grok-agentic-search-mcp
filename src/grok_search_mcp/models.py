"""Validated contracts shared by the MCP, Grok, and persistent research records."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MODEL = "grok-4.6"
Depth = Literal["standard", "deep"]
ClaimStatus = Literal["supported", "qualified", "contradicted", "unverified"]
RunStatus = Literal["queued", "running", "completed", "partial", "cancelled", "failed"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchOptions(StrictModel):
    """Internal execution settings for persistence and evaluations; not MCP tool input."""

    query: str = Field(min_length=1, max_length=20000)
    depth: Depth = "standard"
    allowed_domains: list[str] = Field(default_factory=list, max_length=5)
    excluded_domains: list[str] = Field(default_factory=list, max_length=5)
    allowed_x_handles: list[str] = Field(default_factory=list, max_length=20)
    excluded_x_handles: list[str] = Field(default_factory=list, max_length=20)
    from_date: datetime | None = None
    to_date: datetime | None = None
    enable_image_understanding: bool = True
    enable_video_understanding: bool = True
    include_x: bool = True
    source_urls: list[str] = Field(default_factory=list, max_length=12)
    max_cost_usd: float = Field(default=3.0, gt=0, le=50, allow_inf_nan=False)
    timeout_seconds: float = Field(default=600, ge=10, le=1800, allow_inf_nan=False)
    max_rounds: int = Field(default=2, ge=1, le=4)
    parent_research_id: str | None = None

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain text")
        return value.strip()

    @field_validator("allowed_domains", "excluded_domains")
    @classmethod
    def domains(cls, values: list[str]) -> list[str]:
        import re

        normalized = [v.strip().lower().rstrip(".") for v in values]
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if any(len(v) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", v) for v in normalized):
            raise ValueError("domain filters must be hostnames, without URLs or wildcards")
        return list(dict.fromkeys(normalized))

    @field_validator("allowed_x_handles", "excluded_x_handles")
    @classmethod
    def handles(cls, values: list[str]) -> list[str]:
        import re

        normalized = [v.strip().lstrip("@").lower() for v in values]
        if any(not re.fullmatch(r"[a-z0-9_]{1,15}", v) for v in normalized):
            raise ValueError("X filters must contain valid handles")
        return list(dict.fromkeys(normalized))

    @field_validator("from_date", "to_date")
    @classmethod
    def utc_dates(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    @model_validator(mode="after")
    def filters(self):
        for name in ("domains", "x_handles"):
            if getattr(self, f"allowed_{name}") and getattr(self, f"excluded_{name}"):
                raise ValueError(f"allowed_{name} cannot be combined with excluded_{name}")
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be before or equal to to_date")
        if not self.include_x and any(
            (self.allowed_x_handles, self.excluded_x_handles, self.from_date, self.to_date)
        ):
            raise ValueError("X filters require include_x=True")
        return self


def research_defaults(
    query: str, depth: Depth = "deep", source_urls: list[str] | None = None
) -> SearchOptions:
    """Allow research depth and seed URLs while keeping execution policy server-owned."""
    return SearchOptions(query=query, depth=depth, source_urls=source_urls or [])


class ResearchPlan(StrictModel):
    objective: str = Field(max_length=1500)
    questions: list[str] = Field(min_length=1, max_length=6)
    search_queries: list[str] = Field(min_length=1, max_length=4)


class Discovery(StrictModel):
    urls: list[str] = Field(max_length=16)


class Evidence(StrictModel):
    source_id: str
    quote: str = Field(min_length=15, max_length=700)


class DraftClaim(StrictModel):
    statement: str = Field(min_length=1, max_length=1500)
    question: str = Field(max_length=1500)
    evidence: list[Evidence] = Field(max_length=4)


class Draft(StrictModel):
    claims: list[DraftClaim] = Field(max_length=12)
    gaps: list[str] = Field(max_length=6)


class Claim(StrictModel):
    id: str
    statement: str
    question: str
    status: ClaimStatus = "unverified"
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str = "Not reviewed."


class ClaimCheck(StrictModel):
    claim_id: str
    status: ClaimStatus
    statement: str = Field(min_length=1, max_length=1500)
    evidence: list[Evidence] = Field(max_length=4)
    reason: str = Field(max_length=1500)


class Review(StrictModel):
    checks: list[ClaimCheck] = Field(max_length=12)
    gaps: list[str] = Field(max_length=6)
    answer_claim_ids: list[str] = Field(default_factory=list, max_length=12)


class Source(StrictModel):
    id: str
    requested_url: str
    url: str
    title: str = ""
    retrieved_at: str = Field(default_factory=now)
    status: Literal["read", "failed"] = "failed"
    content_hash: str = ""
    media_type: str = ""
    truncated: bool = False
    error: str | None = None
    text: str = ""


class EvidencePage(Source):
    offset: int
    next_offset: int | None
    total_characters: int
    untrusted_source_content: Literal[True] = True


class Usage(StrictModel):
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_prompt_tokens: int = 0
    reported_cost_usd: float = 0
    cost_complete: bool = True
    server_side_tool_usage: dict[str, int] = Field(default_factory=dict)


class Quality(StrictModel):
    questions_total: int = 0
    questions_addressed: int = 0
    supported_claims: int = 0
    qualified_claims: int = 0
    contradicted_claims: int = 0
    unverified_claims: int = 0
    sources_read: int = 0
    sources_failed: int = 0
    distinct_domains: int = 0


class SearchResult(StrictModel):
    # Keep the original five response fields for existing callers.
    result: str = ""
    citations: list[str] = Field(default_factory=list)
    source_count: int = 0
    model_used: Literal["grok-4.6"] = MODEL
    depth: Depth
    schema_version: str = "2.0"
    research_id: str
    status: RunStatus = "queued"
    phase: str = "queued"
    stop_reason: str | None = None
    verification: Literal["not_requested", "grok_reviewed", "incomplete"] = "incomplete"
    plan: ResearchPlan | None = None
    claims: list[Claim] = Field(default_factory=list)
    answer_claim_ids: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    inline_citations: list[dict] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    quality: Quality = Field(default_factory=Quality)
    elapsed_seconds: float = 0
    rounds_completed: int = 0
    evidence_uri: str = ""


class RunRecord(StrictModel):
    options: SearchOptions
    output: SearchResult
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    owner_pid: int = 0


class JobInfo(StrictModel):
    research_id: str
    status: str
    phase: str
    evidence_uri: str
