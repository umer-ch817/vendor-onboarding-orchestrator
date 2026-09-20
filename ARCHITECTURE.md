# Vendor Onboarding & Risk Orchestrator — Architecture Document

*Generated from the actual codebase. No hallucinated features — only what exists and runs.*

---

## 1. System Overview

### 1.1 Purpose
A portfolio-grade n8n workflow automation project demonstrating deterministic rule-based vendor onboarding with AI guardrails, human-in-the-loop approvals, and full auditability.

### 1.2 Architecture Philosophy
- **n8n = Orchestration only** (webhooks, retries, scheduling, routing, notifications)
- **FastAPI = ALL business logic** (rules, risk scoring, AI calls, state mutations)
- **PostgreSQL = Single source of truth** for state
- **React = Pure data-driven UI** (no business logic)

### 1.3 High-Level Data Flow
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

---

## 2. Component Architecture

### 2.1 Backend (FastAPI) — `backend/app/`

#### Core Modules
| Module | Purpose | Key Files |
|--------|---------|-----------|
| **main.py** | App factory, CORS, lifespan, health check | `main.py` |
| **config.py** | Pydantic Settings v2, all env vars | `config.py` |
| **database.py** | Async SQLAlchemy 2.0 engine/session | `database.py` |
| **models/__init__.py** | 12 SQLAlchemy models | `models/__init__.py` |
| **schemas/__init__.py** | Pydantic v2 API contracts + webhook payloads | `schemas/__init__.py` |
| **api/__init__.py** | 9 routers, FastAPI app assembly | `api/__init__.py` |

#### API Routers (9 total)
| Router | Path Prefix | Responsibility |
|--------|-------------|----------------|
| vendors | `/api/vendors` | Vendor CRUD + risk updates |
| onboarding | `/api/onboarding` | Case lifecycle, submit, assess, summaries |
| documents | `/api/documents` | Upload, classify, extract, verify |
| risk | `/api/risk` | Read-side risk views for Risk Review page |
| exceptions | `/api/exceptions` | Queue, triage, assign, resolve |
| approvals | `/api/approvals` | Human-in-the-loop decisions by role |
| audit | `/api/audit` | Filterable timeline (user, system, AI, n8n) |
| dashboard | `/api/dashboard` | KPI cards, charts, recent activity |
| webhooks | `/api/webhooks` | Inbound n8n callbacks (closed allowlist) |

#### Services Layer
| Service | Responsibility | Key Methods |
|---------|---------------|-------------|
| **vendor_service.py** | Vendor CRUD + risk updates | `create`, `update`, `update_risk` |
| **onboarding_service.py** | Case CRUD + workflow transitions | `create`, `get_with_details`, `update_status`, `submit` |
| **document_service.py** | Document lifecycle | `register`, `classify`, `extract`, `persist_fields`, `build_evidence` |
| **document_processing.py** | Raw text extraction | `extract_text` (PDF, txt, CSV) + scan detection |
| **requirement_service.py** | Resolves document requirements | `resolve` (by vendor type/country/industry/risk) |
| **pipeline.py** | Orchestrates full assessment | `run` → extract→normalize→validate→score→route→persist |
| **risk_service.py** | Read-side risk views | `get_risk_detail`, `get_signals` |
| **approval_service.py** | Approval workflow | `create_approvals`, `decide`, `escalate` |
| **exception_service.py** | Exception CRUD + triage | `list_open`, `triage`, `assign`, `resolve` |
| **audit_service.py** | Event recording | `record_user`, `record_system`, `record_ai`, `record_n8n` |

#### Rule Engine — `app/rules/`
| File | Purpose |
|------|---------|
| `types.py` | Pure dataclasses: Evidence, RuleFinding, RuleEvaluation, RiskScoreResult, RequirementSpec |
| `engine.py` | 11 Rule classes + RuleEngine (evaluates all, isolates failures) |
| `risk_scoring.py` | RiskScoringService with ScoreComponent attribution, severity-floor routing |

