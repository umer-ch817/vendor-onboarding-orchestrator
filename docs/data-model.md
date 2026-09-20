# Data Model — Vendor Onboarding & Risk Orchestrator

*Complete database schema, relationships, and data flow documentation.*

---

## Entity Relationship Diagram

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────────┐
│    User     │       │    Onboarding    │       │    Vendor       │
├─────────────┤       │      Case        │       ├─────────────────┤
│ id (PK)     │◄──────│ id (PK)          │──────▶│ id (PK)         │
│ email       │       │ case_number (UK) │       │ legal_name      │
│ name        │       │ vendor_id (FK)   │       │ trade_name      │
│ role        │       │ requester_id(FK) │       │ vendor_type     │
│ department  │       │ workflow_status  │       │ industry        │
│ is_active   │       │ risk_score       │       │ tax_id          │
│ created_at  │       │ risk_level       │       │ country         │
│ updated_at  │       │ completion_pct   │       │ status          │
└─────────────┘       │ documents_recvd  │       │ risk_score      │
                      │ documents_reqd   │       │ risk_level      │
                      │ created_at       │       │ created_at      │
                      │ updated_at       │       │ updated_at      │
                      └────────┬─────────┘       └────────┬────────┘
                               │                          │
              ┌────────────────┼────────────────┐         │
              ▼                ▼                ▼         ▼
       ┌────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐
       │  Document  │ │ RiskSignal   │ │  Exception   │ │ Approval │
       ├────────────┤ ├──────────────┤ ├──────────────┤ ├──────────┤
       │ id (PK)    │ │ id (PK)      │ │ id (PK)      │ │ id (PK)  │
       │ vendor_id  │ │ vendor_id    │ │ case_id (FK) │ │ case_id  │
       │ case_id    │ │ case_id (FK) │ │ type         │ │ type     │
       │ doc_type   │ │ signal_type  │ │ severity     │ │ status   │
       │ status     │ │ severity     │ │ title        │ │ reviewer │
       │ filename   │ │ description  │ │ description  │ │ decision │
       │ file_path  │ │ evidence     │ │ evidence     │ │ comments │
       │ extracted_ │ │ status       │ │ status       │ │ decided_ │
       │  _confidence│ │ detected_at  │ │ resolution   │ │ at       │
       │ created_at │ │ resolved_at  │ │ type         │ └──────────┘
       └─────┬──────┘ └──────────────┘ └──────────────┘
             │
             ▼
      ┌──────────────┐
      │ExtractedField│
      ├──────────────┤
      │ id (PK)      │
      │ document_id  │
      │ field_name   │
      │ field_value  │
      │ normalized   │
      │ confidence   │
      │ is_valid     │
      │ manually_corr│
      └──────────────┘

