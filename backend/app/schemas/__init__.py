"""Pydantic schemas for API validation and serialization"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from decimal import Decimal

from pydantic import BaseModel, Field, EmailStr, validator


# ==================== Enums ====================

class UserRole(str, Enum):
    ADMIN = "admin"
    PROCUREMENT_ANALYST = "procurement_analyst"
    PROCUREMENT_MANAGER = "procurement_manager"
    COMPLIANCE_REVIEWER = "compliance_reviewer"
    FINANCE_REVIEWER = "finance_reviewer"


class VendorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowStatus(str, Enum):
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


class DocumentType(str, Enum):
    W9 = "w9"
    CERTIFICATE_OF_INSURANCE = "certificate_of_insurance"
    BUSINESS_REGISTRATION = "business_registration"
    BANKING_CONFIRMATION = "banking_confirmation"
    SUPPLIER_QUESTIONNAIRE = "supplier_questionnaire"
    MASTER_SERVICES_AGREEMENT = "master_services_agreement"
    VOIDED_CHECK = "voided_check"
    TAX_CERTIFICATE = "tax_certificate"
    OTHER = "other"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class ExceptionSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CLOSED = "closed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


# ==================== Base Schemas ====================

class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: Optional[datetime] = None


# ==================== User Schemas ====================

class UserBase(BaseModel):
    email: EmailStr
    name: str
    role: UserRole = UserRole.PROCUREMENT_ANALYST
    department: Optional[str] = None


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==================== Vendor Schemas ====================

class VendorBase(BaseModel):
    legal_name: str = Field(..., min_length=1, max_length=255)
    trade_name: Optional[str] = Field(None, max_length=255)
    vendor_type: Optional[str] = Field(None, max_length=50)
    industry: Optional[str] = Field(None, max_length=100)
    tax_id: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=255)

    # Contact
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None

    # Address
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = Field(..., max_length=100)


class VendorCreate(VendorBase):
    bank_name: Optional[str] = None
    bank_account_last4: Optional[str] = Field(None, min_length=4, max_length=4)


class VendorUpdate(BaseModel):
    legal_name: Optional[str] = Field(None, min_length=1, max_length=255)
    trade_name: Optional[str] = None
    vendor_type: Optional[str] = None
    industry: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    status: Optional[VendorStatus] = None


class VendorResponse(VendorBase):
    id: int
    status: VendorStatus
    risk_level: RiskLevel
    risk_score: int
    bank_name: Optional[str] = None
    bank_account_last4: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    onboarding_completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VendorListResponse(BaseModel):
    vendors: List[VendorResponse]
    total: int
    page: int
    page_size: int


# ==================== Onboarding Case Schemas ====================

class OnboardingCaseBase(BaseModel):
    vendor_id: int
    onboarding_type: str = "new_vendor"
    priority: str = "normal"
    requester_name: Optional[str] = None
    requester_email: Optional[EmailStr] = None
    requester_department: Optional[str] = None


class OnboardingCaseCreate(OnboardingCaseBase):
    pass


class OnboardingCaseUpdate(BaseModel):
    workflow_status: Optional[WorkflowStatus] = None
    priority: Optional[str] = None
    assigned_to_id: Optional[int] = None


class OnboardingCaseResponse(OnboardingCaseBase):
    id: int
    case_number: str
    workflow_status: WorkflowStatus
    risk_score: int
    risk_level: RiskLevel
    completion_percentage: int
    documents_received: int
    documents_required: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    vendor: Optional[VendorResponse] = None

    class Config:
        from_attributes = True


class OnboardingCaseListResponse(BaseModel):
    cases: List[OnboardingCaseResponse]
    total: int
    page: int
    page_size: int


class OnboardingCaseDetail(OnboardingCaseResponse):
    documents: List["DocumentResponse"] = []
    risk_signals: List["RiskSignalResponse"] = []
    exceptions: List["ExceptionResponse"] = []
    approvals: List["ApprovalResponse"] = []


# ==================== Document Schemas ====================

class DocumentBase(BaseModel):
    document_type: DocumentType
    case_id: int


class DocumentCreate(DocumentBase):
    vendor_id: int


class DocumentResponse(DocumentBase):
    id: int
    vendor_id: int
    filename: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    status: DocumentStatus
    extraction_confidence: Optional[Decimal] = None
    verification_status: Optional[str] = None
    verification_notes: Optional[str] = None
    expiration_date: Optional[datetime] = None
    document_date: Optional[datetime] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int = 1
    page_size: int = 20


class ExtractedFieldResponse(BaseModel):
    id: int
    document_id: int
    field_name: str
    field_value: Optional[str] = None
    normalized_value: Optional[str] = None
    confidence: Optional[Decimal] = None
    is_valid: bool
    manually_corrected: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentWithExtraction(DocumentResponse):
    extracted_fields: List[ExtractedFieldResponse] = []


# ==================== Risk Schemas ====================

class RiskSignalBase(BaseModel):
    signal_type: str
    severity: ExceptionSeverity
    description: str
    evidence: Optional[Dict[str, Any]] = None
    source: Optional[str] = None


class RiskSignalResponse(RiskSignalBase):
    id: int
    vendor_id: int
    case_id: int
    status: str
    detected_at: datetime
    resolution_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RiskAssessmentBase(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    confidence: Optional[Decimal] = None
    reasoning: Optional[str] = None
    risk_factors: Optional[List[Dict[str, Any]]] = None
    recommended_action: Optional[str] = None


class RiskAssessmentResponse(RiskAssessmentBase):
    id: int
    case_id: int
    ai_model: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== Exception Schemas ====================

class ExceptionBase(BaseModel):
    type: str
    severity: ExceptionSeverity = ExceptionSeverity.MEDIUM
    title: str
    description: str
    evidence: Optional[Dict[str, Any]] = None


class ExceptionCreate(ExceptionBase):
    case_id: int


class ExceptionResolve(BaseModel):
    resolution: str
    # Must match ExceptionService.RESOLUTION_TYPES exactly. "override" is a
    # distinct act from "resolved" and carries the stricter justification
    # requirement, so the two are spelled differently on purpose.
    resolution_type: str = "resolved"  # resolved, override, dismissed, escalated


class ExceptionResponse(ExceptionBase):
    id: int
    case_id: int
    status: ExceptionStatus
    assigned_to_id: Optional[int] = None
    resolution: Optional[str] = None
    resolution_type: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExceptionListResponse(BaseModel):
    exceptions: List[ExceptionResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ==================== Approval Schemas ====================

class ApprovalBase(BaseModel):
    approval_type: str
    requested_from_id: int


class ApprovalCreate(ApprovalBase):
    case_id: int


class ApprovalDecision(BaseModel):
    decision: str  # approved, rejected, escalated
    comments: Optional[str] = None
    escalation_reason: Optional[str] = None
    escalate_to_id: Optional[int] = None


class ApprovalResponse(ApprovalBase):
    id: int
    case_id: int
    status: ApprovalStatus
    decision: Optional[str] = None
    comments: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApprovalListResponse(BaseModel):
    approvals: List[ApprovalResponse]
    total: int


# ==================== Audit Schemas ====================

class AuditEventResponse(BaseModel):
    id: int
    case_id: Optional[int] = None
    actor_type: str
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    event_type: str
    description: str
    input_snapshot: Optional[Dict[str, Any]] = None
    output_snapshot: Optional[Dict[str, Any]] = None
    # For AI events this carries provider, model, prompt_version, latency and
    # token counts. It is the model's metadata, never its chain-of-thought.
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_event(cls, event) -> "AuditEventResponse":
        """Build from an AuditEvent ORM row.

        The ORM attribute is ``event_metadata`` (SQLAlchemy reserves
        ``metadata``), while the API field is ``metadata``. Mapping explicitly
        here keeps that difference in one place instead of leaking a
        storage-layer detail into the contract the frontend codes against.
        """
        return cls(
            id=event.id,
            case_id=event.case_id,
            actor_type=(
                event.actor_type.value
                if hasattr(event.actor_type, "value")
                else str(event.actor_type)
            ),
            actor_id=event.actor_id,
            actor_name=event.actor_name,
            event_type=event.event_type,
            description=event.description,
            input_snapshot=event.input_snapshot,
            output_snapshot=event.output_snapshot,
            metadata=getattr(event, "event_metadata", None),
            timestamp=event.timestamp,
        )


class AuditEventListResponse(BaseModel):
    events: List[AuditEventResponse]
    total: int


# ==================== Dashboard Schemas ====================

class DashboardMetrics(BaseModel):
    total_vendors: int
    active_cases: int
    pending_reviews: int
    open_exceptions: int
    high_risk_vendors: int
    avg_onboarding_time_days: Optional[float] = None
    automation_rate: Optional[float] = None
    cases_this_month: int
    completed_this_month: int


class RiskDistribution(BaseModel):
    low: int
    medium: int
    high: int
    critical: int


class StatusDistribution(BaseModel):
    status: str
    count: int


# ==================== AI Extraction Schemas ====================

class ExtractedFieldResult(BaseModel):
    """Schema for AI extraction results"""
    field_name: str
    value: str
    confidence: Decimal = Field(..., ge=0, le=1)
    source_location: Optional[str] = None


class DocumentExtractionResult(BaseModel):
    """Schema for complete document extraction"""
    document_type: DocumentType
    fields: List[ExtractedFieldResult]
    document_confidence: Decimal = Field(..., ge=0, le=1)
    warnings: List[str] = []
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)


class AIAnalysisResult(BaseModel):
    """Schema for AI risk analysis"""
    risk_signals: List[Dict[str, Any]]
    summary: str
    recommended_action: str
    confidence: Decimal = Field(..., ge=0, le=1)


# ==================== Workflow Trigger Schemas ====================

class WorkflowTrigger(BaseModel):
    """Schema for triggering n8n workflows"""
    case_id: int
    action: str
    metadata: Optional[Dict[str, Any]] = None


class WebhookPayload(BaseModel):
    """Schema for incoming webhooks from n8n"""
    event_type: str
    case_id: int
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WorkflowIncident(BaseModel):
    """Schema for an orchestration failure that belongs to no single case.

    A workflow can fail before it ever resolves a case id -- a webhook that
    arrives malformed, a container that is not reachable, a credential that
    expired at 3am. Those failures are platform events, not case events, and
    forcing them onto a case would either invent a case id or drop the failure.

    This is the only inbound type whose ``case_id`` is optional, and the audit
    row it produces is a platform row: visible in the recent-events view, absent
    from every case timeline.
    """
    event_type: str
    description: Optional[str] = None
    workflow: Optional[str] = None
    execution_id: Optional[str] = None
    node: Optional[str] = None
    message: Optional[str] = None
    case_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ==================== Requirement Schemas ====================

class RequirementBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    document_type: Optional[DocumentType] = None
    is_mandatory: bool = True


class RequirementResponse(RequirementBase):
    id: int
    vendor_types: Optional[List[str]] = None
    countries: Optional[List[str]] = None
    industries: Optional[List[str]] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Update forward references
OnboardingCaseDetail.model_rebuild()
