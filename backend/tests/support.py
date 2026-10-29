"""Test support: a throwaway Postgres database, created on first use and dropped at exit."""

import atexit
import os
import uuid

import psycopg

_state: dict = {}


def setup_db() -> str:
    """Create a temp database, point DATABASE_URL at it, apply migrations. Idempotent."""
    if "name" in _state:
        return _state["name"]
    from app.config import get_settings

    base = get_settings()
    name = f"faultline_test_{uuid.uuid4().hex[:8]}"
    admin_url = base.sync_database_url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    os.environ["DATABASE_URL"] = base.database_url.rsplit("/", 1)[0] + "/" + name
    get_settings.cache_clear()
    from app.db.migrate import run_migrations
    from app.db.session import get_engine

    get_engine.cache_clear()
    run_migrations(get_settings().sync_database_url)
    _state.update(name=name, admin=admin_url)
    atexit.register(_drop)
    return name


def _drop() -> None:
    from app.db.session import get_engine

    try:
        from app.agent import graph

        graph._pool().close()
    except Exception:  # noqa: BLE001
        pass
    get_engine().dispose()
    with psycopg.connect(_state["admin"], autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{_state["name"]}" WITH (FORCE)')
