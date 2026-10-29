import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import errors, health, me, reviews, runs
from app.api.errors_handling import install_error_handlers
from app.config import get_settings
from app.db.migrate import run_migrations
from app.db.repos.runs import fail_interrupted
from app.db.repos.sources import ensure_source
from app.db.session import new_session

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    applied = run_migrations(s.sync_database_url)
    logger.info("migrations applied: %s", applied or "none")
    with new_session() as session:
        ensure_source(session, s)
        session.commit()
        n = fail_interrupted(session)
        if n:
            logger.warning("marked %d interrupted run(s) as failed", n)
    from app.agent.graph import get_checkpointer

    get_checkpointer()  # creates LangGraph checkpoint tables
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Faultline", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_methods=["*"], allow_headers=["*"]
    )
    install_error_handlers(app)
    api = APIRouter(prefix="/api")
    for module in (health, me, errors, runs, reviews):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