**The 11 Deterministic Rules:**
1. `MissingDocumentRule` — required docs not uploaded
2. `ExpiredDocumentRule` — doc expiration_date < today
3. `ExpiringSoonRule` — doc expiring within warning window
4. `EntityNameMismatchRule` — vendor name vs extracted name similarity
5. `BankingMismatchRule` — bank account holder vs vendor legal name
6. `HighRiskGeographyRule` — vendor country in HIGH_RISK_COUNTRIES
7. `InsuranceCoverageRule` — COI coverage below minimum
8. `TaxIdFormatRule` — TIN/EIN format validation
9. `OwnershipDisclosureRule` — supplier questionnaire ownership fields
10. `PaymentTermsRule` — terms validation
11. `IncompleteExtractionRule` — low confidence extracted fields

**Risk Scoring:**
- Additive: each RuleFinding contributes `weight × severity_multiplier`
- ScoreComponents persisted for full explainability
- Severity floors override: CRITICAL finding → route = REVIEW_REQUIRED minimum

#### AI Layer — `app/ai/`
| File | Purpose |
|------|---------|
| `provider.py` | LLMProvider abstraction + OpenAIProvider + MockProvider (deterministic, keyless) |
| `schemas.py` | Pydantic schemas for AI outputs (ClassificationResult, ExtractionResult, RiskAnalysisResult, ExceptionTriageResult) |
| `extraction.py` | DocumentExtractionService (classify → extract with confidence-aware routing) |
| `analysis.py` | VendorRiskAnalysisService + ExceptionTriageService (advisory only) |
| `guardrails.py` | `call_with_validation` — Pydantic validation + 1 repair attempt → exception |

**AI Guardrails (Non-Negotiable):**
- Structured outputs only (Pydantic v2)
- Model never decides; only suggests
- Validation → repair (1 attempt) → exception
- Structured reasoning/evidence stored, never hidden CoT
- MockProvider runs keyless; OpenAI without key falls back to mock

#### Normalization — `app/utils/normalization.py`
Deterministic helpers for:
- Name normalization (legal_name, trade_name)
- Address normalization
- Tax ID normalization (EIN, SSN, VAT)
- Date parsing (multiple formats)
- Payment terms normalization

### 2.2 Frontend (React + Vite) — `frontend/src/`

