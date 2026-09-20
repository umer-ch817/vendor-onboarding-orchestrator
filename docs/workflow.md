# Workflow Orchestration — Vendor Onboarding & Risk Orchestrator

*Complete n8n workflow definitions, trigger points, webhook contracts, and operational runbook.*

---

## Overview

The system uses **four n8n workflows** generated from `n8n/build_workflows.py`. n8n handles **orchestration only** — no business logic. All decisions, scoring, state mutations happen in the FastAPI backend.

```
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (FastAPI)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Pipeline   │  │  Approval   │  │   Audit     │             │
│  │  Service    │  │  Service    │  │  Service    │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
└─────────┼────────────────┼────────────────┼────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       n8n (Orchestration)                       │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │ Case Orchestrator│ │ Document Intake │ │  SLA Escalation │   │
│  │  (main flow)    │ │  (webhook)      │ │  (schedule)     │   │
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘   │
└───────────┼────────────────────┼────────────────────┼────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
       Backend API          Backend API           Backend API
       (assessment)         (doc processing)      (SLA check)
```

---

## Workflow 1: Case Orchestrator (`case_orchestrator.json`)

**Purpose:** Main end-to-end orchestration triggered by `POST /api/onboarding/{id}/assess`.

**Trigger:** HTTP Webhook (called by backend `OnboardingPipeline.run()`)

**Nodes:**

| Node | Type | Function | Retry Policy |
|------|------|----------|--------------|
| `Start` | Webhook | Entry point — receives `{case_id, trigger: "assess"}` | — |
| `Validate Case` | HTTP Request | `GET /api/onboarding/{case_id}` — confirms case exists, status ∈ ASSESSABLE_STATUSES | 3×, 5s, 10s, 20s |
| `Run Assessment` | HTTP Request | `POST /api/onboarding/{case_id}/assess` — synchronous pipeline execution | 2×, 10s, 30s |
| `Check Route` | IF | Branch on `route` from assessment: `AUTO_APPROVE` / `REVIEW_REQUIRED` / `APPROVAL_REQUIRED` / `REJECT` | — |
| `Auto Approve Path` | HTTP Request | `POST /api/onboarding/{case_id}/status` → `ONBOARDING_COMPLETE` | 2×, 5s, 10s |
| `Request Reviews` | HTTP Request | `POST /api/approvals/` × N (per role map) | 2×, 5s, 10s |
| `Notify Reviewers` | HTTP Request | `POST /api/notifications/` — email/Slack to assigned reviewers | 3×, 10s, 30s, 60s |
| `Wait for Approvals` | Wait | Pause until all approvals decided (webhook callbacks resume) | — |
| `Finalize` | HTTP Request | `POST /api/onboarding/{case_id}/finalize` — computes terminal status | 2×, 5s, 10s |
| `Record Success` | HTTP Request | `POST /api/webhooks/n8n` — `WORKFLOW_COMPLETED` | 2×, 5s, 10s |
| `Error Handler` | Error Trigger | Catches any node error → `error_handler` workflow | — |

**Webhook Payload (inbound to n8n):**
```json
{
  "case_id": 123,
  "trigger": "assess",
  "metadata": {
    "source": "backend_pipeline",
    "timestamp": "2026-09-19T10:30:00Z"
  }
}
```

**Backend Callback (n8n → backend):**
```json
// POST /api/webhooks/n8n
{
  "event_type": "WORKFLOW_TRIGGERED",
  "case_id": 123,
  "data": {
    "_workflow": "case_orchestrator",
    "_execution_id": "exec_abc123"
  },
  "timestamp": "2026-09-19T10:30:00Z"
}
```

**Retry Configuration (all HTTP nodes):**
```json
{
  "maxTries": 3,
  "waitBetweenTriesMs": 5000,
  "retryOn": ["ECONNREFUSED", "ETIMEDOUT", "5xx"]
}
```

---

## Workflow 2: Document Intake (`document_intake.json`)

**Purpose:** Async document classification + extraction triggered by document upload.

**Trigger:** HTTP Webhook (called by frontend after file upload, or by backend after `register_document`)

