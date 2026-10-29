import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api import mappers
from app.api import schemas as S
from app.api.errors_handling import ApiError
from app.auth import CurrentUser, require_role
from app.db.repos import reviews as reviews_repo
from app.db.repos import runs as runs_repo
from app.db.session import get_session
from app.pipeline.run import execute_run, resume_run, start_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs")


@router.get("", response_model=S.Page[S.Run], dependencies=[Depends(require_role("viewer"))])
def list_runs(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    session: Session = Depends(get_session),
) -> S.Page[S.Run]:
    rows, total = runs_repo.list_runs(session, page, page_size)
    return S.Page(items=mappers.runs(session, rows), total=total, page=page, page_size=page_size)


@router.post("/trigger", response_model=S.Run, status_code=202)
def trigger(
    background: BackgroundTasks,
    user: CurrentUser = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> S.Run:
    try:
        run = start_run(user.id)
    except runs_repo.RunConflictError:
        raise ApiError(409, "Another run is already requested or running") from None
    background.add_task(execute_run, run.id)
    return mappers.runs(session, [run])[0]


@router.get("/{run_id}", response_model=S.Run, dependencies=[Depends(require_role("viewer"))])
def get_run(run_id: uuid.UUID, session: Session = Depends(get_session)) -> S.Run:
    run = runs_repo.get_run(session, run_id)
    if run is None:
        raise ApiError(404, "Run not found")
    return mappers.runs(session, [run])[0]


@router.post("/{run_id}/review/submit", response_model=S.Run, dependencies=[Depends(require_role("admin"))])
def submit_review(run_id: uuid.UUID, session: Session = Depends(get_session)) -> S.Run:
    run = session.get(runs_repo.Run, run_id, with_for_update=True)
    if run is None:
        raise ApiError(404, "Run not found")
    if run.status != "awaiting_review":
        raise ApiError(409, f"Run is {run.status}, not awaiting_review")
    pending = reviews_repo.pending_ids(session, run_id)
    if pending:
        raise ApiError(
            422, "Some review items are still pending",
            [{"field": f"review_items.{i}", "message": "decision is still pending"} for i in pending],
        )
    run.status = "sending"  # claims the run so a concurrent submit gets 409
    session.commit()
    resume_run(run_id)
    session.expire_all()
    return mappers.runs(session, [runs_repo.get_run(session, run_id)])[0]