┌─────────────┐       ┌──────────────────┐       ┌─────────────────┐
│AuditEvent   │       │  RiskAssessment  │       │  Requirement    │
├─────────────┤       ├──────────────────┤       ├─────────────────┤
│ id (PK)     │       │ id (PK)          │       │ id (PK)         │
│ case_id     │       │ case_id (FK)     │       │ code (UK)       │
│ actor_type  │       │ overall_score    │       │ name            │
│ actor_id    │       │ risk_level       │       │ description     │
│ actor_name  │       │ confidence       │       │ doc_type        │
│ event_type  │       │ reasoning        │       │ is_mandatory    │
│ description │       │ risk_factors     │       │ vendor_types    │
│ input_snap  │       │ recommended_act  │       │ countries       │
│ output_snap │       │ ai_model         │       │ industries      │
│ metadata    │       │ created_at       │       │ risk_levels     │
│ timestamp   │       └──────────────────┘       │ is_active       │
└─────────────┘                                  └─────────────────┘
```

---

## Table Definitions

### 1. User
**Purpose:** Internal reviewers and system actors.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | Primary key |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL | Login / notification email |
| `name` | VARCHAR(255) | NOT NULL | Display name |
| `role` | VARCHAR(50) | NOT NULL, DEFAULT 'procurement_analyst' | Enum: `admin`, `procurement_analyst`, `procurement_manager`, `compliance_reviewer`, `finance_reviewer` |
| `department` | VARCHAR(100) | NULLABLE | Org unit |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | Soft delete |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |
| `updated_at` | TIMESTAMP | NULLABLE | |

**Indexes:** `ix_user_email` (unique), `ix_user_role`

---

### 2. Vendor
**Purpose:** External party being onboarded. Core entity.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `legal_name` | VARCHAR(255) | NOT NULL | Legal entity name |
| `trade_name` | VARCHAR(255) | NULLABLE | DBA name |
| `vendor_type` | VARCHAR(50) | NULLABLE | supplier, contractor, consultant, service_provider |
| `industry` | VARCHAR(100) | NULLABLE | Industry classification |
| `tax_id` | VARCHAR(50) | NULLABLE | EIN/VAT/BN |
| `website` | VARCHAR(255) | NULLABLE | |
| `contact_name` | VARCHAR(255) | NULLABLE | |
| `contact_email` | VARCHAR(255) | NULLABLE | |
| `contact_phone` | VARCHAR(50) | NULLABLE | |
| `address_line1` | VARCHAR(255) | NULLABLE | |
| `address_line2` | VARCHAR(255) | NULLABLE | |
| `city` | VARCHAR(100) | NULLABLE | |
| `state` | VARCHAR(100) | NULLABLE | |
| `postal_code` | VARCHAR(20) | NULLABLE | |
| `country` | VARCHAR(100) | NOT NULL | ISO 3166-1 alpha-2 |
| `bank_name` | VARCHAR(255) | NULLABLE | Synthetic only |
| `bank_account_last4` | VARCHAR(4) | NULLABLE | Synthetic only |
| `status` | VARCHAR(50) | NOT NULL, DEFAULT 'pending' | Enum: `active`, `inactive`, `pending`, `suspended`, `rejected` |
| `risk_score` | INTEGER | NOT NULL, DEFAULT 0 | 0-100 |
| `risk_level` | VARCHAR(20) | NOT NULL, DEFAULT 'low' | Enum: `low`, `medium`, `high`, `critical` |
| `onboarding_completed_at` | TIMESTAMP | NULLABLE | |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |
| `updated_at` | TIMESTAMP | NULLABLE | |

**Indexes:** `ix_vendor_legal_name`, `ix_vendor_country`, `ix_vendor_status`, `ix_vendor_risk_level`

**Unique:** `legal_name` + `country` (business key)

---

### 3. OnboardingCase
**Purpose:** Single onboarding workflow instance for a vendor.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `case_number` | VARCHAR(50) | UNIQUE, NOT NULL | Human-readable: `ONB-2026-000123` |
| `vendor_id` | INTEGER | FK → Vendor.id, NOT NULL | |
| `requester_id` | INTEGER | FK → User.id, NULLABLE | Internal requester |
| `onboarding_type` | VARCHAR(50) | NOT NULL, DEFAULT 'new_vendor' | `new_vendor`, `renewal`, `update` |
| `priority` | VARCHAR(20) | NOT NULL, DEFAULT 'normal' | `low`, `normal`, `high`, `urgent` |
| `workflow_status` | VARCHAR(50) | NOT NULL, DEFAULT 'draft' | Enum (see WorkflowStatus) |
| `risk_score` | INTEGER | NOT NULL, DEFAULT 0 | Copied from assessment |
| `risk_level` | VARCHAR(20) | NOT NULL, DEFAULT 'low' | Copied from assessment |
| `completion_percentage` | INTEGER | NOT NULL, DEFAULT 0 | 0-100 |
| `documents_received` | INTEGER | NOT NULL, DEFAULT 0 | |
| `documents_required` | INTEGER | NOT NULL, DEFAULT 0 | |
| `assigned_to_id` | INTEGER | FK → User.id, NULLABLE | Current reviewer |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |
| `updated_at` | TIMESTAMP | NULLABLE | |
| `completed_at` | TIMESTAMP | NULLABLE | When terminal status reached |

**Indexes:** `ix_onboarding_case_vendor_id`, `ix_onboarding_case_workflow_status`, `ix_onboarding_case_assigned_to_id`

---

### 4. Document
**Purpose:** Artifact submitted for a case.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `vendor_id` | INTEGER | FK → Vendor.id, NOT NULL | Denormalized for queries |
| `case_id` | INTEGER | FK → OnboardingCase.id, NOT NULL | |
| `document_type` | VARCHAR(50) | NOT NULL | Enum (see DocumentType) |
| `filename` | VARCHAR(255) | NOT NULL | Original filename |
| `file_path` | VARCHAR(500) | NULLABLE | Storage path |
| `file_size` | INTEGER | NULLABLE | Bytes |
| `mime_type` | VARCHAR(100) | NULLABLE | |
| `status` | VARCHAR(50) | NOT NULL, DEFAULT 'pending' | Enum (see DocumentStatus) |
| `extraction_confidence` | DECIMAL(3,2) | NULLABLE | 0.00-1.00 aggregate |
| `verification_status` | VARCHAR(50) | NULLABLE | `verified`, `rejected`, `pending` |
| `verification_notes` | TEXT | NULLABLE | Human notes |
| `expiration_date` | DATE | NULLABLE | For COI, tax cert |
| `document_date` | DATE | NULLABLE | Date on document |
| `uploaded_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |
| `processed_at` | TIMESTAMP | NULLABLE | When extraction done |

