# Faultline — Stage 1 Build Plan

Scope reference: `docs/demo-architecture.md` → Stage 1. This document turns that scope
into a concrete, buildable plan against your actual local environment: real Keycloak
realm, real Postgres, real Elasticsearch, real Groq/Tavily keys, all reused from your
other projects in this workspace.

---

## 1. Infrastructure inventory

Everything below is **reused**, not newly provisioned — same pattern as your other
projects (`multiagent-travel-planner`, `pet-grooming-app`).

| Service | Where | Reused from |
|---|---|---|
| Postgres | `localhost:5432`, user `postgres` / `password` | Same container as your other projects. Faultline gets its own database (`faultline`), not a shared one |
| Keycloak | `localhost:8080`, realm **`abhi-org`** (existing, shared) | Same realm as `travel-planner-app` and `salon-app`. Faultline adds a **new client** (`faultline-web`) and **two new realm roles**, scoped by name prefix so they don't collide with other apps' roles |
| Elasticsearch | `localhost:9200` | Yours, freshly confirmed — currently empty, no security enabled (matches spec Section 13 Phase 1 assumption) |
| Groq | API key reused from `multiagent-travel-planner/backend/.env` | Free tier, same key |
| Tavily | API key reused from `multiagent-travel-planner/backend/.env` | Free tier, same key |

**Before you start:** Docker Desktop / your containers need to be running (I couldn't
reach ES or Keycloak on this pass — both returned nothing, likely just not started).
Start them, then re-run the health checks in Section 8 before building against them.

