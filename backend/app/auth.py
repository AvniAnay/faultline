"""Keycloak bearer-token validation (PyJWT + JWKS) and role checks."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.dialects.postgresql import insert

from app.api.errors_handling import ApiError
from app.config import get_settings
from app.db.models import User
from app.db.session import new_session

logger = logging.getLogger(__name__)

Role = Literal["viewer", "admin"]
ROLE_RANK = {"viewer": 1, "admin": 2}
USER_SYNC_SECONDS = 300
_bearer = HTTPBearer(auto_error=False)
_last_sync: dict[str, tuple[float, str]] = {}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    display_name: str | None
    role: Role


@lru_cache
def get_jwks_client() -> PyJWKClient:
    s = get_settings()
    return PyJWKClient(f"{s.keycloak_issuer}/protocol/openid-connect/certs", cache_keys=True, lifespan=3600)


def decode_token(token: str) -> dict:
    """Verify signature, iss, exp and azp. Raises ApiError(401)."""
    s = get_settings()
    try:
        key = get_jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=[a.strip() for a in s.keycloak_algorithms.split(",")],
            issuer=s.keycloak_issuer, options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWKClientConnectionError:
        logger.error("could not fetch Keycloak signing keys")
        raise ApiError(401, "Could not verify token") from None
    except jwt.PyJWTError:
        raise ApiError(401, "Invalid or expired token") from None
    if claims.get("azp") != s.keycloak_client_id:
        raise ApiError(401, "Token was not issued for this application")
    return claims


def role_from_claims(claims: dict) -> Role | None:
    roles = (claims.get("realm_access") or {}).get("roles") or []
    if "faultline-admin" in roles:
        return "admin"
    if "faultline-viewer" in roles:
        return "viewer"
    return None


def sync_user(user: CurrentUser) -> None:
    """Upsert the users row at most once per 5 minutes per user (or when the role changes)."""
    last = _last_sync.get(user.id)
    if last and time.monotonic() - last[0] < USER_SYNC_SECONDS and last[1] == user.role:
        return
    now = datetime.now(UTC)
    stmt = insert(User).values(
        id=user.id, email=user.email, display_name=user.display_name, role=user.role, last_seen_at=now, created_at=now
    )
    with new_session() as session:
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[User.id],
                set_={"email": stmt.excluded.email, "display_name": stmt.excluded.display_name,
                      "role": stmt.excluded.role, "last_seen_at": now},
            )
        )
        session.commit()
    _last_sync[user.id] = (time.monotonic(), user.role)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if creds is None:
        raise ApiError(401, "Missing bearer token")
    claims = decode_token(creds.credentials)
    role = role_from_claims(claims)
    if role is None:
        raise ApiError(403, "You have no Faultline role")
    user = CurrentUser(
        id=claims["sub"], email=claims.get("email"), role=role,
        display_name=claims.get("name") or claims.get("preferred_username"),
    )
    sync_user(user)
    return user


def require_role(minimum: Role):
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise ApiError(403, f"Requires role {minimum}")
        return user

    return dependency
