---
name: faultline-planning-state
description: Faultline planning outputs (tasks.md, api.md), the G1-G46 spec review, and the architect's recommended defaults pending user approval
metadata:
  type: project
---

On 2026-09-23 the architect wrote docs/tasks.md (Weeks 1-5, IDs like W1-BE-07, W4-OPS-01) and docs/api.md (36 endpoints plus 3 proposed ones: P1 report-leak, P2 approve resolution, P3 run retry). The spec review produced G1-G46, which is in the handback, not in a file.

Recommended defaults (NOT yet approved by the user):
- The worker, not the API, resumes the graph. Submit sets runs.status=sending (G3).
- The advisory lock is released at interrupt, so multiple awaiting_review runs are allowed. A fingerprint with a pending item is not re-flagged (G4).
- Add review_items.decision values `cancelled` and `below_threshold` (G9/G12). Add email_log status `failed` (G24).
- The review_items table is the source of truth for decisions, not RunState.decisions (G11).
- Keycloak realm to Week 1 day 1. Auth and audit writer to the start of Week 2. Service/team/routing endpoints to Week 2 (G1/G2).
- One sources row seeded from ES_* env vars (G19). INITIAL_LOOKBACK_HOURS=24 (G18).

**Why:** The spec (Draft v1) has sequencing and state-machine gaps. The user asked for no spec edits, no architecture.md, and no ADRs, only tasks.md and api.md.
**How to apply:** Check the user's answers before relying on these defaults. If approved, docs/api.md "(assumption, see Gx)" markers should be resolved. Never edit docs/spec.md unless asked.
