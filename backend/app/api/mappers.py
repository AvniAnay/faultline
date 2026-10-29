"""ORM rows -> API schemas."""


from sqlalchemy.orm import Session

from app.api import schemas as S
from app.config import get_settings
from app.db.models import Fingerprint, Resolution, ReviewItem, Run
from app.db.models import Sample as SampleRow
from app.db.models import User
from app.db.repos import errors as errors_repo
from app.db.repos import reviews as reviews_repo
from app.db.repos.users import users_by_id


def user_ref(user_id: str | None, users: dict[str, User]) -> S.UserRef | None:
    if not user_id:
        return None
    u = users.get(user_id)
    return S.UserRef(id=user_id, display_name=u.display_name if u else None, email=u.email if u else None)


def sample(row: SampleRow) -> S.Sample:
    return S.Sample(redacted_text=row.redacted_text, seen_at=row.seen_at)


def error_summary(fp: Fingerprint) -> S.ErrorSummary:
    return S.ErrorSummary(
        id=fp.id, service=fp.service, level=fp.level, template=fp.template, category=fp.category,
        severity=fp.severity, team_name=get_settings().default_team_name if fp.category else None,
        status=fp.status, first_seen=fp.first_seen, last_seen=fp.last_seen, total_count=fp.total_count,
    )


def resolution(r: Resolution, users: dict[str, User]) -> S.Resolution:
    return S.Resolution(
        id=r.id, fingerprint_id=r.fingerprint_id, summary=r.summary, probable_cause=r.probable_cause,
        steps=r.steps, sources=r.sources, confidence=r.confidence, origin=r.origin, status=r.status,
        approved_by=user_ref(r.approved_by, users), approved_at=r.approved_at,
    )


def review_items(
    session: Session, rows: list[tuple[ReviewItem, Fingerprint]]
) -> list[S.ReviewItem]:
    samples = errors_repo.samples_for(session, list({f.id for _, f in rows}))
    users = users_by_id(session, [i.reviewer for i, _ in rows])
    return [
        S.ReviewItem(
            id=i.id, run_id=i.run_id, fingerprint_id=i.fingerprint_id,
            error=S.ReviewedError(
                service=f.service, level=f.level, template=f.template, total_count=f.total_count,
                first_seen=f.first_seen, last_seen=f.last_seen, samples=[sample(s) for s in samples[f.id]],
            ),
            proposed=S.ProposedItem.model_validate(i.proposed), decision=i.decision,
            edited=S.ReviewEdits.model_validate(i.edited) if i.edited else None,
            reviewer=user_ref(i.reviewer, users), comment=i.comment, decided_at=i.decided_at,
        )
        for i, f in rows
    ]


def runs(session: Session, rows: list[Run]) -> list[S.Run]:
    users = users_by_id(session, [r.requested_by for r in rows])
    pending = reviews_repo.pending_count(session, [r.id for r in rows])
    return [
        S.Run(
            id=r.id, requested_by=user_ref(r.requested_by, users), started_at=r.started_at,
            finished_at=r.finished_at, window_start=r.window_start, window_end=r.window_end,
            status=r.status, stats=S.RunStats.model_validate(r.stats or {}),
            pending_review_count=pending.get(r.id, 0),
        )
        for r in rows
    ]


def error_detail(session: Session, fp: Fingerprint) -> S.ErrorDetail:
    samples = errors_repo.samples_for(session, [fp.id])[fp.id]
    res_rows = errors_repo.resolutions_for(session, fp.id)
    history = errors_repo.review_items_for_error(session, fp.id)
    users = users_by_id(session, [r.approved_by for r in res_rows] + [i.reviewer for i, _ in history])
    latest_flags = history[0][0].proposed.get("flags", []) if history else []
    pending = next(((i, fp) for i, r in history if i.decision == "pending" and r.status == "awaiting_review"), None)
    return S.ErrorDetail(
        **error_summary(fp).model_dump(), drain_cluster_id=fp.drain_cluster_id,
        samples=[sample(s) for s in samples], latest_flags=latest_flags,
        resolutions=[resolution(r, users) for r in res_rows],
        pending_review_item=review_items(session, [pending])[0] if pending else None,
        review_history=[
            S.ReviewHistoryEntry(
                review_item_id=i.id, run_id=i.run_id, decision=i.decision,
                reviewer=user_ref(i.reviewer, users), comment=i.comment, decided_at=i.decided_at,
            )
            for i, _ in history if i.decision != "pending"
        ],
    )


