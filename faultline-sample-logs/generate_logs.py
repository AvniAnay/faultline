#!/usr/bin/env python3
"""
Generate realistic sample logs for testing Faultline.

Output is Elasticsearch bulk NDJSON. Uses only the Python standard library.
All secrets, IPs, emails, card numbers, and keys are FAKE (documentation IP
ranges, test card numbers, AWS's published example key, example.com domains).

Usage:
    python generate_logs.py                       # 1000 logs, last 24h, ending now
    python generate_logs.py --count 2000 --hours 48 --seed 7 --out logs.ndjson
"""

import argparse
import base64
import json
import random
import string
from collections import Counter
from datetime import datetime, timedelta, timezone

R = random.Random()

# --------------------------------------------------------------------------
# Fake data helpers
# --------------------------------------------------------------------------

FIRST = ["aarav", "priya", "rahul", "ananya", "vikram", "sneha", "arjun", "kavya", "rohan", "meera", "john", "sara"]
LAST = ["sharma", "verma", "iyer", "gupta", "reddy", "nair", "singh", "patel", "mehta", "smith", "khan"]
PASSWORDS = ["Winter2026!", "P@ssw0rd123", "s3cr3t-Adm1n", "Lucknow@2026", "hunter2!", "Qwerty#789", "changeme123"]
TEST_CARDS = ["4111111111111111", "5555555555554444", "4012888888881881", "378282246310005", "6011111111111117"]
SKUS = ["SKU-TSHIRT-M-BLK", "SKU-MUG-350", "SKU-BOOK-PY314", "SKU-CAP-RED", "SKU-SHOE-42", "SKU-BAG-TRAVEL"]
ORDER_STATES = ["PENDING", "PAID", "PACKED", "SHIPPED", "DELIVERED", "CANCELLED"]


def email():
    return f"{R.choice(FIRST)}.{R.choice(LAST)}{R.randint(1, 99)}@{R.choice(['example.com', 'example.org', 'example.in'])}"


def ip_internal():
    return R.choice([f"10.{R.randint(0, 20)}.{R.randint(0, 255)}.{R.randint(1, 254)}",
                     f"192.168.{R.randint(0, 10)}.{R.randint(1, 254)}"])


def ip_public():  # documentation ranges (RFC 5737)
    return R.choice([f"203.0.113.{R.randint(1, 254)}", f"198.51.100.{R.randint(1, 254)}"])


def ipv6():  # documentation range (RFC 3849)
    return f"2001:db8:{R.randint(0, 0xffff):x}:{R.randint(0, 0xffff):x}::{R.randint(1, 0xffff):x}"


def internal_host():
    return f"{R.choice(['db', 'cache', 'mq', 'app', 'bank-gw'])}-{R.randint(1, 9):02d}.corp.example.com"


def order_id():
    return f"ORD-{R.randint(100000, 999999)}"


def customer_id():
    return f"CUST-{R.randint(100000, 999999)}"


def account_id():
    return f"ACC-{R.randint(10000000, 99999999)}"


def phone():
    n = f"9{R.randint(100000000, 999999999)}"
    return R.choice([f"+91 {n}", f"+91-{n[:5]}-{n[5:]}", n])


def uuid():
    h = "".join(R.choice("0123456789abcdef") for _ in range(32))
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:]}"


def token(n=32):
    return "".join(R.choice(string.ascii_letters + string.digits) for _ in range(n))


def b64url(obj):
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()


def jwt():
    head = b64url({"alg": "RS256", "typ": "JWT"})
    body = b64url({"sub": uuid(), "email": email(), "exp": R.randint(1780000000, 1790000000)})
    sig = "".join(R.choice(string.ascii_letters + string.digits + "-_") for _ in range(43))
    return f"{head}.{body}.{sig}"


def luhn_ok(num):
    digits = [int(d) for d in num][::-1]
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digits))
    return total % 10 == 0


