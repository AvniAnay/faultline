"""send_email: log one line per approved/edited item (email is not actually sent)."""

from collections.abc import Callable

from app.agent.deps import Deps
from app.agent.review_utils import effective
from app.agent.state import ErrorItem, RunState
from app.pipeline.run_stats import StatsTracker
from app.redaction.engine import redact


def make_send_email(deps: Deps) -> Callable[[RunState], dict]:
    def send_email(state: RunState) -> dict:
        tracker = StatsTracker(state["run_id"], deps.session_factory)
        s = deps.settings
        sent = 0
        for raw in state["items"]:
            item = ErrorItem.model_validate(raw)
            d = state["decisions"].get(item.fingerprint_id)
            if not d or d["decision"] not in ("approved", "edited"):
                continue
            eff = effective(d["proposed"], d["edits"])
            subject = redact(f"[Faultline] {eff['severity']}: {item.service} - {item.template[:80]}").text
            link = f"{s.dashboard_base_url}/errors/{item.fingerprint_id}"
            body = redact(
                f"fingerprint={item.fingerprint_id} severity={eff['severity']} "
                f"summary={eff['resolution']['summary']} link={link}"
            ).text
            deps.email.send(s.default_team_dl, subject, body)
            sent += 1
        tracker.add(emails_logged=sent)
        return {}

    return send_email
