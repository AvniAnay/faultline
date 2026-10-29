"""Agent state models (spec 5.7). Everything stored here is already redacted text."""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Category = Literal["System", "Application", "Database", "Network", "Security", "Infrastructure", "Third-party", "Unknown"]
Severity = Literal["Critical", "High", "Medium", "Low"]
Confidence = Literal["high", "medium", "low"]
Origin = Literal["kb", "web", "llm_only"]

CATEGORIES: tuple[str, ...] = ("System", "Application", "Database", "Network", "Security", "Infrastructure", "Third-party", "Unknown")
SEVERITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


class ResolutionDraft(BaseModel):
    summary: str
    probable_cause: str
    steps: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: Confidence = "low"
    origin: Origin = "llm_only"


class ErrorItem(BaseModel):
    fingerprint_id: str
    service: str
    level: str
    template: str  # redacted
    samples: list[str] = Field(default_factory=list)  # redacted, newest first
    count: int  # occurrences in this run's window
    flags: list[str] = Field(default_factory=list)
    category: str | None = None
    category_reason: str | None = None
    severity: str | None = None
    severity_reason: str | None = None
    team: str | None = None
    search_query: str | None = None
    resolution: ResolutionDraft | None = None


class RunState(TypedDict):
    run_id: str
    items: list[ErrorItem]
    decisions: dict[str, dict]  # fingerprint_id -> {decision, edits, reviewer, comment}
