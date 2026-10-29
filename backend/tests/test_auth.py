import time
import unittest
from types import SimpleNamespace
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.api.schemas import CheckResult
from app.config import get_settings
from app.main import create_app

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
S = get_settings()


def token(roles=("faultline-viewer",), key=KEY, iss=None, azp=None, exp_delta=300, **extra):
    claims = {
        "sub": "user-1", "iss": iss or S.keycloak_issuer, "azp": azp or S.keycloak_client_id,
        "exp": int(time.time()) + exp_delta, "email": "a@b.com", "name": "Ann",
        "realm_access": {"roles": list(roles)}, **extra,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


class FakeJwks:
    def get_signing_key_from_jwt(self, _token):
        return SimpleNamespace(key=KEY.public_key())


class AuthTests(unittest.TestCase):
    def setUp(self):
        for target, value in (("app.auth.get_jwks_client", lambda: FakeJwks()), ("app.auth.sync_user", lambda user: None)):
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(create_app())

    def get(self, path, tok=None, method="get"):
        headers = {"Authorization": f"Bearer {tok}"} if tok else {}
        return getattr(self.client, method)(path, headers=headers)

    def test_valid_token(self):
        r = self.get("/api/me", token())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"id": "user-1", "email": "a@b.com", "display_name": "Ann", "role": "viewer"})

    def test_admin_role_wins(self):
        r = self.get("/api/me", token(roles=("faultline-viewer", "faultline-admin")))
        self.assertEqual(r.json()["role"], "admin")

    def test_missing_token(self):
        r = self.get("/api/me")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["code"], "unauthorized")

    def test_bad_tokens_are_401(self):
        cases = {
            "expired": token(exp_delta=-10),
            "wrong issuer": token(iss="http://evil/realms/x"),
            "wrong azp": token(azp="other-client"),
            "bad signature": token(key=OTHER_KEY),
            "garbage": "not-a-jwt",
        }
        for name, tok in cases.items():
            with self.subTest(name):
                r = self.get("/api/me", tok)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.json()["code"], "unauthorized")

    def test_no_faultline_role_is_403(self):
        r = self.get("/api/me", token(roles=("some-other-role",)))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["code"], "forbidden")

    def test_viewer_cannot_use_admin_endpoints(self):
        viewer = token()
        for method, path in (
            ("post", "/api/runs/trigger"),
            ("post", "/api/runs/00000000-0000-0000-0000-000000000000/review/submit"),
            ("put", "/api/review-items/00000000-0000-0000-0000-000000000000"),
        ):
            with self.subTest(path):
                r = self.get(path, viewer, method=method)
                self.assertEqual(r.status_code, 403)

    def test_health_needs_no_token(self):
        ok = CheckResult(ok=True)
        with mock.patch("app.api.health._check_db", return_value=ok), mock.patch("app.api.health._check_es", return_value=ok):
            r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_unknown_route_uses_standard_error_body(self):
        r = self.client.get("/api/nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "not_found")

    def test_validation_error_body(self):
        r = self.get("/api/errors?page=0", token())
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertEqual(body["code"], "validation_error")
        self.assertTrue(body["details"][0]["field"].endswith("page"))


if __name__ == "__main__":
    unittest.main()
