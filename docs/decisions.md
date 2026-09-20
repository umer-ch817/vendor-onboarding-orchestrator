# Architecture Decision Records — Vendor Onboarding & Risk Orchestrator

*Every non-obvious design choice, why it was made, and what would change it.*

---

## ADR-001: n8n as Pure Orchestration Layer (No Business Logic)

**Date:** 2026-01-15  
**Status:** Accepted  
**Context:** The project brief explicitly splits "orchestration" (n8n) from "business logic" (Python/FastAPI).

**Decision:** n8n workflows do **not** contain business logic. They only:
- Trigger backend endpoints via HTTP
- Handle retries, scheduling, routing
- Send notifications (email, Slack, webhook)
- Record platform incidents via `/api/webhooks/n8n/incident`
- Record case-scoped events via `/api/webhooks/n8n`

**Rationale:**
- Business logic in workflows is invisible to static analysis, type-checking, and unit tests
- Version-controlling JSON workflows is painful; Python code is reviewable, testable, refactorable
- The backend owns the authoritative state machine; n8n is a reliable delivery mechanism
- This boundary is the single most important architectural constraint in the project

**Consequences:**
- All risk scoring, rule evaluation, document classification, approval logic lives in `backend/app/services/`
- n8n workflows are generated from `n8n/build_workflows.py` — the source of truth is Python
- Adding a new orchestration step = add a Python function + generate workflow JSON

**Revisit if:** n8n adds a first-class TypeScript/Python SDK with type-safe node definitions and local testing.

---

## ADR-002: Deterministic Rule Engine + Additive Risk Scoring

**Date:** 2026-01-15  
**Status:** Accepted

**Decision:** Risk scoring uses a two-stage pipeline:
1. **RuleEngine** — 12 deterministic rules → `RuleFinding` (pass/warn/fail + evidence)
2. **RiskScoringService** — maps findings to `ScoreComponent` (additive points) → `RiskScoreResult` (total + route)

**Rationale:**
- Explainability: every point has a `rule_id`, `description`, `evidence` — auditable, defensible
- Testability: rules are pure functions; scoring is a pure reduction
- No "black box" ML model that stakeholders can't interrogate
- Severity floor: any CRITICAL finding forces minimum `REVIEW_REQUIRED` route (prevents auto-approve on expired insurance bug)

**Consequences:**
- Adding a risk factor = add a rule + a score component weight
- Thresholds (`AUTO_APPROVE ≤ 25`, `REVIEW_REQUIRED ≤ 60`, `APPROVAL_REQUIRED ≤ 85`) are explicit config, not learned
- AI layer provides *advisory* signals only; cannot change route directly

**Revisit if:** Regulatory requirement demands ML-based scoring with model cards / SHAP explanations.

---

## ADR-003: AI Guardrails — Structured Outputs + Repair Pattern

**Date:** 2026-01-15  
**Status:** Accepted

**Decision:** All LLM calls go through `call_with_validation(schema, prompt, context, max_retries=2)`:
- **Attempt 1:** Call provider with structured output schema (Pydantic v2)
- **Attempt 2 (repair):** If validation fails, re-prompt with error details + schema
- **Attempt 3 (exception):** If repair fails, raise `LLMValidationError` — caller handles fallback

**Providers:**
- `MockProvider` — deterministic, keyless, returns synthetic but schema-valid responses (default)
- `OpenAIProvider` — calls OpenAI API; falls back to MockProvider if no key / error

**Rationale:**
- LLMs hallucinate fields, miss required keys, return wrong types — validation catches this
- One repair attempt fixes ~80% of schema violations in practice
- Exception on final failure forces explicit handling (no silent garbage data)
- MockProvider enables keyless CI, deterministic demos, reproducible evals

**Consequences:**
- Every AI call site declares its output schema (Pydantic model)
- No raw JSON parsing; no `json.loads(llm_output)` anywhere
- Token usage, latency, model name recorded in audit metadata (never chain-of-thought)

**Revisit if:** OpenAI adds native structured output guarantees (beta as of 2025) — then repair loop may shrink.

---

## ADR-004: Idempotency via Database Constraints + Idempotency Keys

**Date:** 2026-01-20  
**Status:** Accepted