#### Pages (8)
| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/` | KPI cards, charts, recent activity |
| Vendors | `/vendors` | List + detail with cases, documents, risk |
| Cases | `/cases` | Kanban by workflow status, detail view |
| Documents | `/documents` | Upload, classify, extract, verify |
| Risk Review | `/risk/:caseId` | AI signals + deterministic findings |
| Exceptions | `/exceptions` | Queue with triage actions |
| Approvals | `/approvals` | Human decisions by role |
| Audit | `/audit` | Filterable timeline |

#### API Client — `utils/api.ts`
Typed Axios client for all backend endpoints with:
- Request/response types matching Pydantic schemas
- Interceptor for auth headers
- Error handling

#### State Management
- React Query (TanStack Query) for server state
- Local component state only
- No Redux/Zustand — deliberate simplicity

### 2.3 n8n Orchestration — `n8n/workflows/`

#### Generated Workflows (via `n8n/build_workflows.py`)
| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `case_orchestrator.json` | HTTP POST from `/assess` | Main orchestration: dispatches extraction, polls, routes, notifies |
| `document_intake.json` | Webhook (document upload) | Classify → extract → verify → callback |
| `sla_escalation.json` | Schedule (daily 09:00) | Finds stale cases, escalates, records incidents |
| `error_handler.json` | Error workflow | Records platform incidents via `/webhooks/n8n/incident` |

#### Workflow Design Principles
- **Generated, not hand-written** — prevents JSON drift
- **HTTP nodes stringify JSON bodies** — prevents data loss
- **Error workflow attached** — all failures recorded as platform incidents
- **Callbacks use shared secret** — `X-N8N-Secret` header validated by backend

#### Key n8n → Backend Callbacks
```
POST /api/webhooks/n8n
Headers: X-N8N-Secret: n8n-api-key
Body: { event_type, case_id, timestamp, data }
```
Event types are **closed allowlist** (25 types) — n8n cannot write arbitrary strings.

### 2.4 Database (PostgreSQL) — 12 Tables

| Table | Purpose |
|-------|---------|
| `users` | Internal reviewers (role-based authority) |
| `vendors` | Vendor master data + current risk level/score |
| `onboarding_cases` | Case lifecycle + workflow status + risk |
| `documents` | Uploaded files + processing status + dates |
| `extracted_fields` | Normalized key-value pairs per document |
| `risk_signals` | Per-case signals (type, severity, evidence, status) |
| `risk_assessments` | Historical assessments (score, level, reasoning) |
| `exceptions` | Human-in-the-loop queue (never AI-closed) |
| `approvals` | Role-based approval chain |
| `audit_events` | Immutable trail (actor_type: USER/SYSTEM/AI/N8N) |
| `requirements` | Document checklist with applicability conditions |

---

## 3. Data Models (Key Entities)

### 3.1 Vendor
```typescript
interface Vendor {
  id: number;
  legal_name: string;
  trade_name?: string;
  vendor_type: string;        // supplier, contractor, consultant, service_provider
  industry: string;
  tax_id: string;             // Synthetic/masked in demo
  country: string;            // ISO-2 code
  status: VendorStatus;       // active, inactive, pending, suspended, rejected
  risk_level: RiskLevel;      // low, medium, high, critical
  risk_score: number;         // 0-100
  bank_name?: string;
  bank_account_last4?: string;
}
```

### 3.2 OnboardingCase
```typescript
interface OnboardingCase {
  id: number;
  case_number: string;        // VOR-YYYY-NNNNN
  vendor_id: number;
  workflow_status: WorkflowStatus;  // 11 states from DRAFT → ONBOARDING_COMPLETE
  onboarding_type: string;    // new_vendor, renewal, update
  priority: string;           // low, normal, high, urgent
  risk_score: number;
  risk_level: RiskLevel;
  completion_percentage: number;
  documents_received: number;
  documents_required: number;
  assigned_to_id?: number;
}
```

### 3.3 Document
```typescript
interface Document {
  id: number;
  vendor_id: number;
  case_id: number;
  document_type: DocumentType;  // 10 types
  filename: string;
  status: DocumentStatus;       // pending, processing, extracted, verified, failed, expired
  extraction_confidence: number; // 0.00-1.00
  expiration_date?: Date;
  document_date?: Date;
}
```

### 3.4 RiskSignal
```typescript
interface RiskSignal {
  id: number;
  vendor_id: number;
  case_id: number;
  signal_type: string;          // ENTITY_NAME_MISMATCH, DOCUMENT_EXPIRED, etc.
  severity: ExceptionSeverity;  // low, medium, high, critical
  description: string;
  evidence: Record<string, any>;
  source: string;               // rules_engine, ai_analysis, document_check
  status: string;               // open, acknowledged, resolved, dismissed
}
```

### 3.5 Exception
```typescript
interface Exception {
  id: number;
  case_id: number;
  type: string;                 // MISSING_DOCUMENT, ENTITY_MISMATCH, etc.
  severity: ExceptionSeverity;
  title: string;
  description: string;
  evidence: Record<string, any>; // Includes AI triage suggestions under "triage" key
  status: ExceptionStatus;      // open, in_progress, resolved, escalated, closed
  resolution?: string;
  resolution_type?: string;     // resolved, override, dismissed, escalated
  assigned_to_id?: number;
}
```

### 3.6 Approval
```typescript
interface Approval {
  id: number;
  case_id: number;
  approval_type: string;        // compliance, finance, legal, manager
  requested_from_id: number;
  status: ApprovalStatus;       // pending, approved, rejected, escalated
  decision?: string;
  comments?: string;
  escalated_to_id?: number;
}
```

### 3.7 AuditEvent
```typescript
interface AuditEvent {
  id: number;
  case_id?: number;             // NULL for platform incidents
  actor_type: ActorType;        // USER, SYSTEM, AI, N8N
  actor_id?: number;
  actor_name: string;
  event_type: string;           // Closed vocabularies per actor type
  description: string;
  input_snapshot: Record<string, any>;
  output_snapshot: Record<string, any>;
  metadata: Record<string, any>;
  timestamp: DateTime;
}
```

---

## 4. API Contracts

### 4.1 Key Endpoints

#### Vendor Management
```
POST   /api/vendors/                    → Create vendor
GET    /api/vendors/                    → List (paginated, searchable)
GET    /api/vendors/{id}                → Detail with cases, docs, risk
PATCH  /api/vendors/{id}                → Update
GET    /api/vendors/{id}/risk           → Current risk detail
```

#### Onboarding Cases
```
POST   /api/onboarding/                 → Create case (DRAFT)
GET    /api/onboarding/                 → List (filters: status, risk, search)
GET    /api/onboarding/workflow-summary → Counts by status
GET    /api/onboarding/risk-summary     → Counts by risk level
GET    /api/onboarding/{id}             → Full detail
PATCH  /api/onboarding/{id}             → Update metadata
POST   /api/onboarding/{id}/submit      → DRAFT → DOCUMENT_COLLECTION
POST   /api/onboarding/{id}/assess      → Run full pipeline (sync)
```

#### Documents
```
POST   /api/documents/                  → Register upload
POST   /api/documents/{id}/classify     → AI classify
POST   /api/documents/{id}/extract      → AI extract
POST   /api/documents/{id}/verify       → Human verify
GET    /api/documents/                  → List with filters
```

#### Risk
```
GET    /api/risk/{case_id}              → Full risk detail (signals + AI advisory)
```

#### Exceptions
```
GET    /api/exceptions/                 → Queue (filters: severity, type, assignee)
GET    /api/exceptions/summary          → Counts by severity
POST   /api/exceptions/{id}/triage      → AI suggestions (advisory only)
POST   /api/exceptions/{id}/assign      → Assign to reviewer
POST   /api/exceptions/{id}/resolve     → Close with resolution_type + reason
```

#### Approvals
```
GET    /api/approvals/                  → My pending approvals
POST   /api/approvals/{id}/decide       → Approve/reject/escalate
```

#### Audit
```
GET    /api/audit/                      → Timeline (filters: case, actor, type, date)
GET    /api/audit/event-types           → Allowed vocabularies
```

#### Webhooks (n8n callbacks)
```
POST   /api/webhooks/n8n                → Case-scoped orchestration events
POST   /api/webhooks/n8n/incident       → Platform incidents (no case_id required)
GET    /api/webhooks/n8n/event-types    → Allowlist reference (unauthenticated)
```

### 4.2 Assessment Response (from `/assess`)
```json
{
  "case_id": 1,
  "route": "REVIEW_REQUIRED",
  "score_total": 38,
  "score_components": [
    {"rule_code": "RULE-001", "weight": 15, "severity": "medium", "points": 15},
    {"rule_code": "RULE-006", "weight": 15, "severity": "high", "points": 23}
  ],
  "requirements": [
    {"code": "REQ-W9", "name": "Completed W-9", "document_type": "w9", "is_mandatory": true}
  ],
  "ai_advisory": {
    "summary": "Vendor appears legitimate but insurance expiring soon",
    "risk_factors": ["Expiring insurance", "High-risk geography"],
    "recommended_action": "review",
    "confidence": 0.82
  }
}
```

---

## 5. Workflow Orchestration (n8n)

### 5.1 Case Orchestrator Flow
```
1. Trigger: POST /api/onboarding/{id}/assess → n8n webhook
2. Dispatch document extraction for all unprocessed docs
3. Poll extraction status (wait node)
4. Call backend /assess (deterministic + AI)
5. Route based on result.route:
   - AUTO_APPROVE → Create approvals (compliance, finance) → wait for decisions
   - REVIEW_REQUIRED → Create review assignment → notify reviewers
   - ESCALATE → Create escalation approval → notify senior
   - REJECT → Record rejection → notify requester