**Indexes:** `ix_document_vendor_id`, `ix_document_case_id`, `ix_document_status`, `ix_document_type`

**Unique:** `case_id` + `document_type` (one active per type per case)

---

### 5. ExtractedField
**Purpose:** Individual field extracted from a document.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `document_id` | INTEGER | FK → Document.id, NOT NULL | |
| `field_name` | VARCHAR(100) | NOT NULL | e.g., `ein`, `expiration_date`, `policy_number` |
| `field_value` | TEXT | NULLABLE | Raw extracted value |
| `normalized_value` | TEXT | NULLABLE | Normalized (date → ISO, currency → cents) |
| `confidence` | DECIMAL(3,2) | NOT NULL | 0.00-1.00 |
| `is_valid` | BOOLEAN | NOT NULL, DEFAULT false | Passed validation rules |
| `manually_corrected` | BOOLEAN | NOT NULL, DEFAULT false | Human override |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |

**Indexes:** `ix_extracted_field_document_id`, `ix_extracted_field_field_name`

---

### 6. RiskSignal
**Purpose:** Discrete risk finding from rule engine or AI.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `vendor_id` | INTEGER | FK → Vendor.id, NOT NULL | |
| `case_id` | INTEGER | FK → OnboardingCase.id, NOT NULL | |
| `signal_type` | VARCHAR(100) | NOT NULL | e.g., `MISSING_W9`, `EXPIRING_INSURANCE`, `HIGH_RISK_GEOGRAPHY` |
| `severity` | VARCHAR(20) | NOT NULL | Enum: `low`, `medium`, `high`, `critical` |
| `description` | TEXT | NOT NULL | Human-readable |
| `evidence` | JSONB | NULLABLE | Structured evidence for UI |
| `source` | VARCHAR(50) | NOT NULL | `rule_engine`, `ai_extraction`, `ai_analysis`, `manual` |
| `status` | VARCHAR(50) | NOT NULL, DEFAULT 'open' | `open`, `acknowledged`, `resolved`, `dismissed` |
| `resolution_notes` | TEXT | NULLABLE | |
| `detected_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |
| `resolved_at` | TIMESTAMP | NULLABLE | |

**Indexes:** `ix_risk_signal_vendor_id`, `ix_risk_signal_case_id`, `ix_risk_signal_severity`, `ix_risk_signal_status`

**Unique:** `case_id` + `signal_type` + `vendor_id` (idempotent sync key)

---

### 7. Exception
**Purpose:** Actionable item requiring human review.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `case_id` | INTEGER | FK → OnboardingCase.id, NOT NULL | |
| `type` | VARCHAR(100) | NOT NULL | e.g., `MISSING_DOCUMENT`, `ENTITY_MISMATCH`, `SANCTIONS_HIT` |
| `severity` | VARCHAR(20) | NOT NULL | Enum: `low`, `medium`, `high`, `critical` |
| `title` | VARCHAR(255) | NOT NULL | |
| `description` | TEXT | NOT NULL | |
| `evidence` | JSONB | NULLABLE | |
| `status` | VARCHAR(50) | NOT NULL, DEFAULT 'open' | Enum (see ExceptionStatus) |
| `assigned_to_id` | INTEGER | FK → User.id, NULLABLE | |
| `ai_triage_priority` | VARCHAR(20) | NULLABLE | `low`, `medium`, `high` |
| `ai_triage_resolution_type` | VARCHAR(50) | NULLABLE | `resolved`, `override`, `dismissed`, `escalated` |
| `ai_triage_reasoning` | TEXT | NULLABLE | Structured reasoning (never CoT) |
| `resolution` | TEXT | NULLABLE | Human resolution text |
| `resolution_type` | VARCHAR(50) | NULLABLE | `resolved`, `override`, `dismissed`, `escalated` |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |
| `updated_at` | TIMESTAMP | NULLABLE | |
| `resolved_at` | TIMESTAMP | NULLABLE | |

**Indexes:** `ix_exception_case_id`, `ix_exception_status`, `ix_exception_severity`, `ix_exception_assigned_to_id`

**Unique:** `case_id` + `type` + `vendor_id` (idempotent sync key)

---

### 8. Approval
**Purpose:** Human decision gate.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `case_id` | INTEGER | FK → OnboardingCase.id, NOT NULL | |
| `approval_type` | VARCHAR(50) | NOT NULL | `manager`, `compliance`, `finance`, `legal` |
| `reviewer_id` | INTEGER | FK → User.id, NOT NULL | |
| `status` | VARCHAR(50) | NOT NULL, DEFAULT 'pending' | Enum (see ApprovalStatus) |
| `decision` | VARCHAR(50) | NULLABLE | `approved`, `rejected`, `escalated` |
| `comments` | TEXT | NULLABLE | |
| `escalation_reason` | TEXT | NULLABLE | |
| `escalate_to_id` | INTEGER | FK → User.id, NULLABLE | |
| `decided_at` | TIMESTAMP | NULLABLE | |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |

**Indexes:** `ix_approval_case_id`, `ix_approval_reviewer_id`, `ix_approval_status`

**Unique:** `case_id` + `approval_type` (one per type per case)

---

### 9. RiskAssessment
**Purpose:** Snapshot of risk scoring result.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `case_id` | INTEGER | FK → OnboardingCase.id, UNIQUE, NOT NULL | One per case |
| `overall_score` | INTEGER | NOT NULL | 0-100 |
| `risk_level` | VARCHAR(20) | NOT NULL | Enum: `low`, `medium`, `high`, `critical` |
| `confidence` | DECIMAL(3,2) | NULLABLE | |
| `reasoning` | TEXT | NULLABLE | Structured summary |
| `risk_factors` | JSONB | NULLABLE | ScoreComponent array |
| `recommended_action` | VARCHAR(100) | NULLABLE | `auto_approve`, `review_required`, `approval_required`, `reject` |
| `ai_model` | VARCHAR(100) | NULLABLE | `MockProvider`, `gpt-4o-mini` |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |

**Indexes:** `ix_risk_assessment_case_id` (unique)

---

### 10. AuditEvent
**Purpose:** Immutable event log (case-scoped + platform).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `case_id` | INTEGER | FK → OnboardingCase.id, NULLABLE | NULL = platform incident |
| `actor_type` | VARCHAR(50) | NOT NULL | Enum: `user`, `system`, `ai`, `n8n` |
| `actor_id` | INTEGER | NULLABLE | User.id or null |
| `actor_name` | VARCHAR(255) | NULLABLE | |
| `event_type` | VARCHAR(100) | NOT NULL | From allowlists |
| `description` | TEXT | NOT NULL | Template-rendered, not caller-supplied |
| `input_snapshot` | JSONB | NULLABLE | Request payload |
| `output_snapshot` | JSONB | NULLABLE | Response payload |
| `event_metadata` | JSONB | NULLABLE | Provider, model, latency, tokens (never CoT) |
| `timestamp` | TIMESTAMP | NOT NULL, DEFAULT now() | |

**Indexes:** `ix_audit_event_case_id`, `ix_audit_event_timestamp`, `ix_audit_event_actor_type`, `ix_audit_event_event_type`

---

### 11. Requirement
**Purpose:** Document requirement catalogue with applicability.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | |
| `code` | VARCHAR(50) | UNIQUE, NOT NULL | e.g., `REQ-W9-US` |
| `name` | VARCHAR(255) | NOT NULL | |
| `description` | TEXT | NULLABLE | |
| `document_type` | VARCHAR(50) | NULLABLE | FK → DocumentType enum |
| `is_mandatory` | BOOLEAN | NOT NULL, DEFAULT true | |
| `vendor_types` | JSONB | NULLABLE | Array of vendor_type strings |
| `countries` | JSONB | NULLABLE | Array of ISO country codes |
| `industries` | JSONB | NULLABLE | Array of industry strings |
| `risk_levels` | JSONB | NULLABLE | Array of risk levels that trigger this |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | |

**Indexes:** `ix_requirement_document_type`, `ix_requirement_is_active`

---

## Enumerations (Python Enum → DB VARCHAR)

### UserRole
```
admin | procurement_analyst | procurement_manager | compliance_reviewer | finance_reviewer
```

### VendorStatus
```
active | inactive | pending | suspended | rejected
```

### RiskLevel
```
low | medium | high | critical
```

### WorkflowStatus
```
draft → submitted → document_collection → extraction → validation → risk_analysis → review_required → approval_pending → approved → onboarding_complete
                                                              ↘ rejected
                                                              ↘ blocked