def card():
    c = R.choice(TEST_CARDS)
    style = R.choice(["plain", "spaces", "dashes"])
    if style == "spaces" and len(c) == 16:
        return " ".join(c[i:i + 4] for i in range(0, 16, 4))
    if style == "dashes" and len(c) == 16:
        return "-".join(c[i:i + 4] for i in range(0, 16, 4))
    return c


def non_luhn_16():  # looks like a card but isn't; must NOT be redacted as <CARD>
    while True:
        n = str(R.randint(10 ** 15, 10 ** 16 - 1))
        if not luhn_ok(n):
            return n


def aws_key():
    return R.choice(["AKIAIOSFODNN7EXAMPLE", "AKIA" + "".join(R.choice(string.ascii_uppercase + "234567") for _ in range(16))])


FAKE_PRIVATE_KEY = ("-----BEGIN RSA PRIVATE KEY-----\n"
                    "MIIEowIBAAKCAQEAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE\n"
                    "THISISNOTAREALKEYTHISISNOTAREALKEYTHISISNOTAREALKEY0123456789ab\n"
                    "-----END RSA PRIVATE KEY-----")

# --------------------------------------------------------------------------
# Services, hosts, and line formats
# --------------------------------------------------------------------------

SERVICES = {
    "payment-svc": {"fmt": "java", "logger": "c.e.payment.PaymentClient"},
    "order-svc": {"fmt": "java", "logger": "c.e.order.OrderService"},
    "auth-svc": {"fmt": "python", "logger": "auth_svc.login"},
    "inventory-svc": {"fmt": "node", "logger": "inventory-svc"},
    "notification-svc": {"fmt": "python", "logger": "notification_svc.sender"},
    "api-gateway": {"fmt": "nginx", "logger": ""},
    "postgres": {"fmt": "postgres", "logger": ""},
}
NODES = ["k8s-node-01", "k8s-node-02", "k8s-node-03", "k8s-node-04"]
PODS = {s: [f"{s}-{token(9).lower()}-{token(5).lower()}" for _ in range(2)] for s in SERVICES}

NGINX_LEVEL = {"INFO": "info", "WARN": "warn", "ERROR": "error", "CRITICAL": "crit", "DEBUG": "debug", "FATAL": "emerg"}
PG_LEVEL = {"INFO": "LOG", "WARN": "WARNING", "ERROR": "ERROR", "FATAL": "FATAL", "CRITICAL": "PANIC", "DEBUG": "DEBUG1"}


def format_line(service, level, msg, ts, logger=None):
    fmt = SERVICES[service]["fmt"]
    logger = logger or SERVICES[service]["logger"]
    if fmt == "java":
        t = ts.strftime("%Y-%m-%d %H:%M:%S,") + f"{ts.microsecond // 1000:03d}"
        thread = R.choice([f"pool-{R.randint(1, 5)}-thread-{R.randint(1, 20)}", f"http-nio-8080-exec-{R.randint(1, 50)}", "main"])
        return f"{t} [{thread}] {level:<5} {logger} - {msg}"
    if fmt == "python":
        t = ts.strftime("%Y-%m-%d %H:%M:%S,") + f"{ts.microsecond // 1000:03d}"
        return f"{t} - {logger} - {'WARNING' if level == 'WARN' else level} - {msg}"
    if fmt == "node":
        t = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
        return f"[{t}] {level} ({logger}/{R.randint(1000, 9999)}): {msg}"
    if fmt == "nginx":
        t = ts.strftime("%Y/%m/%d %H:%M:%S")
        return f"{t} [{NGINX_LEVEL[level]}] {R.randint(10, 99)}#{R.randint(0, 3)}: *{R.randint(1000, 99999)} {msg}"
    if fmt == "postgres":
        t = ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d} UTC"
        return f"{t} [{R.randint(1000, 9999)}] {PG_LEVEL[level]}:  {msg}"
    raise ValueError(fmt)