**Decision:** Idempotency at two levels:
1. **Case submission:** `POST /onboarding/{id}/submit` returns 409 if case not in DRAFT — re-submit = success
2. **Exception/Signal sync:** `OnboardingPipeline` uses `INSERT ... ON CONFLICT DO UPDATE` with composite unique keys:
   - `RiskSignal`: `(case_id, signal_type, vendor_id)`
   - `Exception`: `(case_id, type, vendor_id)`

**Rationale:**
- n8n retries webhooks; backend must be safe to re-run
- "409 on submit = success" is the contract the workflow generator encodes
- Composite keys model business reality: same signal type for same case+vendor = update, not duplicate

**Consequences:**
- `OnboardingPipeline.run(case_id)` is safe to call repeatedly
- Seed script can run multiple times without duplicate data
- Workflow retries don't create duplicate exceptions/signals

**Revisit if:** Distributed idempotency needed (e.g., multiple backend replicas) — add Redis idempotency key store.

---

## ADR-005: Audit Trail — Case-Scoped Events + Platform Incidents

**Date:** 2026-01-22  
**Status:** Accepted

**Decision:** Two separate audit vocabularies:
- **Case-scoped events** (`AuditEvent.case_id` NOT NULL): 25 event types in `ALLOWED_EVENT_TYPES` — appear in case timeline
- **Platform incidents** (`AuditEvent.case_id` NULL): 4 event types in `INCIDENT_EVENT_TYPES` — appear in global "recent events" only

**Rationale:**
- A container crash or malformed webhook has no case_id — forcing one would invent data or drop the failure
- Reviewers of vendor #47 should not scroll past "n8n container restarted"
- Closed allowlist on inbound webhook prevents workflow from writing arbitrary strings into audit trail

**Consequences:**
- `/api/webhooks/n8n` only accepts `event_type` from `ALLOWED_EVENT_TYPES`
- `/api/webhooks/n8n/incident` accepts `WorkflowIncident` (case_id optional)
- Frontend has two views: "Case Timeline" (scoped) and "Platform Events" (unscoped)

**Revisit if:** Multi-tenant deployment needs tenant-scoped platform incidents.

---

## ADR-006: Requirement Resolution — Applicability Conditions

**Date:** 2026-01-25  
**Status:** Accepted

**Decision:** Document requirements resolved by `RequirementService.resolve(case)` using `RequirementSpec` with applicability conditions:
- `vendor_types`: list of vendor types this applies to
- `countries`: list of ISO country codes
- `industries`: list of industry codes
- `risk_levels`: list of risk levels (e.g., HIGH_RISK_GEOGRAPHY → requires tax_cert)

**Rationale:**
- "One size fits all" requirements create noise (W-9 for non-US vendors)
- Conditions are data, not code — new requirement = insert row, not deploy
- `DEFAULT_REQUIREMENTS` catalogue covers 7 base document types with conditions

**Consequences:**
- `/api/onboarding/{id}/requirements` returns only applicable requirements
- Document intake UI shows "required" badges only for applicable types
- Rule engine checks missing mandatory docs against resolved set, not full catalogue

**Revisit if:** Requirement logic needs complex expressions (AND/OR/NOT) — move to a rule engine.

---

## ADR-007: Exception Queue — AI Triage Advisory Only, Human Closure Mandatory

**Date:** 2026-01-28  
**Status:** Accepted

**Decision:** `ExceptionService` supports AI triage (`triage_exception`) that returns:
- Suggested priority
- Suggested resolution type
- Reasoning (stored in `ai_triage_reasoning` column)

**But:** Only humans can call `resolve()` / `escalate()` / `dismiss()`. AI cannot close exceptions.

**Rationale:**
- Exceptions represent business risk decisions — accountability requires a human
- AI triage reduces mean-time-to-first-look; human makes the call
- `resolution_type` enum: `resolved` (fixed), `override` (accepted risk), `dismissed` (false positive), `escalated` (needs higher authority)

**Consequences:**
- Exception list shows AI triage badge but decision buttons are human-only
- Audit trail records `actor_type=AI` for triage, `actor_type=USER` for resolution
- Separation of duties: triage ≠ closure

**Revisit if:** Regulatory sandbox approves auto-dismissal of specific false-positive classes with 99.9% precision.

