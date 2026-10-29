"""Run lifecycle: create -> ingest+detect -> agent graph (pauses at human review)."""

import logging
import time
import uuid
from datetime import UTC, datetime

from app.config import get_settings
from app.connectors.elasticsearch import make_client
from app.db.models import Run
from app.db.repos import runs as runs_repo
from app.db.session import new_session
from app.pipeline.drain_persistence import PostgresPersistence
from app.pipeline.fingerprint import Drain3Miner
from app.pipeline.ingest import ingest

logger = logging.getLogger(__name__)


def _thread(run_id: uuid.UUID) -> dict:
    return {"configurable": {"thread_id": str(run_id)}}


def start_run(requested_by: str | None) -> Run:
    """Create the run row (status running). Raises RunConflictError if one is active."""
    with new_session() as session:
        return runs_repo.create_run(session, requested_by)


def execute_run(run_id: uuid.UUID, graph=None, es=None) -> None:
    """Ingest, detect, and run the agent up to the review interrupt. Never raises."""
    started = time.monotonic()
    s = get_settings()
    try:
        with new_session() as session:
            miner = Drain3Miner(PostgresPersistence(session))
            result = ingest(session, run_id, es or make_client(s), miner, s)
            run = session.get(Run, run_id)
            run.window_start, run.window_end = result.window_start, result.window_end
            session.commit()  # ingestion is one transaction: everything or nothing
        with new_session() as session:
            runs_repo.merge_stats(session, run_id, result.stats)
            if not result.flagged:
                runs_repo.merge_stats(session, run_id, {"duration_seconds": round(time.monotonic() - started, 1)})
                runs_repo.set_status(session, run_id, "completed", finished=True)
                return
        graph = graph or _graph()
        graph.invoke(
            {"run_id": str(run_id), "items": [i.model_dump() for i in result.flagged], "decisions": {}},
            _thread(run_id),
        )
        with new_session() as session:
            runs_repo.merge_stats(session, run_id, {"duration_seconds": round(time.monotonic() - started, 1)})
    except Exception as exc:  # noqa: BLE001
        logger.exception("run %s failed", run_id)
        with new_session() as session:
            runs_repo.fail_run(session, run_id, f"{type(exc).__name__}: {exc}")


def resume_run(run_id: uuid.UUID, graph=None) -> None:
    """Resume after review. Failure marks the run failed and re-raises for the API to report."""
    from langgraph.types import Command

    try:
        (graph or _graph()).invoke(Command(resume={"submitted_at": datetime.now(UTC).isoformat()}), _thread(run_id))
    except Exception as exc:
        logger.exception("resume of run %s failed", run_id)
        with new_session() as session:
            runs_repo.fail_run(session, run_id, f"{type(exc).__name__}: {exc}")
        raise


def _graph():
    from app.agent.graph import get_graph

    return get_graph()


def run_once(requested_by: str | None) -> Run:
    """Synchronous run (CLI): create + execute. Returns the run in its resulting state."""
    run = start_run(requested_by)
    execute_run(run.id)
    with new_session() as session:
        return session.get(Run, run.id)
