"""SQLAlchemy database models"""
from datetime import datetime
from typing import Optional, List
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Numeric, Boolean,
    ForeignKey, Enum, JSON, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class UserRole(str, PyEnum):
    ADMIN = "admin"
    PROCUREMENT_ANALYST = "procurement_analyst"
    PROCUREMENT_MANAGER = "procurement_manager"
    COMPLIANCE_REVIEWER = "compliance_reviewer"
    FINANCE_REVIEWER = "finance_reviewer"


class VendorStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class RiskLevel(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowStatus(str, PyEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    DOCUMENT_COLLECTION = "document_collection"
    EXTRACTION = "extraction"
    VALIDATION = "validation"
    RISK_ANALYSIS = "risk_analysis"
    REVIEW_REQUIRED = "review_required"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ONBOARDING_COMPLETE = "onboarding_complete"
    BLOCKED = "blocked"


class DocumentStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class DocumentType(str, PyEnum):
    W9 = "w9"
    CERTIFICATE_OF_INSURANCE = "certificate_of_insurance"
    BUSINESS_REGISTRATION = "business_registration"
    BANKING_CONFIRMATION = "banking_confirmation"
    SUPPLIER_QUESTIONNAIRE = "supplier_questionnaire"
    MASTER_SERVICES_AGREEMENT = "master_services_agreement"
    VOIDED_CHECK = "voided_check"
    TAX_CERTIFICATE = "tax_certificate"
    OTHER = "other"


class ExceptionSeverity(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionStatus(str, PyEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CLOSED = "closed"


class ApprovalStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class ActorType(str, PyEnum):
    USER = "user"
    SYSTEM = "system"
    AI = "ai"
    N8N = "n8n"


# ==================== User Model ====================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.PROCUREMENT_ANALYST)
    department = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    # Two FKs point at users (requested_from_id, escalated_to_id), so the
    # join target must be stated explicitly or SQLAlchemy cannot pick one.
    approvals = relationship(
        "Approval",
        back_populates="reviewer",
        foreign_keys="[Approval.requested_from_id]",
    )
    exceptions_resolved = relationship(
        "Exception",
        back_populates="resolver",
        foreign_keys="[Exception.assigned_to_id]",
    )
    # NOTE: there is deliberately no User.audit_events collection. AuditEvent
    # links its actor through actor_id, which is NOT a foreign key: actors can
    # be users, the system, the AI, or n8n, so a users FK would reject every
    # non-user actor. A relationship without a FK raises
    # "there are no foreign keys linking these tables" at mapper configure
    # time, so the collection side is simply not declared.

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


# ==================== Vendor Model ====================

class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    legal_name = Column(String(255), nullable=False, index=True)
    trade_name = Column(String(255))
    vendor_type = Column(String(50))  # supplier, contractor, consultant, etc.
    industry = Column(String(100))
    tax_id = Column(String(50))  # Encrypted/masked in production
    website = Column(String(255))

    # Contact information
    contact_name = Column(String(255))
    contact_email = Column(String(255))
    contact_phone = Column(String(50))

    # Address
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100), nullable=False)

    # Status and risk
    status = Column(Enum(VendorStatus), default=VendorStatus.PENDING)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)
    risk_score = Column(Integer, default=0)

    # Banking (masked/synthetic for demo)
    bank_name = Column(String(100))
    bank_account_last4 = Column(String(4))

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    onboarding_completed_at = Column(DateTime)

    # Relationships
    onboarding_cases = relationship("OnboardingCase", back_populates="vendor")
    documents = relationship("Document", back_populates="vendor")
    risk_signals = relationship("RiskSignal", back_populates="vendor")

    __table_args__ = (
        # Trigram index for fuzzy vendor-name matching. A GIN index over a
        # varchar needs an explicit operator class; the default gin opclass
        # does not exist for varchar, so without gin_trgm_ops Postgres raises
        # "data type character varying has no default operator class for
        # access method gin". Requires the pg_trgm extension (see init.sql).
        Index(
            'ix_vendors_legal_name_trgm',
            legal_name,
            postgresql_using='gin',
            postgresql_ops={'legal_name': 'gin_trgm_ops'},
        ),
    )

    def __repr__(self):
        return f"<Vendor(id={self.id}, legal_name={self.legal_name})>"


# ==================== Onboarding Case Model ====================

class OnboardingCase(Base):
    __tablename__ = "onboarding_cases"

    id = Column(Integer, primary_key=True, index=True)
    case_number = Column(String(20), unique=True, nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)

    # Requester info
    requester_name = Column(String(255))
    requester_email = Column(String(255))
    requester_department = Column(String(100))

    # Workflow state
    workflow_status = Column(Enum(WorkflowStatus), default=WorkflowStatus.DRAFT)
    onboarding_type = Column(String(50))  # new_vendor, renewal, update
    priority = Column(String(20), default="normal")  # low, normal, high, urgent

    # Risk assessment
    risk_score = Column(Integer, default=0)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)

    # Progress
    completion_percentage = Column(Integer, default=0)
    documents_received = Column(Integer, default=0)
    documents_required = Column(Integer, default=0)

    # Assignment
    assigned_to_id = Column(Integer, ForeignKey("users.id"))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime)

    # Relationships
    vendor = relationship("Vendor", back_populates="onboarding_cases")
    documents = relationship("Document", back_populates="case")
    risk_signals = relationship("RiskSignal", back_populates="case")
    risk_assessments = relationship("RiskAssessment", back_populates="case")
    exceptions = relationship("Exception", back_populates="case")
    approvals = relationship("Approval", back_populates="case")
    audit_events = relationship("AuditEvent", back_populates="case")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])

    __table_args__ = (
        Index('ix_onboarding_cases_status', workflow_status),
        Index('ix_onboarding_cases_risk_level', risk_level),
    )

    def __repr__(self):
        return f"<OnboardingCase(id={self.id}, case_number={self.case_number})>"


