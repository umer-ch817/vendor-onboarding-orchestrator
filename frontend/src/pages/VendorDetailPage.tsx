/** Vendor Detail - the single-case workspace.
 *
 * Everything a reviewer needs to make a decision about one case: the vendor
 * record, the documents, the deterministic risk breakdown, the exceptions and
 * approvals raised against it, and its full audit history. The header carries
 * the two actions that move a case forward (submit, assess), and nothing that
 * decides it -- approval happens in the Approval Queue.
 */

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  CheckCircle2,
  FileText,
  Play,
  Send,
} from 'lucide-react';
import {
  auditApi,
  documentsApi,
  onboardingApi,
  riskApi,
} from '../utils/api';
import { useApi, useMutation } from '../hooks/useApi';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Badge,
  Card,
  DefinitionList,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  ProgressBar,
  Tabs,
  humanize,
} from '../components/ui';
import {
  ApprovalStatusBadge,
  DocumentStatusBadge,
  ExceptionStatusBadge,
  RiskBadge,
  SeverityBadge,
} from '../components/ui/badges';
import { PhaseStepper } from '../components/ui/PhaseStepper';
import { NextStepPanel } from '../components/ui/NextStepPanel';
import { StoryTimeline } from '../components/ui/StoryTimeline';
import {
  formatConfidence,
  formatDate,
  formatDateTime,
  formatRelative,
  textOrDash,
} from '../utils/format';

type TabId =
  | 'story'
  | 'overview'
  | 'documents'
  | 'risk'
  | 'exceptions'
  | 'approvals'
  | 'audit';

/** An exception still blocking a decision, as opposed to one already settled. */
const OPEN_EXCEPTION_STATUSES = new Set<string>(['open', 'in_progress', 'escalated']);