**Nodes:**

| Node | Type | Function |
|------|------|----------|
| `Start` | Webhook | Receives `{document_id, vendor_id, case_id, declared_type?}` |
| `Fetch Document` | HTTP Request | `GET /api/documents/{document_id}/content` — retrieves blob |
| `Classify` | Function | Deterministic classification (filename keywords → content regex) — returns `DocumentType` |
| `Update Classification` | HTTP Request | `PATCH /api/documents/{document_id}` — sets `document_type`, `status=PROCESSING` |
| `Extract Fields` | HTTP Request | `POST /api/ai/extract` — AI extraction with `DocumentExtractionResult` schema |
| `Persist Fields` | HTTP Request | `POST /api/documents/{document_id}/fields` — bulk create `ExtractedField` rows |
| `Validate Fields` | HTTP Request | `POST /api/documents/{document_id}/validate` — runs field-level validation rules |
| `Build Evidence` | HTTP Request | `POST /api/documents/{document_id}/evidence` — creates evidence summary for rules |
| `Complete` | HTTP Request | `PATCH /api/documents/{document_id}` — `status=EXTRACTED` or `FAILED` |
| `Callback` | HTTP Request | `POST /api/webhooks/n8n` — `DOCUMENT_PROCESSING_DISPATCHED` / `RETRY_EXHAUSTED` |

**Webhook Payload:**
```json
{
  "document_id": 456,
  "vendor_id": 123,
  "case_id": 789,
  "declared_type": "certificate_of_insurance",
  "metadata": {
    "source": "frontend_upload",
    "timestamp": "2026-09-19T10:30:00Z"
  }
}
```

---

## Workflow 3: SLA Escalation (`sla_escalation.json`)

**Purpose:** Daily scheduled check for cases approaching or exceeding review deadlines.

**Trigger:** Cron — `0 9 * * *` (daily 09:00 UTC)

**Nodes:**

| Node | Type | Function |
|------|------|----------|
| `Start` | Cron | Daily at 09:00 UTC |
| `Fetch Active Cases` | HTTP Request | `GET /api/onboarding/?status=REVIEW_REQUIRED,APPROVAL_PENDING&limit=500` |
| `Filter SLA` | Function | For each case: compute `days_since_assessment`, compare to SLA (3 days warning, 7 days escalation) |
| `Warning Path` | IF | `days_since_assessment >= 3 AND < 7` → send warning |
| `Send Warning` | HTTP Request | `POST /api/webhooks/n8n` — `SLA_WARNING` per case |
| `Escalation Path` | IF | `days_since_assessment >= 7` → escalate |
| `Escalate Case` | HTTP Request | `POST /api/onboarding/{case_id}/escalate` — bumps to next authority, creates exception |
| `Escalation Callback` | HTTP Request | `POST /api/webhooks/n8n` — `SLA_ESCALATED` per case |
| `Summary` | HTTP Request | `POST /api/webhooks/n8n/incident` — `WORKFLOW_COMPLETED` with summary counts |

**SLA Rules (configurable via env):**
| Priority | Warning | Escalation |
|----------|---------|------------|
| `urgent` | 1 day | 3 days |
| `high` | 2 days | 5 days |
| `normal` | 3 days | 7 days |
| `low` | 5 days | 14 days |

---

## Workflow 4: Error Handler (`error_handler.json`)

**Purpose:** Centralized error handling — records platform incidents for any workflow failure.

**Trigger:** Error Trigger (attached as "Error Workflow" to the other three)

**Nodes:**

| Node | Type | Function |
|------|------|----------|
| `Start` | Error Trigger | Receives error context from failed workflow |
| `Extract Context` | Function | Parses `error.workflow`, `error.node`, `error.message`, `executionId` |
| `Determine Case ID` | Function | Tries to extract `case_id` from workflow data; may be null |
| `Record Incident` | HTTP Request | `POST /api/webhooks/n8n/incident` — `WorkflowIncident` payload |
| `Notify Ops` | HTTP Request | `POST /api/notifications/` — critical alert to ops channel (if configured) |
| `Done` | NoOp | End |

