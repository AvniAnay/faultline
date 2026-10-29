# Faultline

Scheduled agentic workflow that scans unstructured ERROR/WARN logs in Elasticsearch, groups them into distinct errors, researches resolutions, gets human approval, prepares email digests for team distribution lists (logged, not sent, in the MVP), and shows everything in an Angular dashboard.

## What it does

1. **Scans** Elasticsearch on a schedule for ERROR and WARN logs.
2. **Groups** them into distinct errors: lines are redacted of secrets and PII, then fingerprinted with Drain3.
3. **Detects** new errors, spikes and regressions, so only flagged errors reach the LLM.
4. **Researches** each flagged error with a LangGraph agent: classify, apply severity rules, check the internal knowledge base, then search the web (Tavily) if there is no match.
5. **Pauses for human review**. A reviewer approves or edits the report in the dashboard.
6. **Prepares an email digest** per team DL. In the MVP it is written to the log and the `email_log` table, not sent.

Deterministic steps (ingestion, redaction, fingerprinting, detection, routing) are plain Python. The LLM is used only for classification, research and summarization.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Angular |
| Backend | Python 3.14, FastAPI, SQLAlchemy |
| Agent | LangGraph, Groq (LLM), Tavily (web search) |
| Fingerprinting | Drain3 |
| Storage | PostgreSQL |
| Log source | Elasticsearch 9.5 |
| Auth | Keycloak (roles: viewer, reviewer, admin) |

## Repository layout

```
backend/                 FastAPI app, worker, LangGraph agent
  app/agent/             Graph and nodes (classify, web_research, human_review, ...)
  app/api/               REST endpoints
  app/connectors/        Elasticsearch connector
  app/pipeline/          Scan, redact, fingerprint, detect
  app/db/                Models, repos, migrations
  app/worker.py          CLI entry point for a run
frontend/                Angular dashboard
docs/                    spec.md, api.md, tasks.md, architecture notes
faultline-sample-logs/   1,000 fake logs and scripts to load them into Elasticsearch
```

## Prerequisites

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- Docker, for PostgreSQL, Elasticsearch 9.5 and Keycloak
- A [Groq](https://console.groq.com) API key and a [Tavily](https://tavily.com) API key

## Setup

**1. Start the infrastructure.** PostgreSQL (with a database named `faultline`), Elasticsearch and Keycloak need to be running. The defaults in `.env.example` expect:

- Postgres on `localhost:5432`
- Elasticsearch on `http://localhost:9200` (security disabled, plain HTTP, development only)
- Keycloak on `http://localhost:8080` with realm `abhi-org` and client `faultline-web`

**2. Load the sample logs** (optional, for testing):

```bash
cd faultline-sample-logs
./load.sh
```

This creates the `logs-faultline` index with 1,000 logs. All secrets in them are fake. See [faultline-sample-logs/README.md](faultline-sample-logs/README.md).

**3. Backend**

```bash
cd backend
cp .env.example .env     # then set GROQ_API_KEY and TAVILY_API_KEY
uv sync
uv run uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000` and the interactive docs are at `/docs`. Database migrations run on startup.

**4. Run the scan worker**

```bash
cd backend
uv run python -m app.worker run
```

This executes one scan run: it reads new logs, flags errors, runs the agent and stops at `awaiting_review`.

**5. Frontend**

```bash
cd frontend
npm install
npm start
```

Open `http://localhost:4200` and sign in through Keycloak.

## Configuration

All backend settings are environment variables in `backend/.env` (see `backend/.env.example`).

| Variable | Description |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `ES_URL`, `ES_API_KEY`, `ES_CA_CERT` | Elasticsearch connection |
| `ES_INDEX_PATTERN` | Indices to scan (default `logs-*`) |
| `ES_MESSAGE_FIELD`, `ES_SERVICE_FIELD`, `ES_HOST_FIELD` | Field names in your log documents |
| `INITIAL_LOOKBACK_HOURS` | How far back the first run looks |
| `KEYCLOAK_URL`, `KEYCLOAK_ISSUER`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` | Authentication |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_REQUESTS_PER_MINUTE` | LLM and its rate limit |
| `TAVILY_API_KEY` | Web research |
| `DASHBOARD_BASE_URL`, `CORS_ORIGINS` | Frontend URL and allowed origins |
| `DEFAULT_TEAM_NAME`, `DEFAULT_TEAM_DL` | Stage 1 single team and its DL |

Never commit `.env`. It is already in `.gitignore`.

## Documentation

- [docs/spec.md](docs/spec.md): requirements, architecture and data model
- [docs/api.md](docs/api.md): backend API contract
- [docs/tasks.md](docs/tasks.md): task breakdown
- [docs/stage1-plan.md](docs/stage1-plan.md): Stage 1 plan
- [docs/demo-architecture.md](docs/demo-architecture.md): demo architecture

## Status

MVP, Stage 1. Not in scope: real-time alerting, automatic remediation, log sources other than Elasticsearch, and sending real email.
