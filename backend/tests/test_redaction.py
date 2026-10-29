import unittest

from app.redaction.engine import RedactedText, RedactionError, redact, require_redacted
from app.redaction.rules import luhn_valid


def r(text: str) -> str:
    return redact(text).text.text


class RedactionRules(unittest.TestCase):
    def test_1_private_key(self):
        key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEFAKEFAKE\n-----END RSA PRIVATE KEY-----"
        self.assertEqual(r(f"SIGNING_KEY={key} done"), "SIGNING_KEY=<PRIVATE_KEY> done")
        self.assertEqual(r("public key -----BEGIN PUBLIC KEY----- abc"), "public key -----BEGIN PUBLIC KEY----- abc")

    def test_1_truncated_private_key_is_still_removed(self):
        self.assertEqual(r("k=-----BEGIN RSA PRIVATE KEY----- MIIEFAKE"), "k=<PRIVATE_KEY>")

    def test_2_connection_string(self):
        out = r("db: postgresql://payment_user:hunter2!@cache-08.corp.example.com:5432/payments")
        self.assertEqual(out, "db: <CONN_STRING>")
        self.assertEqual(r("jdbc:postgresql://h/db?user=a&password=s3cret&ssl=1"), "<CONN_STRING>")
        text = "GET https://api.example.com:8080/x?e=a@b"  # host:port + @ is not a credentialed URL
        self.assertEqual(r(text), text)

    def test_3_jwt(self):
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"
        self.assertEqual(r(f"token was {jwt} ok"), "token was <JWT> ok")
        self.assertEqual(r("eyJust a word"), "eyJust a word")

    def test_4_auth_header(self):
        self.assertEqual(r("Authorization: Bearer abcDEF123456xyz"), "Authorization: Bearer <TOKEN>")
        self.assertEqual(r("Authorization: Basic dXNlcjpwYXNz"), "Authorization: Basic <TOKEN>")
        self.assertEqual(r("Basic authentication failed; Bearer of bad news"), "Basic authentication failed; Bearer of bad news")

    def test_5_key_value_secrets(self):
        self.assertEqual(r("password=Winter2026! next"), "password=<SECRET> next")
        self.assertEqual(r('{"password": "Lucknow@2026", "a": 1}'), '{"password": "<SECRET>", "a": 1}')
        self.assertEqual(r("x?token=cadQVunsEr6M&y=1"), "x?token=<SECRET>&y=1")
        self.assertEqual(r("a&client_secret%3Des2YgGXI1V4H"), "a&client_secret%3D<SECRET>")
        self.assertEqual(r("api_key=fSXEiG2METPxl2yFEikm"), "api_key=<SECRET>")
        self.assertEqual(r("invalid password for user; token validation failed"), "invalid password for user; token validation failed")

    def test_6_cloud_keys(self):
        self.assertEqual(r("key AKIAIOSFODNN7EXAMPLE used"), "key <CLOUD_KEY> used")
        self.assertEqual(r("AKIA123 and ASIAshort"), "AKIA123 and ASIAshort")

    def test_7_email(self):
        self.assertEqual(r("to priya.sharma12@example.in now"), "to <EMAIL> now")
        self.assertEqual(r("mail @handle and a@b"), "mail @handle and a@b")

    def test_8_card_luhn(self):
        self.assertEqual(r("card 4111 1111 1111 1111 x"), "card <CARD> x")
        self.assertEqual(r("card 5555-5555-5555-4444"), "card <CARD>")
        self.assertEqual(r("amex 378282246310005"), "amex <CARD>")
        self.assertEqual(r("Order reference 2995329215989116 not found"), "Order reference 2995329215989116 not found")
        self.assertTrue(luhn_valid("4111111111111111"))
        self.assertFalse(luhn_valid("2995329215989116"))

    def test_9_ip(self):
        self.assertEqual(r("from 10.4.22.7:8080 and 203.0.113.9"), "from <IP>:8080 and <IP>")
        self.assertEqual(r("client 2001:db8:1a:2b::3c ok"), "client <IP> ok")
        self.assertEqual(r("999.1.1.1 v2.14.3 at 14:31:42 1.2.3.4.5"), "999.1.1.1 v2.14.3 at 14:31:42 1.2.3.4.5")

    def test_10_internal_hosts_and_urls(self):
        self.assertEqual(r("host db-03.corp.example.com down"), "host <HOST> down")
        self.assertEqual(r("GET https://cache-05.corp.example.com/v2/charge now"), "GET <URL> now")
        self.assertEqual(r("svc orders.internal up"), "svc <HOST> up")
        self.assertEqual(r("see https://example.com/docs and api.example.com"), "see https://example.com/docs and api.example.com")

    def test_10_allowlist_keeps_public_vendor_host(self):
        text = "Calling public API https://api.stripe.com/v1/charges took 2.4s"
        self.assertEqual(r(text), text)

    def test_11_phone(self):
        self.assertEqual(r("sms +91 9876543210 failed"), "sms <PHONE> failed")
        self.assertEqual(r("sms +91-98765-43210 failed"), "sms <PHONE> failed")
        self.assertEqual(r("to 9658429212: provider"), "to <PHONE>: provider")
        self.assertEqual(r("took 2245ms, id 12345678901234567890"), "took 2245ms, id 12345678901234567890")

    def test_counts_per_rule(self):
        res = redact("a@b.com c@d.org from 10.0.0.1")
        self.assertEqual(res.counts, {"email": 2, "ipv4": 1})

    def test_uuid_and_versions_untouched(self):
        text = "id=ceacee11-595f-449c-a3ff-f51c8fcb9a10 version=v2.16.1"
        self.assertEqual(r(text), text)


class RedactedTextType(unittest.TestCase):
    def test_cannot_construct_directly(self):
        with self.assertRaises(TypeError):
            RedactedText("raw")

    def test_require_redacted_rejects_str(self):
        with self.assertRaises(TypeError):
            require_redacted("plain")

    def test_fail_closed(self):
        class Boom:
            pattern = None

        with self.assertRaises(RedactionError):
            redact("x", rules=[Boom()])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