**Incident Payload:**
```json
{
  "event_type": "WORKFLOW_FAILED",
  "description": "Case Orchestrator failed at 'Run Assessment': Connection refused to backend",
  "workflow": "case_orchestrator",
  "execution_id": "exec_abc123",
  "node": "Run Assessment",
  "message": "connect ECONNREFUSED 127.0.0.1:8000",
  "case_id": 123,
  "data": {
    "failed_node": "Run Assessment",
    "retry_count": 2,
    "last_error": "ECONNREFUSED"
  },
  "timestamp": "2026-09-19T10:30:00Z"
}
```

---

## Webhook Contracts (Backend ↔ n8n)

### 1. Case-Scoped Events (`POST /api/webhooks/n8n`)
**Auth:** Header `X-N8N-Secret: {N8N_API_KEY}`

**Allowed Event Types (Closed Allowlist):**
| Event Type | Description |
|------------|-------------|
| `WORKFLOW_TRIGGERED` | Orchestration workflow started for this case |
| `WORKFLOW_COMPLETED` | Orchestration workflow finished successfully |
| `WORKFLOW_FAILED` | Orchestration workflow failed after exhausting retries |
| `NOTIFICATION_SENT` | Reviewer notification dispatched |
| `NOTIFICATION_FAILED` | Reviewer notification could not be delivered |
| `NOTIFICATION_SKIPPED` | Notification suppressed (case already actioned) |
| `REVIEWER_ASSIGNED` | Case handed to a reviewer queue |
| `APPROVAL_OPENED` | Approval request raised for human decision |
| `SLA_WARNING` | Case approaching review deadline |
| `SLA_ESCALATED` | Case exceeded deadline and was escalated |
| `DOCUMENT_PROCESSING_DISPATCHED` | Document sent for extraction |
| `RETRY_EXHAUSTED` | Downstream call failed, no retries remain |

**Request Schema:**
```json
{
  "event_type": "WORKFLOW_TRIGGERED",
  "case_id": 123,
  "data": {
    "_workflow": "case_orchestrator",
    "_execution_id": "exec_abc123"
  },
  "timestamp": "2026-09-19T10:30:00Z"
}
```

**Response:**
```json
{
  "recorded": true,
  "event_id": 456,
  "event_type": "WORKFLOW_TRIGGERED",
  "case_id": 123
}
```

---

### 2. Platform Incidents (`POST /api/webhooks/n8n/incident`)
**Auth:** Header `X-N8N-Secret: {N8N_API_KEY}`

**Allowed Event Types:**
| Event Type | Description |
|------------|-------------|
| `WORKFLOW_FAILED` | Orchestration workflow terminated with error |
| `INTEGRATION_UNREACHABLE` | Downstream service did not answer |
| `RETRY_EXHAUSTED` | Downstream call failed, no retries remain |
| `WEBHOOK_REJECTED` | Inbound trigger failed validation |

**Request Schema (`WorkflowIncident`):**
```json
{
  "event_type": "WORKFLOW_FAILED",
  "description": "Optional override description",
  "workflow": "case_orchestrator",
  "execution_id": "exec_abc123",
  "node": "Run Assessment",
  "message": "Error details",
  "case_id": 123,  // optional
  "data": {},
  "timestamp": "2026-09-19T10:30:00Z"
}
```

**Response:**
```json
{
  "recorded": true,
  "event_id": 789,
  "event_type": "WORKFLOW_FAILED",
  "case_id": 123
}
```

---

### 3. Allowlist Discovery (`GET /api/webhooks/n8n/event-types`)
**Auth:** None (public vocabulary)

**Response:**
```json
{
  "event_types": [
    {"event_type": "WORKFLOW_TRIGGERED", "description": "Orchestration workflow started..."},
    ...
  ],
  "incident_event_types": [
    {"event_type": "WORKFLOW_FAILED", "description": "An orchestration workflow terminated..."},
    ...
  ]
}
```

---

## Environment Variables for n8n Workflows

