from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Source

DEFAULT_SOURCE = "default"


def ensure_source(session: Session, s: Settings) -> Source:
    """Seed the single source row from ES_* env on startup (idempotent; keeps the watermark)."""
    src = session.scalar(select(Source).where(Source.name == DEFAULT_SOURCE))
    if src is None:
        src = Source(name=DEFAULT_SOURCE)
        session.add(src)
    src.es_url = s.es_url
    src.index_pattern = s.es_index_pattern
    src.service_field = s.es_service_field
    session.flush()
    return src


def get_source(session: Session) -> Source:
    src = session.scalar(select(Source).where(Source.name == DEFAULT_SOURCE).with_for_update())
    if src is None:
        raise RuntimeError("source row missing; ensure_source() must run on startup")
    return src
