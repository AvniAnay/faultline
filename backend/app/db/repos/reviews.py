import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Fingerprint, ReviewItem, Run

_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def pending_runs(session: Session) -> list[Run]:
    return list(session.scalars(select(Run).where(Run.status == "awaiting_review").order_by(Run.started_at.asc())))


def items_for_runs(session: Session, run_ids: list[uuid.UUID]) -> list[tuple[ReviewItem, Fingerprint]]:
    stmt = select(ReviewItem, Fingerprint).join(Fingerprint, Fingerprint.id == ReviewItem.fingerprint_id).where(
        ReviewItem.run_id.in_(run_ids)
    )
    rows = [(i, f) for i, f in session.execute(stmt)]
    rows.sort(key=lambda r: (-_RANK.get(r[0].proposed.get("severity"), 0), -r[0].proposed.get("window_count", 0)))
    return rows


def get_item(session: Session, item_id: uuid.UUID, lock: bool = False) -> ReviewItem | None:
    return session.get(ReviewItem, item_id, with_for_update=lock)


def pending_count(session: Session, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not run_ids:
        return {}
    rows = session.execute(
        select(ReviewItem.run_id, func.count()).where(ReviewItem.run_id.in_(run_ids), ReviewItem.decision == "pending")
        .group_by(ReviewItem.run_id)
    )
    return {rid: n for rid, n in rows}


def pending_ids(session: Session, run_id: uuid.UUID) -> list[uuid.UUID]:
    return list(session.scalars(select(ReviewItem.id).where(ReviewItem.run_id == run_id, ReviewItem.decision == "pending")))


def record_decision(
    item: ReviewItem, decision: str, edited: dict | None, comment: str | None, reviewer_id: str
) -> None:
    item.decision = decision
    item.edited = edited
    item.comment = comment
    if decision == "pending":
        item.reviewer, item.decided_at = None, None
    else:
        item.reviewer, item.decided_at = reviewer_id, datetime.now(UTC)
