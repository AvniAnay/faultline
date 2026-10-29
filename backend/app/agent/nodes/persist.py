"""persist: save approved resolutions, update fingerprints, complete the run."""

import uuid
from collections.abc import Callable
from datetime import datetime

from app.agent.deps import Deps
from app.agent.review_utils import effective
from app.agent.state import RunState
from app.db.models import Fingerprint, Resolution
from app.db.repos.runs import set_status


def make_persist(deps: Deps) -> Callable[[RunState], dict]:
    def persist(state: RunState) -> dict:
        run_id = uuid.UUID(state["run_id"])
        with deps.session_factory() as session:
            for fp_id_str, d in state["decisions"].items():
                fp_id = uuid.UUID(fp_id_str)
                fp = session.get(Fingerprint, fp_id, with_for_update=True)
                if fp is None or d["decision"] == "pending":
                    continue
                if d["decision"] in ("approved", "edited"):
                    eff = effective(d["proposed"], d["edits"])
                    res = eff["resolution"]
                    session.add(
                        Resolution(
                            fingerprint_id=fp_id, summary=res["summary"], probable_cause=res["probable_cause"],
                            steps=res["steps"], sources=res["sources"], confidence=res["confidence"],
                            origin=res["origin"], status="approved", approved_by=d["reviewer"],
                            approved_at=datetime.fromisoformat(d["decided_at"]) if d["decided_at"] else None,
                        )
                    )
                    fp.category, fp.severity = eff["category"], eff["severity"]
                if fp.status == "new":
                    fp.status = "open"
            session.commit()
            set_status(session, run_id, "completed", finished=True)
        return {}

    return persist

