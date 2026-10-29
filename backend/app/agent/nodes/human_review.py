"""human_review: pause with interrupt(); on resume, load decisions from review_items (source of truth)."""

import uuid
from collections.abc import Callable

from langgraph.types import interrupt
from sqlalchemy import select

from app.agent.deps import Deps
from app.agent.state import RunState
from app.db.models import ReviewItem
from app.db.repos.runs import set_status


def make_human_review(deps: Deps) -> Callable[[RunState], dict]:
    def human_review(state: RunState) -> dict:
        interrupt({"run_id": state["run_id"], "awaiting": "review"})  # returns when resumed
        run_id = uuid.UUID(state["run_id"])
        with deps.session_factory() as session:
            set_status(session, run_id, "sending")
            rows = session.scalars(select(ReviewItem).where(ReviewItem.run_id == run_id)).all()
            decisions = {
                str(r.fingerprint_id): {
                    "decision": r.decision, "edits": r.edited, "reviewer": r.reviewer,
                    "comment": r.comment, "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                    "review_item_id": str(r.id), "proposed": r.proposed,
                }
                for r in rows
            }
        return {"decisions": decisions}

    return human_review
