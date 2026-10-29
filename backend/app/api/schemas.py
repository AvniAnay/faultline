"""API models (Stage 1 contract). snake_case, UTC timestamps with Z."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from app.agent.state import Category, Confidence, Origin, Severity


def _fmt(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


UTCDateTime = Annotated[datetime, PlainSerializer(_fmt, return_type=str, when_used="json")]


class UserRef(BaseModel):
    id: str
    display_name: str | None = None
    email: str | None = None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class Sample(BaseModel):
    redacted_text: str
    seen_at: UTCDateTime


class ResolutionDraft(BaseModel):
    summary: str
    probable_cause: str
    steps: list[str]
    sources: list[str]
    confidence: Confidence
    origin: Origin


class Resolution(ResolutionDraft):
    id: uuid.UUID
    fingerprint_id: uuid.UUID
    status: Literal["draft", "approved", "rejected"]
    approved_by: UserRef | None = None
    approved_at: UTCDateTime | None = None


class ErrorSummary(BaseModel):
    id: uuid.UUID
    service: str
    level: str
    template: str
    category: str | None = None
    severity: str | None = None
    team_name: str | None = None
    status: str
    first_seen: UTCDateTime
    last_seen: UTCDateTime
    total_count: int


class ProposedItem(BaseModel):
    flags: list[str]
    window_count: int
    category: str
    category_reason: str | None = None
    severity: str
    severity_reason: str | None = None
    team_name: str
    resolution: ResolutionDraft


class ResolutionEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str | None = Field(default=None, min_length=1, max_length=4000)
    probable_cause: str | None = Field(default=None, min_length=1, max_length=4000)
    steps: list[Annotated[str, Field(min_length=1, max_length=1000)]] | None = Field(default=None, max_length=20)


class ReviewEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Severity | None = None
    category: Category | None = None
    resolution: ResolutionEdits | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ReviewEdits":
        res = self.resolution
        has_res = res is not None and any(v is not None for v in res.model_dump().values())
        if self.severity is None and self.category is None and not has_res:
            raise ValueError("at least one edited field is required")
        return self


class ReviewedError(BaseModel):
    service: str
    level: str
    template: str
    total_count: int
    first_seen: UTCDateTime
    last_seen: UTCDateTime
    samples: list[Sample]


class ReviewItem(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    fingerprint_id: uuid.UUID
    error: ReviewedError
    proposed: ProposedItem
    decision: Literal["pending", "approved", "edited", "rejected"]
    edited: ReviewEdits | None = None
    reviewer: UserRef | None = None
    comment: str | None = None
    decided_at: UTCDateTime | None = None


class ReviewHistoryEntry(BaseModel):
    review_item_id: uuid.UUID
    run_id: uuid.UUID
    decision: str
    reviewer: UserRef | None = None
    comment: str | None = None
    decided_at: UTCDateTime | None = None


class ErrorDetail(ErrorSummary):
    drain_cluster_id: int
    samples: list[Sample]
    latest_flags: list[str]
    resolutions: list[Resolution]
    pending_review_item: ReviewItem | None = None
    review_history: list[ReviewHistoryEntry]


class LlmTokens(BaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0


class RunStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lines_scanned: int = 0
    lines_dropped_level: int = 0
    distinct_errors: int = 0
    flagged: int = 0
    llm_calls: int = 0
    llm_tokens: LlmTokens = Field(default_factory=LlmTokens)
    tavily_calls: int = 0
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    redaction_failures: int = 0
    emails_logged: int = 0
    duration_seconds: float | None = None
    error: str | None = None


RunStatus = Literal["requested", "running", "awaiting_review", "sending", "completed", "failed"]


class Run(BaseModel):
    id: uuid.UUID
    requested_by: UserRef | None = None
    started_at: UTCDateTime | None = None
    finished_at: UTCDateTime | None = None
    window_start: UTCDateTime | None = None
    window_end: UTCDateTime | None = None
    status: RunStatus
    stats: RunStats
    pending_review_count: int


class PendingRun(BaseModel):
    run: Run
    items: list[ReviewItem]


class PendingReviews(BaseModel):
    runs: list[PendingRun]


class ReviewDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["pending", "approved", "edited", "rejected"]
    edited: ReviewEdits | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _edited_iff_edited(self) -> "ReviewDecisionIn":
        if self.decision == "edited" and self.edited is None:
            raise ValueError("edited is required when decision is 'edited'")
        if self.decision != "edited" and self.edited is not None:
            raise ValueError("edited is only allowed when decision is 'edited'")
        return self

    @field_validator("comment")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None


class OccurrencePoint(BaseModel):
    bucket_start: UTCDateTime
    count: int


class OccurrenceSeries(BaseModel):
    bucket: Literal["hour", "day"]
    points: list[OccurrencePoint]


class Me(BaseModel):
    id: str
    email: str | None = None
    display_name: str | None = None
    role: Literal["viewer", "admin"]


class CheckResult(BaseModel):
    ok: bool
    detail: str | None = None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckResult]
