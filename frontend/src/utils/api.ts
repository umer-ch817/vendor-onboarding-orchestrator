/** API client for the Vendor Onboarding backend.
 *
 * All endpoints are typed against the contracts in src/types. The base URL
 * comes from VITE_API_URL in development, and the Vite proxy in dev mode
 * routes /api to the backend automatically.
 */

import axios, { AxiosInstance, AxiosError } from 'axios';
import type {
  ApiError,
  QueryParams,
  Vendor,
  VendorCreate,
  VendorUpdate,
  VendorListResponse,
  OnboardingCase,
  OnboardingCaseCreate,
  OnboardingCaseUpdate,
  OnboardingCaseDetail,
  OnboardingCaseListResponse,
  Document,
  DocumentWithExtraction,
  DocumentListResponse,
  RiskSignal,
  RiskAssessment,
  Exception,
  ExceptionListResponse,
  ExceptionResolve,
  Approval,
  ApprovalListResponse,
  ApprovalCreate,
  ApprovalDecision,
  AuditEvent,
  AuditEventListResponse,
  DashboardMetrics,
  CaseRiskView,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

const client: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

// Attach the API key header if one is configured (prototype auth only).
client.interceptors.request.use((config) => {
  const apiKey = localStorage.getItem('vendor_orch_api_key');
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey;
  }
  return config;
});

function buildParams(params?: QueryParams): Record<string, string> {
  if (!params) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      out[key] = String(value);
    }
  }
  return out;
}

export function extractError(err: AxiosError<ApiError>): string {
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return detail.message;
  }
  if (err.message) return err.message;
  return 'An unexpected error occurred';
}

// ==================== Vendors ====================

export const vendorsApi = {
  list: (params?: QueryParams) =>
    client.get<VendorListResponse>('/vendors/', { params: buildParams(params) }),
  get: (id: number) => client.get<Vendor>(`/vendors/${id}`),
  create: (data: VendorCreate) => client.post<Vendor>('/vendors/', data),
  update: (id: number, data: VendorUpdate) =>
    client.patch<Vendor>(`/vendors/${id}`, data),
  cases: (id: number) =>
    client.get<{ vendor_id: number; legal_name: string; cases: any[] }>(
      `/vendors/${id}/cases`
    ),
};

// ==================== Onboarding Cases ====================

export const onboardingApi = {
  list: (params?: QueryParams) =>
    client.get<OnboardingCaseListResponse>('/onboarding/', {
      params: buildParams(params),
    }),
  get: (id: number) =>
    client.get<OnboardingCaseDetail>(`/onboarding/${id}`),
  create: (data: OnboardingCaseCreate) =>
    client.post<OnboardingCase>('/onboarding/', data),
  update: (id: number, data: OnboardingCaseUpdate) =>
    client.patch<OnboardingCase>(`/onboarding/${id}`, data),
  submit: (id: number) =>
    client.post<{ case_id: number; status: string; message: string }>(
      `/onboarding/${id}/submit`
    ),
  assess: (id: number) =>
    client.post<Record<string, unknown>>(`/onboarding/${id}/assess`),
  start: (id: number) =>
    client.post<{ case_id: number; started: boolean; message: string }>(
      `/onboarding/${id}/start`
    ),
  workflowSummary: () =>
    client.get<{ by_status: Record<string, number> }>(
      '/onboarding/workflow-summary'
    ),
  riskSummary: () =>
    client.get<{ by_risk_level: Record<string, number> }>(
      '/onboarding/risk-summary'
    ),
};

// ==================== Documents ====================

