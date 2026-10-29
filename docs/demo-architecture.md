# Faultline — Staged Demo Architecture

**Purpose:** `spec.md` describes the full MVP as one build. This document breaks it into
three working stages — **basic → intermediate → advanced** — so there's a running app
with real Keycloak auth after stage 1, not after five weeks. Each stage is a strict
superset of the last: nothing built in stage 1 is thrown away, stage 2 and 3 only add
tables, nodes, and pages back in.

This does not change `spec.md`. It is the *order* in which to build the spec, with an
explicit list of what's deferred at each stage and why. The final system converges on
`spec.md` exactly.

---

## Guiding cut

Every stage keeps this vertical slice intact, because it's the actual value proposition
and the thing worth demoing early:

```
Elasticsearch logs → fingerprint → classify (LLM) → human review (Keycloak-gated) → persist
```

Everything else in the spec — budget limits, mute/snooze, merge, routing rules, audit
log, settings dashboard, scheduler, KB embeddings, redaction's 13 rules — is *hardening
and configurability* around that slice. It's deferred, not skipped.

---

## Stage 1: Basic demo (target: days, not weeks)

**Goal:** prove the loop works end-to-end, gated by real Keycloak roles. This is the
thing you'd demo to convince yourself (or someone else) the idea holds up.

### Kept

| Area | What ships |
|---|---|
| Ingestion | ES connector, single manual trigger (`POST /api/runs/trigger`) — **no scheduler loop** |
| Redaction | 3 rules only: email, key-value secrets (`password=`, `token=`, …), auth headers. Same `redact()` entry point / `RedactedText` wrapper as the spec, so stage 2/3 rules slot in without touching call sites |
| Fingerprinting | Drain3, **one miner total** (not per-service), default `sim_th`/`depth`, no persisted tuning workflow. State still persisted to Postgres — losing it just re-learns |
| Detection | Only the `new` flag. Every distinct fingerprint goes through the agent. No spike/regression/snooze — irrelevant at demo volume |
| Agent graph | `classify → build_report → human_review (interrupt) → persist`. **No `severity_rules`, `kb_lookup`, or `web_research` nodes yet** — classify does severity directly, no KB, no Tavily |
| Email | `LogEmailSender` writes to stdout/app log only. No `email_log` table, no digest formatting — one line per approved item is enough |
| Routing | One hardcoded team in config (`.env`), no `teams`/`routing` tables |
| Settings | Everything is a code constant or `.env` value. No `settings` table, no dashboard config |
| Auth | **Keycloak, for real.** One realm, client `faultline-web` (public, PKCE S256). **Two roles only: `viewer`, `admin`** (merge reviewer+admin — one person approves in a demo). Backend validates every token (PyJWT + JWKS), `Depends(require_role(...))` on write endpoints |
| Audit | None yet |
| Frontend | Angular, **3 routes**: Errors list, Error detail (with approve/reject), login handled by `keycloak-angular`'s `login-required`. No Overview/Runs/Settings/Users/Audit pages |
| DB tables | `fingerprints`, `occurrences`, `samples`, `resolutions`, `review_items`, `runs`, `drain_state`, `users`, LangGraph checkpoint tables. **No** `teams`, `team_routing`, `services`, `settings`, `audit_log`, `email_log`, `fingerprint_aliases` |

### Why this is still a real demo

- Keycloak login and role enforcement are exactly the spec's mechanism (Section 5.9.7),
  just with 2 roles instead of 3 — adding the 3rd role later is a config change in
  Keycloak's admin console plus one more `Depends(require_role("reviewer"))` split, not
  a redesign.
- The redaction *mechanism* (rules list, `redact()`, `RedactedText` wrapper, fail-closed)
  is the final one. Stage 2/3 only append rules to the list.
- The graph shape (`interrupt()` / `PostgresSaver` / `Command(resume=...)`) is final.
  Stage 2/3 insert nodes (`severity_rules`, `kb_lookup`, `web_research`) into the same
  graph, they don't restructure it.

### Explicitly cut (not "simplified")

Budget limiting, mute/snooze, fingerprint merge, audit log, scheduler, KB/embeddings,
Tavily research, settings dashboard, teams/routing tables, 8-page dashboard. These add
no learning about whether the core idea works — they're safety rails and admin UX for
when the volume and user count grow past a demo.

---

## Stage 2: Intermediate (add real operational rails)

Builds on stage 1's tables and graph without changing their shape.

**Adds:**

- Third Keycloak role (`reviewer`), hierarchy enforced (`admin` ⊇ `reviewer` ⊇ `viewer`)
- Scheduler loop (Section 5.1) replacing the manual-only trigger — advisory lock, 30s poll
- Detection: `spike` and `regression` flags (Section 5.6) — this is where suppression
  logic and multi-window comparison start to matter
- `settings` table + minimal **Settings page** (scan levels/keywords, schedule interval only)
- `teams` / `team_routing` tables + real routing, replacing the hardcoded team
- `kb_lookup` node + fastembed embeddings — resolutions start getting reused instead of
  re-researched every time
- `web_research` node (Tavily) for items with no KB match
- Budget guardrails (Section 5.9.6) — needed once the scheduler is unattended
- Mute / snooze (Section 5.9.3)
- Basic `audit_log` (append-only, review decisions + settings changes only)
- Frontend: Overview and Runs pages; Settings tab for the above

**Still deferred:** fingerprint merge, full 13-rule redaction set + entropy detection,
`tune_drain.py`, per-service Drain3 miners, review-timeout reminders, Users/Audit-log
pages, `email_log` table with full digest content, production Elasticsearch security.

---

## Stage 3: Advanced (converges on `spec.md`)

Everything remaining in the spec:

- Full redaction rule set (13 rules incl. Luhn card check, entropy detection, org-specific
  rules from `redaction_rules.json`)
- Per-service Drain3 miners + `tune_drain.py` + tuned config
- Fingerprint merge (Section 5.9.4)
- Review timeout reminders (Section 5.7)
- `email_log` table with full digest content + Run detail email view
- Full audit log coverage (every action in Section 5.9.8) + Audit log page
- Users page
- All 8 dashboard pages, full permission matrix (Section 5.9.7 table)
- Elasticsearch security (API key, HTTPS) — pre-production hardening (Section 13)
- Observability: full `runs.stats`, redaction-failure metrics, budget usage display

At this point the app matches `spec.md` and `docs/tasks.md` exactly — stage 3 is really
"finish the Week 3–5 tasks that stage 1/2 deferred," not new design.

---

## What doesn't change across stages

- **Data model:** stage 1's tables are the final schema for those entities. Stage 2/3
  only *add* tables, never restructure existing ones (e.g. `fingerprints.suppression`
  exists in the schema from the start, stage 1 just never sets it to anything but `none`).
- **Graph shape:** `interrupt()`-based human review with `PostgresSaver`, resumed via
  `Command(resume=...)`, is stage 1's design and the spec's design — identical.
- **Redaction mechanism:** rule list + `redact()` + `RedactedText` — stage 1 ships the
  real mechanism with 3 of the eventual ~13 rules.
- **Auth mechanism:** Keycloak PKCE + PyJWT/JWKS validation — stage 1 is not a stub, it's
  the real thing with fewer roles.

This means nothing needs a rewrite going from stage 1 → 3, only additions — so stage 1
is safe to actually deploy and use while stage 2/3 are being built.