```

### DocumentType
```
w9 | certificate_of_insurance | business_registration | banking_confirmation | supplier_questionnaire | master_services_agreement | voided_check | tax_certificate | other
```

### DocumentStatus
```
pending → processing → extracted → verified
                    ↘ failed
                    ↘ expired
```

### ExceptionSeverity
```
low | medium | high | critical
```

### ExceptionStatus
```
open → in_progress → resolved
            ↘ escalated
            ↘ closed
```

### ApprovalStatus
```
pending → approved
         ↘ rejected
         ↘ escalated
```

### ActorType (AuditEvent)
```
user | system | ai | n8n
```

### OnboardingType
```
new_vendor | renewal | update
```

---

## Key Relationships

| Parent | Child | Type | Cascade |
|--------|-------|------|---------|
| Vendor | OnboardingCase | 1:N | `delete-orphan` |
| Vendor | Document | 1:N | `delete-orphan` |
| Vendor | RiskSignal | 1:N | `delete-orphan` |
| OnboardingCase | Document | 1:N | `delete-orphan` |
| OnboardingCase | RiskSignal | 1:N | `delete-orphan` |
| OnboardingCase | Exception | 1:N | `delete-orphan` |
| OnboardingCase | Approval | 1:N | `delete-orphan` |
| OnboardingCase | RiskAssessment | 1:1 | `delete-orphan` |
| OnboardingCase | AuditEvent | 1:N | `delete-orphan` |
| Document | ExtractedField | 1:N | `delete-orphan` |
| User | OnboardingCase (requester) | 1:N | `set null` |
| User | OnboardingCase (assigned) | 1:N | `set null` |
| User | Exception (assigned) | 1:N | `set null` |
| User | Approval (reviewer) | 1:N | `set null` |
| User | AuditEvent (actor) | 1:N | `set null` |

---

## Data Flow Summary

```
┌─────────────┐
│   Vendor    │
└──────┬──────┘
       │ create
       ▼