export function VendorDetailPage() {
  const { caseId: caseIdParam } = useParams<{ caseId: string }>();
  const caseId = Number(caseIdParam);
  // Story is the default: understanding one case should not mean assembling it
  // from six tabs.
  const [tab, setTab] = useState<TabId>('story');

  const caseQuery = useApi(() => onboardingApi.get(caseId), [caseId]);
  const riskQuery = useApi(() => riskApi.caseView(caseId), [caseId]);

  const submit = useMutation(() => onboardingApi.submit(caseId));
  const assess = useMutation(() => onboardingApi.assess(caseId));
  const start = useMutation(() => onboardingApi.start(caseId));

  const [actionError, setActionError] = useState<string | null>(null);

  if (!Number.isFinite(caseId)) {
    return <ErrorState message="That case id is not valid." />;
  }

  if (caseQuery.loading) return <LoadingState label="Loading case…" />;
  if (caseQuery.error)
    return <ErrorState message={caseQuery.error} onRetry={caseQuery.reload} />;
  if (!caseQuery.data)
    return <EmptyState title="Case not found" description={`No case with id ${caseId}.`} />;

  const detail = caseQuery.data;
  const vendor = detail.vendor;
  const isDraft = detail.workflow_status === 'draft';

  const runAction = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    const result = await fn();
    if (result === null) return;
    caseQuery.reload();
    riskQuery.reload();
  };

  const tabs: Array<{ id: TabId; label: string; count?: number }> = [
    { id: 'story', label: 'Story' },
    { id: 'overview', label: 'Overview' },
    { id: 'documents', label: 'Documents', count: detail.documents.length },
    { id: 'risk', label: 'Risk', count: detail.risk_signals.length },
    { id: 'exceptions', label: 'Issues', count: detail.exceptions.length },
    { id: 'approvals', label: 'Approvals', count: detail.approvals.length },
    { id: 'audit', label: 'Audit' },
  ];

  return (
    <div className="stack">
      <PageHeader
        breadcrumb={
          <Link to="/cases" className="row" style={{ gap: '4px' }}>
            <ArrowLeft size={12} /> Back to Vendor Cases
          </Link>
        }
        title={vendor?.legal_name || detail.case_number}
        description={
          <span className="row wrap" style={{ gap: 'var(--space-2)' }}>
            <span className="font-mono">{detail.case_number}</span>
            <RiskBadge level={detail.risk_level} />
            <span className="text-muted">·</span>
            <span className="text-muted">
              Risk score {detail.risk_score}/100
            </span>
          </span>
        }
        actions={
          <>
            <button
              className="btn btn-primary"
              onClick={() => runAction(start.run)}
              disabled={start.pending}
              title="Hand this case to the n8n orchestrator: submit, assess, approve, notify"
            >
              <Play size={15} />
              {start.pending ? 'Starting…' : 'Start onboarding'}
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => runAction(assess.run)}
              disabled={assess.pending}
            >
              <Play size={15} />
              {assess.pending ? 'Assessing…' : 'Run assessment'}
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => runAction(submit.run)}
              disabled={!isDraft || submit.pending}
              title={
                isDraft
                  ? 'Move this case out of draft so it can be assessed'
                  : 'Only a draft case can be submitted'
              }
            >
              <Send size={15} />
              {submit.pending ? 'Submitting…' : 'Submit case'}
            </button>
          </>
        }
      />

      {(actionError || submit.error || assess.error || start.error) && (
        <div className="callout callout-critical">
          <div className="callout-body">
            {actionError || submit.error || assess.error || start.error}
          </div>
        </div>
      )}

      <PhaseStepper status={detail.workflow_status} />

      <NextStepPanel
        status={detail.workflow_status}
        riskScore={detail.risk_score}
        riskLevel={detail.risk_level}
        components={riskQuery.data?.components ?? []}
        explanation={riskQuery.data?.explanation}
        openExceptions={
          detail.exceptions.filter((e) => OPEN_EXCEPTION_STATUSES.has(e.status))
            .length
        }
        failedDocuments={
          detail.documents.filter((d) => d.status === 'failed').length
        }
        assessment={riskQuery.data?.current ?? null}
        busy={start.pending || assess.pending}
        busyLabel={
          start.pending
            ? 'Starting onboarding'
            : assess.pending
              ? 'Running the assessment'
              : undefined
        }
      />

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === 'story' && <StoryTab caseId={caseId} />}

      {tab === 'overview' && (
        <>
          <div className="grid grid-2">
            <Card title="Case">
              <DefinitionList
                items={[
                  { label: 'Case number', value: <span className="mono-sm">{detail.case_number}</span> },
                  { label: 'Onboarding type', value: humanize(detail.onboarding_type) },
                  { label: 'Priority', value: humanize(detail.priority) },
                  { label: 'Requester', value: textOrDash(detail.requester_name) },
                  { label: 'Requester email', value: textOrDash(detail.requester_email) },
                  { label: 'Department', value: textOrDash(detail.requester_department) },
                  { label: 'Created', value: formatDateTime(detail.created_at) },
                  { label: 'Last updated', value: formatDateTime(detail.updated_at) },
                  { label: 'Completed', value: detail.completed_at ? formatDateTime(detail.completed_at) : 'Not completed' },
                ]}
              />
            </Card>

            <Card title="Progress">
              <div className="stack" style={{ gap: 'var(--space-4)' }}>
                <div>
                  <div className="row-between mb-2">
                    <span className="form-label" style={{ margin: 0 }}>
                      Case completion
                    </span>
                    <span className="mono-sm">{detail.completion_percentage}%</span>
                  </div>
                  <ProgressBar value={detail.completion_percentage} />
                </div>
                <div>
                  <div className="row-between mb-2">
                    <span className="form-label" style={{ margin: 0 }}>
                      Documents received
                    </span>
                    <span className="mono-sm">
                      {detail.documents_received}/{detail.documents_required}
                    </span>
                  </div>
                  <ProgressBar
                    value={detail.documents_received}
                    max={Math.max(1, detail.documents_required)}
                    tone={
                      detail.documents_received >= detail.documents_required
                        ? 'success'
                        : 'warning'
                    }
                  />
                </div>
                <div>
                  <div className="row-between mb-2">
                    <span className="form-label" style={{ margin: 0 }}>
                      Risk score
                    </span>
                    <span className="mono-sm">{detail.risk_score}/100</span>
                  </div>
                  <ProgressBar
                    value={detail.risk_score}
                    tone={
                      detail.risk_score >= 75
                        ? 'danger'
                        : detail.risk_score >= 50
                        ? 'warning'
                        : 'success'
                    }
                  />
                </div>
              </div>
            </Card>
          </div>

          {vendor && (
            <Card
              title="Vendor record"
              subtitle="The system of record. Where a document disagrees with this, the disagreement is itself a finding."
            >
              <div className="grid grid-2">
                <DefinitionList
                  items={[
                    { label: 'Legal name', value: vendor.legal_name },
                    { label: 'Trade name', value: textOrDash(vendor.trade_name) },
                    { label: 'Vendor type', value: humanize(vendor.vendor_type) },
                    { label: 'Industry', value: textOrDash(vendor.industry) },
                    { label: 'Country', value: textOrDash(vendor.country) },
                    { label: 'State', value: textOrDash(vendor.state) },
                  ]}
                />
                <DefinitionList
                  items={[
                    { label: 'Contact', value: textOrDash(vendor.contact_name) },
                    { label: 'Email', value: textOrDash(vendor.contact_email) },
                    { label: 'Phone', value: textOrDash(vendor.contact_phone) },
                    { label: 'Status', value: humanize(vendor.status) },
                    {
                      label: 'Bank',
                      value: vendor.bank_name
                        ? `${vendor.bank_name} ····${vendor.bank_account_last4 || '????'}`
                        : 'Not recorded',
                    },
                    { label: 'Tax ID', value: textOrDash(vendor.tax_id) },
                  ]}
                />
              </div>
            </Card>
          )}
        </>
      )}

      {tab === 'documents' && (
        <DocumentsTab
          documents={detail.documents}
          onChanged={() => {
            caseQuery.reload();
            riskQuery.reload();
          }}
        />
      )}

      {tab === 'risk' && (
        <RiskTab
          loading={riskQuery.loading}
          error={riskQuery.error}
          view={riskQuery.data}
          onRetry={riskQuery.reload}
        />
      )}

      {tab === 'exceptions' && (
        <ExceptionsTab exceptions={detail.exceptions} caseId={caseId} />
      )}

      {tab === 'approvals' && (
        <ApprovalsTab approvals={detail.approvals} caseId={caseId} />
      )}

      {tab === 'audit' && <AuditTab caseId={caseId} />}
    </div>
  );
}

