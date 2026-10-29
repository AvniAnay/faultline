"""CLI: `python -m app.worker run` executes one run synchronously (no scheduler in Stage 1)."""

import logging
import sys

from app.config import get_settings
from app.db.migrate import run_migrations
from app.db.repos.runs import RunConflictError
from app.db.repos.sources import ensure_source
from app.db.session import new_session
from app.pipeline.run import run_once


def main(argv: list[str]) -> int:
    logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if argv[1:] != ["run"]:
        print("usage: python -m app.worker run")
        return 2
    s = get_settings()
    run_migrations(s.sync_database_url)
    with new_session() as session:
        ensure_source(session, s)
        session.commit()
    try:
        run = run_once(requested_by=None)
    except RunConflictError:
        print("another run is already requested or running")
        return 1
    print(f"run {run.id} finished with status {run.status}")
    return 0 if run.status in ("completed", "awaiting_review") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
