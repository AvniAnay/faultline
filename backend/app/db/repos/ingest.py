"""Writes used by the ingestion stage (all inside the caller's transaction)."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Fingerprint, Occurrence, Sample
from app.redaction.engine import RedactedText, require_redacted

MAX_SAMPLES = 5
LEVEL_RANK = {"WARN": 1, "ERROR": 2, "CRITICAL": 3, "FATAL": 4}


def load_fingerprints(session: Session, keys: set[tuple[str, int]]) -> dict[tuple[str, int], Fingerprint]:
    if not keys:
        return {}
    services = {k[0] for k in keys}
    rows = session.scalars(select(Fingerprint).where(Fingerprint.service.in_(services)))
    return {(f.service, f.drain_cluster_id): f for f in rows if (f.service, f.drain_cluster_id) in keys}


def upsert_fingerprint(
    session: Session,
    existing: Fingerprint | None,
    service: str,
    cluster_id: int,
    template: RedactedText,
    level: str,
    first_seen: datetime,
    last_seen: datetime,
    count: int,
) -> tuple[Fingerprint, bool]:
    """Returns (fingerprint, created)."""
    text = require_redacted(template)
    if existing is None:
        fp = Fingerprint(
            id=uuid.uuid4(), service=service, drain_cluster_id=cluster_id, template=text, level=level,
            status="new", first_seen=first_seen, last_seen=last_seen, total_count=count,
        )
        session.add(fp)
        return fp, True
    existing.template = text
    existing.first_seen = min(existing.first_seen, first_seen)
    existing.last_seen = max(existing.last_seen, last_seen)
    existing.total_count += count
    if LEVEL_RANK.get(level, 0) > LEVEL_RANK.get(existing.level, 0):
        existing.level = level
    return existing, False


def add_occurrences(
    session: Session, fingerprint_id: uuid.UUID, run_id: uuid.UUID, buckets: dict[datetime, tuple[datetime, int]]
) -> None:
    """buckets: bucket_start -> (bucket_end, count)."""
    for start, (end, count) in buckets.items():
        session.add(Occurrence(fingerprint_id=fingerprint_id, run_id=run_id, window_start=start, window_end=end, count=count))


def add_samples(session: Session, fingerprint_id: uuid.UUID, samples: list[tuple[datetime, RedactedText]]) -> None:
    for seen_at, text in samples:
        session.add(Sample(fingerprint_id=fingerprint_id, redacted_text=require_redacted(text), seen_at=seen_at))
    session.flush()
    keep = select(Sample.id).where(Sample.fingerprint_id == fingerprint_id).order_by(
        Sample.seen_at.desc(), Sample.id.desc()
    ).limit(MAX_SAMPLES)
    session.execute(
        delete(Sample).where(Sample.fingerprint_id == fingerprint_id, Sample.id.not_in(keep.scalar_subquery()))
    )


def baseline_total(session: Session, fingerprint_id: uuid.UUID, start: datetime, end: datetime) -> int:
    from sqlalchemy import func

    total = session.scalar(
        select(func.coalesce(func.sum(Occurrence.count), 0)).where(
            Occurrence.fingerprint_id == fingerprint_id,
            Occurrence.window_start >= start,
            Occurrence.window_start < end,
        )
    )
    return int(total or 0)
