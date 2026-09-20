/** TypeScript contracts mirroring the backend API.
 *
 * Keep these in sync with backend/app/schemas/__init__.py. If the backend
 * changes, the frontend types must change - they are not independent.
 */

// ==================== Enums ====================

export type UserRole =
  | 'admin'
  | 'procurement_analyst'
  | 'procurement_manager'
  | 'compliance_reviewer'
  | 'finance_reviewer';

export type VendorStatus =
  | 'active'
  | 'inactive'
  | 'pending'
  | 'suspended'
  | 'rejected';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export type WorkflowStatus =
  | 'draft'
  | 'submitted'
  | 'document_collection'
  | 'extraction'
  | 'validation'
  | 'risk_analysis'
  | 'review_required'
  | 'approval_pending'
  | 'approved'
  | 'rejected'
  | 'onboarding_complete'
  | 'blocked';

export type DocumentStatus =
  | 'pending'
  | 'processing'
  | 'extracted'
  | 'verified'
  | 'failed'
  | 'expired';

export type DocumentType =
  | 'certificate_of_insurance'
  | 'business_registration'
  | 'banking_confirmation'
  | 'supplier_questionnaire'
  | 'master_services_agreement'
  | 'voided_check'
  | 'tax_certificate'
  | 'other';

export type ExceptionSeverity = 'low' | 'medium' | 'high' | 'critical';

export type ExceptionStatus =
  | 'open'
  | 'in_progress'
  | 'resolved'
  | 'escalated'
  | 'closed';

export type ExceptionResolutionType =
  | 'resolved'
  | 'override'
  | 'dismissed'
  | 'escalated';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'escalated';

export type ActorType = 'user' | 'system' | 'ai' | 'n8n';

// ==================== Core Entities ====================

