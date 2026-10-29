import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import mappers
from app.api import schemas as S
from app.api.errors_handling import ApiError
from app.auth import CurrentUser, require_role
from app.db.models import Fingerprint, Run
from app.db.repos import reviews as repo
from app.db.session import get_session
from app.redaction.engine import RedactionError, redact_user_text

router = APIRouter()


@router.get("/reviews/pending", response_model=S.PendingReviews, dependencies=[Depends(require_role("viewer"))])
def pending(session: Session = Depends(get_session)) -> S.PendingReviews:
    runs = repo.pending_runs(session)
    run_schemas = {r.id: r for r in mappers.runs(session, runs)}
    rows = repo.items_for_runs(session, [r.id for r in runs])
    items = mappers.review_items(session, rows)
    return S.PendingReviews(
        runs=[S.PendingRun(run=run_schemas[r.id], items=[i for i in items if i.run_id == r.id]) for r in runs]
    )


def _redacted_edits(edited: S.ReviewEdits) -> dict:
    """Redact free text before storage (a failure rejects the request; nothing is stored)."""
    data = edited.model_dump(exclude_none=True)
    res = data.get("resolution") or {}
    for key in ("summary", "probable_cause"):
        if key in res:
            res[key] = redact_user_text(res[key]).text
    if "steps" in res:
        res["steps"] = [redact_user_text(s).text for s in res["steps"]]
    return data


@router.put("/review-items/{item_id}", response_model=S.ReviewItem)
def decide(
    item_id: uuid.UUID,
    body: S.ReviewDecisionIn,
    user: CurrentUser = Depends(require_role("admin")),
    session: Session = Depends(get_session),
) -> S.ReviewItem:
    item = repo.get_item(session, item_id, lock=True)
    if item is None:
        raise ApiError(404, "Review item not found")
    run = session.get(Run, item.run_id)
    if run is None or run.status != "awaiting_review":
        raise ApiError(409, "Run is not awaiting review")
    try:
        edited = _redacted_edits(body.edited) if body.edited else None
        comment = redact_user_text(body.comment).text if body.comment else None
    except RedactionError:
        raise ApiError(422, "Text could not be safely processed; please rephrase") from None
    repo.record_decision(item, body.decision, edited, comment, user.id)
    session.commit()
    fp = session.get(Fingerprint, item.fingerprint_id)
    return mappers.review_items(session, [(item, fp)])[0]