// ==================== Documents ====================

function StoryTab({ caseId }: { caseId: number }) {
  const { data, loading, error, reload } = useApi(
    () => auditApi.caseTimeline(caseId, 1, 200),
    [caseId],
  );

  if (loading) return <LoadingState label="Loading what happened…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  return <StoryTimeline events={data?.events ?? []} />;
}

function DocumentsTab({
  documents,
  onChanged,
}: {
  documents: any[];
  onChanged: () => void;
}) {
  const process = useMutation((id: number) => documentsApi.process(id));

  const columns: Column<any>[] = [
    {
      key: 'filename',
      header: 'File',
      sortable: true,
      render: (row) => (
        <Link to={`/documents/${row.id}`} className="row" style={{ gap: 'var(--space-2)' }}>
          <FileText size={15} className="text-muted" />
          <span className="truncate" style={{ maxWidth: '260px' }}>
            {row.filename}
          </span>
        </Link>
      ),
    },
    {
      key: 'document_type',
      header: 'Type',
      sortable: true,
      render: (row) => humanize(row.document_type),
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      render: (row) => <DocumentStatusBadge status={row.status} />,
    },
    {
      key: 'extraction_confidence',
      header: 'Confidence',
      sortable: true,
      align: 'right',
      render: (row) => formatConfidence(row.extraction_confidence),
    },
    {
      key: 'expiration_date',
      header: 'Expires',
      sortable: true,
      render: (row) => {
        if (!row.expiration_date) return <span className="text-muted">—</span>;
        const expired = new Date(row.expiration_date) < new Date();
        return (
          <span style={{ color: expired ? 'var(--color-critical)' : undefined }}>
            {formatDate(row.expiration_date)}
            {expired && ' (expired)'}
          </span>
        );
      },
    },
    {
      key: 'uploaded_at',
      header: 'Uploaded',
      sortable: true,
      render: (row) => (
        <span className="text-muted text-xs">{formatRelative(row.uploaded_at)}</span>
      ),
    },
    {
      key: 'actions',
      header: '',
      width: '110px',
      render: (row) => (
        <button
          className="btn btn-secondary btn-sm"
          onClick={async (e) => {
            e.stopPropagation();
            const ok = await process.run(row.id);
            if (ok !== null) onChanged();
          }}
          disabled={process.pending}
        >
          {row.status === 'pending' ? 'Extract' : 'Re-extract'}
        </button>
      ),
    },
  ];

  if (documents.length === 0) {
    return (
      <EmptyState
        title="No documents yet"
        description="Nothing has been uploaded. A W-9 is usually the first document a vendor sends, followed by a certificate of insurance."
        icon={FileText}
      />
    );
  }

  return (
    <>
      {process.error && (
        <div className="callout callout-critical">
          <div className="callout-body">{process.error}</div>
        </div>
      )}
      <Card padded={false}>
        <DataTable columns={columns} data={documents} keyExtractor={(r) => r.id} />
      </Card>
    </>
  );
}

// ==================== Risk ====================