| Variable | Description | Native Mode Value | Docker Mode Value |
|----------|-------------|-------------------|-------------------|
| `VOR_BACKEND_URL` | Backend base URL | `http://host.docker.internal:8000` | `http://backend:8000` |
| `VOR_CALLBACK_SECRET` | Webhook auth secret | `n8n-api-key` | `n8n-api-key` |
| `VOR_NOTIFICATION_URL` | Notification service | `http://host.docker.internal:8000` | `http://backend:8000` |

**Set in n8n:** Workflow → Settings → Environment Variables (or via `.env` in n8n container)

---

## Importing Workflows

### Via n8n UI
1. Open http://localhost:5678 (admin / admin123)
2. Workflows → Import → Select each `.json` from `n8n/workflows/`
3. For each workflow: Settings → Error Workflow → "Vendor Onboarding — Error Handler"
4. Activate each workflow (toggle top-right)

### Via CLI (inside n8n container)
```bash
docker exec -it vendor-n8n sh
n8n import:workflow --input=/home/node/.n8n/workflows/case_orchestrator.json
n8n import:workflow --input=/home/node/.n8n/workflows/document_intake.json
n8n import:workflow --input=/home/node/.n8n/workflows/sla_escalation.json
n8n import:workflow --input=/home/node/.n8n/workflows/error_handler.json
```

---

## Regenerating Workflows

**Source of truth:** `n8n/build_workflows.py` (Python)

```bash
cd n8n
python build_workflows.py
```

This overwrites all 4 JSON files in `n8n/workflows/`. Run after any orchestration logic change.

---

## Operational Runbook

### Starting the Stack
```bash
# 1. Infrastructure
docker compose up -d

# 2. Backend (native)
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql://vendoruser:vendorpass@localhost:5432/vendordb \
  uvicorn app.main:app --reload --port 8000

# 3. Frontend (native)
cd ../frontend
npm install
npm run dev

# 4. Import & activate n8n workflows (see above)
```

### Verifying n8n Connectivity
```bash
# From host - test backend reachable from n8n container
docker exec vendor-n8n wget -qO- http://host.docker.internal:8000/health

# Check n8n logs
docker compose logs -f n8n
```

### Common Issues

| Symptom | Diagnosis | Fix |
|---------|-----------|-----|
| Workflow fails at "Run Assessment" | Backend not reachable from n8n | Check `VOR_BACKEND_URL` = `http://host.docker.internal:8000` |
| Webhook returns 401 | Secret mismatch | `VOR_CALLBACK_SECRET` must equal `N8N_API_KEY` in `.env` |
| Workflow not triggering | Not activated | Toggle "Active" in n8n UI |
| "Error Workflow" not called | Not configured | Set Error Workflow in each workflow's Settings |
| SLA workflow not running | Cron not firing | Check n8n container timezone (UTC) and cron expression |

### Debugging a Failed Execution
1. Open n8n UI → Executions → Find failed run
2. Click execution → Inspect each node's input/output
3. Check backend logs for corresponding HTTP requests
4. Check `AuditEvent` table for `WORKFLOW_FAILED` / `RETRY_EXHAUSTED` events
5. Re-run from failed node (n8n UI) after fixing root cause

---

## Workflow Versioning

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-15 | Initial four workflows |
| 1.1 | 2026-02-01 | Added `maxTries`/`waitBetweenTriesMs` to all HTTP nodes |
| 1.2 | 2026-02-15 | Added `WORKFLOW_COMPLETED` callback on success path |
| 1.3 | 2026-03-01 | Separated platform incidents from case events |

**Current:** v1.3 (generated from `build_workflows.py`)

---

## Extending Workflows

To add a new orchestration step:

1. **Add backend endpoint** in `backend/app/api/` (business logic)
2. **Add node** in `n8n/build_workflows.py` (HTTP Request node config)
3. **Regenerate:** `python n8n/build_workflows.py`
4. **Re-import** in n8n (delete old, import new)
5. **Test** end-to-end via `POST /api/onboarding/{id}/assess`

**Never** hand-edit the JSON files — they are generated artifacts.

---

*Workflow Orchestration v1.3 — Generated from `n8n/build_workflows.py`*