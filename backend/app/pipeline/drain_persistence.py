"""Drain3 PersistenceHandler backed by the drain_state table (single global row)."""

from datetime import UTC, datetime

from drain3.persistence_handler import PersistenceHandler
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import DrainState

GLOBAL_KEY = "__global__"


class PostgresPersistence(PersistenceHandler):
    """Reads/writes inside the caller's session; the caller owns commit/rollback."""

    def __init__(self, session: Session, key: str = GLOBAL_KEY) -> None:
        self.session = session
        self.key = key

    def save_state(self, state: bytes) -> None:
        stmt = insert(DrainState).values(service=self.key, state=state, updated_at=datetime.now(UTC))
        self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[DrainState.service],
                set_={"state": stmt.excluded.state, "updated_at": stmt.excluded.updated_at},
            )
        )

    def load_state(self) -> bytes | None:
        row = self.session.get(DrainState, self.key)
        return bytes(row.state) if row else None