---

## ADR-008: Approval Workflow — Role-Based Authority + Separation of Duties

**Date:** 2026-02-01  
**Status:** Accepted

**Decision:** `ApprovalService` enforces:
- **Role authority map:** manager → compliance → finance → legal (escalating)
- **Separation of duties:** Requester cannot approve their own case
- **No approval over unresolved blockers:** `request()` fails if case has open CRITICAL exceptions
- **Deterministic reviewer selection:** `reviewer_id = hash(case_id) % reviewer_count` for role — consistent, auditable

**Rationale:**
- Prevents "rubber stamp" approvals by same person
- Blockers gate ensures risk is addressed before sign-off
- Deterministic assignment = reproducible, no "reviewer shopping"

**Consequences:**
- `POST /api/approvals/{id}/decide` checks all guards before recording decision
- Audit event captures `actor_role`, `separation_of_duties_checked`, `blockers_cleared`

**Revisit if:** Delegation / vacation coverage needed — add `delegation_to` on User model.

---

## ADR-009: Frontend/Backend Contract Sync — Generated Types + Static Checker

**Date:** 2026-02-05  
**Status:** Accepted

**Decision:** Two mechanisms prevent drift:
1. **Pydantic → TypeScript generation** (manual for now, scriptable): `tools/check_contracts.py` parses both sides
2. **Static checker** (`tools/check_contracts.py`) catches 4 bug classes:
   - Field name mismatch (camelCase vs snake_case)
   - Missing fields in frontend interface
   - Type incompatibility (string vs number, optional vs required)
   - Enum value drift

**Rationale:**
- "Keep in sync" is not a process — it's a check that fails CI
- Frontend consumes 58 backend models; manual sync is error-prone
- No `openapi-typescript-codegen` in sandbox — built our own lightweight checker

**Consequences:**
- Every backend schema change = run `python tools/check_contracts.py` before commit
- Frontend `src/types/api.ts` is the single source of truth for TS side
- Checker runs in <500ms — fast enough for pre-commit hook

**Revisit if:** Project adopts OpenAPI 3.1 + `openapi-typescript` — then generation replaces checking.

---

## ADR-010: Static Verification Substitutes for pytest/tsc

**Date:** 2026-02-10  
**Status:** Accepted

**Decision:** No package registry access → no pytest, no tsc. Instead:
- `backend/check_static.py` — 5-pass AST verification:
  1. Syntax errors
  2. Import resolution (internal modules only)
  3. Route duplication + shadowing (literal path after param path)
  4. SQLAlchemy reserved names on mapped classes
  5. ORM attribute references (catches `Vendor.risk_leval` typos)
- `frontend/check_static.py` — AST check for React: unused imports, missing dependencies, hook rules
- `tools/check_contracts.py` — frontend/backend type sync

**Rationale:**
- Sandbox has no PyPI/npm — cannot install test runners
- Static checks catch the bugs that *actually* shipped (route shadowing, ORM typos, contract drift)
- Runs in seconds, no dependencies, no flakiness

**Consequences:**
- `python backend/check_static.py` and `python tools/check_contracts.py` are the "test suite"
- CI would run these; they exit non-zero on errors
- Not a replacement for runtime tests — a supplement for the constrained environment

**Revisit if:** Package registry access restored — add pytest + tsc + playwright.

---

## ADR-011: Security Constraints — Explicit, Verbatim, Non-Negotiable

**Date:** 2026-02-15  
**Status:** Accepted

**Decision:** The following constraints are **requirements**, not guidelines. They appear in the project brief and must persist verbatim in all docs:

1. **Never expose realistic personal banking information** — use synthetic data only
2. **Store structured reasoning/evidence summaries** — never hidden chain-of-thought
3. **LLM cannot directly approve/reject vendors** or create irreversible financial actions
4. **Secrets via environment variables only** — no `.env` in repo, no hardcoded keys
5. **Don't claim thresholds are scientifically optimal** — they're prototype config
6. **Numbers must be calculated from synthetic evaluation dataset** — no made-up metrics
7. **Clearly label as "Demo Dataset" or "Prototype Metrics"** — everywhere
8. **Distinguish prototype security from production security** — document the gap

