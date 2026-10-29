import unittest

from app.pipeline.preprocess import preprocess

APP = ["com.example.", "/app/"]


def pp(msg: str):
    return preprocess(msg, APP)


class Preprocess(unittest.TestCase):
    def test_java(self):
        r = pp("2026-09-22 14:31:42,689 [http-nio-8080-exec-14] ERROR c.e.payment.PaymentClient - Timeout after 3303ms")
        self.assertEqual((r.level, r.text), ("ERROR", "Timeout after 3303ms"))

    def test_python(self):
        r = pp("2026-09-22 15:13:36,328 - auth_svc.login - ERROR - Login failed")
        self.assertEqual((r.level, r.text), ("ERROR", "Login failed"))

    def test_node(self):
        r = pp("[2026-09-22T14:23:03.892Z] ERROR (inventory-svc/2804): Error: connect ECONNREFUSED")
        self.assertEqual((r.level, r.text), ("ERROR", "Error: connect ECONNREFUSED"))

    def test_nginx_lowercase_level(self):
        r = pp("2026/09/22 14:42:22 [error] 81#2: *65725 upstream timed out")
        self.assertEqual((r.level, r.text), ("ERROR", "upstream timed out"))
        self.assertEqual(pp("2026/09/23 00:10:32 [warn] 76#1: *40968 buffered").level, "WARN")

    def test_postgres_levels(self):
        self.assertEqual(pp("2026-09-22 16:44:51.845 UTC [9061] FATAL:  remaining slots").level, "FATAL")
        self.assertEqual(pp("2026-09-22 16:44:00.873 UTC [5254] WARNING:  checkpoints").level, "WARN")
        self.assertIsNone(pp("2026-09-22 14:21:12.650 UTC [7845] LOG:  checkpoint complete"))

    def test_info_line_containing_exception_is_dropped(self):
        self.assertIsNone(pp("2026-09-22 14:52:26,205 [main] INFO  c.e.payment.PaymentClient - Retry after SocketTimeoutException"))

    def test_level_aliases(self):
        self.assertEqual(pp("2026-09-22 15:18:07,299 - x.y - WARNING - careful").level, "WARN")

    def test_no_prefix_keyword_falls_back_to_error(self):
        self.assertEqual(pp("something threw an Exception here").level, "ERROR")
        self.assertIsNone(pp("all quiet"))

    def test_java_stack_keeps_exception_and_first_three_app_frames(self):
        msg = (
            "2026-09-22 17:51:38,579 [t] ERROR c.e.X - Charge failed\njava.net.SocketTimeoutException: Read timed out\n"
            "\tat java.base/java.net.SocketInputStream.socketRead0(Native Method)\n"
            "\tat com.example.a.A.one(A.java:1)\n\tat com.example.a.B.two(B.java:2)\n"
            "\tat org.springframework.web.Servlet.service(Servlet.java:9)\n"
            "\tat com.example.a.C.three(C.java:3)\n\tat com.example.a.D.four(D.java:4)"
        )
        text = pp(msg).text
        self.assertIn("SocketTimeoutException: Read timed out", text)
        for kept in ("A.one", "B.two", "C.three"):
            self.assertIn(kept, text)
        for dropped in ("socketRead0", "Servlet.service", "D.four"):
            self.assertNotIn(dropped, text)

    def test_python_traceback_drops_framework_frames_and_code(self):
        msg = (
            "2026-09-22 18:12:20,801 - a.b - ERROR - Token failed\nTraceback (most recent call last):\n"
            '  File "/app/auth_svc/tokens.py", line 88, in verify\n    claims = jwt.decode(token)\n'
            '  File "/usr/local/lib/python3.14/site-packages/jwt/api_jwt.py", line 222, in decode\n    raise Expired()\n'
            "jwt.exceptions.ExpiredSignatureError: Signature has expired"
        )
        text = pp(msg).text
        self.assertIn("tokens.py", text)
        self.assertIn("claims = jwt.decode", text)
        self.assertNotIn("api_jwt", text)
        self.assertNotIn("raise Expired", text)
        self.assertIn("ExpiredSignatureError", text)

    def test_whitespace_and_length_cap(self):
        r = preprocess("[2026-09-22T14:23:03.892Z] ERROR (s/1): a   b\n\n c", APP, 3, 5)
        self.assertEqual(r.text, "a b c")


if __name__ == "__main__":
    unittest.main()
