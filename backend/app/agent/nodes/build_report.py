"""build_report: create pending review_items and move the run to awaiting_review."""

import uuid
from collections.abc import Callable

from sqlalchemy import select

from app.agent.deps import Deps
from app.agent.state import SEVERITY_RANK, ErrorItem, RunState
from app.db.models import ReviewItem
from app.db.repos.runs import set_status


def proposed_json(item: ErrorItem) -> dict:
    assert item.resolution is not None
    return {
        "flags": item.flags,
        "window_count": item.count,
        "category": item.category,
        "category_reason": item.category_reason,
        "severity": item.severity,
        "severity_reason": item.severity_reason,
        "team_name": item.team,
        "resolution": item.resolution.model_dump(),
    }


def make_build_report(deps: Deps) -> Callable[[RunState], dict]:
    def build_report(state: RunState) -> dict:
        run_id = uuid.UUID(state["run_id"])
        items = sorted(
            (ErrorItem.model_validate(d) for d in state["items"]),
            key=lambda i: (-SEVERITY_RANK.get(i.severity or "", 0), -i.count),
        )
        with deps.session_factory() as session:
            existing = set(session.scalars(select(ReviewItem.fingerprint_id).where(ReviewItem.run_id == run_id)))
            for item in items:
                fp_id = uuid.UUID(item.fingerprint_id)
                if fp_id not in existing:  # idempotent if the node is retried
                    session.add(ReviewItem(run_id=run_id, fingerprint_id=fp_id, proposed=proposed_json(item), decision="pending"))
            session.commit()
            set_status(session, run_id, "awaiting_review")
        return {"items": [i.model_dump() for i in items]}

    return build_report