6. Callback each step via /api/webhooks/n8n
```

### 5.2 Document Intake Flow
```
1. Trigger: Document upload → n8n webhook
2. Call backend /documents/{id}/classify
3. If confidence < 0.75 → route to human verification
4. Call backend /documents/{id}/extract
5. Persist extracted fields
6. Callback /api/webhooks/n8n with DOCUMENT_PROCESSING_DISPATCHED
```

### 5.3 SLA Escalation (Daily Cron)
```
1. Find cases in REVIEW_REQUIRED > 5 business days
2. For each: POST /api/exceptions/ (SLA_BREACH, HIGH)
3. POST /api/webhooks/n8n/incident (SLA_ESCALATED)
4. Notify assigned reviewer + manager
```

### 5.4 Error Handler
```
1. Trigger: Any workflow error
2. Extract workflow, execution_id, node, error message
3. POST /api/webhooks/n8n/incident with event_type=WORKFLOW_FAILED
```

---

## 6. Security Model

### 6.1 Authentication (Prototype)
- **API Keys**: Static list in `API_KEYS` env var → `X-API-Key` header
- **n8n Webhooks**: Shared secret `N8N_API_KEY` → `X-N8N-Secret` header (HMAC compare_digest)
- **No JWT/OAuth** — deliberate prototype choice

### 6.2 Authorization (Role-Based)
| Role | Permissions |
|------|-------------|
| admin | All |
| procurement_analyst | Create vendors, cases, submit, view |
| procurement_manager | All analyst + approve manager-level |
| compliance_reviewer | Approve compliance, resolve exceptions |
| finance_reviewer | Approve finance, banking verification |

### 6.3 AI Safety Constraints (Enforced in Code)
| Constraint | Enforcement |
|------------|-------------|
| Never expose real banking info | Synthetic data only; bank_account_last4 only |
| AI never approves/rejects | `approval_service.py` requires human actor |
| AI never creates irreversible financial actions | No payment APIs exist |
| AI never modifies sensitive records without validation | All mutations through service layer with Pydantic validation |
| Secrets via env only | `.env.example` documents all; no secrets in source |
| Structured reasoning stored | `audit_service.record_ai` stores `analysis` + `output_snapshot` |
| Thresholds not "scientifically optimal" | Configurable via env; labelled prototype defaults |
| Numbers from synthetic dataset only | Evaluation script computes from generated data |

---

## 7. Idempotency Guarantees

| Operation | Idempotency Key | Behavior |
|-----------|-----------------|----------|
| `POST /onboarding/{id}/submit` | case_id + status=DRAFT | 409 if not DRAFT = success |
| `POST /onboarding/{id}/assess` | case_id + assessable status | Re-run closes old findings, creates new |
| `POST /approvals/{id}/decide` | approval_id + status=PENDING | 409 if already decided = success |
| `POST /exceptions/{id}/resolve` | exception_id + open status | 409 if already closed = success |
| Document upload | vendor_id + document_type + filename | Upsert on unique constraint |

**Deterministic reviewer selection**: `case_id % reviewer_count` — same case always routes to same reviewer.

---

## 8. Audit Trail Design

### 8.1 Dual Vocabulary
| Category | Table | case_id | Examples |
|----------|-------|---------|----------|
| **Case Events** | `audit_events` | Required | CASE_CREATED, DOCUMENT_UPLOADED, ASSESSMENT_COMPLETED, APPROVAL_DECIDED |
| **Platform Incidents** | `audit_events` | Optional (NULL) | WORKFLOW_FAILED, INTEGRATION_UNREACHABLE, RETRY_EXHAUSTED, WEBHOOK_REJECTED |

### 8.2 Actor Types
- `USER` — Human action (with user_id, user_name)
- `SYSTEM` — Backend automated (pipeline, cron, rule engine)
- `AI` — Model inference (with model, prompt_version, output_snapshot)
- `N8N` — Orchestration callbacks (with workflow, execution_id)

### 8.3 Query Patterns
- **Per-case timeline**: `WHERE case_id = ? ORDER BY timestamp`
- **Recent platform incidents**: `WHERE case_id IS NULL AND actor_type = 'N8N' ORDER BY timestamp DESC LIMIT 50`
- **User activity**: `WHERE actor_type = 'USER' AND actor_id = ?`

---

## 9. Document Processing Pipeline

### 9.1 Flow
```
Upload → Register (document_service.register)
  → Classify (AI: DocumentExtractionService.classify)
  → Extract (AI: DocumentExtractionService.extract)
  → Normalize (normalization.py)
  → Validate (rules: TaxIdFormatRule, etc.)
  → Persist fields (document_service.persist_fields)
  → Build evidence (document_service.build_evidence)
  → Verify (human: document_service.verify)