┌──────────────────┐
│ OnboardingCase   │──▶ status: DRAFT
└──────┬───────────┘
       │ submit()
       ▼
┌──────────────────┐
│ Document(s)      │──▶ register → classify → extract → persist fields
└──────┬───────────┘
       │ assess()
       ▼
┌──────────────────┐
│ RuleEngine       │──▶ 12 rules → RuleFinding[]
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ RiskScoringService│──▶ ScoreComponent[] → total + route
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ AI Analysis      │──▶ advisory signals (MockProvider/OpenAI)
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ RiskAssessment   │ (persisted)
│ Exception(s)     │ (created from CRITICAL findings)
│ AuditEvent(s)    │ (recorded)
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Approval(s)      │ (requested per role map)
└──────┬───────────┘
       │ human decisions
       ▼
┌──────────────────┐
│ Terminal Status  │ (approved / rejected / onboarding_complete)
└──────────────────┘
```

---

## Idempotency Keys

| Operation | Key | Conflict Resolution |
|-----------|-----|---------------------|
| `POST /onboarding/{id}/submit` | case_id + status=DRAFT | 409 if not DRAFT (re-submit = success) |
| RiskSignal upsert | (case_id, signal_type, vendor_id) | `ON CONFLICT DO UPDATE` |
| Exception upsert | (case_id, type, vendor_id) | `ON CONFLICT DO UPDATE` |
| Document register | (case_id, document_type) | Unique constraint → 409 |

---

## Synthetic Data Notes (Demo Dataset)

- **All vendors:** 20 synthetic entities across 6 scenarios
- **Names:** `Apex Industrial Solutions LLC`, `Blue Ridge Contracting Inc`, etc. (`.example` domains)
- **Tax IDs:** Synthetic EIN (`XX-XXXXXXX`), BN, VAT formats
- **Bank accounts:** Last-4 only, synthetic (`1000`-`9999`)
- **Addresses:** Real cities, synthetic street numbers
- **Documents:** Text content generated programmatically (not real PDFs)
- **Risk signals:** Deterministically derived from scenario rules
- **Exceptions:** Auto-created from CRITICAL signals + some manual
- **Approvals:** Deterministic reviewer assignment by `case_id % count`
- **Audit events:** User, system, AI, and n8n actor types represented

**Label:** All data returned by API includes `demo: true` flag in metadata where applicable.

---

*Data Model v1.0 — Generated from SQLAlchemy models in `backend/app/models/__init__.py`*