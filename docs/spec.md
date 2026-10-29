# Faultline — Requirements Specification

*Faultline is an agentic log analysis system: it finds distinct errors in your logs, researches fixes, and routes approved reports to the right teams.*

**Project:** Faultline
**Status:** Draft v1 (MVP scope)
**Audience:** Engineering team starting implementation

---

## 1. Summary

An agentic workflow that scans application and system logs stored in **Elasticsearch** on a configurable schedule (for example, hourly or daily). It:

1. Finds all **distinct** ERROR and WARNING logs.
2. Classifies each by **category**, **severity**, and **owning team**.
3. Researches likely **resolutions**, first from an internal knowledge base, then from the web (Tavily).
4. Builds a per-team report and **pauses for human review**.
5. After approval, **prepares an email digest** for each team's distribution list (DL). In the MVP the email is written to the log, not actually sent.
6. Shows everything in an **Angular dashboard**: errors, trends, resolutions, and the review queue.

### Problem it solves

Teams receive large volumes of repeated errors with no grouping, context, or suggested fixes. Engineers spend time searching for the same errors repeatedly, and alerts often reach the wrong team.

### Goals

- Collapse thousands of raw log lines into a small set of distinct, trackable errors.
- Attach a researched, sourced resolution to each new error.
- Route each error to the right team, with human approval before anything is sent.
- Build an internal knowledge base of approved resolutions that improves over time.

### Non-goals (MVP)

- Real-time alerting. This is a scheduled batch process, not a paging system.
- Automatic remediation. The system suggests fixes; it never applies them.
- Replacing existing monitoring tools.
- Log sources other than Elasticsearch.

---

## 2. Key assumptions

| Area | Assumption |
|---|---|
| Log source | Elasticsearch only |
| Log format | **Unstructured** text messages (no reliable `level` or `error.type` field) |
| Volume | Unknown. The design filters in Elasticsearch and groups before any LLM call, so volume mainly affects ingestion time, not LLM cost |
| External APIs | Allowed, **only after redaction** (Groq LLM and Tavily) |
| LLM | **Groq** free tier (rate-limited; see Section 5.10) |
| Embeddings | **Free local model** via `fastembed`; no API, no cost |
| Authentication | **Keycloak**, role-based (viewer, reviewer, admin) |
| Email | **Not sent** in the MVP; email content is written to the log and the `email_log` table |
| Infrastructure | **PostgreSQL, Keycloak, and Elasticsearch 9.5.3 run in Docker** on the development machine. For Phase 1, Elasticsearch security is disabled and the app connects over plain HTTP |
| Dependencies | **Bare minimum.** SQLAlchemy for database access; no migration tool, scheduler library, template engine, linters, or type checkers |
| Redaction | **Custom logic only** (regex and rules). No Presidio or ML-based detection |

---

## 3. MVP scope

**In scope:**

- Scheduled log scanner (Elasticsearch connector, preprocessing, redaction, fingerprinting, new/spike detection)
- LangGraph agent workflow (classification, severity rules, knowledge-base lookup, Tavily research, report building)
- Human review step (pause and resume)
- Email digests per team, **logged instead of sent**
- Groq as the LLM, with a free local embedding model
- Keycloak login and role-based access
- FastAPI backend
- **Angular dashboard** (overview, errors, error detail, review queue, runs, settings)
- Postgres storage (the existing Docker container), accessed through SQLAlchemy
- **Settings managed from the dashboard** (Section 5.9):
  - Log levels and keywords to scan
  - Services and their criticality
  - Mute and snooze for individual errors
  - Merging fingerprints that Drain3 split incorrectly
  - Teams, DLs, and a minimum email severity per team
  - LLM and Tavily budget per run
  - Role-based access from Keycloak (admin, reviewer, viewer)
  - Audit log of every change

**Later phases:** see Section 18.

---

## 4. Architecture

```mermaid
flowchart TD
    S[Scheduler<br/>worker loop] --> ES[Elasticsearch Connector<br/>watermark + PIT paging]
    ES --> PP[Preprocess<br/>strip prefix, extract level/service]
    PP --> RD[Redaction<br/>custom rules]
    RD --> FP[Fingerprinting<br/>Drain3 w/ persisted state]
    FP --> DB[(Postgres)]
    FP --> DT[Detection<br/>new / spike / regression]
    DT -->|only flagged errors| AG

    subgraph AG[LangGraph Agent Workflow]
        C[classify] --> SR[severity_rules]
        SR --> KB[kb_lookup]
        KB -->|no match| WR[web_research<br/>Tavily]
        KB -->|match| BR
        WR --> BR[build_report]
        BR --> HR[human_review<br/>interrupt]
        HR --> EM[send_email]
        EM --> PS[persist]
    end

    AG <--> DB
    API[FastAPI] <--> DB
    API -->|resume graph| AG
    UI[Angular Dashboard] <--> API
    UI -->|login| KC[Keycloak]
    API -->|verify token| KC
    EM --> MAIL[Email log<br/>not sent]
```

**Design principle:** deterministic steps (ingestion, redaction, fingerprinting, detection, routing) are plain Python code. The LLM is used only where judgment is needed: classification, research, and summarization.

---

## 5. Components

### 5.1 Scheduler

- A simple loop in the worker process; **no scheduler library**. Every 30 seconds it checks whether a run is due (`now >= last run start + schedule.interval_minutes`) or has been requested manually, and starts one. Interval changes made in the dashboard apply automatically.
- **No overlapping runs:** take a Postgres advisory lock at run start. If a run is still going, skip this check and log it.
- **Manual trigger:** `POST /api/runs/trigger` inserts a `runs` row with status `requested`; the worker picks it up on its next check.

### 5.2 Elasticsearch connector

- **Connection:** `ES_URL` (plain HTTP in Phase 1). If `ES_API_KEY` is set, the client sends it; if `ES_CA_CERT` is set, the client uses it to verify HTTPS. Both are empty in Phase 1.
- Query only the time window since the last successful run:
  - `window_start` = stored watermark for the source
  - `window_end` = `now - ingest_lag` (default 2 minutes, to allow for late-arriving logs)
- Because logs are unstructured, filter on the message text. The level and keyword list is **built from the dashboard settings** `scan.levels` and `scan.keywords` (Section 5.9.1), read at the start of every run. The example below shows the defaults:

```json
{
  "bool": {
    "filter": [
      { "range": { "@timestamp": { "gt": "<window_start>", "lte": "<window_end>" } } },
      { "query_string": {
          "default_field": "message",
          "query": "ERROR OR WARN OR WARNING OR FATAL OR CRITICAL OR Exception"
      } }
    ]
  }
}
```

- Page through results with a **point-in-time (PIT) snapshot plus `search_after`**, sorted by `[@timestamp, _shard_doc]`. Do not use `from`/`size` paging.
- Fetch only the needed fields: `@timestamp`, `message`, and the configured service/host metadata fields.
- Update the watermark **only after the run's ingestion stage succeeds**.
- The service name comes from configurable metadata fields (for example, `service.name`, `kubernetes.container.name`, or the index name). **This must be confirmed against real documents** (see Section 15).
- Output: a stream of `LogRecord(timestamp, level, service, host, message, es_id, index)`.

### 5.3 Preprocessing

For each record:

1. **Strip the prefix.** Use configurable regex patterns to remove leading timestamps, thread names, and level tokens. Example: `2026-09-22 10:14:03,221 [pool-3-thread-7] ERROR`.
2. **Extract the level** from the stripped prefix or the message text. Drop records whose level is not in `scan.levels` (the text query can match words like "Exception" inside INFO messages). A line with no recognizable level that matches a configured keyword is treated as the level mapped to that keyword (default `ERROR`).
3. **Normalize** whitespace and cap message length (default 4,000 characters).
4. **Handle stack traces:**
   - If a stack trace arrives as one document: keep the exception line plus the first N frames (default 3) from application packages (configurable prefixes, such as `com.yourcompany.`). Framework frames are dropped when building the template input.
   - If stack traces arrive split across documents, that is a shipper configuration problem. Raise it before the MVP (see Section 15); don't try to reassemble traces in the MVP.

