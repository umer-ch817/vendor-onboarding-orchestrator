# Vendor Onboarding & Risk Orchestrator

A production-style AI automation system for intelligent vendor onboarding, document processing, and risk management.

## Problem

Companies struggle with fragmented vendor onboarding processes. Information arrives through multiple channels—registration forms, emails, uploaded documents, W-9s, certificates, contracts—requiring manual extraction, validation, cross-document consistency checks, and risk assessment. This creates bottlenecks, inconsistencies, and compliance gaps.

## Solution

An intelligent orchestration system that combines deterministic business rules, AI-powered document extraction, structured validation, risk scoring, and human-in-the-loop workflows to transform vendor onboarding from a manual process into a controlled, auditable, semi-automated workflow.

**Key principle:** Automate the operational work while keeping humans in control of consequential decisions.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         VENDOR SUBMISSION                        │
│                    (Form / Email / Portal Upload)                │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                          FRONTEND (React)                        │
│  Dashboard | Vendor Cases | Document Review | Risk Analysis    │
│  Exceptions | Approvals | Audit Timeline | Metrics              │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    n8n WORKFLOW ORCHESTRATION                    │
│  Webhooks | API Routing | State Transitions | Notifications    │
│  Retries | Human-in-Loop Routing | Error Handling               │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PYTHON BACKEND (FastAPI)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Document   │  │    Rules     │  │    Risk      │          │
│  │  Processing  │  │    Engine    │  │   Engine     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │     AI       │  │   Validation │  │   Audit      │          │
│  │   Services   │  │    Layer     │  │   System     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
        ┌──────────────────┐      ┌──────────────────┐
        │   PostgreSQL     │      │   LLM Provider   │
        │   (Data Store)   │      │   (OpenAI/etc)   │
        └──────────────────┘      └──────────────────┘
                                 │
                                 ▼
        ┌─────────────────────────────────────────────────────────┐
        │                    EXTERNAL SYSTEMS                      │
        │  Mock ERP | Mock Compliance Service | Notifications     │
        └─────────────────────────────────────────────────────────┘
```

**System Boundaries:**

- **AI Components:** Document extraction, classification, risk analysis, reasoning
- **Deterministic Components:** Rules engine, validation, risk scoring, state transitions
- **Human Actions:** Review, approval, exception resolution, override
- **Orchestration:** n8n handles workflow state, routing, and external integrations

## Workflow

```
Vendor Submission
       ↓
  Case Creation
       ↓
Document Collection
       ↓
 Document Extraction  ─────→ AI Service (Structured Output)
       ↓
 Data Normalization
       ↓
Requirement Validation  ───→ Rules Engine
       ↓
Cross-Document Checks
       ↓
 Vendor Risk Analysis  ─────→ AI + Deterministic Scoring
       ↓
   Risk Scoring
       ↓
  Decision Routing
       ↓
  ┌────┴────┐
  │         │
Low Risk  Medium/High Risk
  │         │
  ↓         ↓
Auto      Human Review Queue
Approve        │
  │            ↓
  │      Resolve Exceptions
  │            │
  │            ↓
  │       Approve/Reject
  │            │
  └────────────┤
               ↓
    Vendor Record Created
               ↓
    Onboarding Complete
               ↓
       Audit Trail Updated
