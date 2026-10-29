"""Shared auth helpers for API tests: local RSA key + patched JWKS/user sync."""

import time
from types import SimpleNamespace
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import get_settings

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def bearer(role: str) -> dict[str, str]:
    s = get_settings()
    roles = {"admin": ["faultline-admin"], "viewer": ["faultline-viewer"]}[role]
    tok = jwt.encode(
        {"sub": f"{role}-1", "iss": s.keycloak_issuer, "azp": s.keycloak_client_id, "exp": int(time.time()) + 600,
         "email": f"{role}@example.com", "name": role.title(), "realm_access": {"roles": roles}},
        _KEY, algorithm="RS256", headers={"kid": "k"},
    )
    return {"Authorization": f"Bearer {tok}"}


def patch_auth(case) -> None:
    fake = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=_KEY.public_key()))
    for target, value in (("app.auth.get_jwks_client", lambda: fake), ("app.auth.sync_user", lambda user: None)):
        p = mock.patch(target, value)
        p.start()
        case.addCleanup(p.stop)