# --------------------------------------------------------------------------
# Templates: (id, service, level, weight, secret categories, message builder)
# Weight is relative frequency. Secret categories describe what redaction should catch.
# --------------------------------------------------------------------------

def java_trace(exc, frames):
    lines = [exc] + [f"\tat {f}" for f in frames]
    return "\n".join(lines)


T = []


def tpl(tid, service, level, weight, secrets, builder, logger=None):
    T.append({"id": tid, "service": service, "level": level, "weight": weight,
              "secrets": secrets, "build": builder, "logger": logger})


# ---- payment-svc
tpl("E01", "payment-svc", "ERROR", 30, [], lambda: f"Timeout after {R.randint(3000, 9000)}ms calling bank-gateway for order {order_id()}")
tpl("E02", "payment-svc", "ERROR", 12, ["card", "customer_id"], lambda: f"Payment declined for card {card()} customer {customer_id()} reason=INSUFFICIENT_FUNDS")
tpl("E03", "payment-svc", "ERROR", 8, [], lambda: "Charge request failed\n" + java_trace(
    "java.net.SocketTimeoutException: Read timed out",
    ["java.base/java.net.SocketInputStream.socketRead0(Native Method)",
     "com.example.payment.client.BankGatewayClient.charge(BankGatewayClient.java:142)",
     "com.example.payment.service.PaymentService.process(PaymentService.java:87)",
     "org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"]))
tpl("E04", "payment-svc", "ERROR", 5, ["conn_string", "password", "internal_host"],
    lambda: f"Failed to connect to database: postgresql://payment_user:{R.choice(PASSWORDS)}@{internal_host()}:5432/payments")
tpl("E23a", "payment-svc", "ERROR", 6, ["ip"], lambda: f"Connection reset by peer: {ip_internal()}:{R.choice([443, 8443])}")
tpl("W01", "payment-svc", "WARN", 15, ["internal_host"], lambda: f"Retrying request to https://{internal_host()}/v2/charge (attempt {R.randint(1, 3)}/3)")
tpl("W09", "payment-svc", "WARN", 4, [], lambda: "Calling public API https://api.stripe.com/v1/charges took 2.4s (allowlisted host, should NOT be redacted)")

# ---- order-svc
tpl("E05", "order-svc", "ERROR", 14, [], lambda: (lambda a, b: f"Invalid state transition {a}->{b} for order {order_id()}")(*R.sample(ORDER_STATES, 2)))
tpl("E06", "order-svc", "ERROR", 9, [], lambda: "Unhandled exception while applying discount\n" + java_trace(
    "java.lang.NullPointerException: Cannot invoke \"java.math.BigDecimal.multiply(java.math.BigDecimal)\" because \"discount.rate\" is null",
    ["com.example.order.service.DiscountService.apply(DiscountService.java:58)",
     "com.example.order.service.OrderService.applyDiscount(OrderService.java:211)",
     "com.example.order.api.OrderController.checkout(OrderController.java:74)"]))
tpl("E24", "order-svc", "ERROR", 4, ["email", "password", "card"],
    lambda: "Request failed, body=" + json.dumps({"user": email(), "password": R.choice(PASSWORDS), "card": R.choice(TEST_CARDS), "amount": R.randint(100, 9999)}))
tpl("E25", "order-svc", "ERROR", 0, [], lambda: f"Kafka producer send failed: topic=order-events partition={R.randint(0, 11)} error=NOT_LEADER_OR_FOLLOWER")  # injected only in last 2h
tpl("W02", "order-svc", "WARN", 14, ["customer_id"], lambda: f"Slow query took {R.randint(1200, 8000)}ms: SELECT * FROM orders WHERE customer_id = '{customer_id()}'")
tpl("W03", "order-svc", "WARN", 10, [], lambda: f"Inventory reservation pending for order {order_id()}, sku={R.choice(SKUS)}, retry in {R.randint(5, 60)}s")
tpl("W10", "order-svc", "WARN", 4, [], lambda: f"Order reference {non_luhn_16()} not found in cache (16-digit number that fails Luhn, should NOT be redacted as a card)")

