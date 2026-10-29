# Faultline — Backend API Contract (MVP)

Source of truth: `docs/spec.md` Section 7 (endpoints), Section 6 (data model), Section 5.7 (state), Section 5.9.7 (roles), and Section 5.9.8 (audit).
This document is the contract that the backend Pydantic models and the hand-written Angular models (`core/api/models/`) both follow. FastAPI's `/docs` must match it.

Items marked **(assumption, see Gx)** are choices the spec does not fix. Gx refers to the spec review list. Change them here first if the decision goes the other way.

---

## 1. Conventions

- **Base path:** `/api`. All bodies are JSON, `Content-Type: application/json`, with **snake_case** fields.
- **Timestamps:** ISO 8601 in UTC with a `Z` suffix (`2026-09-23T10:14:03Z`). Request timestamps without an offset are rejected (422).
- **IDs:** fingerprints, runs, resolutions, review items, teams, routing rules, email logs, and audit entries use UUID strings **(assumption: the spec only says UUID for fingerprints; UUIDs for every `id` keep one ID type)**. Users use the Keycloak `sub` string. Services are keyed by `name` (the table has no `id`; see G43).
- **Authentication:** `Authorization: Bearer <access token>` on every endpoint except `GET /api/health`. Token rules are in spec 5.9.7.
- **Roles:** hierarchical: `admin` ⊃ `reviewer` ⊃ `viewer`. "Min role" below is the lowest role allowed.
- **Pagination** (list endpoints marked "paged"): query `page` (int ≥ 1, default 1) and `page_size` (int 1–100, default 25). The response is `Page<T>`.
- **Sorting:** query `sort` = field name, prefixed with `-` for descending. Only the listed fields are allowed. Others return 422.
- **Repeatable filters:** multi-value filters repeat the parameter (`?severity=Critical&severity=High`).
- **Free text** from users (reasons, comments, edited resolution text) is passed through `redact()` before storage **(assumption, see G37)**.

### 1.1 Standard error body

