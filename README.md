# AI-HAS: AI-Powered Enterprise Helpdesk & Workflow Automation System

A Level-1 IT support assistant that answers from an approved knowledge base with citations, takes confirmed actions
(password reset link, ticket creation, escalation), and hands anything uncertain to a human agent.

**Stack:** FastAPI, PostgreSQL 16, ChromaDB, LangChain with Google Gemini, Next.js, Docker Compose.

## Features

- **Grounded RAG:** hybrid retrieval (vector + BM25, Reciprocal Rank Fusion), confidence gate, mandatory citations, output checks.
- **Function calling:** `reset_password`, `create_ticket`, `escalate_to_agent`, `get_ticket_status` with confirm-before-act and a full audit log.
- **Governance:** JWT + RBAC, PII redaction before storage and before the LLM, prompt-injection detection, rate limits, login lockout.
- **Human in the loop:** agent queue with claim, reply and resolve; live handoff from the employee chat.
- **Observability:** admin dashboard for deflection, latency, MTTR, guardrail events and tool calls.

## Quick start

Requirements: Docker Desktop, Git, a Google Gemini API key.

```powershell
git clone <your-repo-url>
cd ai-has
Copy-Item .env.example .env
```

Edit `.env`: set `GEMINI_API_KEY`, a long random `JWT_SECRET` and a random `WEBHOOK_SECRET`
(`python -c "import secrets; print(secrets.token_hex(32))"`). Never commit `.env`.

```powershell
docker compose up -d --build
docker compose exec backend python -m app.seed
docker compose exec backend python -m app.rag.ingest
```

| URL | What |
|---|---|
| http://localhost:3000 | Web app |
| http://localhost:8000/docs | Interactive API documentation |
| http://localhost:8010 | Mock Jira / Active Directory / webhook sink |

Demo accounts (capstone only): `employee@aihas.local` / `Employee123!`, `agent@aihas.local` / `Agent123!`, `admin@aihas.local` / `Admin123!`.

## Tests and evaluation

```powershell
docker compose exec backend python -m pytest tests/unit -q
docker compose exec backend python -m pytest tests/integration -q
docker compose exec backend python -m tests.eval.run_eval --judge
docker compose exec backend locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 60s --host http://localhost:8000
```

## Repository layout

```
backend/app/        api, rag, guardrails, tools, services, schemas, core
frontend/src/       Next.js app (chat, agent, admin)
automation/         mock Jira / AD / webhook sink
knowledge_base/     IT SOP files (Markdown)
db/schema.sql       database schema and KPI views
tests/              unit, integration, eval, load
docs/               technical documentation
```

## Configuration

See `.env.example`. Key tuning values: `RAG_MIN_VECTOR` (0.76), `RAG_STRONG_VECTOR` (0.85), `CHAT_RATE_PER_MINUTE` (12).

## Known limits

Free-tier Gemini (daily quota, 4 to 6 second answers), in-memory rate limiting, regex-based PII detection, mock Jira / AD.
See the technical documentation, section 12.
