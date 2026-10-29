"""SQLAlchemy models. The SQL migrations are the source of truth; keep these in sync."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, REAL, BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    es_url: Mapped[str] = mapped_column(Text)
    index_pattern: Mapped[str] = mapped_column(Text)
    service_field: Mapped[str] = mapped_column(Text)
    watermark: Mapped[datetime | None] = mapped_column(TZ)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requested_by: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    window_start: Mapped[datetime | None] = mapped_column(TZ)
    window_end: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)


class Fingerprint(Base):
    __tablename__ = "fingerprints"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    drain_cluster_id: Mapped[int] = mapped_column(Integer)
    template: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(Text)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="new")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fingerprints.id"))
    first_seen: Mapped[datetime] = mapped_column(TZ)
    last_seen: Mapped[datetime] = mapped_column(TZ)
    total_count: Mapped[int] = mapped_column(BigInteger, default=0)
    deferred: Mapped[bool] = mapped_column(Boolean, default=False)
    suppression: Mapped[str] = mapped_column(Text, default="none")
    snoozed_until: Mapped[datetime | None] = mapped_column(TZ)
    alert_on_spike: Mapped[bool] = mapped_column(Boolean, default=False)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    suppressed_by: Mapped[str | None] = mapped_column(Text)
    suppressed_at: Mapped[datetime | None] = mapped_column(TZ)


class Occurrence(Base):
    __tablename__ = "occurrences"
    fingerprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fingerprints.id"), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    window_end: Mapped[datetime] = mapped_column(TZ)
    count: Mapped[int] = mapped_column(Integer)


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fingerprints.id"))
    redacted_text: Mapped[str] = mapped_column(Text)
    seen_at: Mapped[datetime] = mapped_column(TZ)


class Resolution(Base):
    __tablename__ = "resolutions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fingerprints.id"))
    summary: Mapped[str] = mapped_column(Text)
    probable_cause: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSONB, default=list)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    confidence: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(REAL))


class ReviewItem(Base):
    __tablename__ = "review_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"))
    fingerprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fingerprints.id"))
    proposed: Mapped[dict] = mapped_column(JSONB)
    decision: Mapped[str] = mapped_column(Text, default="pending")
    edited: Mapped[dict | None] = mapped_column(JSONB)
    reviewer: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(TZ)


class DrainState(Base):
    __tablename__ = "drain_state"
    service: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(TZ)