Every non-2xx response has this body (FastAPI's default `{"detail": ...}` is replaced by an exception handler):

```json
{
  "code": "validation_error",
  "message": "Human-readable summary",
  "details": [ { "field": "body.until", "message": "must be at most 90 days in the future" } ]
}
```

| Field | Type | Notes |
|---|---|---|
| `code` | string | One of: `unauthorized`, `forbidden`, `not_found`, `validation_error`, `conflict`, `upstream_error`, `internal_error` |
| `message` | string | Safe to show in a toast |
| `details` | `FieldError[]` \| null | For `validation_error` only |

`FieldError`: `{ field: string, message: string }`

### 1.2 Status codes used everywhere

| Status | Meaning |
|---|---|
| 200 | OK, with a body |
| 201 | Created, with a body |
| 202 | Accepted. The worker completes the action asynchronously |
| 204 | No content (DELETE) |
| 401 | Missing, malformed, expired, or wrongly signed token; wrong `iss` or `azp` |
| 403 | Valid token but the role is too low, or the user has none of the three Faultline roles |
| 404 | Entity not found |
| 409 | State conflict (for example, the run is not `awaiting_review`, or a unique name is taken) |
| 422 | Validation error |
| 502 | Elasticsearch unreachable (`upstream_error`) |
| 503 | Health check failed |

401 and 403 apply to every authenticated endpoint and are not repeated below.

---

## 2. Enums (exactly as in the spec)

| Enum | Values | Spec |
|---|---|---|
| `Severity` | `Critical`, `High`, `Medium`, `Low` | 5.7 |
| `Category` | `System`, `Application`, `Database`, `Network`, `Security`, `Infrastructure`, `Third-party`, `Unknown` | 5.7 |
| `ScanLevel` | `FATAL`, `CRITICAL`, `ERROR`, `WARN`, `WARNING` | 5.9.1, 9 |
| `LogLevel` (stored on a fingerprint) | `FATAL`, `CRITICAL`, `ERROR`, `WARN` **(assumption: WARNING is normalized to WARN, see G23)** | 5.3 |
| `FingerprintStatus` | `new`, `open`, `acknowledged`, `resolved`, `ignored`, `merged` | 6 |
| `Suppression` | `none`, `muted`, `snoozed` | 6 |
| `Flag` | `new`, `spike`, `regression`, `snooze_expired` | 5.6, 5.7 |
| `RunStatus` | `requested`, `running`, `awaiting_review`, `sending`, `completed`, `failed` | 6 |
| `ReviewDecision` | `pending`, `approved`, `edited`, `rejected`. **Proposed, pending approval:** `cancelled` (G12), `below_threshold` (G9) | 6, 5.9.4, 5.7 |
| `ResolutionStatus` | `draft`, `approved`, `rejected` | 6 |
| `Confidence` | `high`, `medium`, `low` | 5.7 |
| `Origin` | `kb`, `web`, `llm_only` | 5.7 |
| `Criticality` | `high`, `medium`, `low` | 5.9.2 |
| `MatchType` | `service`, `category`, `service_regex` | 6 |
| `EmailStatus` | `logged`. **Proposed, pending approval:** `failed` (G24) | 6 |
| `Role` | `viewer`, `reviewer`, `admin` (from Keycloak roles `faultline-viewer/reviewer/admin`) | 5.9.7 |
| `TeamSource` | `rule`, `service_default`, `llm_suggestion`, `fallback`, `none` **(assumption, see G10)** | 5.9.5 |
| `AuditAction` | `settings.update`, `service.create`, `service.update`, `team.create`, `team.update`, `team.delete`, `routing.create`, `routing.update`, `routing.delete`, `error.update`, `error.mute`, `error.snooze`, `error.unsuppress`, `error.merge`, `review.decide`, `review.submit`, `run.trigger`. Plus `error.snooze_expired` and `service.auto_register` for system actions with a null actor **(assumption: names not given in spec 5.9.8, see G22)** | 5.9.8 |
| `AuditEntityType` | `setting`, `service`, `team`, `routing_rule`, `fingerprint`, `review_item`, `run` **(assumption)** | 5.9.8 |

Severity order for sorting and thresholds: `Critical` > `High` > `Medium` > `Low`.

---

## 3. Shared schemas

Fields are required and non-null unless marked `?` (optional or nullable).

### `Page<T>`
| Field | Type |
|---|---|
| `items` | `T[]` |
| `total` | int (total matching rows) |
| `page` | int |
| `page_size` | int |

### `UserRef`
| Field | Type |
|---|---|
| `id` | string (Keycloak `sub`) |
| `display_name` | string? |
| `email` | string? |

`null` in place of a `UserRef` means the system or scheduler did it.

### `TeamRef`
`{ id: uuid, name: string }`

### `ResolutionDraft` (spec 5.7)
| Field | Type | Notes |
|---|---|---|
| `summary` | string | |
| `probable_cause` | string | |
| `steps` | string[] | |
| `sources` | string[] | URLs, or `kb:<resolution_id>` |
| `confidence` | `Confidence` | |
| `origin` | `Origin` | |

When research is skipped because the budget ran out: `origin = llm_only`, `confidence = low`, `sources = []`, `summary` starts with `"Research skipped: budget reached"` **(assumption, see G8)**.

### `Resolution` (the `resolutions` row; `embedding` is never returned)
| Field | Type |
|---|---|
| `id` | uuid |
| `fingerprint_id` | uuid |
| `summary`, `probable_cause` | string |
| `steps`, `sources` | string[] |
| `confidence` | `Confidence` |
| `origin` | `Origin` |
| `status` | `ResolutionStatus` |
| `approved_by` | `UserRef`? |
| `approved_at` | timestamp? |

### `Sample`
`{ redacted_text: string, seen_at: timestamp }`

### `ErrorSummary` (a row in the Errors list)
| Field | Type | Source |
|---|---|---|
| `id` | uuid | `fingerprints.id` |
| `service` | string | |
| `level` | `LogLevel` | see G21 |
| `template` | string | full text. The UI truncates it |
| `category` | `Category`? | null until classified |
| `severity` | `Severity`? | null until classified |
| `team_id` | uuid? | |
| `team_name` | string? | joined from `teams` |
| `status` | `FingerprintStatus` | never `merged` in lists |
| `suppression` | `Suppression` | |
| `snoozed_until` | timestamp? | |
| `first_seen`, `last_seen` | timestamp | |
| `total_count` | int | |
| `deferred` | bool | |
| `trend` | int[] | 14 daily counts, oldest first, zero-filled, for the sparkline **(assumption, see G28)** |

### `ReviewHistoryEntry`
`{ review_item_id: uuid, run_id: uuid, decision: ReviewDecision, reviewer: UserRef?, comment: string?, decided_at: timestamp? }`

### `ErrorDetail` = `ErrorSummary` plus:
| Field | Type | Notes |
|---|---|---|
| `drain_cluster_id` | string | |
| `merged_into_id` | uuid? | set when `status = merged`. The UI redirects to the target |
| `alert_on_spike` | bool | |
| `suppression_reason` | string? | |
| `suppressed_by` | `UserRef`? | |
| `suppressed_at` | timestamp? | |
| `samples` | `Sample[]` | up to 5, newest first |
| `latest_flags` | `Flag[]` | flags from the most recent run that flagged it **(assumption, see G28)** |
| `resolutions` | `Resolution[]` | approved first, then drafts (several after a merge), then rejected |
| `pending_proposal` | `ProposedItem`? | from the open review item, if any |
| `review_history` | `ReviewHistoryEntry[]` | newest first |
| `audit_history` | `AuditEntry[]` | entries with `entity_type = fingerprint` and `entity_id = id`, newest first. Visible to viewers **(assumption, see G28)** |

### `ProposedItem` (the `review_items.proposed` JSON; **assumption, see G10**)
| Field | Type | Notes |
|---|---|---|
| `flags` | `Flag[]` | |
| `window_count` | int | count in this run's window |
| `category` | `Category` | from the LLM (or `Unknown` if classify was skipped) |
| `category_reason` | string? | LLM one-line reason |
| `llm_suggested_severity` | `Severity`? | null if classify was skipped |
| `severity` | `Severity` | final severity after `severity_rules` |
| `severity_adjustments` | string[] | for example `"FATAL → at least High"`, `"service criticality high → +1"` |
| `severity_reason` | string? | LLM reason |
| `team_id` | uuid? | final team (null = unrouted) |
| `team_name` | string? | |
| `team_source` | `TeamSource` | `llm_suggestion` must be labeled in the UI |
| `llm_suggested_team` | string? | raw LLM suggestion |
| `team_reason` | string? | |
| `resolution` | `ResolutionDraft` | |
| `below_threshold` | bool | true if below the team's `min_email_severity` (see G9) |

### `ReviewEdits` (the `review_items.edited` JSON)
All fields are optional. At least one is required when `decision = edited`.
| Field | Type | Validation |
|---|---|---|
| `severity` | `Severity` | |
| `category` | `Category` | |
| `team_id` | uuid | must exist and be enabled |
| `resolution` | object | any of `summary` (1–2000 chars), `probable_cause` (≤ 2000), `steps` (string[], 1–20 items, each ≤ 500), `sources` (string[], ≤ 20, each an `http(s)` URL or `kb:<uuid>`) |

### `ReviewItem`
| Field | Type |
|---|---|
| `id` | uuid |
| `run_id` | uuid |
| `fingerprint_id` | uuid |
| `error` | `{ service, level, template, total_count, first_seen, last_seen, samples: Sample[] }` (samples: at most 5) |
| `proposed` | `ProposedItem` |
| `decision` | `ReviewDecision` |
| `edited` | `ReviewEdits`? |
| `reviewer` | `UserRef`? |
| `comment` | string? |
| `decided_at` | timestamp? |

### `RunStats` (the `runs.stats` JSON, spec 6 and 14)
| Field | Type |
|---|---|
| `lines_scanned` | int. Records fetched from ES by the connector for the run's window (unique `es_id`), counted before any level filtering or redaction drops |
| `lines_dropped_level` | int. Fetched lines dropped in preprocessing because their extracted level is not in `scan.levels` |
| `distinct_errors` | int |
| `flagged` | int |
| `deferred` | int |
| `llm_calls` | int |
| `llm_tokens` | `{ prompt: int, completion: int, total: int }` |
| `rate_limit_retries` | int |
| `tavily_calls` | int |
| `budget` | `{ max_items_per_run: int, max_llm_calls_per_run: int, max_tavily_calls_per_run: int, items_processed: int, llm_calls_used: int, tavily_calls_used: int }` |
| `redaction_counts` | `{ [rule_name: string]: int }` |
| `redaction_failures` | int |
| `emails_logged` | int |
| `emails_failed` | int **(assumption, see G24)** |
| `duration_seconds` | number? |
| `error` | string? (failure message when `status = failed`; **assumption, see G6**) |
| `reminder_sent_at` | timestamp? **(assumption, see G5)** |

All counters default to 0 while a run is in progress. `settings_snapshot` is stored in `stats` but returned only by `GET /api/runs/{id}`.

### `Run`
| Field | Type |
|---|---|
| `id` | uuid |
| `requested_by` | `UserRef`? (null = scheduler) |
| `started_at` | timestamp? (null while `requested`) |
| `finished_at` | timestamp? |
| `window_start`, `window_end` | timestamp? |
| `status` | `RunStatus` |
| `stats` | `RunStats` |
| `pending_review_count` | int (review items still `pending`) |

### `EmailSummary`
`{ id: uuid, run_id: uuid, team_id: uuid?, team_name: string?, recipients: string[], subject: string, status: EmailStatus, created_at: timestamp }`
`team_id = null` means a review-timeout reminder **(assumption, see G24)**. `recipients` is stored as `text[]` **(assumption)**.

### `EmailLog` = `EmailSummary` + `body: string` (full plain text)

### `RunDetail` = `Run` plus:
| Field | Type | Notes |
|---|---|---|
| `settings_snapshot` | object | the settings the run used |
| `emails` | `EmailSummary[]` | without bodies. Full bodies come from `/api/runs/{id}/emails` **(assumption, see G27)** |

### `Service`
| Field | Type |
|---|---|
| `name` | string |
| `criticality` | `Criticality` |
| `default_team_id` | uuid? |
| `enabled` | bool |
| `configured` | bool |
| `notes` | string? |
| `first_seen` | timestamp |

### `Team`
`{ id: uuid, name: string, email_dl: string, min_email_severity: Severity, enabled: bool }`

### `RoutingRule`
`{ id: uuid, match_type: MatchType, match_value: string, team_id: uuid, priority: int }`

### `KeywordMapping`
`{ keyword: string, level: ScanLevel }`

### `Settings` (the `settings` table as one document)
| Field | Type | Default (spec 9) | Validation |
|---|---|---|---|
| `scan.levels` | `ScanLevel[]` | `[FATAL, CRITICAL, ERROR, WARN, WARNING]` | at least 1, unique. The UI presents WARN/WARNING as one option that sets both **(assumption, see G23)** |
| `scan.keywords` | `KeywordMapping[]` | `[{Exception, ERROR}, {Traceback, ERROR}]` | ≤ 50. `keyword` matches `^[A-Za-z][A-Za-z0-9_.-]{1,63}$` (safe for `query_string`, **assumption, see G23**). Unique case-insensitively. `level` must be in `scan.levels` |
| `schedule.interval_minutes` | int | 60 | 5–1440 **(assumption)** |
| `detection.spike_multiplier` | number | 3 | > 1 and ≤ 100 |
| `detection.spike_lookback_windows` | int | 24 | 1–168 |
| `detection.spike_min_count` | int | 20 | ≥ 1 |
| `budget.max_items_per_run` | int | 30 | 1–500 |
| `budget.max_llm_calls_per_run` | int | 30 | 0–1000 |
| `budget.max_tavily_calls_per_run` | int | 20 | 0–1000 |
| `review.timeout_hours` | int | 4 | 1–168 |
| `review.reviewer_dl` | string | `faultline-review@example.com` | a valid email address |
| `routing.fallback_team_id` | uuid? | null **(assumption, see G2)** | an existing, enabled team, or null |

JSON shape: the keys are used literally as flat dotted keys, which mirrors the `settings` table (`{"scan.levels": [...], "budget.max_items_per_run": 30, ...}`). **(assumption: flat keys avoid a mapping layer.)**

### `SettingsResponse`
`{ values: Settings, updated: { [key: string]: { updated_by: UserRef?, updated_at: timestamp } } }`

### `AuditEntry`
| Field | Type |
|---|---|
| `id` | uuid |
| `actor` | `UserRef`? (from `actor_user_id`. Null = system) |
| `action` | `AuditAction` |
| `entity_type` | `AuditEntityType` |
| `entity_id` | string |
| `before` | object? |
| `after` | object? |
| `reason` | string? |
| `created_at` | timestamp |

### `User`
`{ id: string, email: string?, display_name: string?, role: Role?, last_seen_at: timestamp, created_at: timestamp }`

### `Me`
`{ id: string, email: string?, display_name: string?, role: Role, keycloak_admin_console_url: string }`
`role` is the highest of the user's Faultline roles. `keycloak_admin_console_url` = `{keycloak base}/admin/{realm}/console/` **(assumption, see G29; the frontend can also derive it from `config.json`)**.

---

## 4. Endpoints

Audit column: "Yes (`action`)" means the endpoint writes that audit entry in the same transaction as the change.

### 4.1 Health

#### `GET /api/health`
- **Min role:** none (no auth).
- **Response 200 / 503:** `{ status: "ok" | "degraded", checks: { database: Check, elasticsearch: Check, scheduler: Check } }`, where `Check = { ok: bool, detail: string? , last_heartbeat_at?: timestamp }`.
  - `database`: `select 1`. `elasticsearch`: cluster ping.
  - `scheduler`: ok if the worker's last heartbeat is less than 2 minutes old **(assumption, see G17: needs a heartbeat store)**.
- 200 if all checks are ok. 503 if any check fails (`status = degraded`).
- **Audit:** No.

### 4.2 Dashboard

#### `GET /api/dashboard/summary`
- **Min role:** viewer.
- **Query:** `days` (int 1–90, default 14): range for the trend chart and the top lists.
- **Response 200:**

| Field | Type | Notes |
|---|---|---|
| `new_today` | int | fingerprints with `first_seen` ≥ 00:00 UTC today **(assumption, see G45)** |
| `open_by_severity` | `{ Critical: int, High: int, Medium: int, Low: int }` | status in `new`, `open`, `acknowledged` |
| `counts_by_status` | `{ [FingerprintStatus]: int }` | excludes `merged` |
| `awaiting_review_items` | int | pending review items across all runs |
| `last_run` | `Run`? | |
| `deferred_count` | int | fingerprints with `deferred = true` (drives the Overview warning) |
| `unconfigured_services` | string[] | `services.configured = false` |
| `trend` | `{ date: string (YYYY-MM-DD), Critical: int, High: int, Medium: int, Low: int, Unclassified: int }[]` | distinct fingerprints with occurrences that day, by current severity |
| `top_services` | `{ service: string, count: int }[]` | top 10 by occurrence count in range |
| `top_errors` | `{ id: uuid, template: string, service: string, severity: Severity?, count: int }[]` | top 10 by occurrence count in range |

- **Errors:** 422 on an invalid `days`.
- **Audit:** No.

### 4.3 Errors

#### `GET /api/errors` (paged)
- **Min role:** viewer.
- **Query:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page`, `page_size` | int | 1, 25 | |
| `sort` | string | `-last_seen` | allowed: `severity`, `last_seen`, `first_seen`, `total_count`, `service`, `status` (± prefix). Severity sorts by rank |
| `severity` | `Severity` (repeatable) | all | |
| `category` | `Category` (repeatable) | all | |
| `team_id` | uuid (repeatable) | all | |
| `service` | string (repeatable) | all | |
| `status` | `FingerprintStatus` (repeatable, `merged` not allowed) | all except `merged` | |
| `from`, `to` | timestamp | none | matches errors with `last_seen ≥ from` and `first_seen ≤ to` **(assumption, see G45)** |
| `q` | string (≤ 200) | none | case-insensitive substring of `template` |
| `include_suppressed` | bool | `false` | "Show suppressed" |

- **Response 200:** `Page<ErrorSummary>`.
- **Errors:** 422 (bad enum, sort field, or dates).
- **Audit:** No.

#### `GET /api/errors/{id}`
- **Min role:** viewer.
- **Path:** `id` uuid.
- **Response 200:** `ErrorDetail`. Merged fingerprints are returned with `status = merged` and `merged_into_id` set.
- **Errors:** 404.
- **Audit:** No.

#### `PATCH /api/errors/{id}` (manual override)
- **Min role:** reviewer.
- **Body** (at least one of the first four fields is required):

| Field | Type | Req | Validation |
|---|---|---|---|
| `status` | `FingerprintStatus` | opt | only `open`, `acknowledged`, `resolved`, `ignored` (`new` and `merged` are system-set) **(assumption, see G22)** |
| `severity` | `Severity` | opt | |
| `team_id` | uuid | opt | existing team |
| `category` | `Category` | opt | |
| `reason` | string | opt | ≤ 1000 chars |

- **Response 200:** `ErrorDetail`.
- **Errors:** 404; 409 if `status = merged`; 422 (empty body or invalid value).
- **Audit:** Yes (`error.update`; `before`/`after` hold only the changed fields).

#### `GET /api/errors/{id}/occurrences`
- **Min role:** viewer.
- **Query:** `from` (default now − 7 days), `to` (default now), `bucket` = `hour` \| `day` (default `day`). The range may be at most 180 days (the retention limit).
- **Response 200:** `{ bucket: "hour" | "day", points: { bucket_start: timestamp, count: int }[] }`, zero-filled and oldest first. A run window that spans buckets is counted in the bucket containing its `window_end` **(assumption)**.
- **Errors:** 404; 422 (`from ≥ to`, range too large).
- **Audit:** No.

#### `POST /api/errors/{id}/mute`
- **Min role:** reviewer.
- **Body:** `reason` (string, required, 1–1000), `alert_on_spike` (bool, optional, default `false`).
- **Effect:** `suppression = muted`, `snoozed_until = null`, and `suppression_reason`, `alert_on_spike`, `suppressed_by`, and `suppressed_at` set. Re-muting overwrites.
- **Response 200:** `ErrorDetail`.
- **Errors:** 404; 409 if merged; 422.
- **Audit:** Yes (`error.mute`).

#### `POST /api/errors/{id}/snooze`
- **Min role:** reviewer.
- **Body:** `until` (timestamp, required, > now and ≤ now + 90 days), `reason` (string, required, 1–1000).
- **Effect:** `suppression = snoozed`, `snoozed_until = until`, `alert_on_spike = false`.
- **Response 200:** `ErrorDetail`.
- **Errors:** 404; 409 if merged; 422.
- **Audit:** Yes (`error.snooze`).

#### `POST /api/errors/{id}/unsuppress`
- **Min role:** reviewer.
- **Body:** `reason` (string, optional, ≤ 1000).
- **Effect:** `suppression = none`, and the other suppression fields are cleared.
- **Response 200:** `ErrorDetail`.
- **Errors:** 404; 409 if already `none` or merged.
- **Audit:** Yes (`error.unsuppress`).

#### `POST /api/errors/bulk/suppress`
- **Min role:** reviewer.
- **Body:**

| Field | Type | Req | Validation |
|---|---|---|---|
| `ids` | uuid[] | yes | 1–200, unique |
| `action` | `"mute"` \| `"snooze"` | yes | |
| `reason` | string | yes | 1–1000 |
| `alert_on_spike` | bool | opt | only for `mute` (default `false`) |
| `until` | timestamp | for `snooze` | > now, ≤ now + 90 days |

- **Behavior:** all or nothing in one transaction **(assumption)**.
- **Response 200:** `{ updated: ErrorSummary[] }`.
- **Errors:** 422 if any ID is missing or merged (listed in `details`).
- **Audit:** Yes, one `error.mute`/`error.snooze` entry per error.

#### `GET /api/errors/{id}/merge-candidates` (paged)
- **Min role:** reviewer.
- **Query:** `q` (string, optional, template substring), `page`, `page_size` (default 1, 25).
- **Response 200:** `Page<MergeCandidate>`, where `MergeCandidate = ErrorSummary + { samples: Sample[] (up to 2) }`. Returns only the same service, excluding `merged` and the target itself.
- **Errors:** 404; 409 if the target is merged.
- **Audit:** No.

#### `POST /api/errors/{id}/merge`
- **Min role:** reviewer.
- **Body:** `source_ids` (uuid[], required, 1–20, unique, must not contain `id`), `reason` (string, optional, ≤ 1000).
- **Validation:** every source has the same `service` as the target; neither the target nor any source is `merged`; no affected review item belongs to a run in status `sending` (409) **(assumption, see G42)**.
- **Effect:** spec 5.9.4 steps 1–5 in one transaction.
- **Response 200:** `{ target: ErrorDetail, cancelled_review_item_ids: uuid[], created_review_item_id: uuid? }`.
- **Errors:** 404 (target or a source); 409; 422 (different service, empty list).
- **Audit:** Yes (`error.merge`: one entry on the target with `after.source_ids`, and one per source with `after.merged_into_id`).

### 4.4 Runs

#### `GET /api/runs` (paged)
- **Min role:** viewer.
- **Query:** `page`, `page_size` (1, 25); `status` (`RunStatus`, repeatable); `from`, `to` (applied to `started_at`, or the creation time for `requested` runs); `sort` (default `-started_at`, allowed `started_at`).
- **Response 200:** `Page<Run>`.
- **Audit:** No.

#### `GET /api/runs/{id}`
- **Min role:** viewer.
- **Response 200:** `RunDetail`.
- **Errors:** 404.
- **Audit:** No.

#### `POST /api/runs/trigger`
- **Min role:** reviewer.
- **Body:** none (an empty body or `{}`).
- **Effect:** inserts a `runs` row with `status = requested` and `requested_by` = the caller. The worker picks it up within about 30 seconds. The request returns immediately and never waits for the lock. If a run is in progress, the worker skips its check (non-blocking lock, spec 5.1) and picks up the `requested` row on a later check after the current run releases the lock.
- **Response 202:** `Run`.
- **Errors:** 409 if a `requested` run already exists (`details` gives its ID) **(assumption, see G6)**.
- **Audit:** Yes (`run.trigger`).

#### `GET /api/runs/{id}/emails`
- **Min role:** viewer.
- **Response 200:** `EmailLog[]` (full bodies, digests first, then reminders, by `created_at`).
- **Errors:** 404 (run).
- **Audit:** No.

### 4.5 Reviews

#### `GET /api/reviews/pending`
- **Min role:** viewer (read-only for viewers) **(assumption, see G38)**.
- **Query:** `run_id` (uuid, optional), `team_id` (uuid, optional; use `team_id=none` for unrouted items).
- **Response 200:**

```
{
  runs: [
    {
      run: Run,
      teams: [
        { team: TeamRef | null, items: ReviewItem[] }  // items sorted by proposed.severity desc, then window_count desc
      ]
    }
  ]  // runs ordered by started_at asc (oldest first)
}
```
Only runs in status `awaiting_review` that still have items are included. Each run's items are all items that aren't `cancelled` or `below_threshold`, including those already decided, so the reviewer sees progress **(assumption)**.
- **Audit:** No.

#### `PUT /api/review-items/{id}`
- **Min role:** reviewer.
- **Body:**

| Field | Type | Req | Validation |
|---|---|---|---|
| `decision` | `"pending"` \| `"approved"` \| `"edited"` \| `"rejected"` | yes | `pending` resets the decision |
| `edited` | `ReviewEdits` | when `decision = edited` | must be null or absent for the other decisions. If a client sends `approved` with edits, it gets 422 and must use `edited` **(assumption, see G41)** |
| `comment` | string | opt | ≤ 2000 |

- **Rules:** for `approved`/`edited`, the final team (`edited.team_id`, else `proposed.team_id`) must be non-null (422 otherwise; see G2). `reviewer` comes from the token and `decided_at = now`.
- **Response 200:** `ReviewItem`.
- **Errors:** 404; 409 if the item's run is not `awaiting_review` or the item is `cancelled`/`below_threshold`; 422.
- **Audit:** Yes (`review.decide`, before and after decision and edits).

#### `POST /api/runs/{id}/review/submit`
- **Min role:** reviewer.
- **Body:** none (or `{}`).
- **Validation:** the run is `awaiting_review` (409 otherwise); no item of the run is `pending` (422, with the pending item IDs in `details`) **(assumption, see G41)**.
- **Effect:** sets `runs.status = sending`. The worker resumes the graph with `Command(resume=...)`. `send_email` and `persist` read the decisions from `review_items` **(assumption, see G3, G11)**.
- **Response 202:** `Run`.
- **Audit:** Yes (`review.submit`, `after` = counts per decision).

### 4.6 Services

#### `GET /api/services`
- **Min role:** viewer (needed for filters and the Overview banner) **(assumption, see G38)**.
- **Query:** `configured` (bool, optional), `enabled` (bool, optional), `q` (name substring, optional).
- **Response 200:** `Service[]`, sorted by `name` (not paged; the list is small) **(assumption)**.
- **Audit:** No.

#### `POST /api/services`
- **Min role:** admin.
- **Body:** `name` (string, required, 1–200, unique), `criticality` (`Criticality`, optional, default `medium`), `default_team_id` (uuid?, optional, existing team), `enabled` (bool, default `true`), `notes` (string?, ≤ 2000).
- **Effect:** `configured = true`, `first_seen = now`.
- **Response 201:** `Service`.
- **Errors:** 409 if the name exists; 422.
- **Audit:** Yes (`service.create`).

#### `PUT /api/services/{name}`
- **Min role:** admin.
- **Path:** `name` (URL-encoded) **(assumption, see G43)**.
- **Body:** `criticality` (required), `default_team_id` (uuid?, required, may be null), `enabled` (bool, required), `notes` (string?, optional). A full replacement of the editable fields. `name` cannot be changed.
- **Effect:** also sets `configured = true`.
- **Response 200:** `Service`.
- **Errors:** 404; 422.
- **Audit:** Yes (`service.update`).

### 4.7 Teams

#### `GET /api/teams`
- **Min role:** viewer (needed for filters and review edits) **(assumption, see G38)**.
- **Query:** `enabled` (bool, optional).
- **Response 200:** `Team[]`, sorted by `name`.
- **Audit:** No.

#### `POST /api/teams`
- **Min role:** admin.
- **Body:** `name` (string, required, 1–100, unique case-insensitively), `email_dl` (string, required, a valid email address), `min_email_severity` (`Severity`, optional, default `Low`), `enabled` (bool, optional, default `true`).
- **Response 201:** `Team`.
- **Errors:** 409 if the name exists; 422.
- **Audit:** Yes (`team.create`).

#### `PUT /api/teams/{id}`
- **Min role:** admin.
- **Body:** `name`, `email_dl`, `min_email_severity`, `enabled`, all required (full replacement), with the same validation as POST.
- **Response 200:** `Team`.
- **Errors:** 404; 409 (name taken); 422 if disabling the team set as `routing.fallback_team_id`.
- **Audit:** Yes (`team.update`).

#### `DELETE /api/teams/{id}`
- **Min role:** admin.
- **Response 204.**
- **Errors:** 404; 409 if the team is referenced by any routing rule, `services.default_team_id`, `routing.fallback_team_id`, fingerprint, review item, or email log (`details` lists the references; the UI suggests disabling instead) **(assumption, see G46)**.
- **Audit:** Yes (`team.delete`, with `before` = the team).

### 4.8 Routing rules

#### `GET /api/routing`
- **Min role:** admin **(assumption, see G38)**.
- **Response 200:** `RoutingRule[]`, in evaluation order: `priority` ascending (lower is evaluated first), then `id` **(assumption)**.
- **Audit:** No.

#### `POST /api/routing`
- **Min role:** admin.
- **Body:**

| Field | Type | Req | Validation |
|---|---|---|---|
| `match_type` | `MatchType` | yes | |
| `match_value` | string | yes | `service`: 1–200 chars; `category`: a `Category` value; `service_regex`: ≤ 200 chars and must compile with Python `re` |
| `team_id` | uuid | yes | existing team |
| `priority` | int | yes | 0–10000 |

- **Response 201:** `RoutingRule`.
- **Errors:** 422.
- **Audit:** Yes (`routing.create`).

#### `PUT /api/routing/{id}`
- **Min role:** admin.
- **Body:** same as POST (full replacement).
- **Response 200:** `RoutingRule`.
- **Errors:** 404; 422.
- **Audit:** Yes (`routing.update`).

#### `DELETE /api/routing/{id}`
- **Min role:** admin.
- **Response 204.**
- **Errors:** 404.
- **Audit:** Yes (`routing.delete`).

### 4.9 Settings

#### `GET /api/settings`
- **Min role:** admin.
- **Response 200:** `SettingsResponse`. Every key is always present (code defaults apply when a key has no row).
- **Audit:** No.

#### `PUT /api/settings`
- **Min role:** admin.
- **Body:** a partial `Settings` object. Include any subset of keys; omitted keys are unchanged. An optional `reason` (string ≤ 1000) is stored on each audit entry **(assumption)**.
- **Validation:** per the `Settings` table, applied to the merged result (for example, keyword levels must be in the resulting `scan.levels`). Unknown keys return 422.
- **Effect:** takes effect from the next run. Runs in progress keep their snapshot.
- **Response 200:** `SettingsResponse`.
- **Errors:** 422.
- **Audit:** Yes (`settings.update`, one entry per changed key, `entity_type = setting`, `entity_id = key`).

#### `POST /api/settings/scan/preview`
- **Min role:** admin.
- **Body:** `scan.levels` (`ScanLevel[]`, required), `scan.keywords` (`KeywordMapping[]`, required). The validation is the same as for `Settings`. The values are not saved.
- **Response 200:** `{ query: object (the ES bool query that would run, with the range filter set to the last 24 hours), query_string: string, window_start: timestamp, window_end: timestamp, count_24h: int }`. The count is ES `_count` for the text query only. Level extraction in preprocessing may drop further lines **(see G39)**.
- **Errors:** 422; 502 if ES is unreachable.
- **Audit:** No.

### 4.10 Users and identity

#### `GET /api/me`
- **Min role:** viewer (any user with at least one Faultline role).
- **Response 200:** `Me`.
- **Audit:** No.

#### `GET /api/users`
- **Min role:** admin.
- **Query:** `q` (optional, matches name or email).
- **Response 200:** `User[]`, sorted by `last_seen_at` descending (not paged) **(assumption)**.
- **Audit:** No.

### 4.11 Audit log

#### `GET /api/audit-log` (paged)
- **Min role:** admin.
- **Query:** `page` (1), `page_size` (default 50, max 100), `actor_user_id` (string), `action` (`AuditAction`, repeatable), `entity_type` (`AuditEntityType`), `entity_id` (string), `from`, `to` (applied to `created_at`). Sort is fixed to `-created_at`.
- **Response 200:** `Page<AuditEntry>`.
- **Errors:** 422.
- **Audit:** No (reads are not audited).

---

## 5. Endpoint summary

| # | Method | Path | Min role | Audit |
|---|---|---|---|---|
| 1 | GET | `/api/health` | none | No |
| 2 | GET | `/api/dashboard/summary` | viewer | No |
| 3 | GET | `/api/errors` | viewer | No |
| 4 | GET | `/api/errors/{id}` | viewer | No |
| 5 | PATCH | `/api/errors/{id}` | reviewer | `error.update` |
| 6 | GET | `/api/errors/{id}/occurrences` | viewer | No |
| 7 | GET | `/api/runs` | viewer | No |
| 8 | GET | `/api/runs/{id}` | viewer | No |
| 9 | POST | `/api/runs/trigger` | reviewer | `run.trigger` |
| 10 | GET | `/api/reviews/pending` | viewer | No |
| 11 | PUT | `/api/review-items/{id}` | reviewer | `review.decide` |
| 12 | POST | `/api/runs/{id}/review/submit` | reviewer | `review.submit` |
| 13 | POST | `/api/errors/{id}/mute` | reviewer | `error.mute` |
| 14 | POST | `/api/errors/{id}/snooze` | reviewer | `error.snooze` |
| 15 | POST | `/api/errors/{id}/unsuppress` | reviewer | `error.unsuppress` |
| 16 | POST | `/api/errors/bulk/suppress` | reviewer | per error |
| 17 | GET | `/api/errors/{id}/merge-candidates` | reviewer | No |
| 18 | POST | `/api/errors/{id}/merge` | reviewer | `error.merge` |
| 19 | GET | `/api/services` | viewer | No |
| 20 | POST | `/api/services` | admin | `service.create` |
| 21 | PUT | `/api/services/{name}` | admin | `service.update` |
| 22 | GET | `/api/teams` | viewer | No |
| 23 | POST | `/api/teams` | admin | `team.create` |
| 24 | PUT | `/api/teams/{id}` | admin | `team.update` |
| 25 | DELETE | `/api/teams/{id}` | admin | `team.delete` |
| 26 | GET | `/api/routing` | admin | No |
| 27 | POST | `/api/routing` | admin | `routing.create` |
| 28 | PUT | `/api/routing/{id}` | admin | `routing.update` |
| 29 | DELETE | `/api/routing/{id}` | admin | `routing.delete` |
| 30 | GET | `/api/settings` | admin | No |
| 31 | PUT | `/api/settings` | admin | `settings.update` per key |
| 32 | POST | `/api/settings/scan/preview` | admin | No |
| 33 | GET | `/api/me` | viewer | No |
| 34 | GET | `/api/users` | admin | No |
| 35 | GET | `/api/runs/{id}/emails` | viewer | No |
| 36 | GET | `/api/audit-log` | admin | No |

---

## 6. Endpoints missing from Section 7 (PROPOSED, pending approval)

The spec describes these features, but Section 7 has no endpoint for them. **Do not implement them until the user approves.**

### P1. Report leaked data (see G13; spec 8, Review queue)
`POST /api/review-items/{id}/report-leak`: min role reviewer.
- Body: `sample_index` (int, 0–4, required), `note` (string ≤ 1000, optional).
- Effect: sets a flag on the review item (new column `review_items.leak_reported_at`/`leak_reported_by`, **proposed**), removes the reported sample from `samples`, and logs a notification through `EmailSender` to the admins (recipient: a new setting `notify.admin_dl`, or `review.reviewer_dl` if not added; **proposed**).
- Response 200: `ReviewItem` (with `leak_reported: true`).
- Audit: Yes (`review.report_leak`, **proposed action**).

### P2. Choose the best resolution after a merge (see G14; spec 5.9.4 step 4)
`POST /api/errors/{id}/resolutions/{resolution_id}/approve`: min role reviewer.
- Body: `reason` (string, optional).
- Effect: the chosen resolution becomes `approved` (`approved_by` and `approved_at` set). Other `approved`/`draft` resolutions for the fingerprint become `rejected`. The embedding must already exist (the worker computes embeddings for all persisted resolutions, so the API never loads fastembed).
- Response 200: `ErrorDetail`. Errors: 404; 409 if the resolution belongs to a different fingerprint or is already approved.
- Audit: Yes (`resolution.approve`, **proposed action**).

### P3. Retry a failed run from its checkpoint (see G15; spec 12, Failures)
`POST /api/runs/{id}/retry`: min role reviewer.
- Validation: `status = failed` and a LangGraph checkpoint exists for `thread_id = id` (otherwise 409: an ingestion failure is retried automatically by the next run).
- Effect: sets `status = requested`. The worker sees the existing checkpoint and resumes the graph with `graph.invoke(None, config)` instead of ingesting.
- Response 202: `Run`.
- Audit: Yes (`run.retry`, **proposed action**).

### Not endpoints, but contract gaps covered by fields above
- Sparkline data: `ErrorSummary.trend` (G28).
- Error review and audit history: `ErrorDetail.review_history` and `audit_history` (G28).
- Keycloak admin console link: `Me.keycloak_admin_console_url` (G29).
- Scheduler health: needs a worker heartbeat store (G17).
