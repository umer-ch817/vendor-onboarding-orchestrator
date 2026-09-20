# Vendor Onboarding & Risk Orchestrator — Runbook

*How to see the product running **today**, with every known blocker called out and worked around.*

---

## TL;DR — The Commands

```bash
cd vendor-onboarding-orchestrator

# 1. Copy the env template
cp .env.example .env

# 2. Start infrastructure (Postgres + Mock Services + n8n)
docker compose up -d

# 3. Backend — run from the REPO ROOT, not from backend/.
#    app/config.py resolves ".env" relative to the working directory, so
#    launching from backend/ falls back to Docker hostnames and the API
#    cannot reach Postgres. PYTHONPATH is required because the app
#    imports `app.*`.
python3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
PYTHONPATH="$PWD/backend" \
  backend/.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# 4. Frontend (Terminal 3)
cd frontend
npm install
npm run dev
```

Or just run `./scripts/start-dev.sh`, which does all of the above and waits
until both servers answer. Add `--seed` to load demo data.

> **Python 3.12 required.** The pinned `pydantic 2.5.3` / `fastapi 0.109`
> publish no wheels for 3.13 or 3.14, so installing into a newer venv fails.

**Then open:**
- **API (Swagger):** http://localhost:8000/docs
- **Frontend:** http://localhost:5173
- **n8n canvas:** http://localhost:5678 — no default login; the first visit
  creates the owner account (see the n8n Canvas section)

---

## What You're Actually Running

| Component | Status | How it runs |
|-----------|--------|-------------|
| **Postgres** | ✅ Works in Docker | `docker compose up -d` — real DB, no mocks |
| **Mock ERP / Compliance** | ✅ Works in Docker | `docker compose up -d` — deterministic synthetic services |
| **Backend (FastAPI)** | ✅ Runs natively | `uvicorn app.main:app --reload` — Python 3.10+, hot-reloads on code change |
| **Frontend (React + Vite)** | ✅ Runs natively | `npm run dev` — Vite dev server with `/api` proxy to backend |
| **n8n** | ✅ Works in Docker | `docker compose up -d` — canvas at :5678; workflows imported manually |

---

## The Architecture (Why This Works)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React     │────▶│  FastAPI    │────▶│  PostgreSQL │
│  (Frontend) │     │  (Backend)  │     │  (State)    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │     n8n     │
                    │ (Orchestra- │
                    │   tion)     │
                    └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌─────────┐ ┌───────────┐ ┌────────────┐
         │Mock ERP │ │Mock Comp  │ │  (Future)  │
         │ :8001   │ │ :8002     │ │  Real APIs │
         └─────────┘ └───────────┘ └────────────┘