# ==================== Document Model ====================

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("onboarding_cases.id"), nullable=False)

    # Document info
    document_type = Column(Enum(DocumentType), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500))
    file_size = Column(Integer)
    mime_type = Column(String(100))

    # Processing status
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    extraction_confidence = Column(Numeric(3, 2))  # 0.00 to 1.00
    verification_status = Column(String(20))  # pending, verified, rejected
    verification_notes = Column(Text)
    verified_by_id = Column(Integer, ForeignKey("users.id"))
    verified_at = Column(DateTime)

    # Document dates
    document_date = Column(DateTime)  # Date on the document
    expiration_date = Column(DateTime)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)

    # Relationships
    vendor = relationship("Vendor", back_populates="documents")
    case = relationship("OnboardingCase", back_populates="documents")
    extracted_fields = relationship("ExtractedField", back_populates="document")
    verified_by = relationship("User", foreign_keys=[verified_by_id])

    __table_args__ = (
        Index('ix_documents_case_type', case_id, document_type),
    )

    def __repr__(self):
        return f"<Document(id={self.id}, type={self.document_type}, filename={self.filename})>"


# ==================== Extracted Field Model ====================

class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    # Field identification
    field_name = Column(String(100), nullable=False)
    field_value = Column(Text)
    normalized_value = Column(Text)  # Normalized representation

    # Confidence and source
    confidence = Column(Numeric(3, 2))  # 0.00 to 1.00
    source_location = Column(String(255))  # Page, section, coordinates

    # Validation
    is_valid = Column(Boolean, default=True)
    validation_errors = Column(JSON)
    manually_corrected = Column(Boolean, default=False)
    corrected_by_id = Column(Integer, ForeignKey("users.id"))
    corrected_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="extracted_fields")
    corrected_by = relationship("User", foreign_keys=[corrected_by_id])

    __table_args__ = (
        UniqueConstraint('document_id', 'field_name', name='uq_document_field'),
        Index('ix_extracted_fields_name_value', field_name, field_value),
    )

    def __repr__(self):
        return f"<ExtractedField(id={self.id}, field={self.field_name})>"


# ==================== Risk Signal Model ====================

class RiskSignal(Base):
    __tablename__ = "risk_signals"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("onboarding_cases.id"), nullable=False)

    # Signal details
    signal_type = Column(String(50), nullable=False)  # e.g., ENTITY_NAME_MISMATCH, DOCUMENT_EXPIRED
    severity = Column(Enum(ExceptionSeverity), default=ExceptionSeverity.MEDIUM)
    description = Column(Text, nullable=False)
    evidence = Column(JSON)  # Structured evidence
    source = Column(String(50))  # rules_engine, ai_analysis, document_check

    # Resolution
    status = Column(String(20), default="open")  # open, acknowledged, resolved, dismissed
    resolution_notes = Column(Text)
    resolved_by_id = Column(Integer, ForeignKey("users.id"))
    resolved_at = Column(DateTime)

    # Timestamps
    detected_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    vendor = relationship("Vendor", back_populates="risk_signals")
    case = relationship("OnboardingCase", back_populates="risk_signals")
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])

    __table_args__ = (
        Index('ix_risk_signals_type_severity', signal_type, severity),
    )

    def __repr__(self):
        return f"<RiskSignal(id={self.id}, type={self.signal_type}, severity={self.severity})>"


# ==================== Risk Assessment Model ====================