export const documentsApi = {
  list: (params?: QueryParams) =>
    client.get<DocumentListResponse>('/documents/', {
      params: buildParams(params),
    }),
  get: (id: number) =>
    client.get<DocumentWithExtraction>(`/documents/${id}`),
  upload: (
    vendorId: number,
    caseId: number,
    file: File,
    documentType?: string
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post<Document>(
      `/documents/upload?vendor_id=${vendorId}&case_id=${caseId}${
        documentType ? `&document_type=${documentType}` : ''
      }`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
  },
  process: (id: number) =>
    client.post<Record<string, unknown>>(`/documents/${id}/process`),
  verify: (id: number, verified: boolean, notes?: string) =>
    client.post<{ document_id: number; verification_status: string }>(
      `/documents/${id}/verify?verified=${verified}${
        notes ? `&notes=${encodeURIComponent(notes)}` : ''
      }`
    ),
};

// ==================== Risk ====================

export const riskApi = {
  caseView: (caseId: number) =>
    client.get<CaseRiskView>(`/risk/case/${caseId}`),
  latestAssessment: (caseId: number) =>
    client.get<RiskAssessment>(`/risk/case/${caseId}/assessment`),
  history: (caseId: number, limit?: number) =>
    client.get<{ case_id: number; assessments: any[] }>(
      `/risk/case/${caseId}/history`,
      { params: limit ? { limit } : undefined }
    ),
  signals: (caseId: number) =>
    client.get<{ case_id: number; signals: RiskSignal[] }>(
      `/risk/case/${caseId}/signals`
    ),
  acknowledgeSignal: (signalId: number) =>
    client.post<{ signal_id: number; status: string }>(
      `/risk/signal/${signalId}/acknowledge`
    ),
  resolveSignal: (signalId: number, notes: string) =>
    client.post<{ signal_id: number; status: string; resolved_at: string }>(
      `/risk/signal/${signalId}/resolve?resolution_notes=${encodeURIComponent(
        notes
      )}`
    ),
};

// ==================== Exceptions ====================

export const exceptionsApi = {
  list: (params?: QueryParams) =>
    client.get<ExceptionListResponse>('/exceptions/', {
      params: buildParams(params),
    }),
  summary: () =>
    client.get<Record<string, number>>('/exceptions/summary'),
  get: (id: number) => client.get<Exception>(`/exceptions/${id}`),
  caseExceptions: (caseId: number) =>
    client.get<{ case_id: number; exceptions: Exception[] }>(
      `/exceptions/case/${caseId}`
    ),
  assign: (id: number, userId: number) =>
    client.post<Exception>(
      `/exceptions/${id}/assign?user_id=${userId}&actor_user_id=1`
    ),
  resolve: (
    id: number,
    data: ExceptionResolve,
    actorUserId: number = 1,
    actorName?: string
  ) =>
    client.post<Exception>(
      `/exceptions/${id}/resolve?actor_user_id=${actorUserId}${
        actorName ? `&actor_user_name=${encodeURIComponent(actorName)}` : ''
      }`,
      data
    ),
  triage: (id: number) =>
    client.post<{
      exception_id: number;
      success: boolean;
      degraded: boolean;
      failure_reason?: string;
      triage?: any;
    }>(`/exceptions/${id}/triage`),
};

// ==================== Approvals ====================

export const approvalsApi = {
  list: (params?: QueryParams) =>
    client.get<ApprovalListResponse>('/approvals/', {
      params: buildParams(params),
    }),
  authority: () =>
    client.get<{ authority: Record<string, string[]> }>(
      '/approvals/authority'
    ),
  reviewers: (approvalType: string) =>
    client.get<{
      approval_type: string;
      reviewers: Array<{
        id: number;
        name: string;
        email: string;
        role: string;
      }>;
    }>(`/approvals/reviewers?approval_type=${approvalType}`),
  caseApprovals: (caseId: number) =>
    client.get<ApprovalListResponse>(`/approvals/case/${caseId}`),
  get: (id: number) => client.get<Approval>(`/approvals/${id}`),
  create: (data: ApprovalCreate, actorUserId?: number) =>
    client.post<Approval>(
      `/approvals/?${actorUserId ? `actor_user_id=${actorUserId}` : ''}`,
      data
    ),
  decide: (
    id: number,
    data: ApprovalDecision,
    actorUserId: number
  ) =>
    client.post<Approval>(
      `/approvals/${id}/decide?actor_user_id=${actorUserId}`,
      data
    ),
  escalate: (
    id: number,
    data: ApprovalDecision,
    actorUserId: number
  ) =>
    client.post<Approval>(
      `/approvals/${id}/escalate?actor_user_id=${actorUserId}`,
      data
    ),
};

// ==================== Audit ====================

export const auditApi = {
  recent: (limit?: number, eventType?: string) =>
    client.get<AuditEventListResponse>('/audit/', {
      params: buildParams({ limit, event_type: eventType }),
    }),
  types: () =>
    client.get<{ event_types: string[] }>('/audit/types'),
  caseTimeline: (caseId: number, page?: number, pageSize?: number) =>
    client.get<AuditEventListResponse>(`/audit/case/${caseId}`, {
      params: buildParams({ page, page_size: pageSize }),
    }),
  get: (eventId: number) =>
    client.get<AuditEvent>(`/audit/event/${eventId}`),
};

// ==================== Dashboard ====================

export const dashboardApi = {
  metrics: () =>
    client.get<DashboardMetrics>('/dashboard/metrics'),
  full: () => client.get<DashboardMetrics & Record<string, unknown>>('/dashboard/'),
};

export default client;