```

- **Backend & Frontend run natively** on the host — hot reload works, no Docker build issues
- **Postgres, Mock ERP, Mock Compliance, n8n run in Docker** — isolated, reproducible, no host pollution
- **n8n reaches backend via `host.docker.internal:8000`** — works on Docker Desktop (Mac/Win) and Linux
- **Frontend Vite proxy** forwards `/api/*` to `http://localhost:8000` — no CORS issues

---

## What You'll See at Each URL

### http://localhost:8000/docs — **The Honest Truth**
The Swagger UI is fully populated. Every endpoint, schema, enum, and validation rule is there. You can execute calls directly against the live database. This is the most complete view of "what the product does."

**Try these first:**
1. `POST /api/vendors/` — create a vendor (needs `legal_name`, `country`)
2. `POST /api/onboarding/` — create an onboarding case (needs `vendor_id`)
3. `POST /api/onboarding/{case_id}/submit` — move from DRAFT → DOCUMENT_COLLECTION
4. `POST /api/onboarding/{case_id}/assess` — run the full deterministic + AI pipeline
5. `GET /api/dashboard/metrics` — aggregate counts
6. `GET /api/audit/` — event timeline (will be empty until you run above)

All responses use the exact Pydantic models the frontend consumes.

### http://localhost:5173 — **The Dashboard (Empty Until Seeded)**
Eight pages, all data-driven:
- **Dashboard** — KPI cards, charts, recent activity
- **Vendors** — list + detail with cases, documents, risk
- **Cases** — kanban by workflow status, detail with documents, exceptions, approvals
- **Documents** — upload, classify, extract, verify
- **Risk Review** — AI signals + deterministic findings per case
- **Exceptions** — queue with triage actions
- **Approvals** — human-in-the-loop decisions by role
- **Audit** — filterable timeline

With an empty DB, every page renders a "no data" state. That's not a bug — it's the dataset gap.

### http://localhost:5678 — **n8n Canvas**

**Sign-in:** there are no default credentials. `N8N_BASIC_AUTH_*` was removed
in n8n 1.0, and the image here is n8n 2.x, which uses built-in user
management — the first time you open the editor it asks you to create the
owner account. Pick any email and a password of 8+ characters.

Four workflows are pre-built in `n8n/workflows/`:
1. `case_orchestrator.json` — main orchestration (webhook: `POST /webhook/vendor-onboarding/case`)
2. `document_intake.json` — document classification + extraction (webhook endpoint)
3. `sla_escalation.json` — scheduled daily SLA check
4. `error_handler.json` — platform incident recording

**They are not auto-imported.** Import, publish, then restart n8n so the
published version takes effect:

```bash
for f in case_orchestrator document_intake sla_escalation error_handler; do
  docker compose exec -T n8n n8n import:workflow \
    --input="/home/node/.n8n/workflows/$f.json"
done

# workflow ids are stable (derived from the name); publish each, then restart
docker compose exec -T n8n n8n list:workflow          # shows id|name
docker compose exec -T n8n n8n publish:workflow --id=<id>
docker compose restart n8n
```

Verify all four are live with
`docker compose logs n8n | grep -i activated`.

**Triggering it.** The backend does *not* call n8n — the orchestrator is
entered through its own webhook:

```bash
curl -X POST http://localhost:5678/webhook/vendor-onboarding/case \
  -H 'Content-Type: application/json' \
  -d '{"case_id":1,"vendor_id":1,"action":"submit"}'
```

The workflow then calls *into* the backend (`/onboarding/{id}/submit`,
`/onboarding/{id}/assess`, `/approvals/reviewers`, …) and reports each step
back to `POST /api/webhooks/n8n`, which appends to the audit trail. A
successful run on a fresh case produces, in order:
`WORKFLOW_TRIGGERED` → `ASSESSMENT_COMPLETED` → `AI_RISK_ANALYSIS` → `CASE_ROUTED`.

**Environment variables the workflows expect:**
| Variable | Value (native mode) |
|----------|---------------------|
| `VOR_BACKEND_URL` | `http://host.docker.internal:8000` |
| `VOR_CALLBACK_SECRET` | `n8n-api-key` (matches `N8N_API_KEY` in `.env`) |
| `VOR_NOTIFICATION_URL` | `http://host.docker.internal:8000` (not used in demo) |

> **Note:** From inside the n8n container, `host.docker.internal` reaches your host machine where the native backend runs on 8000. If you run n8n natively too, use `http://localhost:8000`.

---

## Creating Demo Data

### Option A: Seed Script (Recommended)
There is no `backend` service in `docker-compose.yml` (the backend runs
natively), so seed with the native interpreter:

```bash
PYTHONPATH="$PWD/backend" \
  DATABASE_URL="postgresql://vendoruser:vendorpass@localhost:5432/vendordb" \
  LLM_PROVIDER=mock \
  DOCUMENT_STORAGE_PATH="$PWD/documents/uploads" \
  backend/.venv/Scripts/python.exe backend/scripts/seed_demo_data.py
```

This creates **20 synthetic vendors across 6 risk scenarios** with documents, risk signals, exceptions, approvals, and audit trail.

> The seed is **not idempotent** — running it twice duplicates every vendor.
> Truncate first:
> `docker compose exec -T postgres psql -U vendoruser -d vendordb -c "TRUNCATE TABLE approvals, audit_events, documents, extracted_fields, exceptions, onboarding_cases, requirements, risk_assessments, risk_signals, users, vendors RESTART IDENTITY CASCADE;"`

### Option B: Manual API Calls (Quick Test)
```bash
# 1. Create a vendor
POST /api/vendors/
{
  "legal_name": "Acme Corp",
  "trade_name": "Acme",
  "country": "US",
  "contact_email": "ops@acme.example",
  "industry": "Software"
}

# 2. Create an onboarding case
POST /api/onboarding/
{
  "vendor_id": 1,
  "onboarding_type": "new_vendor",
  "priority": "normal",
  "requester_name": "Jane Doe",
  "requester_email": "jane@internal.example"
}

# 3. Submit it (starts the pipeline)
POST /api/onboarding/1/submit

# 4. Run assessment (deterministic + AI)
POST /api/onboarding/1/assess
```

The assessment runs synchronously and returns:
```json
{
  "case_id": 1,
  "route": "REVIEW_REQUIRED",
  "score_total": 38,
  "score_components": [...],
  "requirements": [...],
  "ai_advisory": {...}
}
```

After this, the Dashboard, Cases, Risk Review, and Audit pages will have data.

---

## n8n Workflow Integration (Optional)

If you want to see n8n actually orchestrate:

1. Start infrastructure: `docker compose up -d`
2. Import, publish and restart as shown in the "n8n Canvas" section above
3. In n8n, open each workflow and set **Error Workflow** → "Vendor Onboarding — Error Handler"
4. Trigger it: `POST http://localhost:5678/webhook/vendor-onboarding/case`

**Direction of travel.** n8n calls the backend; the backend never calls n8n.
`N8N_WEBHOOK_URL` exists in `app/config.py` but nothing reads it, and
`backend/app/services/pipeline.py` contains no outbound n8n call — an earlier
version of this file claimed otherwise. The only n8n-facing route in the
backend is the *inbound* `POST /api/webhooks/n8n`, authenticated with header
`X-N8N-Secret: n8n-api-key`, which appends one audit event per call and can
change no case state.

That boundary is deliberate: orchestration lives in n8n, business logic lives
in the backend, and the webhook cannot mutate anything.

**Environment variables the workflows read** (set on the n8n container in
`docker-compose.yml`, read via `$env.*` expressions):

| Variable | Value (native mode) |
|----------|---------------------|
| `VOR_BACKEND_URL` | `http://host.docker.internal:8000` |
| `VOR_CALLBACK_SECRET` | `n8n-api-key` (matches `N8N_API_KEY` in `.env`) |
| `VOR_NOTIFICATION_URL` | `http://host.docker.internal:8000` (not used in demo) |

Reading `$env.*` requires `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, which the
compose file sets. Without it the URLs resolve to empty and every HTTP node
fails with `Invalid URL`. The tradeoff — any expression in n8n can then read
any variable in that container — is acceptable locally and is recorded in
`docs/decisions.md`.

---

## Key Environment Variables

Create `.env` from `.env.example` and adjust as needed:

```bash
# Database (matches compose)
DATABASE_URL=postgresql://vendoruser:vendorpass@localhost:5432/vendordb

# LLM — "mock" = deterministic, keyless demo
LLM_PROVIDER=mock
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# n8n
# N8N_WEBHOOK_URL is declared in app/config.py but nothing reads it: the
# backend does not call n8n. Kept so the setting is documented, not relied on.
N8N_WEBHOOK_URL=http://localhost:5678
# Shared secret for the INBOUND callback (POST /api/webhooks/n8n). This is the
# one n8n setting that must match docker-compose.yml's VOR_CALLBACK_SECRET.
N8N_API_KEY=n8n-api-key

# Mock services (used in Docker compose)
ERP_API_URL=http://localhost:8001
COMPLIANCE_API_URL=http://localhost:8002

# CORS (for Vite dev proxy)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Auth (prototype only — static keys)
API_KEYS=demo-api-key-001,demo-api-key-002
```

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| `uvicorn` fails: "Address already in use" | Another process on 8000. Kill it or change port. |
| `npm run dev` fails: "Port 5173 in use" | Vite picks next free port; check terminal output. |
| Frontend shows "Failed to fetch" | Backend not running, or CORS. Check terminal 2. |
| `psycopg2` install fails on Windows | `pip install psycopg2-binary` (already in requirements) |
| n8n workflows show "Error: connect ECONNREFUSED" | `VOR_BACKEND_URL` wrong. Use `host.docker.internal:8000` from container. |
| `docker compose up` fails: "no such file or directory" | Make sure you're in the project root with `docker-compose.yml` |
| Mock services not healthy | Check `docker compose logs mock-erp` / `mock-compliance` |

---

## Architecture Reminder (for Portfolio Context)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React     │────▶│  FastAPI    │────▶│  PostgreSQL │
│  (Frontend) │     │  (Backend)  │     │  (State)    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │     n8n     │
                    │ (Orchestra- │
                    │   tion)     │
                    └─────────────┘
```

- **n8n does:** webhooks, retries, scheduling, routing, notifications
- **Backend does:** ALL business logic, rules, risk scoring, AI calls, state mutations
- **MockProvider** runs keyless; `LLM_PROVIDER=openai` without key falls back to mock

---

## Verification (Run These Before You Trust Anything)

Four checks stand in for the test suite this sandbox cannot host. Each exits
non-zero on failure, so all four are safe to wire into CI as-is.

```bash
cd vendor-onboarding-orchestrator

# 1. Backend: syntax, imports, route shadowing, SQLAlchemy reserved names, ORM typos
python3 backend/check_static.py

# 2. Frontend: broken imports, unnamed exports, dead links, undefined CSS tokens
python3 frontend/check_static.py

# 3. Frontend/backend type drift (field names, missing fields, type and enum drift)
python3 tools/check_contracts.py

# 4. n8n workflow JSON: unique ids, every link resolves, no orphan nodes
python3 n8n/build_workflows.py --check

# 5. project_spec.json is not stale relative to the source it describes
python3 tools/build_project_spec.py --check
```

### Evaluation (the numbers in the portfolio)

The rule engine and risk scorer are evaluated over 50 synthetic cases. The run
is deterministic and writes both a human-readable report and per-case JSON.

```bash
python3 backend/scripts/run_evaluation.py
```

Outputs:

- `evaluation/REPORT.md` — confusion matrix, per-route precision/recall, score
  distribution, rule firing counts, and the severity-floor regression test
- `evaluation/results.json` — the same metrics plus every individual case

The harness asserts the properties that no accuracy figure excuses: no case
requiring human review may be auto-approved, every case that should block must
block, and no clean case may be flagged. If any of those fail it exits non-zero
and prints which case broke.

> **Prototype Metrics.** The 50 cases are synthetic and their labels come from
> the same policy the engine encodes, so the figures measure implementation
> fidelity, not real-world detection precision. The report says this too — it is
> not a footnote hidden in a README.

---

## Generating project_spec.json

`project_spec.json` is the machine-readable description of the system: every
endpoint, table, column, enum, rule, threshold and workflow, plus the webhook
contracts and the environment-variable schema.

It is **generated from the source**, not written by hand — the routes are parsed
out of the FastAPI decorators, the tables out of the SQLAlchemy models, the rules
out of `RuleEngine`, and the tunables out of `Settings`. A route rename therefore
changes the spec, and a spec that was not regenerated fails `--check`.

```bash
python3 tools/build_project_spec.py           # regenerate
python3 tools/build_project_spec.py --check   # verify it is current
```

The small amount of prose it carries (what each workflow is *for*, what each
event type *means*) is asserted against the source at build time: delete a
workflow file or rename a webhook allowlist entry, and the generator fails rather
than emitting a document describing a system that no longer exists.

---

## What's Next (The Roadmap)

| Task | Status | What It Unlocks |
|------|--------|-----------------|
| Seed data (20 vendors, 6 scenarios) | **Ready** | `python backend/scripts/seed_demo_data.py` against a live Postgres |
| Evaluation (50 cases, real metrics) | **Done** | `python3 backend/scripts/run_evaluation.py` → `evaluation/REPORT.md` |
| Documentation package | **Done** | `docs/decisions.md`, `docs/data-model.md`, `docs/workflow.md`, `ARCHITECTURE.md` |
| Machine-readable spec | **Done** | `project_spec.json` via `tools/build_project_spec.py` |
| Mock ERP / Compliance services | **Done** | Full integration demos |

---

## Quick Test: Is It Alive?

```bash
# Backend health
curl http://localhost:8000/health

# Frontend dev server
curl -I http://localhost:5173

# n8n (if running in Docker)
curl -I http://localhost:5678

# Mock ERP
curl http://localhost:8001/health

# Mock Compliance
curl http://localhost:8002/health

# Postgres
docker compose exec postgres pg_isready -U vendoruser -d vendordb
```

All should return 200/304 or "accepting connections".

---

*Generated from the actual codebase on 2026-09-19. No hallucinated features — only what exists and runs.*