```

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React, TypeScript, Vite, Tailwind CSS | Enterprise dashboard UI |
| Backend | Python, FastAPI, Pydantic | API layer, business logic |
| Database | PostgreSQL | Persistent storage |
| Workflow | n8n | Orchestration, routing |
| AI | OpenAI API (provider abstraction) | Document extraction, analysis |
| Documents | PyPDF2, python-docx | PDF/document processing |
| Containerization | Docker, Docker Compose | Local deployment |

## AI Components

### Document Extraction Service
- Extracts structured fields from W-9, insurance certificates, business registrations, banking documents
- Returns confidence scores for each field
- Schema-validated JSON output

### Risk Analysis Service
- Analyzes vendor documents for risk signals
- Identifies inconsistencies across documents
- Provides evidence-backed reasoning

### Document Classification
- Automatically identifies document types
- Routes to appropriate extraction pipelines

**Guardrails:**
- Structured outputs with Pydantic validation
- Confidence thresholds with fallback to human review
- Retry logic for invalid outputs
- No direct approval authority—AI recommends only

## Deterministic Components

### Rules Engine
- Document requirement validation
- Expiration checks
- Cross-document consistency validation
- Configurable thresholds

### Risk Scoring
- Formula-based scoring (not LLM-generated)
- Transparent factor weights
- Configurable thresholds

### Validation Layer
- Field format validation
- Business rule validation
- State transition validation

## Human-in-the-Loop

Every consequential decision requires human approval:

- **Review Queue:** Documents with low confidence or detected issues
- **Approval Queue:** All vendors require human approval before ERP creation
- **Exception Queue:** Mismatches, missing documents, policy violations
- **Override Capability:** Reviewers can correct AI findings

All human actions are fully audited.

## Risk Model

**Scoring Formula:**
```
risk_score = Σ(factor_weight × factor_value)

Factors:
- Missing documents: +15 per required document
- Expired documents: +25 per expired document
- Document mismatches: +20 per mismatch
- Banking inconsistencies: +30
- High-risk geography: +15
- Low extraction confidence: +10 per low-confidence field
- Incomplete ownership info: +15
```

**Risk Levels:**
| Score Range | Level | Routing |
|-------------|-------|---------|
| 0-25 | LOW | Standard review |
| 26-50 | MEDIUM | Compliance review |
| 51-75 | HIGH | Senior review required |
| 76+ | CRITICAL | Escalation + dual approval |

## Exception Handling

| Exception Type | Severity | Auto-Resolution |
|----------------|----------|-----------------|
| MISSING_DOCUMENT | HIGH | No - requires upload |
| DOCUMENT_EXPIRED | MEDIUM | No - requires renewal |
| ENTITY_NAME_MISMATCH | HIGH | No - requires review |
| LOW_CONFIDENCE_EXTRACTION | LOW | No - requires verification |
| BANKING_MISMATCH | HIGH | No - requires verification |

## Evaluation

The system includes an evaluation framework with 50 synthetic test cases:

- Field extraction accuracy
- Document classification accuracy
- Mismatch detection precision/recall
- Routing decision accuracy

See `evaluation/` directory for results and methodology.

## Demo Scenarios

The system includes 20 synthetic vendors demonstrating various edge cases:

1. **Clean Vendor** - Straight-through processing
2. **Missing Document** - Exception handling
3. **Document Mismatch** - Cross-document validation
4. **Expired Document** - Expiration detection
5. **Low Confidence Extraction** - Human review routing
6. **Normalized Equivalence** - False positive prevention

## Running Locally

```bash
# Clone the repository
git clone <repository-url>
cd vendor-onboarding-orchestrator

# Copy environment variables
cp .env.example .env

# One command: infrastructure + backend + frontend (+ --seed for demo data)
./scripts/start-dev.sh --seed
```

**Requirements:** Docker, Node 18+, and **Python 3.12**. The pinned
dependencies (`pydantic 2.5.3`, `fastapi 0.109`) publish no wheels for 3.13 or
3.14, so a 3.13+ venv cannot install them.

| URL | What it is |
|-----|------------|
| http://localhost:5173 | Frontend dashboard |
| http://localhost:8000 | Backend API |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:5678 | n8n — create the owner account on first open |

### Manual start (if you prefer separate terminals)

Docker runs Postgres, the mock ERP/compliance services and n8n. The backend and
frontend run natively so that hot-reload works:

```bash
# 1. Infrastructure
docker compose up -d

# 2. Backend — MUST be launched from the repo root, because app/config.py
#    resolves ".env" relative to the working directory.
python3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
PYTHONPATH="$PWD/backend" backend/.venv/Scripts/python.exe \
  -m uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd frontend && npm install && npm run dev