function RiskTab({
  loading,
  error,
  view,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  view: any;
  onRetry: () => void;
}) {
  if (loading) return <LoadingState label="Loading risk view…" />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (!view) return <EmptyState title="No risk view available" />;

  if (!view.current) {
    return (
      <EmptyState
        title="This case has not been assessed"
        description="Run the assessment to produce a deterministic score. The score is computed by the rule engine, not by the language model."
        icon={Play}
      />
    );
  }

  const attribution = view.attribution || { total: 0, factor_count: 0, sum_check: 0 };
  const sums = attribution.sum_check === attribution.total;

  return (
    <div className="stack">
      <Card
        title="Deterministic score"
        subtitle="Computed by the rule engine from the findings below. The language model never sets or adjusts this number."
      >
        <div className="grid grid-2">
          <div>
            <div className="metric-value" style={{ marginBottom: 'var(--space-2)' }}>
              {view.risk_score}
              <span className="text-muted" style={{ fontSize: 'var(--text-base)' }}>
                {' '}
                / 100
              </span>
            </div>
            <div className="row" style={{ gap: 'var(--space-2)' }}>
              <RiskBadge level={view.risk_level} />
              {view.recommended_action && (
                <Badge tone="info">Route: {humanize(view.recommended_action)}</Badge>
              )}
            </div>
            {view.explanation && (
              <p className="text-sm mt-4" style={{ color: 'var(--color-text-muted)' }}>
                {view.explanation}
              </p>
            )}
          </div>
          <DefinitionList
            items={[
              { label: 'Contributing factors', value: attribution.factor_count },
              {
                label: 'Points from factors',
                value: (
                  <span
                    className="mono-sm"
                    style={{ color: sums ? undefined : 'var(--color-high)' }}
                  >
                    {attribution.sum_check}
                    {!sums && ` (header shows ${attribution.total})`}
                  </span>
                ),
              },
              {
                label: 'Largest factor',
                value: attribution.largest_factor
                  ? `${attribution.largest_factor.label} (+${attribution.largest_factor.points})`
                  : 'None',
              },
              { label: 'Assessed', value: formatDateTime(view.current.created_at) },
              { label: 'AI model', value: textOrDash(view.current.ai_model) },
              { label: 'Prompt version', value: textOrDash(view.current.ai_prompt_version) },
            ]}
          />
        </div>
      </Card>

      <Card
        title="Score breakdown"
        subtitle="Each factor adds points. A reviewer who disagrees with the total can point at the line item they disagree with."
        padded={false}
      >
        {view.components.length === 0 ? (
          <EmptyState
            title="No factors contributed"
            description="Nothing in the current assessment added to the score."
            icon={CheckCircle2}
          />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: '80px', textAlign: 'right' }}>Points</th>
                  <th>Factor</th>
                  <th>Severity</th>
                  <th>Why it fired</th>
                  <th style={{ width: '120px' }}>Code</th>
                </tr>
              </thead>
              <tbody>
                {view.components.map((c: any, i: number) => (
                  <tr key={`${c.code}-${i}`}>
                    <td style={{ textAlign: 'right' }} className="font-mono">
                      +{c.points}
                    </td>
                    <td>{c.label}</td>
                    <td>
                      <SeverityBadge severity={c.severity} />
                    </td>
                    <td className="text-muted text-sm">{c.evidence_summary || '—'}</td>
                    <td className="mono-sm text-muted">{c.code}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Risk signals"
        subtitle="Detected conditions attached to this case. Acknowledgement and resolution are separate acts."
        padded={false}
      >
        {view.signals.length === 0 ? (
          <EmptyState
            title="Nothing was flagged"
            description="No rule fired on this case. Either the documents are complete and consistent, or the case has not been assessed yet."
            icon={CheckCircle2}
          />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Signal</th>
                  <th>Description</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Detected</th>
                </tr>
              </thead>
              <tbody>
                {view.signals.map((s: any) => (
                  <tr key={s.id}>
                    <td>
                      <SeverityBadge severity={s.severity} />
                    </td>
                    <td className="mono-sm">{s.type}</td>
                    <td className="text-sm">{s.description}</td>
                    <td className="text-muted text-xs">{s.source}</td>
                    <td>
                      <Badge tone={s.status === 'resolved' ? 'success' : 'medium'}>
                        {humanize(s.status)}
                      </Badge>
                    </td>
                    <td className="text-muted text-xs">
                      {formatRelative(s.detected_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ==================== Exceptions ====================

function ExceptionsTab({
  exceptions,
  caseId,
}: {
  exceptions: any[];
  caseId: number;
}) {
  if (exceptions.length === 0) {
    return (
      <EmptyState
        title="No issues on this case"
        description="An issue is raised when something needs a person's decision. There are none, so far."
        icon={CheckCircle2}
      />
    );
  }

  return (
    <Card
      title="Exceptions"
      subtitle={`Open items belong in the Exception Queue, where they carry the resolution workflow.`}
      padded={false}
      actions={
        <Link className="btn btn-secondary btn-sm" to="/exceptions">
          Open queue
        </Link>
      }
    >
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Title</th>
              <th>Type</th>
              <th>Status</th>
              <th>Raised</th>
              <th>Resolved</th>
            </tr>
          </thead>
          <tbody>
            {exceptions.map((e) => (
              <tr key={e.id}>
                <td>
                  <SeverityBadge severity={e.severity} />
                </td>
                <td>{e.title}</td>
                <td className="mono-sm text-muted">{e.type}</td>
                <td>
                  <ExceptionStatusBadge status={e.status} />
                </td>
                <td className="text-muted text-xs">{formatRelative(e.created_at)}</td>
                <td className="text-muted text-xs">
                  {e.resolved_at ? formatRelative(e.resolved_at) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-body text-xs text-muted">
        Case #{caseId} — resolutions are recorded against the acting user and are
        visible in the audit trail.
      </div>
    </Card>
  );
}

// ==================== Approvals ====================

function ApprovalsTab({
  approvals,
  caseId,
}: {
  approvals: any[];
  caseId: number;
}) {
  if (approvals.length === 0) {
    return (
      <EmptyState
        title="No approvals raised"
        description="A case reaches the approval stage once its assessment routes it there. No vendor is onboarded without a human approval."
        icon={CheckCircle2}
      />
    );
  }

  return (
    <Card
      title="Approvals"
      subtitle="Decisions are made in the Approval Queue, where authority and separation-of-duties are enforced."
      padded={false}
      actions={
        <Link className="btn btn-secondary btn-sm" to="/approvals">
          Open queue
        </Link>
      }
    >
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Status</th>
              <th>Requested from</th>
              <th>Decision</th>
              <th>Comments</th>
              <th>Requested</th>
              <th>Decided</th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((a) => (
              <tr key={a.id}>
                <td>
                  <Badge tone="info">{humanize(a.approval_type)}</Badge>
                </td>
                <td>
                  <ApprovalStatusBadge status={a.status} />
                </td>
                <td className="mono-sm">user #{a.requested_from_id}</td>
                <td>{textOrDash(a.decision)}</td>
                <td className="text-sm text-muted truncate" style={{ maxWidth: '220px' }}>
                  {textOrDash(a.comments)}
                </td>
                <td className="text-muted text-xs">{formatRelative(a.created_at)}</td>
                <td className="text-muted text-xs">
                  {a.decided_at ? formatRelative(a.decided_at) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-body text-xs text-muted">
        Case #{caseId} — the decision record is append-only from the API's
        perspective; the audit trail is read-only by construction.
      </div>
    </Card>
  );
}

// ==================== Audit ====================

function AuditTab({ caseId }: { caseId: number }) {
  const { data, loading, error, reload } = useApi(
    () => auditApi.caseTimeline(caseId, 1, 200),
    [caseId]
  );

  if (loading) return <LoadingState label="Loading audit trail…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data || data.events.length === 0) {
    return (
      <EmptyState
        title="No audit events"
        description="Nothing has been recorded yet. Press Start onboarding and this trail will fill in, oldest first."
      />
    );
  }

  return (
    <Card
      title="Audit trail"
      subtitle="Oldest first. Read-only by construction — an audit trail an application can edit is not an audit trail."
    >
      <div className="stack" style={{ gap: 'var(--space-3)' }}>
        {data.events.map((event) => (
          <div
            key={event.id}
            className="row"
            style={{ gap: 'var(--space-3)', alignItems: 'flex-start' }}
          >
            <span className="mono-sm text-muted nowrap" style={{ width: '104px' }}>
              {formatDateTime(event.timestamp)}
            </span>
            <div style={{ flex: 1 }}>
              <div className="row wrap" style={{ gap: 'var(--space-2)' }}>
                <Badge tone="neutral">{event.event_type}</Badge>
                <span className="text-xs text-muted">
                  {event.actor_name || humanize(String(event.actor_type))}
                </span>
              </div>
              <div className="text-sm mt-2">{event.description}</div>
              {event.metadata && Object.keys(event.metadata).length > 0 && (
                <details className="mt-2">
                  <summary className="text-xs text-muted" style={{ cursor: 'pointer' }}>
                    Model metadata
                  </summary>
                  <pre className="mono-sm" style={{ whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(event.metadata, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