class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("onboarding_cases.id"), nullable=False)

    # Assessment results
    overall_score = Column(Integer, nullable=False)  # 0-100
    risk_level = Column(Enum(RiskLevel), nullable=False)
    confidence = Column(Numeric(3, 2))

    # Reasoning
    reasoning = Column(Text)
    risk_factors = Column(JSON)  # Array of factors
    recommended_action = Column(String(50))  # approve, review, reject, escalate

    # AI metadata
    ai_model = Column(String(50))
    ai_prompt_version = Column(String(20))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    case = relationship("OnboardingCase", back_populates="risk_assessments")

    def __repr__(self):
        return f"<RiskAssessment(id={self.id}, score={self.overall_score}, level={self.risk_level})>"


# ==================== Exception Model ====================

class Exception(Base):
    __tablename__ = "exceptions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("onboarding_cases.id"), nullable=False)

    # Exception details
    type = Column(String(50), nullable=False)  # MISSING_DOCUMENT, ENTITY_MISMATCH, etc.
    severity = Column(Enum(ExceptionSeverity), default=ExceptionSeverity.MEDIUM)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    evidence = Column(JSON)  # Structured evidence

    # Status
    status = Column(Enum(ExceptionStatus), default=ExceptionStatus.OPEN)
    assigned_to_id = Column(Integer, ForeignKey("users.id"))

    # Resolution
    resolution = Column(Text)
    resolution_type = Column(String(50))  # resolved, escalated, overridden, dismissed
    resolved_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    case = relationship("OnboardingCase", back_populates="exceptions")
    resolver = relationship("User", back_populates="exceptions_resolved", foreign_keys=[assigned_to_id])

    __table_args__ = (
        Index('ix_exceptions_status_severity', status, severity),
    )

    def __repr__(self):
        return f"<Exception(id={self.id}, type={self.type}, status={self.status})>"


# ==================== Approval Model ====================

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("onboarding_cases.id"), nullable=False)

    # Approval details
    approval_type = Column(String(50), nullable=False)  # compliance, finance, legal, manager
    requested_from_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Status
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)

    # Decision
    decision = Column(String(20))  # approved, rejected, escalated
    comments = Column(Text)
    decided_at = Column(DateTime)

    # Escalation
    escalated_to_id = Column(Integer, ForeignKey("users.id"))
    escalation_reason = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    case = relationship("OnboardingCase", back_populates="approvals")
    reviewer = relationship("User", back_populates="approvals", foreign_keys=[requested_from_id])
    escalated_to = relationship("User", foreign_keys=[escalated_to_id])

    def __repr__(self):
        return f"<Approval(id={self.id}, type={self.approval_type}, status={self.status})>"


# ==================== Audit Event Model ====================

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("onboarding_cases.id"))

    # Actor
    actor_type = Column(Enum(ActorType), nullable=False)
    actor_id = Column(Integer)
    actor_name = Column(String(255))

    # Event details
    event_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)

    # Data snapshots
    input_snapshot = Column(JSON)
    output_snapshot = Column(JSON)

    # Named ``event_metadata`` in Python, ``metadata`` in the database.
    # SQLAlchemy's Declarative API reserves the attribute name ``metadata``
    # (it is the registry's MetaData object), so declaring a mapped attribute
    # with that name raises InvalidRequestError at import time. Mapping an
    # explicit column name keeps the database column honest without tripping
    # the guard.
    event_metadata = Column("metadata", JSON)

    # Timestamp
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    case = relationship("OnboardingCase", back_populates="audit_events")
    # actor_id is not a foreign key (see the note on User), so the join has to
    # be spelled out as a primaryjoin; `foreign_keys` alone is not enough
    # because SQLAlchemy looks for real ForeignKey metadata. Read-only, so it
    # can never attempt to persist a non-user actor id.
    user = relationship(
        "User",
        primaryjoin="AuditEvent.actor_id == User.id",
        foreign_keys=[actor_id],
        viewonly=True,
    )

    __table_args__ = (
        Index('ix_audit_events_case_timestamp', case_id, timestamp),
        Index('ix_audit_events_type', event_type),
    )

    def __repr__(self):
        return f"<AuditEvent(id={self.id}, type={self.event_type}, actor={self.actor_type})>"


# ==================== Requirement Model ====================

class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(Integer, primary_key=True, index=True)

    # Requirement identification
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Conditions
    vendor_types = Column(JSON)  # Array of vendor types this applies to
    countries = Column(JSON)  # Array of country codes
    industries = Column(JSON)  # Array of industries
    risk_levels = Column(JSON)  # Array of risk levels

    # Document requirement
    document_type = Column(Enum(DocumentType))
    is_mandatory = Column(Boolean, default=True)

    # Validation rules
    validation_rules = Column(JSON)

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Requirement(id={self.id}, code={self.code}, name={self.name})>"