**Log data:** ES has no data yet. Use the ready-made fixture at
`~/Downloads/faultline-sample-logs/` instead of writing a generator — it's already built
for this exact spec (1,000 unstructured lines, 7 services, 5 log-prefix formats, 38
distinct error/warning templates, built-in spike/new/regression scenarios, and every
redaction rule's planted secret type, including Luhn/allowlist false-positive checks).
See Section 5.

---

## 2. Keycloak setup (reusing `abhi-org`)

Done once, in the Keycloak admin console (`http://localhost:8080/admin`), realm `abhi-org`:

1. **Client:** create `faultline-web` — public client, standard flow only (Authorization
   Code + PKCE, method `S256`), no client secret. Redirect URIs and web origins:
   `http://localhost:4200/*` and `http://localhost:4200`.
2. **Realm roles:** create `faultline-viewer` and `faultline-admin` (2 roles for Stage 1,
   not 3 — `faultline-reviewer` gets added in Stage 2). Prefixed so they're unambiguous
   in a realm shared with other apps.
3. **Assign roles:** assign `faultline-admin` to your own user (so you can both view and
   approve), and optionally a second test user with only `faultline-viewer` to verify the
   permission boundary works.
4. **Issuer URL:** `http://localhost:8080/realms/abhi-org` — this is `KEYCLOAK_ISSUER`.

No other realm-level changes. Nothing here affects `travel-planner-app` or `salon-app`.

---

## 3. Environment configuration

`backend/.env` (git-ignored) and `backend/.env.example` (committed, no real values):

```bash
# Postgres — faultline gets its own database in the shared container
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/faultline

# Elasticsearch (Phase 1: security disabled, plain HTTP)
ES_URL=http://localhost:9200
ES_API_KEY=
ES_CA_CERT=
ES_INDEX_PATTERN=logs-*
ES_MESSAGE_FIELD=message
ES_SERVICE_FIELD=kubernetes.container.name
ES_HOST_FIELD=host.name

# Keycloak — reusing the abhi-org realm
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_ISSUER=http://localhost:8080/realms/abhi-org
KEYCLOAK_REALM=abhi-org
KEYCLOAK_CLIENT_ID=faultline-web
KEYCLOAK_ALGORITHMS=RS256

# LLM (Groq) — same key as multiagent-travel-planner
GROQ_API_KEY=<reused>
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_REQUESTS_PER_MINUTE=20

# Web search (Tavily) — same key as multiagent-travel-planner
TAVILY_API_KEY=<reused>

# App
DASHBOARD_BASE_URL=http://localhost:4200
CORS_ORIGINS=http://localhost:4200
LOG_LEVEL=INFO

# Stage 1 only: hardcoded single team, no teams/routing table yet
DEFAULT_TEAM_NAME=Platform
DEFAULT_TEAM_DL=platform-team@example.com
```

`ES_SERVICE_FIELD` is `kubernetes.container.name`, confirmed against the sample fixture's
mapping (there is no `service.name` field) — this resolves spec Section 15, decision #4
for local/demo purposes. Re-confirm against real documents once this points at an
actual app.

`frontend/public/config.json`:

```json
{
  "apiBaseUrl": "http://localhost:8000/api",
  "keycloak": { "url": "http://localhost:8080", "realm": "abhi-org", "clientId": "faultline-web" }
}
```

---

## 4. Database — Stage 1 schema only

New database `faultline` in the existing Postgres container. Tables, trimmed from the
full spec (Section 6) to what Stage 1 actually uses:

```
fingerprints   — id, service, level, drain_cluster_id, template, category, severity,
                 status, first_seen, last_seen, total_count
                 (suppression/team_id/merged_into_id columns exist per final schema,
                 unused until Stage 2/3 — see demo-architecture.md "what doesn't change")
occurrences    — fingerprint_id, run_id, window_start, window_end, count
samples        — fingerprint_id, redacted_text, seen_at (latest 5)
resolutions    — id, fingerprint_id, summary, probable_cause, steps, sources,
                 confidence, origin, status
review_items   — id, run_id, fingerprint_id, proposed, decision, edited, reviewer,
                 comment, decided_at
runs           — id, requested_by, started_at, finished_at, window_start, window_end,
                 status, stats
drain_state    — service, state, updated_at
users          — id (Keycloak sub), email, display_name, role, last_seen_at, created_at
+ LangGraph checkpoint tables (created by PostgresSaver.setup())
```

**Not created in Stage 1:** `teams`, `team_routing`, `services`, `settings`,
`audit_log`, `email_log`, `fingerprint_aliases`. Adding these in Stage 2 is new `.sql`
migration files, not changes to existing tables — the migration runner (Section 5.9 of
spec) already works this way.

Same SQL-file migration approach as the spec: `backend/app/db/migrations/001_init.sql`,
applied in order, tracked in `schema_migrations`. This keeps Stage 1 → 2 → 3 a matter of
adding `002_...sql`, `003_...sql`, never editing `001_init.sql`.

---

## 5. Backend components (Stage 1 scope)

```
backend/
├── pyproject.toml, uv.lock, .env.example
├── app/
│   ├── main.py                # FastAPI app, runs migrations on startup
│   ├── worker.py              # NOT a loop in Stage 1 — a CLI: `python -m app.worker run`
│   │                          # triggers one run synchronously, for `POST /api/runs/trigger`
│   │                          # and local dev
│   ├── config.py              # Settings (pydantic-settings), all Stage 1 env vars above
│   ├── auth.py                # Keycloak token validation, require_role() — 2 roles
│   ├── db/
│   │   ├── session.py, models.py, migrate.py
│   │   └── migrations/001_init.sql   # Stage 1 tables only (Section 4)
│   ├── connectors/
│   │   └── elasticsearch.py   # PIT + search_after, watermark, same as spec 5.2
│   ├── pipeline/
│   │   ├── preprocess.py      # prefix strip, level/service extraction (spec 5.3)
│   │   ├── fingerprint.py     # TemplateMiner interface over Drain3 — single global
│   │   │                      # miner in Stage 1 (spec's per-service miner comes in
│   │   │                      # Stage 2/3 once there's more than a handful of services)
│   │   └── drain_persistence.py
│   ├── redaction/
│   │   ├── rules.py           # 11 of the spec's 13 rules (spec 5.4 #1-11): private key
│   │   │                      # blocks, connection strings, JWTs, auth headers,
│   │   │                      # key-value secrets, cloud keys, emails, cards (Luhn),
│   │   │                      # IPv4/IPv6, internal hosts/URLs, phone numbers, plus
│   │   │                      # the allowlist (api.stripe.com). Deferred: #12
│   │   │                      # org-specific IDs (needs the redaction_rules.json
│   │   │                      # loader) and #13 entropy detection (needs tuning) —
│   │   │                      # both land in Stage 2/3
│   │   └── engine.py          # redact() / RedactedText — final mechanism, same as spec
│   ├── agent/
│   │   ├── state.py           # RunState / ErrorItem / ResolutionDraft — same as spec
│   │   ├── llm.py             # ChatGroq + rate limiter
│   │   ├── nodes/
│   │   │   ├── classify.py    # category + severity + team (no severity_rules node —
│   │   │   │                  # classify sets severity directly in Stage 1)
│   │   │   ├── build_report.py
│   │   │   ├── human_review.py  # interrupt()
│   │   │   └── persist.py
│   │   └── graph.py            # classify → build_report → human_review → persist
│   │                            # (no severity_rules / kb_lookup / web_research nodes —
│   │                            #  added in Stage 2, same graph object extended)
│   ├── notify/
│   │   └── email_sender.py    # LogEmailSender — logs one line per approved item,
│   │                          # no email_log table, no digest formatting yet
│   └── api/
│       ├── health.py          # GET /api/health
│       ├── runs.py            # POST /api/runs/trigger, GET /api/runs, GET /api/runs/{id}
│       ├── errors.py          # GET /api/errors, GET /api/errors/{id}
│       ├── reviews.py         # GET /api/reviews/pending, PUT /api/review-items/{id},
│       │                      # POST /api/runs/{id}/review/submit
│       └── me.py               # GET /api/me
```

### Why no `severity_rules` / `kb_lookup` / `web_research` nodes yet

- `severity_rules` depends on `services.criticality`, which doesn't exist as a table in
  Stage 1 — classify's LLM output is used directly.
- `kb_lookup` needs fastembed + stored embeddings, which means every resolution needs
  vectors from day one; deferring it means Stage 1 has one less dependency (`fastembed`/
  `onnxruntime`, which is exactly the thing spec flags as needing a Python 3.14
  compatibility check — Section 10 note, Section 15 #2/#31). Worth confirming separately
  before Stage 2 rather than blocking Stage 1 on it.
- `web_research` (Tavily) is easy to add back — it's one node with no schema
  dependency. Consider adding it even in Stage 1 if you want resolutions to look
  real rather than LLM-only; it doesn't complicate anything else. **Recommendation:
  include `web_research` in Stage 1**, skip only `kb_lookup` (Tavily key is already
  available, no new table needed, and it makes the demo materially more convincing).

Updated Stage 1 graph: `classify → web_research → build_report → human_review → persist`.

---

## 6. Frontend (Stage 1 scope)

```
frontend/src/app/
├── core/
│   ├── api/          # models/{errors,runs,reviews}.ts + ErrorsApiService, RunsApiService,
│   │                 # ReviewsApiService. No settings/admin models yet.
│   └── auth/          # keycloak-angular setup, AuthStore (2 roles), bearer interceptor
├── shared/ui/          # button, badge, table, dialog, toast (skip tabs/filter-bar
│                        # complexity — Stage 1 has one filter: status)
└── features/
    ├── errors/         # list: fingerprint, template, severity, service, count, status
    ├── error-detail/    # template, samples, resolution, occurrence chart, review actions
    └── review/          # pending items, approve/reject/edit, submit → resumes graph
```

3 routes + login (handled by `login-required`). No Overview, Runs, Settings, Users, or
Audit log pages — `GET /api/runs` still exists on the backend (used by the review page
to show which run an item belongs to) but there's no dedicated Runs page yet.

---

## 7. Run lifecycle (Stage 1, no scheduler)

1. You call `POST /api/runs/trigger` (button on the Errors page, or curl).
2. Synchronous: connector fetches the ES window → preprocess → redact → Drain3 →
   fingerprints/occurrences/samples updated → detection flags `new` only.
3. If anything's flagged, the LangGraph workflow runs inline: classify → web_research →
   build_report → `interrupt()`. Run status becomes `awaiting_review`.
4. You review in the dashboard, approve/reject/edit, submit.
5. Backend resumes the graph synchronously in the request handler (Stage 1 doesn't need
   the worker-resumes-async design from spec's G3 — there's no scheduler contending for
   it). `send_email` logs each approved item, `persist` saves and marks `completed`.

This collapses spec's worker/API split into simpler synchronous calls for now. Moving to
the scheduler-driven async version (spec Section 5.1, G3's "worker resumes" decision) is
a Stage 2 change localized to `worker.py` and two endpoint handlers — the graph and state
model don't change.

---

## 8. Before-you-build checklist

```bash
# 1. Confirm infra is up
curl -s http://localhost:9200            # Elasticsearch
curl -s http://localhost:8080/realms/abhi-org   # Keycloak realm exists
psql "postgresql://postgres:password@localhost:5432/postgres" -c '\l'   # Postgres reachable

# 2. Create the faultline database
psql "postgresql://postgres:password@localhost:5432/postgres" -c 'CREATE DATABASE faultline;'

# 3. Keycloak: create faultline-web client + faultline-viewer/faultline-admin roles
#    (admin console, see Section 2) — assign faultline-admin to your own user

# 4. Load the sample logs (regenerate first so timestamps are inside the scan window)
cd ~/Downloads/faultline-sample-logs
python generate_logs.py
./load.sh
```

---

## 9. Build order

| # | Task | Notes |
|---|---|---|
| 1 | Keycloak client + roles (Section 2) | Manual, ~10 min |
| 2 | Backend scaffold: `pyproject.toml`, `config.py`, `.env`, `main.py` | |
| 3 | `001_init.sql` (Stage 1 tables only) + migration runner + models | |
| 4 | `auth.py`: token validation, `require_role()`, `/api/me` | Test with a curl + real token before building anything else on top |
| 5 | Regenerate + load `~/Downloads/faultline-sample-logs/` (`python generate_logs.py`, then `./load.sh`) | Unblocks everything downstream. Regenerate first so timestamps fall inside the scan window |
| 6 | ES connector + preprocessing | Use the 5 prefix regexes from the fixture's README directly. Verify against `sample-logs-summary.json` counts |
| 7 | Redaction (11 rules) | Unit tests per rule, using the planted secrets in the fixture (README has the full list + expected placeholders) |
| 8 | Drain3 fingerprinting (single miner) + `drain_state` persistence | Confirm same input → same fingerprint across two runs |
| 9 | Detection (`new` flag only) | |
| 10 | Agent graph: classify → web_research → build_report → human_review → persist | Test the interrupt/resume cycle manually before wiring the API |
| 11 | API endpoints (Section 5 list) | |
| 12 | Frontend: Keycloak login, shell, Errors + Error detail + Review pages | |
| 13 | End-to-end pass: trigger a run, see flagged errors, review, approve, confirm the email log line and `persist` | This is "Stage 1 done" |

---

## 10. Stage 1 acceptance criteria

- Logging in requires Keycloak; a viewer can see errors and review items but the
  approve/reject actions are rejected server-side (403), not just hidden in the UI.
- Loading the fixture twice and triggering a run twice does not double-count or
  duplicate fingerprints for the same sample errors.
- Fingerprint count for the ~38 E/W templates roughly matches `sample-logs-summary.json`
  (spot-check against `faultline_test.template_id`, per the fixture's README — Faultline
  itself never reads that field).
- None of the planted secret values (emails, IPs, internal hosts, connection strings,
  AWS keys, the private key block, card numbers, phone numbers) appear unredacted in
  Postgres, LLM prompts, or the logged "email." `api.stripe.com` (W09) is *not* redacted
  (allowlist), and the Luhn-invalid 16-digit references in W10 are *not* redacted as cards.
- `E01` (payment timeouts) is flagged `spike`; `E25` (Kafka producer failures) is flagged
  `new`; `E23a`/`E23b` (same message, different services) produce two separate fingerprints.
- A reviewer can approve one item and reject another in the same run, submit, and see
  the run reach `completed` with only the approved item's resolution persisted.
- No Elasticsearch call uses `from`/`size` paging (PIT + `search_after` only).

---

## 11. Explicit non-goals for this pass

Same list as `demo-architecture.md` Stage 1: no scheduler, budget limits, mute/snooze,
merge, audit log, settings dashboard, teams/routing tables, KB/embeddings, Overview/Runs/
Settings/Users/Audit pages. All still land in Stage 2/3 without restructuring anything
built here.