```

### 9.2 Confidence-Aware Routing
| Confidence | Route |
|------------|-------|
| ≥ 0.90 (HIGH) | Auto-verify, no human needed |
| 0.75–0.89 (MEDIUM) | Queue for human verification |
| < 0.75 (LOW) | Reject extraction, request re-upload |

### 9.3 Supported Formats
- PDF (text + scanned detection via `pdfplumber` + `pdf2image` + `pytesseract`)
- Plain text
- CSV

---

## 10. Requirement Resolution

### 10.1 Data-Driven Checklist
Requirements are **data**, not code. Each row in `requirements` table has:
- `code` — stable identifier (e.g., `REQ-W9`)
- `vendor_types` — array or null (all)
- `countries` — ISO-2 array or null (all)
- `industries` — array or null (all)
- `risk_levels` — array or null (all)
- `is_mandatory` — boolean
- `validation_rules` — JSON (e.g., `{"require_tin": true}`)

### 10.2 Special Logic (in `_applies`)
- `REQ-W9` → Only for US vendors
- `REQ-TAX-CERT` → Never for US (W-9 covers it)
- All conditions are **opt-in** (null = applies to everyone)

### 10.3 High-Risk Countries (Prototype List)
`RU, BY, IR, KP, SY, CU, VE` — explicitly labelled as prototype, not authoritative

---

## 11. Risk Scoring Algorithm

### 11.1 Additive Model
```
score_total = Σ (rule_weight × severity_multiplier)
```
| Severity | Multiplier |
|----------|------------|
| low | 1.0 |
| medium | 1.5 |
| high | 2.0 |
| critical | 3.0 |

### 11.2 ScoreComponents (Persisted for Explainability)
```json
{
  "rule_code": "RULE-006",
  "rule_name": "High Risk Geography",
  "weight": 15,
  "severity": "high",
  "multiplier": 2.0,
  "points_contributed": 30,
  "evidence": {"country": "RU", "is_high_risk": true}
}
```

### 11.3 Risk Level Thresholds (Configurable)
| Level | Score Range |
|-------|-------------|
| LOW | 0–24 |
| MEDIUM | 25–49 |
| HIGH | 50–74 |
| CRITICAL | 75–100 |

### 11.4 Routing Rules
| Route | Condition |
|-------|-----------|
| AUTO_APPROVE | score ≤ 25 AND no CRITICAL findings |
| REVIEW_REQUIRED | score 26–74 OR any HIGH finding |
| ESCALATE | score ≥ 75 OR any CRITICAL finding |
| REJECT | score ≥ 90 OR critical banking mismatch |

**Severity floor**: A single CRITICAL finding forces minimum `REVIEW_REQUIRED` route.

---

## 12. Exception Handling

### 12.1 Principles
1. **AI never closes** — only suggests (stored under `evidence.triage`)
2. **Resolution recorded, not deleted** — exception stays in history
3. **Override requires justification** — ≥20 chars for risk acceptance

### 12.2 Resolution Types
| Type | Meaning | Required |
|------|---------|----------|
| `resolved` | Problem fixed | Resolution text |
| `override` | Risk accepted | Resolution ≥20 chars |
| `dismissed` | Raised in error | Resolution text |
| `escalated` | Needs higher authority | Resolution text |

### 12.3 AI Triage (Advisory Only)
```
GET /exceptions/{id}/triage → ExceptionTriageService.triage()
Stores in evidence.triage:
  - likely_root_cause
  - resolution_options[]
  - vendor_message_draft
  - reviewer_notes
  - urgency
  - advisory_only: true
