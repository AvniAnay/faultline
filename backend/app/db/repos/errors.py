import uuid
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.db.models import Fingerprint, Occurrence, Resolution, ReviewItem, Run, Sample

SORT_FIELDS = {"severity", "last_seen", "first_seen", "total_count", "service", "status"}
SEVERITY_RANK = case(
    (Fingerprint.severity == "Critical", 4),
    (Fingerprint.severity == "High", 3),
    (Fingerprint.severity == "Medium", 2),
    (Fingerprint.severity == "Low", 1),
    else_=0,
)


def list_errors(
    session: Session, page: int, page_size: int, statuses: list[str], sort: str
) -> tuple[list[Fingerprint], int]:
    desc = sort.startswith("-")
    field = sort.lstrip("-")
    if field not in SORT_FIELDS:
        raise ValueError(field)
    stmt: Select = select(Fingerprint).where(Fingerprint.status != "merged")
    if statuses:
        stmt = stmt.where(Fingerprint.status.in_(statuses))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SEVERITY_RANK if field == "severity" else getattr(Fingerprint, field)
    stmt = stmt.order_by(col.desc() if desc else col.asc(), Fingerprint.id).limit(page_size).offset((page - 1) * page_size)
    return list(session.scalars(stmt)), total


def get_error(session: Session, fingerprint_id: uuid.UUID) -> Fingerprint | None:
    return session.get(Fingerprint, fingerprint_id)


def samples_for(session: Session, fingerprint_ids: list[uuid.UUID], limit: int = 5) -> dict[uuid.UUID, list[Sample]]:
    out: dict[uuid.UUID, list[Sample]] = {i: [] for i in fingerprint_ids}
    rows = session.scalars(
        select(Sample).where(Sample.fingerprint_id.in_(fingerprint_ids)).order_by(Sample.seen_at.desc(), Sample.id.desc())
    )
    for s in rows:
        if len(out[s.fingerprint_id]) < limit:
            out[s.fingerprint_id].append(s)
    return out


def resolutions_for(session: Session, fingerprint_id: uuid.UUID) -> list[Resolution]:
    return list(
        session.scalars(
            select(Resolution).where(Resolution.fingerprint_id == fingerprint_id)
            .order_by(Resolution.approved_at.desc().nulls_last(), Resolution.id)
        )
    )


def review_items_for_error(session: Session, fingerprint_id: uuid.UUID) -> list[tuple[ReviewItem, Run]]:
    """Newest run first."""
    stmt = (
        select(ReviewItem, Run).join(Run, Run.id == ReviewItem.run_id)
        .where(ReviewItem.fingerprint_id == fingerprint_id)
        .order_by(Run.started_at.desc().nulls_last())
    )
    return [(i, r) for i, r in session.execute(stmt)]


def occurrence_series(
    session: Session, fingerprint_id: uuid.UUID, bucket: Literal["hour", "day"], start: datetime, end: datetime
) -> list[tuple[datetime, int]]:
    """Zero-filled (bucket_start, count), oldest first; buckets are UTC."""
    trunc = func.date_trunc(bucket, func.timezone("UTC", Occurrence.window_start))
    first = start.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        first = first.replace(hour=0)
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    rows = session.execute(
        select(trunc, func.sum(Occurrence.count))
        .where(Occurrence.fingerprint_id == fingerprint_id, Occurrence.window_start >= first, Occurrence.window_start <= end)
        .group_by(trunc)
    )
    found = {ts.replace(tzinfo=first.tzinfo): int(n) for ts, n in rows}
    points, cur = [], first
    while cur <= end:
        points.append((cur, found.get(cur, 0)))
        cur += step
    return points