### 5.4 Redaction (custom logic)

**Purpose:** ensure no sensitive data leaves the network or lands in Postgres, emails, or the dashboard. Raw logs stay only in Elasticsearch, under its existing access controls.

**This is separate from Drain3 masking.** Drain3 masks variables so errors group together. Redaction removes sensitive data. Keep the two independent.

#### Module design

- `redaction/rules.py`: an ordered list of `RedactionRule(name, pattern, placeholder, validator=None)`.
- `redaction/engine.py`: `redact(text) -> RedactionResult(text, counts_by_rule)`.
- Built-in rules ship with the code. Organization-specific rules are loaded from `config/redaction_rules.json` (parsed with Python's standard `json` module), so they can be added without code changes.
- An **allowlist** of values that should never be redacted (for example, public vendor hostnames like `api.stripe.com`) avoids over-redaction.

#### Rules, applied in this order

The order matters: broad or multi-part patterns run first, so smaller patterns don't break them apart.

| # | Rule | Placeholder | Notes |
|---|---|---|---|
| 1 | Private key blocks | `<PRIVATE_KEY>` | `-----BEGIN ... PRIVATE KEY-----` through `END` |
| 2 | Connection strings with credentials | `<CONN_STRING>` | e.g. `postgres://user:pass@host/db`, `mongodb+srv://...`, JDBC URLs with `password=` |
| 3 | JWTs | `<JWT>` | Three base64url segments separated by dots, starting with `eyJ` |
| 4 | Authorization headers | `<TOKEN>` | `Bearer ...`, `Basic ...` |
| 5 | Key-value secrets | `<SECRET>` | Keys like `password`, `passwd`, `pwd`, `secret`, `token`, `api_key`, `apikey`, `access_key`, `client_secret`, followed by `=`, `:`, or JSON `": "`. Only the value is replaced; the key is kept |
| 6 | Cloud keys | `<CLOUD_KEY>` | AWS access key IDs (`AKIA`/`ASIA` + 16 characters), and patterns for other clouds as needed |
| 7 | Email addresses | `<EMAIL>` | |
| 8 | Card numbers | `<CARD>` | 13–19 digits, allowing spaces or dashes, **and must pass the Luhn checksum** (cuts false positives) |
| 9 | IPv4 / IPv6 | `<IP>` | Validate octet ranges for IPv4 |
| 10 | Internal hostnames and URLs | `<HOST>` / `<URL>` | Configurable internal domain suffixes (e.g. `.corp.example.com`, `.internal`) |
| 11 | Phone numbers | `<PHONE>` | Including Indian formats (`+91`, 10-digit mobile numbers) |
| 12 | Custom business identifiers | `<CUSTOMER_ID>`, `<ACCOUNT_ID>`, … | Defined per organization in `redaction_rules.json` |
| 13 | High-entropy strings | `<SECRET>` | Tokens of 20+ characters with Shannon entropy above ~4.0, skipping known-safe formats (such as UUIDs, which are handled by Drain3 masking). Catches unknown API keys |

#### Guarantees

- **Fail closed:** if redaction raises an exception for a line, drop the line and increment a `redaction_failures` metric. Never pass unredacted text through.
- **Single entry point:** every path that sends text to the LLM, Tavily, email, or Postgres must go through `redact()`. Storage models and outbound clients accept only a `RedactedText` wrapper type, not plain strings, so unredacted text can't be passed by mistake. Enforce this in code review.
- **Tavily queries** are generated from redacted text only, and are short search phrases (for example, `"PostgreSQL remaining connection slots are reserved" fix`), never raw log lines.
- **Metrics:** count redactions by rule per run, shown on the Runs page, to spot rules that fire too much or too little.

### 5.5 Fingerprinting (Drain3)

**Why Drain3:** unstructured messages contain variable values (IDs, durations, counts), so identical errors never match as exact strings. Drain3 learns templates such as `Timeout after <*>ms calling payment-svc for order <*>`, which gives each distinct error a stable identity.

**Configuration (starting values, to be tuned):**

- `sim_th`: 0.4
- `depth`: 4
- `max_children`: 100
- Masking instructions for: UUIDs, hex strings (`0x...`), numbers, durations (`\d+ms`, `\d+s`), file paths, and the redaction placeholders (so `<IP>` and similar are treated as fixed tokens).

**Identity rules:**

- The **fingerprint = `service` + Drain3 `cluster_id`**, not a hash of the template text. Templates generalize as Drain3 learns (`Timeout calling payment-svc` may become `Timeout calling <*>`), which would change a text hash; the cluster ID stays stable.
- Maintain **one Drain3 miner per service**, so errors from different services never merge.
- **Persist Drain3 state** in Postgres through a custom `PersistenceHandler` (table `drain_state`, one row per service), saved after each run. Losing this state makes every error look new, so include it in database backups.
- Use `add_log_message()` (learning mode) during ingestion only. Use `match()` (lookup only, no learning) anywhere else, such as tools that check which known error a line belongs to.
- On each run, update the fingerprint's latest template text, `last_seen`, counts, and keep up to 5 recent **redacted** sample lines.

**Tuning tool (build first):** `scripts/tune_drain.py` pulls a chosen time range from Elasticsearch, runs the full preprocess, redact, and template pipeline, and prints the top N templates with counts. Used to tune `sim_th`, `depth`, and masks against real data **before** the agent workflow is built.

- Too many templates for one real error → add masks or lower `sim_th`.
- Different errors merged into one template → raise `sim_th` or `depth`.

### 5.6 Detection

After fingerprinting, flag errors for the agent workflow if **any** of these holds:

| Flag | Condition |
|---|---|
| `new` | Fingerprint seen for the first time |
| `spike` | Count in this window > `max(spike_multiplier × average of last N windows, spike_min_count)`. Defaults: multiplier 3, N = 24, min count 20 |
| `regression` | Fingerprint status was `resolved` and it has appeared again |
| `snooze_expired` | Snooze ended and the error is still occurring |

Unflagged errors only update counts and trends; they don't go to the LLM and are not emailed.

**Suppression is checked before flagging** (see Section 5.9.3):

- **Muted** errors are never flagged, unless the mute has `alert_on_spike = true` and the error spikes.
- **Snoozed** errors are not flagged until `snoozed_until` passes. If the error is still occurring when the snooze expires, it is flagged `snooze_expired` and goes through the workflow again.
- Suppressed errors still update counts, so the dashboard shows whether they are still happening.

**Budget is applied after flagging** (see Section 5.9.6). If flagged errors exceed the run budget, they are prioritized and the rest are deferred to the next run.

### 5.7 Agent workflow (LangGraph)

#### State

```python
class ResolutionDraft(BaseModel):
    summary: str
    probable_cause: str
    steps: list[str]
    sources: list[str]          # URLs, or "kb:<resolution_id>"
    confidence: Literal["high", "medium", "low"]
    origin: Literal["kb", "web", "llm_only"]

class ErrorItem(BaseModel):
    fingerprint_id: str
    service: str
    level: str
    template: str
    samples: list[str]          # redacted
    count: int
    flags: list[str]            # new | spike | regression | snooze_expired
    category: str | None = None
    severity: str | None = None
    team: str | None = None
    resolution: ResolutionDraft | None = None

class RunState(TypedDict):
    run_id: str
    items: list[ErrorItem]
    decisions: dict[str, dict]  # fingerprint_id -> {decision, edits, reviewer, comment}
```

#### Nodes

1. **`classify`**: LLM with structured output (Pydantic). Processes items in batches of about 10. Returns:
   - `category`: one of `System`, `Application`, `Database`, `Network`, `Security`, `Infrastructure`, `Third-party`, `Unknown`
   - `suggested_severity`: `Critical` | `High` | `Medium` | `Low`
   - `suggested_team`: from the list of teams in `team_routing` (passed in the prompt)
   - a one-line reason for each choice
2. **`severity_rules`**: deterministic adjustments applied after the LLM:
   - Level `FATAL`/`CRITICAL` → at least `High`
   - Service marked `criticality: high` in the `services` table (managed from the dashboard) → raise by one level; `low` → lower by one level (never below `Low`)
   - `spike` flag → raise by one level
   - `Security` category → at least `High`
   - The final team comes from the `team_routing` table. The LLM's suggestion is used only when no routing rule matches, and is labeled as a suggestion in the review UI.
3. **`kb_lookup`**:
   - If this fingerprint already has an **approved** resolution, reuse it.
   - Otherwise, embed the template plus category with the local embedding model (Section 5.10) and compare it with the stored embeddings of approved resolutions using cosine similarity, computed in Python with NumPy. The knowledge base is small, so this is fast. If similarity ≥ 0.85, reuse the match with `origin = kb`.
4. **`web_research`** (only for items with no KB match):
   - The LLM writes 1–2 short search queries from the redacted template.
   - Tavily search: `search_depth = "basic"` by default (advanced searches use more of the plan's credits), `max_results = 5`. Optionally prefer domains like official docs, Stack Overflow, and GitHub issues.
   - The LLM summarizes the results into a `ResolutionDraft` with source URLs.
   - `confidence`: `high` if multiple sources agree and match the specific error; `low` if results are generic or off-topic. If nothing relevant is found, return `origin = llm_only`, `confidence = low`, and clearly say so. Never present an unsourced guess as a confirmed fix.
   - Application-specific errors (the organization's own code) will often get low confidence. That's expected.
5. **`build_report`**: groups items by team, sorted by severity, and creates `review_items` rows. Items **below the team's minimum email severity** (Section 5.9.5) are not sent for review or email; they are marked `below_threshold` and remain visible on the dashboard.
6. **`human_review`**: calls `interrupt()`. The graph pauses, and its state is saved by LangGraph's `PostgresSaver` checkpointer. The run status becomes `awaiting_review`.
7. **`send_email`**: when resumed, sends only `approved` or `edited` items, as one digest per team.
8. **`persist`**: saves approved resolutions (and their embeddings) to the knowledge base, updates fingerprint severity, category, and team based on reviewer edits, and marks the run `completed`.

#### Resuming after review

The dashboard submits decisions to `POST /api/runs/{run_id}/review/submit`. The backend then resumes the graph:

```python
graph.invoke(
    Command(resume={"decisions": decisions}),
    config={"configurable": {"thread_id": run_id}},
)
```

#### Review timeout (configurable)

- If a run is still awaiting review after `review.timeout_hours` (default 4), send a reminder email to the reviewer group.
- Pending items from an expired run carry over into the next run's review queue, so nothing is lost and nothing is sent without approval.

### 5.8 Email (logged, not sent)

The MVP **does not send real email**. Everything is built as if it did, but the final step writes the email to the log.

- Emails go through an `EmailSender` interface with one implementation, `LogEmailSender`.
- One **digest per team per run**, containing only approved or edited items.
- The email is plain text, built with Python string formatting (no template engine): recipients (the team's DL), subject, summary counts by severity, then a section per error with template, service, count, first/last seen, severity, category, resolution steps, sources, confidence, and a link to the error's page in the dashboard.
- `LogEmailSender` writes each email to the application log as one structured JSON entry and saves it in `email_log` with the full body and status `logged`.
- The **Run detail** view in the dashboard lists each run's emails with their full content, so reviewers can see exactly what would have been sent.
- Review-timeout reminders (Section 5.7) go through the same sender.
- Sending real email later only needs a second `EmailSender` implementation (Section 18); nothing else changes.

### 5.9 Settings managed from the dashboard

General rules for everything in this section:

- Changes take effect **from the next run**. A run in progress keeps the settings it started with (a snapshot is stored in `runs.stats.settings_snapshot`).
- Every change is validated on the server, restricted by role (Section 5.9.7), and written to the audit log (Section 5.9.8).
- Every setting has a default in code, so the system works on a fresh install before anyone configures it.

#### 5.9.1 Log levels and keywords

- `scan.levels`: which levels to scan. Options: `FATAL`, `CRITICAL`, `ERROR`, `WARN`/`WARNING`. Default: all of them. At least one must be selected.
- `scan.keywords`: extra words that mark a line as an error even when no level is present (for example `Exception`, `Traceback`, `Timeout`, `OutOfMemory`). Each keyword maps to a level (default `ERROR`).
- Used to build the Elasticsearch query (Section 5.2) and by level extraction in preprocessing (Section 5.3).
- The Settings page shows a **preview**: the generated query and a count of matching documents in the last 24 hours (via Elasticsearch `_count`), so admins can see the effect before saving.

#### 5.9.2 Services and criticality

- `services` table: `name`, `criticality` (`high`, `medium`, `low`), `default_team_id`, `enabled`, `notes`.
- **Auto-discovery:** when a new service name appears in logs, a row is created automatically with `criticality = medium` and marked **unconfigured**. The dashboard shows a banner listing unconfigured services until an admin reviews them.
- Disabling a service stops its errors from being flagged (counts are still recorded).
- `criticality` feeds the severity rules (Section 5.7). `default_team_id` is used as a routing fallback before the LLM's suggestion.
- Service settings live only in this table, not in environment variables or code.

#### 5.9.3 Mute and snooze

Available on the Error detail page, and as a bulk action on the Errors list.

- **Mute:** permanently stops an error from being flagged, researched, reviewed, or emailed. Options:
  - `reason` (required text)
  - `alert_on_spike` (default off): if on, the error is still flagged when it spikes
- **Snooze:** same as mute, but only until a chosen date and time (`snoozed_until`, maximum 90 days ahead). Common use: a fix is being deployed. When it expires, see `snooze_expired` in Section 5.6.
- **Unmute / unsnooze:** returns the error to normal handling immediately.
- Suppressed errors appear on the Errors list with a muted or snoozed badge, hidden by default behind a "Show suppressed" filter, and their counts keep updating.
- Stored on `fingerprints` (see Section 6). Every action records who did it and why.

#### 5.9.4 Merge fingerprints

For when Drain3 splits one real error into two or more fingerprints.

- From the Error detail page, a reviewer chooses **"Merge into this error"** and selects one or more other fingerprints (search by template text). The page shows a side-by-side comparison of templates and samples before confirming.
- **MVP restriction:** fingerprints can only be merged if they belong to the **same service**.
- What happens on merge (in one database transaction):
  1. The selected fingerprints are marked `status = merged` and `merged_into_id = <target>`.
  2. Their Drain3 cluster IDs are added to `fingerprint_aliases`, so future log lines matching those clusters are counted against the target.
  3. Their occurrences and samples are reassigned to the target; `first_seen`, `last_seen`, and `total_count` are recalculated.
  4. Their resolutions are kept, attached to the target with `status = draft`, so a reviewer can pick the best one.
  5. Pending review items for merged fingerprints are cancelled and replaced by one item for the target.
- The fingerprinting stage (Section 5.5) checks `fingerprint_aliases` after getting a Drain3 cluster ID: if the cluster is an alias, it uses the target fingerprint.
- Merged fingerprints stay in the database (hidden from lists) so the merge can be undone in a later phase.

#### 5.9.5 Teams, routing, and minimum severity

- `teams` table: `name`, `email_dl`, `min_email_severity` (default `Low`, meaning everything), `enabled`.
- `team_routing` rules now reference a team instead of storing the DL directly, so a team's DL is changed in one place.
- Routing order: routing rules by priority → the service's `default_team_id` → the LLM's suggested team (flagged for the reviewer) → a configurable fallback team.
- `min_email_severity`: items below this severity are not sent to review or email for that team (Section 5.7), but remain on the dashboard.
- Critical items are **always** sent for review, regardless of the threshold, to prevent a team accidentally filtering out critical errors.

#### 5.9.6 Run budget

Protects against high costs during an error storm (for example, a bad deployment producing hundreds of new errors at once).

- `budget.max_items_per_run`: maximum flagged errors processed by the agent per run (default 30)
- `budget.max_llm_calls_per_run` (default 30)
- `budget.max_tavily_calls_per_run` (default 20)
- The defaults are sized for the Groq and Tavily free tiers (Section 5.10). With hourly runs, 30 LLM calls per run stays under Groq's daily request limit.
- When flagged errors exceed the budget, they are **prioritized** by: rule-based pre-severity (level + service criticality + flags), then count in this window. Errors beyond the budget are marked `deferred` and processed first in the next run.
- If the LLM or Tavily call limit is reached mid-run, remaining items finish without that step (for example, a resolution is marked "research skipped: budget reached") rather than failing the run.
- The Runs page shows budget usage per run, and the Overview page shows a warning when items were deferred.

#### 5.9.7 Authentication and roles (Keycloak)

Keycloak (already running in Docker) handles login, users, and role assignment. The app stores no passwords and has no role-management screens of its own.

**Keycloak setup** (done once; exact steps documented in `docs/keycloak-setup.md`):

- A realm for the app, for example `faultline` (see Section 15).
- A client `faultline-web`: public client, standard flow (Authorization Code with PKCE, method `S256`), redirect URIs and web origins set to the dashboard URL.
- Three realm roles: `faultline-viewer`, `faultline-reviewer`, `faultline-admin`, assigned to users or groups in the Keycloak admin console. The prefix avoids clashes if the realm is shared with other apps.

**Frontend:**

- `keycloak-angular` with `keycloak-js`. The app requires login on start (`onLoad: 'login-required'`, PKCE `S256`).
- The library's bearer-token interceptor adds the access token to requests for the API base URL only, and refreshes the token before it expires.
- Roles are read from the token to show or hide actions and to guard admin routes. A logout button ends the Keycloak session.

**Backend:**

- Every endpoint except `/api/health` requires `Authorization: Bearer <access token>`.
- Tokens are validated with PyJWT: signature checked against the realm's public keys (fetched from `{issuer}/protocol/openid-connect/certs` and cached by `PyJWKClient`), `iss` must equal the configured issuer, `exp` must be in the future, and `azp` must equal `faultline-web`.
- The role comes from `realm_access.roles`. Roles are hierarchical (admin includes reviewer, reviewer includes viewer); a user with none of the three gets `403`.
- Each route declares its minimum role with a FastAPI dependency such as `Depends(require_role("reviewer"))`.
- The `users` table is updated from the token (Keycloak user ID, email, name, current role, last seen), at most once every 5 minutes per user. It gives names to the audit log and review history.

**Permissions:**

| Action | Viewer | Reviewer | Admin |
|---|:-:|:-:|:-:|
| View dashboard, errors, runs, logged emails | ✓ | ✓ | ✓ |
| Review items (approve, edit, reject) | | ✓ | ✓ |
| Change error status, severity, team, category | | ✓ | ✓ |
| Mute, snooze, unmute | | ✓ | ✓ |
| Merge fingerprints | | ✓ | ✓ |
| Trigger a run manually | | ✓ | ✓ |
| Edit settings (levels, services, teams, routing, budget, schedule) | | | ✓ |
| View users and audit log | | | ✓ |
| Assign roles | In the Keycloak admin console, not the dashboard |||

- Roles are enforced **on the server** for every endpoint. The Angular app also hides actions the user can't perform, but that is for convenience, not security.

#### 5.9.8 Audit log

- Records: every settings change, mute, snooze, unmute, merge, manual override, review decision, and run trigger. (Role changes happen in Keycloak, which keeps its own admin event log.)
- Each entry: `actor`, `action`, `entity_type`, `entity_id`, `before` (JSON), `after` (JSON), `reason`, `created_at`.
- **Append-only:** the API offers no update or delete; the database user used by the app has no `UPDATE`/`DELETE` permission on this table.
- The Audit log page (admin only) filters by user, action, entity, and date range. Each error's detail page also shows the audit entries for that error.

#### 5.9.9 Kept out of the dashboard

These stay in environment variables (`.env`) or code, changed by developers:

- **Secrets and API keys** (Elasticsearch, Groq, Tavily): environment variables only.
- **Drain3 parameters** (`sim_th`, `depth`, masks): changing them can reshuffle error identities. Change only after checking the results with `tune_drain.py`.
- **LLM and embedding model choice**: switching models changes classification behavior, and changing embedding models requires re-embedding the knowledge base.
- **Redaction rules**: in `redaction_rules.json` for the MVP, changed by developers and reviewed carefully, since a bad rule can leak data. A UI editor is planned for a later phase (Section 18).

### 5.10 LLM (Groq) and embeddings

#### LLM

- **Provider:** Groq, through `langchain-groq` (`ChatGroq`), with `temperature = 0`.
- **Model:** set with `GROQ_MODEL`. Default `llama-3.3-70b-versatile`; `openai/gpt-oss-120b` is an alternative. Groq's model list changes, so confirm the choice against the current list at the start of the project. The model must support tool calling, which structured output relies on.
- **Free-tier limits:** Groq's free tier is rate-limited per model. For the 70B model, published limits are around 30 requests per minute, 1,000 requests per day, and roughly 12,000 tokens per minute. The token limit is usually the one that binds first. The design handles this as follows:
  - **Client-side rate limiter:** LangChain's built-in `InMemoryRateLimiter`, set from `GROQ_REQUESTS_PER_MINUTE` (default 20), so requests are spaced out instead of hitting the limit.
  - **Small prompts:** send the template plus at most 2 redacted sample lines, each truncated to 500 characters. Classification is batched, about 10 errors per call.
  - **Rate-limit errors (HTTP 429):** wait for the time Groq's `retry-after` header gives, and retry up to 3 times. If it still fails, the remaining items are marked `deferred` for the next run; the run itself doesn't fail.
  - **Budget:** the per-run budget defaults (Section 5.9.6) keep hourly runs within the daily limit.
- Token usage reported in Groq's responses is added to the run's stats.

#### Embeddings

- **Model:** `BAAI/bge-small-en-v1.5` through `fastembed`. It runs locally on the CPU (ONNX runtime), needs no GPU, API key, or network access after the first download, and produces 384-number vectors.
- The model is downloaded once on first use into `EMBEDDING_CACHE_DIR` and loaded once per process.
- Embeddings are stored in Postgres as `real[]` columns, so **no pgvector extension is needed** in the existing Postgres container. Similarity is computed in Python (Section 5.7).
- For reference: pgvector is an extension installed inside the same Postgres database, not a separate database. It adds a vector column type and indexed similarity search. It's only worth adding if the knowledge base grows to tens of thousands of resolutions (Section 18).
- Changing the embedding model requires re-embedding the knowledge base with `scripts/reembed.py`.

---

## 6. Data model (Postgres)

| Table | Key columns |
|---|---|
| `sources` | `id`, `name`, `es_url`, `index_pattern`, `service_field`, `watermark`, `enabled` |
| `runs` | `id`, `requested_by`, `started_at`, `finished_at`, `window_start`, `window_end`, `status` (`requested`, `running`, `awaiting_review`, `sending`, `completed`, `failed`), `stats` (JSON: lines scanned, distinct errors, flagged, redaction counts) |
| `fingerprints` | `id` (UUID), `service`, `level`, `drain_cluster_id`, `template`, `category`, `severity`, `team_id`, `status` (`new`, `open`, `acknowledged`, `resolved`, `ignored`, `merged`), `merged_into_id`, `first_seen`, `last_seen`, `total_count`, `deferred` (bool). Suppression: `suppression` (`none`, `muted`, `snoozed`), `snoozed_until`, `alert_on_spike`, `suppression_reason`, `suppressed_by`, `suppressed_at`. Unique on (`service`, `drain_cluster_id`) |
| `fingerprint_aliases` | `service`, `drain_cluster_id`, `fingerprint_id` (target), `created_by`, `created_at`. Unique on (`service`, `drain_cluster_id`) |
| `services` | `name` (unique), `criticality`, `default_team_id`, `enabled`, `configured` (bool), `notes`, `first_seen` |
| `teams` | `id`, `name` (unique), `email_dl`, `min_email_severity`, `enabled` |
| `users` | `id` (Keycloak user ID, the token's `sub`), `email`, `display_name`, `role` (as last seen in the token), `last_seen_at`, `created_at`. Updated from the token; roles are managed in Keycloak |
| `audit_log` | `id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `before` (JSON), `after` (JSON), `reason`, `created_at`. Append-only |
| `occurrences` | `fingerprint_id`, `run_id`, `window_start`, `window_end`, `count` |
| `samples` | `fingerprint_id`, `redacted_text`, `seen_at` (keep latest 5 per fingerprint) |
| `resolutions` | `id`, `fingerprint_id`, `summary`, `probable_cause`, `steps` (JSON), `sources` (JSON), `confidence`, `origin`, `status` (`draft`, `approved`, `rejected`), `approved_by`, `approved_at`, `embedding` (`real[]`, 384 values) |
| `review_items` | `id`, `run_id`, `fingerprint_id`, `proposed` (JSON), `decision` (`pending`, `approved`, `edited`, `rejected`), `edited` (JSON), `reviewer`, `comment`, `decided_at` |
| `team_routing` | `id`, `match_type` (`service`, `category`, `service_regex`), `match_value`, `team_id`, `priority` |
| `email_log` | `id`, `run_id`, `team_id`, `recipients`, `subject`, `body`, `status` (`logged`), `created_at` |
| `drain_state` | `service`, `state` (bytes), `updated_at` |
| `settings` | `key`, `value` (JSON), `updated_by`, `updated_at`. Keys: `scan.levels`, `scan.keywords`, `schedule.interval_minutes`, `detection.*`, `budget.*`, `review.timeout_hours`, `review.reviewer_dl`, `routing.fallback_team_id` |
| LangGraph checkpoint tables | Created by `PostgresSaver.setup()` |

**Database access:** SQLAlchemy 2.0 (ORM, 2.0-style `select()` API) with the psycopg 3 driver (`postgresql+psycopg://` URLs). Models live in `db/models.py`; queries live in one small repository module per area, so routers and pipeline code never build queries themselves. The `embedding` column is mapped as `ARRAY(REAL)`.

**Migrations:** plain SQL files in `backend/app/db/migrations/` (`001_init.sql`, `002_….sql`). A small runner at startup applies, in order, every file not yet recorded in a `schema_migrations` table, each in its own transaction. No migration library. The SQL files are the source of truth for the schema: SQLAlchemy models must match them, and `metadata.create_all()` is never used.

The app uses its own database (for example `faultline`) and database user in the existing Postgres container. Index `occurrences(fingerprint_id, window_start)`, `fingerprints(status, severity, last_seen)`, `fingerprints(suppression, snoozed_until)`, and `audit_log(entity_type, entity_id, created_at)`.

**Retention (default):** occurrences kept 180 days, samples 30 days, runs and email logs 90 days. Configurable.

---

## 7. Backend API (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health check (DB, Elasticsearch, scheduler) |
| GET | `/api/dashboard/summary` | Counts by severity/status, new today, top services, trend data |
| GET | `/api/errors` | List with filters: severity, category, team, status, service, date range, search; paginated |
| GET | `/api/errors/{id}` | Detail: template, samples, resolution, flags |
| PATCH | `/api/errors/{id}` | Update status, severity, team, category (manual override) |
| GET | `/api/errors/{id}/occurrences` | Time series for charts |
| GET | `/api/runs` | Run history with stats |
| GET | `/api/runs/{id}` | Run detail, including email log |
| POST | `/api/runs/trigger` | Start a run now |
| GET | `/api/reviews/pending` | All pending review items, grouped by run and team |
| PUT | `/api/review-items/{id}` | Save a decision and edits for one item |
| POST | `/api/runs/{id}/review/submit` | Finalize review and resume the workflow |
| POST | `/api/errors/{id}/mute` | Mute (`reason`, `alert_on_spike`) |
| POST | `/api/errors/{id}/snooze` | Snooze (`until`, `reason`) |
| POST | `/api/errors/{id}/unsuppress` | Remove mute or snooze |
| POST | `/api/errors/bulk/suppress` | Mute or snooze several errors at once |
| GET | `/api/errors/{id}/merge-candidates` | Search same-service fingerprints to merge |
| POST | `/api/errors/{id}/merge` | Merge `source_ids` into this error |
| GET/POST/PUT | `/api/services` | List and edit services, criticality, default team |
| GET/POST/PUT/DELETE | `/api/teams` | Manage teams, DLs, minimum email severity |
| GET/POST/PUT/DELETE | `/api/routing` | Manage team routing rules |
| GET/PUT | `/api/settings` | Levels, keywords, schedule, detection, budget, review settings |
| POST | `/api/settings/scan/preview` | Preview generated query and 24-hour match count |
| GET | `/api/me` | Current user and role |
| GET | `/api/users` | Users who have signed in, with current role and last seen (admin, read-only) |
| GET | `/api/runs/{id}/emails` | Logged emails for a run, with full content |
| GET | `/api/audit-log` | Filterable audit log (admin) |

- Request and response models use Pydantic. FastAPI's built-in API docs (`/docs`) are the reference for the front-end developer. The Angular client is written by hand (see Section 8, API client conventions).
- Authentication: Keycloak bearer tokens on every endpoint except `/api/health` (Section 5.9.7). Reviewer identity on decisions comes from the token.
- CORS allows only the dashboard origin (`CORS_ORIGINS`).

---

## 8. Angular dashboard

### Stack

- **Angular 22** with standalone components, signals, and built-in control flow (see Section 10 for versions)
- **Tailwind CSS v4** for all styling (no Angular Material)
- **No Angular Material, CDK, NgRx, or component libraries.** Dialogs use the native `<dialog>` element (`showModal()` provides focus trapping and Esc to close); menus and dropdowns use native `<select>` or the HTML `popover` attribute
- **Keycloak** login through `keycloak-angular` and `keycloak-js` (Section 5.9.7)
- A small in-house component set in `shared/ui/`, styled with Tailwind: button, badge (severity/status), data table with sorting and paging, dialog, tabs, toast notifications, filter bar, and a chart wrapper. Date and time inputs (for snooze) use native `<input type="datetime-local">`
- **ECharts** for charts, used directly through a small `shared/ui/chart` wrapper component (no ngx-echarts)
- Hand-written API client (see API client conventions below)
- Lazy-loaded feature routes

### API client conventions

The Angular API client is written by hand, with no code generation. To keep it in sync with the backend:

- **Models:** all API request and response interfaces live in `core/api/models/`, one file per backend area (`errors.ts`, `runs.ts`, `reviews.ts`, `settings.ts`, `admin.ts`). Each interface mirrors the matching Pydantic model, with the same field names.
- **Services:** all HTTP calls live in services under `core/api/` (for example `ErrorsApiService`, `ReviewsApiService`), one per backend router. Components never call `HttpClient` directly.
- **Shared behavior** (base URL, auth headers, error handling, showing a toast on failure) is handled once in HTTP interceptors, not repeated in each service.
- **Changes:** when a backend developer changes an endpoint or model, they note it in the pull request description and tell the front-end developer, who updates the matching interface in the same sprint.

### State management (signals, no NgRx)

- Each feature has **one store service** that owns its state as signals, for example `ErrorsStore`, `ReviewStore`, `RunsStore`, `SettingsStore`.
- State is held in private writable `signal()`s and exposed as read-only signals (`.asReadonly()`), with `computed()` for derived values such as filtered lists and counts.
- Store methods call the API services, update the signals, and track `loading` and `error` signals for the UI.
- Components inject stores, read signals in their templates, and call store methods. Components don't keep their own copies of shared state.
- App-wide state (current user and roles, theme) lives in root-provided services (`AuthStore`, `ThemeStore`). Page-specific stores are provided in the route's `providers`, so their state resets when the user leaves the page.
- `effect()` is used only for side effects, such as syncing filters to URL query parameters, never to derive state.
- RxJS is used only inside the API services, because `HttpClient` returns observables. Stores convert at the boundary (for example with `firstValueFrom`), so state is never held in subjects.
- Angular's `resource()` / `httpResource()` can be used for simple read-only data where it makes the code shorter.

### Pages

1. **Overview**
   - Cards: new errors today, open Critical/High counts, errors awaiting review, last run status
   - Warnings: items deferred due to budget, unconfigured services
   - Chart: distinct errors over time, stacked by severity
   - Top 10 noisiest services and top 10 errors by count
2. **Errors**
   - Filterable, sortable table: severity, template (truncated), service, category, team, count, last seen, status, and a small trend sparkline
   - Filters: severity, category, team, service, status, date range, text search, and "Show suppressed"
   - Muted/snoozed badges; bulk select to mute or snooze
3. **Error detail**
   - Full template, redacted sample lines, flags (new/spike/regression)
   - Resolution: summary, probable cause, steps, sources (links), confidence badge, origin (KB/web/LLM-only)
   - Occurrence chart over time
   - Review, status, and audit history
   - Actions: change status, override severity, team, or category; mute; snooze (date picker); unmute
   - "Merge into this error": search same-service errors, side-by-side comparison, confirm dialog
4. **Review queue**
   - Pending items grouped by run and team, sorted by severity
   - For each item: approve, reject, or edit (severity, category, team, resolution text)
   - Clearly show which values came from the LLM and which from rules
   - "Report leaked data" button on sample lines, which flags the item and notifies admins
   - "Submit review" button, which calls the submit endpoint and resumes the workflow
5. **Runs**
   - History: window, status, lines scanned, distinct errors, flagged errors, deferred errors, budget usage, redaction counts by rule, emails sent or failed
   - Run detail: stats, budget usage, and the emails logged for that run with their full content
   - Button to trigger a run manually (reviewer and admin)
6. **Settings** (admin; tabs)
   - **Scanning:** log levels, keywords with level mapping, schedule interval, query preview with 24-hour match count
   - **Services:** table of services with criticality, default team, enabled; unconfigured services highlighted
   - **Teams & routing:** teams with DL and minimum email severity; routing rules with priority; fallback team
   - **Detection & budget:** spike thresholds, per-run limits for items, LLM calls, and Tavily calls
   - **Review:** review timeout, reviewer DL
7. **Users** (admin, read-only)
   - Users who have signed in, with their current role and last seen time, plus a link to the Keycloak admin console for role changes
8. **Audit log** (admin)
   - Filterable table (user, action, entity, date range) with a before/after view for each entry

### UX notes

- Severity colors are used consistently across all pages, always paired with a text label (not color alone).
- Tables use server-side paging and filtering.
- Navigation and action buttons adapt to the user's role (from `/api/me`); admin pages are protected by a route guard.
- Destructive or high-impact actions (mute, merge, settings save) use a confirmation dialog, and mute/snooze require a reason.
- Dark and light themes: colors are defined once as design tokens with Tailwind v4's CSS-first `@theme` configuration, and dark mode uses a class-based `dark:` variant so users can toggle it.
- Severity colors are defined as named tokens (for example `--color-sev-critical`) so every page uses the same palette.

---

## 9. Configuration

There is no configuration file format to parse. Configuration comes from three places:

1. **Environment variables** (a `.env` file in development), read with `pydantic-settings` into one `Settings` class in `backend/app/config.py`. Secrets live only here.
2. **Code defaults** in the same `Settings` class for technical values that rarely change (ingest lag, page size, prefix patterns, app package prefixes, Drain3 parameters, knowledge-base threshold). Each can be overridden with an environment variable.
3. **Dashboard settings** in the `settings` table (Section 5.9), seeded with defaults on first start.

### `backend/.env.example`

```bash
# Postgres (existing Docker container)
DATABASE_URL=postgresql+psycopg://faultline:<password>@localhost:5432/faultline

# Elasticsearch
ES_URL=http://localhost:9200
ES_API_KEY=                      # empty in Phase 1 (security disabled); set when security is enabled
ES_CA_CERT=                      # only needed with HTTPS and a self-signed certificate
ES_INDEX_PATTERN=logs-*
ES_MESSAGE_FIELD=message
ES_SERVICE_FIELD=kubernetes.container.name   # confirm against real documents
ES_HOST_FIELD=host.name

# Keycloak (existing Docker container)
KEYCLOAK_ISSUER=http://localhost:8080/realms/faultline
KEYCLOAK_CLIENT_ID=faultline-web

# LLM (Groq)
GROQ_API_KEY=<key>
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_REQUESTS_PER_MINUTE=20

# Web search (Tavily)
TAVILY_API_KEY=<key>
TAVILY_SEARCH_DEPTH=basic

# Embeddings (local, free)
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_CACHE_DIR=./.cache/fastembed

# App
DASHBOARD_BASE_URL=http://localhost:4200
CORS_ORIGINS=http://localhost:4200
EMAIL_FROM=faultline@example.com
LOG_LEVEL=INFO
```

### Dashboard setting defaults (seeded on first start)

| Key | Default |
|---|---|
| `scan.levels` | `FATAL, CRITICAL, ERROR, WARN, WARNING` |
| `scan.keywords` | `Exception → ERROR`, `Traceback → ERROR` |
| `schedule.interval_minutes` | 60 |
| `detection.spike_multiplier` / `spike_lookback_windows` / `spike_min_count` | 3 / 24 / 20 |
| `budget.max_items_per_run` / `max_llm_calls_per_run` / `max_tavily_calls_per_run` | 30 / 30 / 20 |
| `review.timeout_hours` | 4 |
| `review.reviewer_dl` | `faultline-review@example.com` |

### Frontend configuration

`frontend/public/config.json`, loaded at startup, so the same build works in every environment:

```json
{
  "apiBaseUrl": "http://localhost:8000/api",
  "keycloak": { "url": "http://localhost:8080", "realm": "faultline", "clientId": "faultline-web" }
}
```

---

## 10. Tech stack and versions

Versions below were checked against PyPI and npm on **23 September 2026**. Use the latest patch release of each at project start.

**Dependency rule:** only the packages listed here. No migration tool, scheduler library, template engine, tracing tool, linter, or type checker. Adding any other dependency needs a clear reason and approval.

### Runtimes and infrastructure

| Component | Version | Notes |
|---|---|---|
| Python | **3.14** (latest 3.14.x) | All backend dependencies below support it |
| Node.js | **24 LTS** (≥ 24.15) | Required by Angular 22 |
| PostgreSQL | Existing Docker container | No extensions needed (embeddings are stored as `real[]`) |
| Keycloak | Existing Docker container | `keycloak-js` 26.x works with current Keycloak servers; check your server version and see Section 15 |
| Elasticsearch | **9.5.3**, running in Docker | Phase 1: security disabled, plain HTTP, no credentials |
| uv | Latest | Python package manager (`pyproject.toml` + `uv.lock`) |

### Backend (Python): 13 packages

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.141.x | API |
| `uvicorn` | 0.53.x | ASGI server |
| `pydantic-settings` | 2.15.x | Environment configuration (brings `pydantic` 2.13) |
| `sqlalchemy` | 2.0.x (currently 2.0.54) | ORM and connection pool. Stay on 2.0; 2.1 is still a release candidate |
| `psycopg[binary]` | 3.3.x | Postgres driver for SQLAlchemy; also used directly by the LangGraph checkpointer |
| `langgraph` | 1.2.x | Agent workflow, `interrupt()` / `Command(resume=...)` |
| `langgraph-checkpoint-postgres` | 3.1.x | `PostgresSaver` checkpointer |
| `langchain-groq` | 1.1.x | `ChatGroq` (brings `langchain-core` 1.6 and the `groq` SDK) |
| `langchain-tavily` | 0.2.x | Tavily search |
| `elasticsearch` | 9.5.x | Matches the 9.5.3 cluster |
| `drain3` | 0.9.11 | Log templating (see note below) |
| `fastembed` | 0.8.x | Local embeddings (brings `numpy` and `onnxruntime`) |
| `pyjwt[crypto]` | 2.14.x | Keycloak token validation |

**Note on Drain3:** it is stable and widely used but has had no release since 2022. Keep it behind our own `TemplateMiner` interface in `pipeline/fingerprint.py`, so it can be replaced or forked without touching other code, and confirm in Week 1 that it works on Python 3.14.

### Frontend (Angular)

| Package | Version | Notes |
|---|---|---|
| `@angular/*` | **22.1.x** | Whatever `ng new` generates for Angular 22 (core, common, router, forms, platform-browser, build tooling) |
| `typescript` | **6.0.x** | Not TypeScript 7: Angular 22's compiler requires `>=6.0 <6.1` |
| `rxjs` | 7.8.x | Required by Angular; used only inside API services, not for state |
| `tailwindcss` | **4.3.x** | Set up with Tailwind's official v4 Angular guide (`@tailwindcss/postcss`, `@import "tailwindcss";`, no `tailwind.config.js`) |
| `@tailwindcss/postcss`, `postcss` | 4.3.x / latest | Build-time only |
| `keycloak-angular` | 22.x | Angular 22 integration for Keycloak |
| `keycloak-js` | 26.x | Keycloak client library |
| `echarts` | 6.x (currently 6.1) | Used directly through a small wrapper component |

### Conventions

- **Backend:** type hints throughout and Pydantic models at every boundary, even without a type checker in the toolchain.
- **Angular:** standalone components, signals, built-in control flow (`@if`, `@for`), `inject()`, functional guards and interceptors, and the setup `ng new` generates for Angular 22.
- **Verification:** `ng build` must succeed with no errors, and the backend must start cleanly and apply its migrations.
- Commit the lock files (`uv.lock`, `package-lock.json`). Re-check versions at project start.

---

## 11. Repository structure

```
faultline/
├── backend/
│   ├── pyproject.toml, uv.lock, .env.example
│   ├── app/
│   │   ├── main.py                   # FastAPI app; runs migrations on startup
│   │   ├── worker.py                 # scheduler loop + run orchestration
│   │   ├── config.py                 # pydantic-settings Settings class
│   │   ├── auth.py                   # Keycloak token validation, require_role()
│   │   ├── db/
│   │   │   ├── session.py            # SQLAlchemy engine + session
│   │   │   ├── models.py             # SQLAlchemy models (match the SQL migrations)
│   │   │   ├── migrate.py            # applies SQL migrations in order
│   │   │   ├── migrations/           # 001_init.sql, 002_....sql
│   │   │   └── repos/                # queries, one module per area
│   │   ├── connectors/
│   │   │   └── elasticsearch.py      # PIT + search_after, watermark
│   │   ├── pipeline/
│   │   │   ├── preprocess.py         # prefix strip, level/service extraction, stack traces
│   │   │   ├── fingerprint.py        # TemplateMiner interface over Drain3
│   │   │   ├── drain_persistence.py  # Postgres PersistenceHandler
│   │   │   └── detection.py          # new / spike / regression / snooze expiry
│   │   ├── redaction/
│   │   │   ├── rules.py
│   │   │   ├── engine.py
│   │   │   └── entropy.py
│   │   ├── agent/
│   │   │   ├── state.py
│   │   │   ├── llm.py                # ChatGroq + rate limiter + 429 handling
│   │   │   ├── embeddings.py         # fastembed model, cosine similarity
│   │   │   ├── nodes/                # classify, severity_rules, kb_lookup, web_research, ...
│   │   │   ├── prompts/
│   │   │   └── graph.py
│   │   ├── notify/
│   │   │   └── email_sender.py       # EmailSender interface + LogEmailSender
│   │   ├── admin/
│   │   │   ├── settings_service.py   # load/validate/snapshot dashboard settings
│   │   │   ├── suppression.py        # mute / snooze
│   │   │   ├── merge.py              # fingerprint merge (transactional)
│   │   │   ├── budget.py             # prioritization + deferral
│   │   │   └── audit.py              # append-only audit writer
│   │   └── api/                      # FastAPI routers
│   ├── config/
│   │   └── redaction_rules.json
│   └── scripts/
│       ├── tune_drain.py
│       └── reembed.py
├── frontend/
│   ├── public/config.json            # API URL + Keycloak settings
│   └── src/app/
│       ├── core/
│       │   ├── api/                  # models/ + API services (HttpClient only here)
│       │   ├── auth/                 # Keycloak setup, role guard, AuthStore
│       │   └── theme/                # ThemeStore
│       ├── shared/ui/                # button, badge, table, dialog, tabs, toast, filters, chart
│       └── features/                 # each feature has its components + one store service
│           ├── overview/
│           ├── errors/
│           ├── error-detail/
│           ├── review/
│           ├── runs/
│           ├── settings/             # scanning, services, teams, detection, review tabs
│           ├── users/
│           └── audit-log/
└── docs/
    ├── spec.md
    └── keycloak-setup.md
```

### Running locally

PostgreSQL, Keycloak, and Elasticsearch already run in Docker. The app itself runs as three processes:

- API: `cd backend && uv run uvicorn app.main:app --reload`
- Worker: `cd backend && uv run python -m app.worker`
- Dashboard: `cd frontend && npx ng serve`

One-time setup: create the `faultline` database and user in Postgres; create the realm, client, and roles in Keycloak (`docs/keycloak-setup.md`); no Elasticsearch setup is needed in Phase 1, since security is disabled.

---

## 12. Run lifecycle

1. The scheduler fires and acquires the run lock. A `runs` row is created with status `running`, and a snapshot of the current dashboard settings is saved with it.
2. The Elasticsearch connector fetches records matching the configured levels and keywords for the window.
3. Each record goes through preprocessing, then redaction, then Drain3. Cluster IDs are resolved through `fingerprint_aliases` (merges). New services are auto-registered as unconfigured.
4. Fingerprints, occurrences, and samples are updated. Drain3 state is saved. The watermark is advanced.
5. Detection skips muted, snoozed, and disabled-service errors, then flags new, spiking, regressed, and snooze-expired errors. Deferred errors from the previous run are added first. The budget is applied, and any excess is deferred.
6. If nothing is flagged, the run is marked `completed`. Otherwise the LangGraph workflow starts, with `thread_id = run_id`.
7. The workflow pauses at `human_review`. The run status becomes `awaiting_review`.
8. A reviewer approves, edits, or rejects items in the dashboard and submits.
9. The workflow resumes: emails are sent, resolutions are saved, and the run is marked `completed`.

**Failures:** if ingestion fails, the watermark is not advanced, so the next run retries the same window. If the agent workflow fails, the run is marked `failed` with the error, and it can be retried from the last checkpoint.

---

## 13. Security and privacy

- All text sent to Groq, Tavily, the email log, or Postgres is redacted (Section 5.4). Raw logs stay in Elasticsearch.
- **Elasticsearch (Phase 1):** security is disabled and the app connects over plain HTTP with no credentials. This is acceptable only because Elasticsearch runs on the local development machine: its port (9200) must not be reachable from other machines or the internet. The connector already supports `ES_API_KEY` and `ES_CA_CERT`, so turning security on later is a configuration change, not a code change. Before any shared or production use, enable security, use HTTPS, and connect with a **read-only API key** limited to the log indices (Section 18).
- Secrets live only in environment variables; `.env` is never committed.
- Authentication is handled by Keycloak. The backend validates every token's signature, issuer, expiry, and client, and enforces roles on every endpoint (Section 5.9.7).
- Every review decision, setting change, mute, and merge is recorded in the append-only audit log (Section 5.9.8).
- LLM prompts treat log content as data. Prompts must instruct the model to ignore any instructions found inside log text or search results (log lines and web pages can contain text that looks like instructions).
- The app's own logs contain only redacted text. LLM prompt contents are logged only at `DEBUG` level.

---

## 14. Observability

No tracing tool; everything comes from the app's own logs and run stats.

- **Structured JSON logging** for the API and worker.
- **Each LLM and Tavily call** is logged at `INFO` with duration, token counts (for Groq), and outcome, but not its content.
- **Run stats**, stored in `runs.stats` and shown on the Runs page: lines scanned, distinct errors, flagged, deferred, LLM calls and tokens, rate-limit retries, Tavily calls, redaction counts by rule, redaction failures, emails logged, and run duration.

---

## 15. Decisions

### Decided

| Area | Decision |
|---|---|
| LLM | Groq free tier, default model `llama-3.3-70b-versatile` |
| Embeddings | `BAAI/bge-small-en-v1.5` via `fastembed`, running locally |
| Email | Logged, not sent, in the MVP |
| Authentication | Keycloak, with realm roles `faultline-viewer`, `faultline-reviewer`, `faultline-admin` |
| Infrastructure | Existing Docker containers for PostgreSQL, Keycloak, and Elasticsearch 9.5.3 (security disabled, HTTP only, for Phase 1) |
| Database access | SQLAlchemy 2.0 with psycopg 3; SQL-file migrations |
| Dependencies | Bare minimum (Section 10) |

### Still open (resolve before or during Week 1)

| # | Decision | Notes |
|---|---|---|
| 1 | Keycloak: new `faultline` realm or an existing realm, and the server version | Affects `KEYCLOAK_ISSUER`; confirm `keycloak-js` 26 works with the server |
| 2 | Confirm the Groq model against Groq's current model list and limits | Default `llama-3.3-70b-versatile` |
| 3 | Tavily plan and its monthly credits | Sets `max_tavily_calls_per_run` |
| 4 | Which field identifies the service in log documents | Check real documents |
| 5 | Are stack traces one document or split across documents? | If split, fix multiline handling in the log shipper |
| 6 | Initial team list and DL mapping | Used as recipients in the logged emails |
| 7 | Initial service list with criticality | Seeds the `services` table |
| 8 | Who reviews, and the expected review turnaround | Sets `review.timeout_hours` and reviewer DL |
| 9 | Organization-specific identifiers to redact (customer IDs, account numbers, etc.) | Add to `redaction_rules.json` |

---

## 16. Milestones

Assumes one backend developer and one front-end developer.

The dashboard-managed settings add roughly one week, so the MVP is now about **5 weeks**.

**Week 1: Log scanner foundation**
- Repository setup, `.env` configuration, connection to the existing Postgres, SQLAlchemy models, SQL migrations and runner (including `services`, `teams`, `users`, `audit_log`, `fingerprint_aliases`)
- Sample logs loaded into the Elasticsearch 9.5.3 container for development
- Elasticsearch connector with watermark and PIT paging, reading levels and keywords from settings
- Preprocessing and the redaction module
- Drain3 with Postgres persistence and alias resolution
- `tune_drain.py`, run against real logs; tune settings
- Settings service with defaults and per-run snapshot
- Front end: Angular project setup with Tailwind and Keycloak login, layout, routing, shared UI components, API client models and services

**Week 2: Detection and agent workflow**
- Detection (new, spike, regression, snooze expiry) with suppression checks
- Budget prioritization and deferral
- Groq client with rate limiter and 429 handling; local embeddings with fastembed
- LangGraph workflow: classify, severity rules (using service criticality), KB lookup, Tavily research, build report (with team thresholds)
- Human review interrupt with `PostgresSaver`
- API endpoints for errors, runs, reviews
- Front end: Errors list and Error detail pages

**Week 3: Review, email, and core dashboard**
- Review submit and resume, timeout reminders
- Email digests written to the log and `email_log` (no real sending)
- Front end: Review queue, Overview, Runs pages

**Week 4: Dashboard-managed settings and administration**
- Keycloak realm, client, and roles set up (`docs/keycloak-setup.md`); token validation and role checks on every endpoint; user sync from tokens; audit log writer
- Mute, snooze, and bulk suppression
- Fingerprint merge
- Services, teams, routing, and settings endpoints (including scan preview)
- Front end: Settings tabs, Users, Audit log pages; mute/snooze/merge actions; role-aware UI

**Week 5: Hardening**
- Run stats and structured logging
- Pilot with one or two teams; tune Drain3, spike thresholds, and prompts based on feedback
- Documentation (setup, configuration, runbook)

---

## 17. MVP acceptance criteria

- A scheduled run processes an Elasticsearch time window without missing or double-counting records (verified against Elasticsearch counts).
- On real logs, one real-world error maps to one fingerprint in the large majority of sampled cases (spot-check the top 50 templates).
- The same error keeps the same fingerprint across runs and after a worker restart.
- No unredacted secrets appear in Postgres, emails, LLM traces, or Tavily queries, confirmed by manual spot checks of real run output.
- Only new, spiking, or regressed errors are sent to the LLM.
- Every flagged error has a category, severity, team, and resolution with a confidence level and sources (or is clearly marked "no sourced resolution found").
- No email is logged as sent without a human approval recorded in `review_items`.
- Each team gets one logged digest per run containing only its approved items, and its full content is visible on the Run detail page.
- The Angular dashboard shows all eight pages with working filters and charts, and reviewers can complete a review end-to-end.
- Changing log levels or keywords in the dashboard changes what the next run scans, and the preview count matches Elasticsearch.
- A muted error is never emailed (unless `alert_on_spike` is on and it spikes); a snoozed error returns automatically after its snooze date if still occurring.
- After merging two fingerprints, new log lines for either are counted against the merged error, with no loss of history.
- Items below a team's minimum severity are not emailed to that team; Critical items always go to review.
- When the budget is exceeded, the highest-priority errors are processed and the rest are deferred to the next run, with no run failure.
- Login goes through Keycloak, and each Keycloak role can do exactly what the permission table allows, enforced on the server. Requests with missing, expired, or wrongly signed tokens are rejected.
- Groq rate-limit errors are retried or deferred to the next run; they never fail a run.
- The backend and frontend use only the dependencies listed in Section 10.
- Every change listed in Section 5.9.8 appears in the audit log with correct before/after values.

---

## 18. Future phases

- **Before any shared or production deployment:** enable Elasticsearch security, switch to HTTPS, and connect with a read-only API key (set `ES_API_KEY` and, if needed, `ES_CA_CERT`).
- **Phase 2:** MCP servers wrapping the Elasticsearch connector and email sender (so new sources plug in easily and logs can be queried from MCP-enabled clients); Slack or Teams notifications; real email sending (SMTP, Microsoft 365, or Amazon SES) as a second `EmailSender`; a paid Groq tier or another LLM provider if free-tier limits are too tight; pgvector if the knowledge base grows large.
- **Phase 2, more dashboard-managed settings:**
  - Scanning: Elasticsearch index patterns and scan window/lag
  - Noise control: exclude patterns (regex rules that drop lines entirely, such as health-check noise)
  - Fingerprints: split a wrongly merged error, and undo a merge
  - Classification: severity rules editor and editable category list
  - Notifications: per-team digest frequency, escalation contact for Critical errors on review timeout
  - Review: reviewers per team, auto-approve rules (for example, recurring errors that already have an approved KB resolution)
  - Research: preferred and blocked domains for Tavily, knowledge-base match threshold
  - Redaction: rules and allowlist editor with a preview box showing the redacted output; admin-only, and versioned so changes can be rolled back
  - Knowledge base: edit, retire, or mark resolutions outdated; teams add their own runbook entries for application-specific errors
- **Phase 3:** automatic Jira or ServiceNow ticket creation for approved Critical/High errors; using reviewer edits as examples to improve classification prompts; resolution-effectiveness tracking (did the error stop after the fix?); additional log sources.