```

---

## 13. Configuration (Environment Variables)

All settings in `.env.example` — **no secrets in source code**.

### 13.1 Required
```bash
DATABASE_URL=postgresql://user:pass@host:5432/db
N8N_API_KEY=n8n-api-key          # Shared secret for webhooks
API_KEYS=key1,key2               # Comma-separated API keys
```

### 13.2 AI Provider
```bash
LLM_PROVIDER=mock                # mock | openai
OPENAI_API_KEY=                  # Optional; empty → falls back to mock
OPENAI_MODEL=gpt-4o-mini
```

### 13.3 Risk Weights (Tunable)
```bash
RISK_WEIGHT_MISSING_DOCUMENT=15
RISK_WEIGHT_EXPIRED_DOCUMENT=25
RISK_WEIGHT_BANKING_MISMATCH=30
RISK_WEIGHT_HIGH_RISK_GEOGRAPHY=15
# ... 6 more
```

### 13.4 Rule Thresholds
```bash
RULE_INSURANCE_MIN_COVERAGE=2000000
RULE_VENDOR_NAME_SIMILARITY_THRESHOLD=0.92
RULE_AUTO_APPROVE_MAX_RISK=25
```

---

## 14. Running the System

### 14.1 Prerequisites
- PostgreSQL 14+ (Docker or native)
- Python 3.10+
- Node.js 18+
- n8n (Docker recommended)

### 14.2 Native Run (Recommended — bypasses Docker blockers)
```bash
cd vendor-onboarding-orchestrator