# ---- auth-svc
tpl("E07", "auth-svc", "ERROR", 16, ["email", "ip"], lambda: f"Login failed for user {email()} from {R.choice([ip_public(), ip_internal()])}: invalid password")
tpl("E08", "auth-svc", "ERROR", 7, ["jwt"], lambda: (
    "Token validation failed (Authorization: Bearer " + jwt() + ")\n"
    "Traceback (most recent call last):\n"
    '  File "/app/auth_svc/tokens.py", line 88, in verify\n'
    "    claims = jwt.decode(token, key, algorithms=[\"RS256\"])\n"
    '  File "/usr/local/lib/python3.14/site-packages/jwt/api_jwt.py", line 222, in decode\n'
    "    raise ExpiredSignatureError(\"Signature has expired\")\n"
    "jwt.exceptions.ExpiredSignatureError: Signature has expired"), logger="auth_svc.tokens")
tpl("E09", "auth-svc", "CRITICAL", 0.3, ["private_key"], lambda: f"Unable to load signing key from env SIGNING_KEY={FAKE_PRIVATE_KEY}", logger="auth_svc.keys")
tpl("E10", "auth-svc", "ERROR", 4, ["password", "internal_host"],
    lambda: f"LDAP bind failed for cn=svc-auth,ou=services,dc=corp,dc=example,dc=com host={internal_host()} password={R.choice(PASSWORDS)}", logger="auth_svc.ldap")
tpl("W04", "auth-svc", "WARN", 12, ["ip"], lambda: f"Rate limit exceeded for client {R.choice([ip_public(), ipv6()])} ({R.randint(120, 900)} requests in 60s)", logger="auth_svc.ratelimit")
tpl("W05", "auth-svc", "WARN", 5, ["secret"],
    lambda: f"OAuth callback error: redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb&client_secret%3D{token(40)}", logger="auth_svc.oauth")
tpl("W11", "auth-svc", "WARN", 5, ["api_key"], lambda: f"Deprecated header X-Api-Key used by client, api_key={token(36)}", logger="auth_svc.middleware")

# ---- inventory-svc
tpl("E11", "inventory-svc", "ERROR", 12, ["ip"], lambda: f"Error: connect ECONNREFUSED {ip_internal()}:6379")
tpl("E12", "inventory-svc", "ERROR", 8, [], lambda: (
    "Unhandled promise rejection: TypeError: Cannot read properties of undefined (reading 'quantity')\n"
    "    at reserveStock (/app/src/services/stock.js:41:27)\n"
    "    at async OrderConsumer.handle (/app/src/consumers/order.js:19:5)"))
tpl("E13", "inventory-svc", "ERROR", 4, ["aws_key"], lambda: f"S3 upload failed for bucket inventory-exports: AccessDenied (accessKeyId={aws_key()}, requestId={uuid()})")
tpl("E23b", "inventory-svc", "ERROR", 6, ["ip"], lambda: f"Connection reset by peer: {ip_internal()}:{R.choice([443, 8443])}")
tpl("W06", "inventory-svc", "WARN", 12, [], lambda: f"Stock level low for sku {R.choice(SKUS)}: {R.randint(0, 9)} units remaining")

# ---- notification-svc
tpl("E14", "notification-svc", "ERROR", 9, ["email", "internal_host"], lambda: f"SMTP send failed to {email()}: 421 Service not available ({internal_host()})")
tpl("E15", "notification-svc", "ERROR", 8, ["phone"], lambda: f"SMS delivery failed to {phone()}: provider returned 503")
tpl("E16", "notification-svc", "ERROR", 5, ["customer_id"], lambda: f"Template render error: missing variable 'first_name' for customer {customer_id()} (account {account_id()})", logger="notification_svc.templates")
tpl("W07", "notification-svc", "WARN", 6, ["token"], lambda: f"Webhook to https://hooks.partner.example.net/notify?token={token(32)} returned 500", logger="notification_svc.webhooks")

