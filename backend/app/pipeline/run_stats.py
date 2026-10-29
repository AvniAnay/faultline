"""Incremental run stats persisted to runs.stats (counts of LLM/Tavily calls, tokens, emails)."""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.models import Run


class StatsTracker:
    def __init__(self, run_id: uuid.UUID | str, session_factory: Callable[[], Session]) -> None:
        self.run_id = uuid.UUID(str(run_id))
        self.session_factory = session_factory

    def _mutate(self, fn: Callable[[dict], None]) -> None:
        with self.session_factory() as session:
            run = session.get(Run, self.run_id, with_for_update=True)
            if run is None:
                return
            stats = dict(run.stats or {})
            fn(stats)
            run.stats = stats
            session.commit()

    def add(self, **counters: int) -> None:
        def apply(stats: dict) -> None:
            for key, n in counters.items():
                stats[key] = int(stats.get(key, 0)) + n

        self._mutate(apply)

    def add_tokens(self, prompt: int, completion: int) -> None:
        def apply(stats: dict) -> None:
            t = dict(stats.get("llm_tokens") or {"prompt": 0, "completion": 0, "total": 0})
            t["prompt"] += prompt
            t["completion"] += completion
            t["total"] = t["prompt"] + t["completion"]
            stats["llm_tokens"] = t

        self._mutate(apply)