# 1. Start Postgres only
docker compose up postgres -d

# 2. Backend (Terminal 2) — launch from the REPO ROOT, not from backend/.
#    app/config.py resolves ".env" relative to the working directory, so
#    starting inside backend/ silently falls back to Docker hostnames and the
#    API cannot reach Postgres. PYTHONPATH must contain backend/ because the
#    app imports `app.*`.
pip install -r backend/requirements.txt
DATABASE_URL=postgresql://vendoruser:vendorpass@localhost:5432/vendordb \
  PYTHONPATH="$PWD/backend" \
  uvicorn app.main:app --reload --reload-dir "$PWD/backend/app" --port 8000

# 3. Frontend (Terminal 3)
cd frontend
npm install
npm run dev
```

### 14.3 Access Points
| Service | URL |
|---------|-----|
| API (Swagger) | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |
| n8n Canvas | http://localhost:5678 (admin/admin123) |

### 14.4 n8n Workflow Import
1. Start n8n: `docker compose up n8n -d`
2. Import all 4 `.json` files from `n8n/workflows/`
3. Set Error Workflow → "Vendor Onboarding — Error Handler"
4. Activate workflows
5. Set env vars in n8n:
   - `VOR_BACKEND_URL=http://host.docker.internal:8000`
   - `VOR_CALLBACK_SECRET=n8n-api-key`

---

## 15. Known Limitations (Prototype Grade)

