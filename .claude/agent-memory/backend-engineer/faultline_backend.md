---
name: faultline-backend
description: Faultline Stage 1 backend facts that are not obvious from code (model, fixture timing, test setup, restrictions)
metadata:
  type: project
---

- Backend in /backend, run from there: `uv run uvicorn app.main:app`, tests `uv run python -m unittest discover -s tests` (stdlib unittest, tests create+drop a temp Postgres DB via tests/support.py).
- Principal forbade editing docs/ (so docs/api-changes.md was NOT written; report API changes in the hand-off message instead). No git commits unless asked.
- Groq `llama-3.3-70b-versatile` returns 404 (removed, Sep 2026); default is now `openai/gpt-oss-120b`. Check `GET https://api.groq.com/openai/v1/models` before changing.
- Fixture logs are dated 2026-09-22/23; they age out of INITIAL_LOOKBACK_HOURS. Spike detection anchors "last 60 min" on the newest record in the run (not wall clock) so the fixture still spikes.
- Never `cat > $TMPDIR/x` style heredocs with unset vars (hangs); scratch scripts go in the session scratchpad; macOS sed needs `-i.bak`.
- Real Groq/Tavily smoke calls are limited by the principal (<=5 each) to preserve the free daily budget.
