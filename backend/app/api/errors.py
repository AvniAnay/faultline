import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import mappers
from app.api import schemas as S
from app.api.errors_handling import ApiError
from app.auth import require_role
from app.db.repos import errors as repo
from app.db.session import get_session

router = APIRouter(prefix="/errors", dependencies=[Depends(require_role("viewer"))])


@router.get("", response_model=S.Page[S.ErrorSummary])
def list_errors(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status: Annotated[list[str] | None, Query()] = None,
    sort: str = "-last_seen",
    session: Session = Depends(get_session),
) -> S.Page[S.ErrorSummary]:
    if sort.lstrip("-") not in repo.SORT_FIELDS:
        raise ApiError(422, "Invalid sort", [{"field": "query.sort", "message": f"allowed: {sorted(repo.SORT_FIELDS)}"}])
    rows, total = repo.list_errors(session, page, page_size, status or [], sort)
    return S.Page(items=[mappers.error_summary(r) for r in rows], total=total, page=page, page_size=page_size)


def _get_or_404(session: Session, error_id: uuid.UUID):
    fp = repo.get_error(session, error_id)
    if fp is None:
        raise ApiError(404, "Error not found")
    return fp


@router.get("/{error_id}", response_model=S.ErrorDetail)
def error_detail(error_id: uuid.UUID, session: Session = Depends(get_session)) -> S.ErrorDetail:
    return mappers.error_detail(session, _get_or_404(session, error_id))


def _utc(ts: datetime | None, field: str) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        raise ApiError(422, "Timestamp needs a UTC offset", [{"field": f"query.{field}", "message": "missing timezone offset"}])
    return ts.astimezone(UTC)


@router.get("/{error_id}/occurrences", response_model=S.OccurrenceSeries)
def occurrences(
    error_id: uuid.UUID,
    bucket: Literal["hour", "day"] = "day",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    session: Session = Depends(get_session),
) -> S.OccurrenceSeries:
    _get_or_404(session, error_id)
    end = _utc(to, "to") or datetime.now(UTC)
    start = _utc(from_, "from") or end - timedelta(days=7)
    if start > end:
        raise ApiError(422, "from must be before to", [{"field": "query.from", "message": "must be before 'to'"}])
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    if (end - start) / step > 2000:
        raise ApiError(422, "Range too large for this bucket size", [{"field": "query.from", "message": "range too large"}])
    points = repo.occurrence_series(session, error_id, bucket, start, end)
    return S.OccurrenceSeries(bucket=bucket, points=[S.OccurrencePoint(bucket_start=t, count=n) for t, n in points])
