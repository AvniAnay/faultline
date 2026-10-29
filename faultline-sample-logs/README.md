# Faultline sample logs

1,000 realistic, unstructured log lines from 7 services, for testing Faultline's
ingestion, level filtering, fingerprinting (Drain3), detection, and redaction.

**Every secret in these logs is fake:** documentation IP ranges (`203.0.113.x`,
`198.51.100.x`, `2001:db8::`), public test card numbers, AWS's published example
key, `example.com` domains, and a private key made of the word "FAKE".

## Files

| File | Purpose |
|---|---|
| `sample-logs.ndjson` | 1,000 logs in Elasticsearch bulk format, spread over 24 hours |
| `sample-logs-summary.json` | Counts by level, service, template, and secret type |
| `generate_logs.py` | Regenerates the logs (standard library only) |
| `mapping.json` | Index mapping |
| `load.sh` / `load.ps1` | Create the index and bulk-load the logs |
| `delete.sh` | Delete the index to start over |

## Load into Elasticsearch

Linux / macOS / WSL:

```bash
./load.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\load.ps1
```

Both default to `http://localhost:9200` and index `logs-faultline`, which matches
Faultline's default `ES_INDEX_PATTERN=logs-*`. Override with `ES_URL` / `INDEX`
(bash) or `-EsUrl` / `-Index` (PowerShell).

## Regenerate with fresh timestamps

The included file covers the 24 hours up to when it was generated. Faultline scans
recent windows, so regenerate just before loading if time has passed:

```bash
python generate_logs.py                         # 1,000 logs, last 24h, ending now
python generate_logs.py --count 5000 --hours 72 # bigger set
python generate_logs.py --seed 7                # different random values
```

Then `./delete.sh` and `./load.sh`.

## What's inside

**Levels:** about 52% INFO, 30% ERROR, 12% WARN, 4% DEBUG, and a few FATAL/CRITICAL.
There is no separate level field; the level exists only inside the message text,
as the spec assumes.

**Services and line formats** (five different formats, to test prefix stripping):

| Service | Format | Example prefix |
|---|---|---|
| payment-svc, order-svc | Java (Logback) | `2026-09-22 14:31:42,689 [http-nio-8080-exec-14] ERROR c.e.payment.PaymentClient - ` |
| auth-svc, notification-svc | Python logging | `2026-09-22 18:12:20,801 - auth_svc.tokens - ERROR - ` |
| inventory-svc | Node.js | `[2026-09-22T16:15:50.858Z] ERROR (inventory-svc/8708): ` |
| api-gateway | Nginx error log | `2026/09/22 14:42:22 [error] 81#2: *65725 ` |
| postgres | PostgreSQL | `2026-09-22 16:44:51.845 UTC [9061] FATAL:  ` |

These prefix patterns match every line in the file; each captures the level in the `level` group:

```text
^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[[^\]]+\] (?P<level>[A-Z]+)\s+\S+ -
^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - \S+ - (?P<level>[A-Z]+) -
^\[\d{4}-\d{2}-\d{2}T[\d:.]+Z\] (?P<level>[A-Z]+) \([^)]*\):
^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} \[(?P<level>[a-z]+)\] \d+#\d+: \*\d+
^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} UTC \[\d+\] (?P<level>[A-Z0-9]+):\s+
```

Level names differ by format: Nginx uses lowercase (`error`, `warn`), PostgreSQL uses
`WARNING`, `FATAL`, and `LOG` (its INFO). Level extraction must normalize these.

**Error and warning templates:** 38 distinct ones (IDs starting `E` or `W`), each
repeated with changing values (order IDs, durations, IPs), so Drain3 should group
each into one fingerprint. They include:

- Java and Python stack traces, and PostgreSQL `DETAIL:` lines, inside a single message
- Application-specific errors that web search won't help with (`Invalid state transition PAID->PENDING`)
- Well-known infrastructure errors where search should help (PostgreSQL connection slots, Nginx upstream timeouts, `ECONNREFUSED`)

## Built-in test scenarios

| Scenario | Where | What Faultline should do |
|---|---|---|
| **Spike** | `E01` payment timeouts: about 40 extra in the last hour | Flag as `spike` |
| **New error** | `E25` Kafka producer failures: only in the last 2 hours | Flag as `new` on a run covering that window |
| **Rare errors** | `E09` (CRITICAL, private key), `E18` (SSL handshake): 3 each | Still fingerprinted and flagged |
| **Same message, different services** | `E23a` payment-svc and `E23b` inventory-svc: "Connection reset by peer" | Two separate fingerprints |
| **"Exception" in an INFO line** | `I08` | Matched by the Elasticsearch keyword query, then dropped by level extraction |
| **Level aliases** | Nginx lowercase levels, PostgreSQL `WARNING`/`FATAL` | Recognized as WARN / ERROR-class levels |

## Planted sensitive data (for redaction)

| Type | Examples | Expected placeholder |
|---|---|---|
| IPv4 / IPv6 | `10.4.22.7`, `203.0.113.9`, `2001:db8:1a:2b::3c` | `<IP>` |
| Internal hostnames | `db-03.corp.example.com` | `<HOST>` |
| Emails | `priya.sharma12@example.in` | `<EMAIL>` |
| Passwords | `password=Winter2026!`, JSON `"password": "..."`, inside a connection string | `<SECRET>` / `<CONN_STRING>` |
| Connection strings | `postgresql://payment_user:<pw>@db-01.corp.example.com:5432/payments` | `<CONN_STRING>` |
| JWTs | `Authorization: Bearer eyJ...` | `<TOKEN>` / `<JWT>` |
| AWS keys | `AKIAIOSFODNN7EXAMPLE` and random `AKIA...` | `<CLOUD_KEY>` |
| Private key block | `-----BEGIN RSA PRIVATE KEY----- ...` | `<PRIVATE_KEY>` |
| Card numbers | `4111 1111 1111 1111`, `5555-5555-5555-4444`, `378282246310005` | `<CARD>` |
| Phone numbers | `+91 9876543210`, `+91-98765-43210` | `<PHONE>` |
| Customer / account IDs | `CUST-820999`, `ACC-12345678` | `<CUSTOMER_ID>` / `<ACCOUNT_ID>` (org-specific rules) |
| URL-encoded secret | `client_secret%3D...` | `<SECRET>` |
| High-entropy tokens | `api_key=...`, webhook `?token=...` | `<SECRET>` |

**Should NOT be redacted** (false-positive checks):

- `W10`: 16-digit order references that fail the Luhn check (not card numbers)
- `W09`: the public host `api.stripe.com` (add it to the redaction allowlist)
- UUIDs and version strings such as `v2.14.3` (handled by Drain3 masking, not redaction)

## Checking results against the ground truth

Each document has a `faultline_test` field with the template ID, the true level,
and the secret types planted in that line. Faultline never reads it (the connector
fetches only the fields it needs), but you can use it to check results:

```bash
# How many lines each error template produced
curl -s "localhost:9200/logs-faultline/_search?size=0" -H 'Content-Type: application/json' -d '{
  "aggs": { "t": { "terms": { "field": "faultline_test.template_id", "size": 100 } } } }'

# All lines that contain a planted card number
curl -s "localhost:9200/logs-faultline/_search?q=faultline_test.secrets:card&size=5"
```

Compare the number of fingerprints Faultline creates with the 38 E/W templates
(`sample-logs-summary.json` lists exact counts), and search the Postgres samples,
logged emails, and app logs for any of the values above to confirm nothing leaked.
