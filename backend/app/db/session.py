from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def new_session() -> Session:
    return sessionmaker(get_engine(), expire_on_commit=False)()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with new_session() as session:
        yield session
