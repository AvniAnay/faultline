import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.db.models import Run

LOCK_KEY = 727_002
ACTIVE = ("requested", "running")


class RunConflictError(Exception):
    """Another run is requested or running."""


def create_run(session: Session, requested_by: str | None) -> Run:
    """Insert a `running` run; raises RunConflictError if one is already requested/running."""
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    if session.scalar(select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE))):
        session.rollback()
        raise RunConflictError
    run = Run(id=uuid.uuid4(), requested_by=requested_by, started_at=datetime.now(UTC), status="running", stats={})
    session.add(run)
    session.commit()
    return run


def set_status(session: Session, run_id: uuid.UUID, status: str, finished: bool = False) -> None:
    values: dict = {"status": status}
    if finished:
        values["finished_at"] = datetime.now(UTC)
    session.execute(update(Run).where(Run.id == run_id).values(**values))
    session.commit()


def merge_stats(session: Session, run_id: uuid.UUID, values: dict) -> None:
    run = session.get(Run, run_id, with_for_update=True)
    if run is not None:
        run.stats = {**(run.stats or {}), **values}
        session.commit()


def fail_run(session: Session, run_id: uuid.UUID, error: str) -> None:
    run = session.get(Run, run_id, with_for_update=True)
    if run is None:
        return
    run.stats = {**(run.stats or {}), "error": error[:500]}
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    session.commit()


def fail_interrupted(session: Session) -> int:
    """On API startup: runs left `running` by a previous process are failed."""
    runs = session.scalars(select(Run).where(Run.status == "running").with_for_update()).all()
    for run in runs:
        run.stats = {**(run.stats or {}), "error": "interrupted by restart"}
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
    session.commit()
    return len(runs)


def get_run(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session, page: int, page_size: int) -> tuple[list[Run], int]:
    total = session.scalar(select(func.count()).select_from(Run)) or 0
    rows = session.scalars(
        select(Run).order_by(Run.started_at.desc().nulls_last()).limit(page_size).offset((page - 1) * page_size)
    )
    return list(rows), total