**Rationale:**
- This is a portfolio piece — credibility depends on honesty about prototype limitations
- Synthetic data avoids PII/compliance issues in public repos
- Explicit labeling prevents misuse of demo numbers in real decisions

**Consequences:**
- Seed script generates obviously fake names (`.example` domains, synthetic tax IDs)
- Swagger UI shows "Demo Dataset" badges
- `ARCHITECTURE.md` has "Security Model" section documenting prototype vs production gap
- No production deployment instructions — only "run the demo"

**Revisit if:** Never — these are portfolio integrity constraints.

---

## ADR-012: MockProvider Default — Keyless Demo by Default

**Date:** 2026-02-20  
**Status:** Accepted

**Decision:** `LLM_PROVIDER=mock` is the default in `.env.example` and `config.py`. OpenAI requires explicit opt-in + API key.

**Rationale:**
- Portfolio reviewers may not have OpenAI keys
- MockProvider returns deterministic, schema-valid responses — demo works offline
- Zero-cost, zero-friction evaluation

**Consequences:**
- `docker compose up` works without any API keys
- AI signals in Risk Review show "MockProvider" badge
- Switching to OpenAI = set `LLM_PROVIDER=openai` + `OPENAI_API_KEY`

**Revisit if:** OpenAI adds a free tier with generous limits — then default could change.

---

## ADR-013: Database — Async SQLAlchemy 2.0 + asyncpg

**Date:** 2026-01-15  
**Status:** Accepted

**Decision:** `backend/app/database/__init__.py` uses:
- `create_async_engine` with `asyncpg` driver
- `async_session_maker` for dependency injection
- Declarative models with `Mapped` / `mapped_column` (SQLAlchemy 2.0 style)

**Rationale:**
- Async I/O for concurrent request handling (FastAPI native)
- SQLAlchemy 2.0 is current major version; 1.4 is legacy
- `asyncpg` is the fastest Postgres driver for Python

**Consequences:**
- All DB calls are `await session.execute(...)`
- Models use `Mapped[str] = mapped_column(...)` not `Column(...)`
- Migrations via Alembic (not yet added — `create_all` for demo)

**Revisit if:** Project scales to need connection pooling tuning / read replicas.

---

## ADR-014: Document Processing Pipeline — Register → Classify → Extract → Persist → Evidence

**Date:** 2026-02-25  
**Status:** Accepted

**Decision:** `DocumentService` orchestrates:
1. `register_document()` — stores blob, creates `Document` row (PENDING)
2. `classify_document()` — deterministic classifier (filename + content heuristics) → `DocumentType`
3. `extract_fields()` — AI extraction with `DocumentExtractionResult` schema
4. `persist_extracted_fields()` — creates `ExtractedField` rows with confidence
5. `build_evidence_summary()` — concatenates field values for rule engine context

**Rationale:**
- Explicit stages = observable, retryable, auditable
- Classification is deterministic (no LLM) — rules: filename keywords, then content regex
- Extraction uses AI guardrails (ADR-003)
- Evidence summary feeds rule engine (no raw blobs in rules)

**Consequences:**
- `Document.status` tracks pipeline stage
- `extraction_confidence` aggregates field confidences
- Failed extraction → status=FAILED, exception auto-created

**Revisit if:** OCR needed for scanned PDFs — add Tesseract / cloud OCR step before extraction.

---

## ADR-015: Project Spec — Machine-Readable Package

**Date:** 2026-03-01  
**Status:** Accepted

**Decision:** `project_spec.json` contains:
- All API endpoints (method, path, request/response schemas)
- All database models (tables, columns, relationships)
- All enums with values
- All workflow definitions (n8n JSON + node descriptions)
- Configuration schema (env vars, defaults, descriptions)
- Evaluation dataset schema + metrics definitions

**Rationale:**
- Portfolio reviewers can ingest spec programmatically
- Enables automated client generation, API docs, schema validation
- Single source of truth for "what does this system do?"

**Consequences:**
- `project_spec.json` generated by script (not hand-written)
- Updated whenever backend schemas or n8n workflows change
- Versioned alongside code

**Revisit if:** OpenAPI 3.1 spec covers everything — then `project_spec.json` = transformed OpenAPI.

---

*End of Architecture Decision Records. Total: 15 ADRs.*