export interface User {
  id: number;
  email: string;
  name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface Vendor {
  id: number;
  legal_name: string;
  trade_name?: string;
  vendor_type?: string;
  industry?: string;
  tax_id?: string;
  website?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
  status: VendorStatus;
  risk_level: RiskLevel;
  risk_score: number;
  bank_name?: string;
  bank_account_last4?: string;
  created_at: string;
  updated_at: string;
  onboarding_completed_at?: string;
}

export interface OnboardingCase {
  id: number;
  case_number: string;
  vendor_id: number;
  vendor?: Vendor;
  requester_name?: string;
  requester_email?: string;
  requester_department?: string;
  workflow_status: WorkflowStatus;
  onboarding_type: string;
  priority: string;
  risk_score: number;
  risk_level: RiskLevel;
  completion_percentage: number;
  documents_received: number;
  documents_required: number;
  created_at: string;
  updated_at?: string;
  completed_at?: string;
}

export interface OnboardingCaseDetail extends OnboardingCase {
  documents: Document[];
  risk_signals: RiskSignal[];
  exceptions: Exception[];
  approvals: Approval[];
}

export interface Document {
  id: number;
  vendor_id: number;
  case_id: number;
  document_type: DocumentType;
  filename: string;
  file_path?: string;
  file_size?: number;
  mime_type?: string;
  status: DocumentStatus;
  extraction_confidence?: number;
  verification_status?: string;
  verification_notes?: string;
  document_date?: string;
  expiration_date?: string;
  uploaded_at: string;
  processed_at?: string;
}

/** Document plus its extracted fields — the shape returned by GET /documents/{id}. */
export interface DocumentWithExtraction extends Document {
  extracted_fields: ExtractedField[];
}

export interface ExtractedField {
  id: number;
  document_id: number;
  field_name: string;
  field_value?: string;
  normalized_value?: string;
  confidence?: number;
  is_valid: boolean;
  manually_corrected: boolean;
  created_at: string;
}

export interface RiskSignal {
  id: number;
  vendor_id: number;
  case_id: number;
  signal_type: string;
  severity: ExceptionSeverity;
  description: string;
  evidence?: Record<string, unknown>;
  source?: string;
  status: string;
  resolution_notes?: string;
  resolved_at?: string;
  detected_at: string;
}

export interface RiskAssessment {
  id: number;
  case_id: number;
  overall_score: number;
  risk_level: RiskLevel;
  confidence?: number;
  reasoning?: string;
  /** Each entry is a score component dict, not a prose string. */
  risk_factors?: Array<Record<string, unknown>>;
  recommended_action?: string;
  ai_model?: string;
  created_at: string;
}

export interface Exception {
  id: number;
  case_id: number;
  type: string;
  severity: ExceptionSeverity;
  title: string;
  description: string;
  evidence?: Record<string, unknown>;
  status: ExceptionStatus;
  assigned_to_id?: number;
  resolution?: string;
  resolution_type?: ExceptionResolutionType;
  created_at: string;
  updated_at?: string;
  resolved_at?: string;
}

export interface Approval {
  id: number;
  case_id: number;
  approval_type: string;
  requested_from_id: number;
  status: ApprovalStatus;
  decision?: string;
  comments?: string;
  decided_at?: string;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  case_id?: number;
  actor_type: ActorType | string;
  actor_id?: number;
  actor_name?: string;
  event_type: string;
  description: string;
  input_snapshot?: Record<string, unknown>;
  output_snapshot?: Record<string, unknown>;
  /** For AI events: provider, model, prompt_version, latency, tokens. Never chain-of-thought. */
  metadata?: Record<string, unknown>;
  timestamp: string;
}

// ==================== Paginated Responses ====================
//
// The API names each collection after its contents rather than using a generic
// `items` key. These mirror the Pydantic response models exactly -- a mismatch
// here fails silently in TypeScript, because the field simply reads undefined.

export interface VendorListResponse {
  vendors: Vendor[];
  total: number;
  page: number;
  page_size: number;
}

export interface OnboardingCaseListResponse {
  cases: OnboardingCase[];
  total: number;
  page: number;
  page_size: number;
}

export interface DocumentListResponse {
  documents: Document[];
  total: number;
  page: number;
  page_size: number;
}

export interface ExceptionListResponse {
  exceptions: Exception[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApprovalListResponse {
  approvals: Approval[];
  total: number;
}

export interface AuditEventListResponse {
  events: AuditEvent[];
  total: number;
}

// ==================== Dashboard ====================

export interface DashboardMetrics {
  total_vendors: number;
  active_cases: number;
  pending_reviews: number;
  open_exceptions: number;
  high_risk_vendors: number;
  avg_onboarding_time_days?: number;
  automation_rate?: number;
  cases_this_month: number;
  completed_this_month: number;
  by_status?: Record<string, number>;
  risk_distribution?: Record<string, number>;
  exceptions_by_severity?: Record<string, number>;
  needs_attention?: Array<{
    case_id: number;
    case_number: string;
    workflow_status: string;
    risk_score: number;
    risk_level: string;
    priority: string;
    updated_at?: string;
  }>;
  definitions?: Record<string, string>;
  dataset_label?: string;
}

// ==================== Request/Response Payloads ====================

export interface VendorCreate {
  legal_name: string;
  country: string;
  trade_name?: string;
  vendor_type?: string;
  industry?: string;
  tax_id?: string;
  website?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  bank_name?: string;
  bank_account_last4?: string;
}

export interface VendorUpdate {
  legal_name?: string;
  trade_name?: string;
  vendor_type?: string;
  industry?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  address_line1?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
  status?: VendorStatus;
}

export interface OnboardingCaseCreate {
  vendor_id: number;
  onboarding_type?: string;
  priority?: string;
  requester_name?: string;
  requester_email?: string;
  requester_department?: string;
}

export interface OnboardingCaseUpdate {
  workflow_status?: WorkflowStatus;
  priority?: string;
  assigned_to_id?: number;
}

export interface ExceptionResolve {
  resolution: string;
  resolution_type: ExceptionResolutionType;
}

export interface ApprovalDecision {
  decision: 'approved' | 'rejected' | 'escalated';
  comments?: string;
  escalation_reason?: string;
  escalate_to_id?: number;
}

export interface ApprovalCreate {
  case_id: number;
  approval_type: string;
  requested_from_id: number;
}

// ==================== Risk View ====================
//
// GET /risk/case/{id} returns a plain dict assembled by RiskService, not a
// Pydantic model, so these types describe the hand-shaped payload. The key
// property to preserve is that the deterministic score (`current`,
// `components`, `attribution`) and the AI commentary (`ai_commentary`) stay
// separate fields -- merging them would erase the line the architecture exists
// to protect.

/** One line item in the additive score. Matches ScoreComponent.to_dict(). */
export interface RiskScoreComponent {
  code: string;
  label: string;
  points: number;
  severity: ExceptionSeverity;
  /** The rule's own words for why it fired. Not a model's reasoning. */
  evidence_summary: string;
}

/** This matches _assessment_payload() in the backend risk service. */
export interface CurrentAssessment {
  id: number;
  score: number;
  level: string;
  reasoning: string | null;
  recommended_action: string | null;
  risk_factors: RiskScoreComponent[];
  ai_model: string | null;
  ai_prompt_version: string | null;
  created_at: string | null;
}

export interface RiskSignalSummary {
  id: number;
  type: string;
  severity: ExceptionSeverity;
  description: string;
  evidence: Record<string, unknown>;
  source?: string;
  status: string;
  detected_at?: string | null;
}

export interface RiskAttribution {
  total: number;
  factor_count: number;
  largest_factor: RiskScoreComponent | null;
  /** The sum of the components, so a reviewer can check it against `total`. */
  sum_check: number;
}

export interface CaseRiskView {
  case_id: number;
  case_number: string | null;
  workflow_status: string | null;
  risk_score: number;
  risk_level: string;
  /** The latest persisted assessment, or null if the case was never assessed. */
  current: CurrentAssessment | null;
  /** The additive components behind `risk_score`. */
  components: RiskScoreComponent[];
  explanation: string;
  recommended_action?: string | null;
  signals: RiskSignalSummary[];
  attribution: RiskAttribution;
}

// ==================== Utility Types ====================

export type ApiError = {
  detail: string | { reason: string; message: string };
};

export type QueryParams = Record<string, string | number | boolean | undefined>;

// ==================== Helper Functions ====================

export function getSeverityClass(severity: ExceptionSeverity): string {
  switch (severity) {
    case 'critical':
      return 'badge-critical';
    case 'high':
      return 'badge-high';
    case 'medium':
      return 'badge-medium';
    case 'low':
      return 'badge-low';
  }
}

export function getStatusClass(status: string): string {
  const s = status.toLowerCase();
  if (s.includes('critical')) return 'badge-critical';
  if (s.includes('high')) return 'badge-high';
  if (s.includes('pending') || s.includes('submitted')) return 'badge-pending';
  if (s.includes('approved') || s.includes('complete')) return 'badge-approved';
  if (s.includes('rejected')) return 'badge-rejected';
  if (s.includes('blocked')) return 'badge-blocked';
  if (s.includes('open')) return 'badge-open';
  if (s.includes('in_progress')) return 'badge-in-progress';
  if (s.includes('resolved') || s.includes('closed')) return 'badge-resolved';
  return 'badge-medium';
}

export function getRiskLevelClass(level: RiskLevel): string {
  switch (level) {
    case 'critical':
      return 'badge-critical';
    case 'high':
      return 'badge-high';
    case 'medium':
      return 'badge-medium';
    case 'low':
      return 'badge-low';
  }
}