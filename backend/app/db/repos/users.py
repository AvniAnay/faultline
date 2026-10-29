from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


def users_by_id(session: Session, ids: Iterable[str | None]) -> dict[str, User]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: u for u in session.scalars(select(User).where(User.id.in_(wanted)))}