# ---- api-gateway (nginx error log format)
tpl("E17", "api-gateway", "ERROR", 14, ["ip"], lambda: (lambda o: f'upstream timed out (110: Connection timed out) while reading response header from upstream, client: {ip_public()}, server: api.example.com, request: "GET /api/v1/orders/{o} HTTP/1.1", upstream: "http://{ip_internal()}:8080/orders/{o}"')(order_id()))
tpl("E18", "api-gateway", "ERROR", 0.5, ["ip"], lambda: f"SSL_do_handshake() failed (SSL: error:0A00010B:SSL routines::wrong version number) while SSL handshaking to upstream, client: {ip_public()}")
tpl("W08", "api-gateway", "WARN", 8, ["ip"], lambda: f"an upstream response is buffered to a temporary file /var/cache/nginx/proxy_temp/{R.randint(1, 9)}/{R.randint(10, 99)}/{R.randint(100000, 999999)} while reading upstream, client: {ipv6()}")

# ---- postgres
tpl("E19", "postgres", "FATAL", 6, [], lambda: "remaining connection slots are reserved for non-replication superuser connections")
tpl("E20", "postgres", "ERROR", 7, [], lambda: (lambda n: f'duplicate key value violates unique constraint "orders_pkey"\nDETAIL:  Key (id)=({n}) already exists.')(R.randint(10000, 99999)))
tpl("E21", "postgres", "ERROR", 3, [], lambda: f"deadlock detected\nDETAIL:  Process {R.randint(1000, 9999)} waits for ShareLock on transaction {R.randint(100000, 999999)}; blocked by process {R.randint(1000, 9999)}.")
tpl("E22", "postgres", "FATAL", 4, ["ip"], lambda: f'password authentication failed for user "reporting"\nDETAIL:  Connection from {ip_internal()} rejected.')
tpl("W12", "postgres", "WARN", 5, [], lambda: f"checkpoints are occurring too frequently ({R.randint(5, 25)} seconds apart)")

# ---- INFO and DEBUG (noise, plus traps)
tpl("I01", "payment-svc", "INFO", 60, [], lambda: f"Payment captured for order {order_id()} amount={R.randint(100, 50000)} INR in {R.randint(80, 900)}ms")
tpl("I02", "order-svc", "INFO", 60, [], lambda: f"Order {order_id()} moved to {R.choice(ORDER_STATES)}")
tpl("I03", "auth-svc", "INFO", 55, ["email", "ip"], lambda: f"User {email()} logged in from {R.choice([ip_public(), ip_internal()])}")
tpl("I04", "inventory-svc", "INFO", 50, [], lambda: f"Reserved {R.randint(1, 5)} x {R.choice(SKUS)} for order {order_id()}")
tpl("I05", "notification-svc", "INFO", 45, ["email"], lambda: f"Email queued to {email()} template=order_confirmation")
tpl("I06", "api-gateway", "INFO", 60, [], lambda: f"upstream health check OK for {R.choice(['orders', 'payments', 'auth', 'inventory'])}-backend in {R.randint(2, 40)}ms")
tpl("I07", "postgres", "INFO", 25, [], lambda: f"checkpoint complete: wrote {R.randint(100, 9000)} buffers ({R.uniform(0.1, 9.9):.1f}%)")
tpl("I08", "payment-svc", "INFO", 25, [], lambda: f"Retry succeeded after SocketTimeoutException for order {order_id()} (INFO line containing 'Exception', should NOT be flagged)")
tpl("I09", "order-svc", "INFO", 30, [], lambda: f"Scheduled job reconcile-orders finished in {R.randint(1, 120)}s, processed={R.randint(0, 5000)}")
tpl("I10", "inventory-svc", "INFO", 25, [], lambda: f"Cache hit ratio {R.uniform(70, 99.9):.1f}% over last 5m")
tpl("I11", "auth-svc", "INFO", 20, [], lambda: f"Service started version=v2.{R.randint(10, 20)}.{R.randint(0, 9)} request_id={uuid()}")
tpl("D01", "inventory-svc", "DEBUG", 15, [], lambda: f"Cache lookup key=stock:{R.choice(SKUS)} hit={R.choice(['true', 'false'])}")
tpl("D02", "order-svc", "DEBUG", 12, [], lambda: f"Loaded pricing rules for region={R.choice(['IN-UP', 'IN-MH', 'IN-KA', 'IN-DL'])} rules={R.randint(5, 40)}")