# 4. Demo data (truncates first; the seed is not idempotent)
PYTHONPATH="$PWD/backend" \
  DATABASE_URL="postgresql://vendoruser:vendorpass@localhost:5432/vendordb" \
  LLM_PROVIDER=mock \
  backend/.venv/Scripts/python.exe backend/scripts/seed_demo_data.py
```

## Environment Variables

Because the backend and frontend run natively, every host below is
`localhost` — the Docker service names (`postgres`, `mock-erp`, `n8n`) only
resolve from inside the compose network.

```env
# Database
DATABASE_URL=postgresql://vendoruser:vendorpass@localhost:5432/vendordb

# AI Provider — "mock" is deterministic and needs no key
LLM_PROVIDER=mock
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# Security
SECRET_KEY=your-secret-key-here
API_KEY_HEADER=X-API-Key

# n8n
N8N_WEBHOOK_URL=http://localhost:5678
N8N_API_KEY=n8n-api-key

# Mock Services
ERP_API_URL=http://localhost:8001
COMPLIANCE_API_URL=http://localhost:8002

# Document storage — writable path for the native run
DOCUMENT_STORAGE_PATH=./documents/uploads
```

## Project Structure

```
vendor-onboarding-orchestrator/
├── README.md
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/              # API routes
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── services/         # Business logic
│   │   ├── rules/            # Rules engine
│   │   ├── ai/               # AI services
│   │   ├── database/         # DB configuration
│   │   └── utils/            # Utilities
│   ├── scripts/              # seed_demo_data.py, run_evaluation.py
│   ├── prompts/              # Prompt templates
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/       # Reusable UI components
│   │   ├── pages/            # Page components
│   │   ├── features/         # Feature modules
│   │   ├── services/         # API clients
│   │   └── types/            # TypeScript types
│   └── package.json
│
├── n8n/
│   └── workflows/            # n8n workflow JSON files
│
├── documents/
│   ├── demo/                 # Synthetic demo documents
│   └── evaluation/           # Test fixtures
│
├── evaluation/
│   ├── dataset.json          # Evaluation test cases
│   ├── results.json          # Evaluation results
│   └── run_evaluation.py     # Evaluation script
│
├── scripts/
│   └── start-dev.sh          # One-command local startup
│
└── docs/
    ├── architecture.md       # Detailed architecture
    ├── workflow.md           # Workflow documentation
    ├── data-model.md         # Database schema docs
    └── decisions.md          # Engineering decisions
```

## Engineering Decisions

See `docs/decisions.md` for detailed rationale on:
- Why n8n for orchestration vs. pure Python
- Why deterministic risk scoring vs. LLM-based
- Why PostgreSQL vs. NoSQL
- Why human review is mandatory
- Confidence threshold selection
- Provider abstraction design

## Limitations

This is a **portfolio prototype**, not production software:

- Authentication is simplified (API key-based)
- Mock external services instead of real integrations
- Single-node deployment (not distributed)
- No encryption at rest for uploaded documents
- Basic error handling (not comprehensive)
- Synthetic test data only

**Do not deploy to production without proper security review, scalability planning, and compliance verification.**

## Future Improvements

- Real ERP integration (SAP, Oracle, NetSuite)
- Enhanced document OCR for scanned documents
- Duplicate vendor detection
- Vendor portal for self-service document submission
- Advanced analytics and reporting
- Multi-tenant support
- Real-time collaboration features
- Mobile-responsive review interface
- Integration with actual compliance databases
- Automated renewal tracking

## Screenshots

See `docs/screenshots/` for portfolio-ready images of:
- Main dashboard
- Vendor case detail
- Document extraction interface
- Risk analysis view
- Exception queue
- Approval workflow
- Audit timeline

---

**Built as a portfolio demonstration of AI automation engineering capabilities.**

This project showcases:
- Complex workflow orchestration
- AI integration with proper guardrails
- Human-in-the-loop system design
- Production-style architecture
- Deterministic + AI hybrid approach
- Comprehensive auditability
- Realistic business workflow automation