| Area | Limitation | Production Fix |
|------|------------|----------------|
| Auth | Static API keys, no rotation | OAuth2/OIDC, short-lived tokens |
| n8n Auth | One shared secret, no replay protection | mTLS or signed requests with nonce/timestamp |
| Mock Services | ERP, Compliance, Notifications don't exist | Implement or integrate real services |
| Seed Data | No automated seed (Task #10) | Run `scripts/seed_demo_data.py` |
| Evaluation | No test suite (static verification only) | Pytest + contract tests |
| Frontend Build | No `package-lock.json`, nginx port mismatch | `npm install` → generates lock; fix Dockerfile |
| Document Storage | Local filesystem path | S3/GCS with presigned URLs |
| Audit Retention | No retention policy | Partition + archive strategy |
| Rate Limiting | None | Redis-backed limiter |
| Observability | JSON logs only | OpenTelemetry + Prometheus/Grafana |

---

## 16. File Map (Key Files)

```
vendor-onboarding-orchestrator/
├── docker-compose.yml              # 6 services (4 blockers documented)
├── .env.example                    # All required env vars
├── RUNBOOK.md                      # This runbook
├── ARCHITECTURE.md                 # This file
├── README.md                       # Project overview
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app
│   │   ├── config.py               # Pydantic Settings
│   │   ├── database.py             # Async SQLAlchemy
│   │   ├── models/__init__.py      # 12 models
│   │   ├── schemas/__init__.py     # Pydantic API contracts
│   │   ├── api/
│   │   │   ├── __init__.py         # 9 routers
│   │   │   ├── vendors.py
│   │   │   ├── onboarding.py
│   │   │   ├── documents.py
│   │   │   ├── risk.py
│   │   │   ├── exceptions.py
│   │   │   ├── approvals.py
│   │   │   ├── audit.py
│   │   │   ├── dashboard.py
│   │   │   └── webhooks.py         # n8n callbacks
│   │   ├── services/
│   │   │   ├── vendor_service.py
│   │   │   ├── onboarding_service.py
│   │   │   ├── document_service.py
│   │   │   ├── document_processing.py
│   │   │   ├── requirement_service.py
│   │   │   ├── pipeline.py
│   │   │   ├── risk_service.py
│   │   │   ├── approval_service.py
│   │   │   ├── exception_service.py
│   │   │   └── audit_service.py
│   │   ├── rules/
│   │   │   ├── types.py
│   │   │   ├── engine.py           # 12 rules
│   │   │   └── risk_scoring.py
│   │   ├── ai/
│   │   │   ├── provider.py
│   │   │   ├── schemas.py
│   │   │   ├── extraction.py
│   │   │   ├── analysis.py
│   │   │   └── guardrails.py
│   │   ├── utils/
│   │   │   ├── normalization.py
│   │   │   └── logging.py
│   │   └── prompts/                # System prompts
│   ├── scripts/
│   │   └── seed_demo_data.py       # Task #10 (to create)
│   ├── requirements.txt
│   └── check_static.py             # Static verification
├── frontend/
│   ├── src/
│   │   ├── pages/                  # 8 pages
│   │   ├── components/             # Reusable UI
│   │   ├── utils/api.ts            # Typed Axios client
│   │   └── App.tsx
│   ├── vite.config.ts              # Proxy to :8000
│   └── package.json
├── n8n/
│   ├── workflows/                  # 4 generated JSONs
│   └── build_workflows.py          # Generator script
├── tools/
│   └── check_contracts.py          # Frontend↔Backend type sync
└── docs/                           # Task #12 outputs
    ├── decisions.md
    ├── architecture.md
    ├── data-model.md
    └── workflow.md
```

---

## 17. Verification & Quality Gates

### 17.1 Backend Static Verification (`backend/check_static.py`)
5 AST-based passes (no pytest/tsc needed):
1. **Import hygiene** — no unused, no cycles, stdlib first
2. **Route coverage** — every router has ≥1 handler
3. **Pydantic v2** — no v1 patterns (`Config` class, `schema_extra`)
4. **SQLAlchemy 2.0** — `select()` not `query()`, async session
5. **Error handling** — no bare `except:`, HTTPException used

Run: `cd backend && python check_static.py`

### 17.2 Frontend Static Verification (`tools/check_contracts.py`)
Catches 4 bug classes:
1. **API response shape mismatch** — frontend expects field, backend doesn't return
2. **Enum drift** — frontend enum value not in backend enum
3. **Missing required fields** — backend requires, frontend doesn't send
4. **Type narrowing gaps** — discriminated unions not exhaustive

Run: `python tools/check_contracts.py`

### 17.3 Contract Sync Invariant
> **Frontend types must match backend schemas exactly.**
> The checker makes this executable — run it before every commit.

---

## 18. Portfolio Deliverables (Task #12)

| Document | Purpose |
|----------|---------|
| `decisions.md` | Architectural decision records (ADRs) with rationale |
| `architecture.md` | This file — system architecture |
| `data-model.md` | ERD + table descriptions + indexes |
| `workflow.md` | n8n workflow documentation + diagrams |
| `project_spec.json` | Machine-readable spec (models, APIs, workflows, config) |

---

## 19. Next Steps (Roadmap)

| Priority | Task | Description |
|----------|------|-------------|
| **P0** | Seed Script | `backend/scripts/seed_demo_data.py` — 20 vendors, 6 scenarios, synthetic docs |
| **P0** | Evaluation | 50 synthetic cases → real metrics (precision/recall/F1 per rule) |
| **P1** | Docs Package | ADRs, ERD, workflow diagrams, project_spec.json |
| **P1** | Mock Services | ERP, Compliance, Notifications for full integration demo |
| **P2** | Frontend Build Fix | package-lock.json, nginx config, Dockerfile |
| **P2** | Rate Limiting | Redis-backed per-API-key limits |
| **P3** | Observability | OpenTelemetry, structured logging correlation |

---

## 20. Quick Start Checklist

- [ ] Copy `.env.example` → `.env`
- [ ] Start Postgres: `docker compose up postgres -d`
- [ ] Install backend deps: `cd backend && pip install -r requirements.txt`
- [ ] Run backend: `DATABASE_URL=... uvicorn app.main:app --reload --port 8000`
- [ ] Install frontend: `cd ../frontend && npm install`
- [ ] Run frontend: `npm run dev`
- [ ] Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`
- [ ] Open Swagger: http://localhost:8000/docs
- [ ] Create vendor + case + submit + assess (see RUNBOOK.md)
- [ ] (Optional) Start n8n + import workflows

---

*This document reflects the codebase as of 2026-09-19. Update when architecture changes.*