BY_ID = {t["id"]: t for t in T}


def make_doc(t, ts):
    msg = t["build"]()
    line = format_line(t["service"], t["level"], msg, ts, t["logger"])
    svc = t["service"]
    return {
        "@timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
        "message": line,
        "host": {"name": R.choice(NODES)},
        "kubernetes": {"container": {"name": svc}, "pod": {"name": R.choice(PODS[svc])}},
        # Ground truth for checking Faultline's results. The app never reads this field.
        "faultline_test": {"template_id": t["id"], "level": t["level"], "secrets": t["secrets"]},
    }


def main():
    ap = argparse.ArgumentParser(description="Generate sample logs for Faultline (Elasticsearch bulk NDJSON).")
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--hours", type=int, default=24, help="time window the logs are spread over")
    ap.add_argument("--end", help="window end, ISO 8601 UTC (default: now)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="sample-logs.ndjson")
    args = ap.parse_args()

    R.seed(args.seed)
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)

    def ts_between(a, b):
        return a + timedelta(seconds=R.uniform(0, (b - a).total_seconds()))

    docs = []
    # 1) Spike: extra E01 timeouts in the last hour
    spike = max(1, int(args.count * 0.04))
    for _ in range(spike):
        docs.append(make_doc(BY_ID["E01"], ts_between(end - timedelta(hours=1), end)))
    # 2) New error: E25 appears only in the last 2 hours
    new = max(1, int(args.count * 0.015))
    for _ in range(new):
        docs.append(make_doc(BY_ID["E25"], ts_between(end - timedelta(hours=2), end)))
    # 3) Rare errors: guarantee they appear at least a couple of times
    for tid, n in (("E09", 2), ("E18", 3)):
        for _ in range(n):
            docs.append(make_doc(BY_ID[tid], ts_between(start, end)))
    # 4) Everything else by weight across the whole window
    pool = [t for t in T if t["weight"] > 0]
    weights = [t["weight"] for t in pool]
    while len(docs) < args.count:
        docs.append(make_doc(R.choices(pool, weights)[0], ts_between(start, end)))

    docs.sort(key=lambda d: d["@timestamp"])

    with open(args.out, "w", encoding="utf-8") as f:
        for d in docs:
            f.write('{"index":{}}\n')
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    levels = Counter(d["faultline_test"]["level"] for d in docs)
    templates = Counter(d["faultline_test"]["template_id"] for d in docs)
    services = Counter(d["kubernetes"]["container"]["name"] for d in docs)
    secrets = Counter(s for d in docs for s in d["faultline_test"]["secrets"])
    err_templates = sorted(t for t in templates if t[0] in "EW")

    print(f"Wrote {len(docs)} logs to {args.out}  ({start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC)")
    print("Levels:   ", dict(levels.most_common()))
    print("Services: ", dict(services.most_common()))
    print(f"Distinct ERROR/WARN templates: {len(err_templates)}")
    print("Template counts:", {t: templates[t] for t in err_templates})
    print("Lines with planted secrets, by type:", dict(secrets.most_common()))

    summary = {"count": len(docs), "window": [start.isoformat(), end.isoformat()], "levels": levels,
               "services": services, "templates": templates, "secrets": secrets}
    with open(args.out.rsplit(".", 1)[0] + "-summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=dict)


if __name__ == "__main__":
    main()
