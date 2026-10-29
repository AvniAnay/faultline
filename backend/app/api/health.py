import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.schemas import CheckResult, Health
from app.config import get_settings
from app.connectors.elasticsearch import make_client
from app.db.session import new_session

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_db() -> CheckResult:
    try:
        with new_session() as session:
            session.execute(text("SELECT 1"))
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: database check failed: %s", type(exc).__name__)
        return CheckResult(ok=False, detail=type(exc).__name__)


def _check_es() -> CheckResult:
    try:
        make_client(get_settings()).info()
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: elasticsearch check failed: %s", type(exc).__name__)
        return CheckResult(ok=False, detail=type(exc).__name__)


@router.get("/health", response_model=Health)
def health() -> JSONResponse:
    checks = {"database": _check_db(), "elasticsearch": _check_es()}
    ok = all(c.ok for c in checks.values())
    body = Health(status="ok" if ok else "degraded", checks=checks)
    return JSONResponse(body.model_dump(exclude_none=True), status_code=200 if ok else 503)
