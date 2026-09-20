/** Risk Review - where a reviewer interrogates the score rather than accepting it.
 *
 * Two modes share this route. Without a case id it lists the cases currently
 * sitting in a review state, worst score first, so the queue is worked in
 * priority order. With a case id it renders the full breakdown: every additive
 * component, the checksum against the total, and the signals behind them.
 *
 * The AI commentary, when present, is rendered in its own panel and labelled as
 * commentary. It never appears inside the score breakdown, because it did not
 * contribute to the score.
 */

import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, CheckCircle2, Info } from 'lucide-react';
import { onboardingApi, riskApi } from '../utils/api';
import { useApi } from '../hooks/useApi';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Tabs,
  humanize,
} from '../components/ui';
import {
  RiskBadge,
  SeverityBadge,
  WorkflowStatusBadge,
} from '../components/ui/badges';
import { formatDateTime, formatRelative, riskRank } from '../utils/format';

type ReviewStatus = 'review_required' | 'blocked' | 'approval_pending';

const REVIEW_TABS: Array<{ id: ReviewStatus; label: string }> = [
  { id: 'review_required', label: 'Review Required' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'approval_pending', label: 'Approval Pending' },
];

export function RiskReviewPage() {
  const { caseId: caseIdParam } = useParams<{ caseId: string }>();
  const caseId = caseIdParam ? Number(caseIdParam) : null;

  if (caseId !== null && Number.isFinite(caseId)) {
    return <CaseRiskView caseId={caseId} />;
  }
  return <RiskQueue />;
}

// ==================== Queue ====================

function RiskQueue() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<ReviewStatus>('review_required');

  const { data, loading, error, reload } = useApi(
    () => onboardingApi.list({ status, page_size: 50, page: 1 }),
    [status]
  );

  const columns: Column<any>[] = [
    {
      key: 'risk_score',
      header: 'Score',
      sortable: true,
      width: '90px',
      align: 'right',
      render: (row) => (
        <span
          className="font-mono"
          style={{ fontWeight: 700, color: riskColor(row.risk_level) }}
        >
          {row.risk_score}
        </span>
      ),
    },
    {
      key: 'risk_level',
      header: 'Level',
      sortable: true,
      width: '110px',
      render: (row) => <RiskBadge level={row.risk_level} />,
    },
    {
      key: 'case_number',
      header: 'Case',
      sortable: true,
      width: '130px',
      render: (row) => (
        <Link to={`/cases/${row.id}`} className="mono-sm" onClick={(e) => e.stopPropagation()}>
          {row.case_number}
        </Link>
      ),
    },
    {
      key: 'vendor',
      header: 'Vendor',
      sortable: false,
      render: (row) => (
        <span className="truncate" style={{ maxWidth: '240px', display: 'inline-block' }}>
          {row.vendor?.legal_name || '—'}
        </span>
      ),
    },
    {
      key: 'workflow_status',
      header: 'Status',
      sortable: true,
      width: '160px',
      render: (row) => <WorkflowStatusBadge status={row.workflow_status} />,
    },
    {
      key: 'priority',
      header: 'Priority',
      sortable: true,
      width: '100px',
      render: (row) => humanize(row.priority),
    },
    {
      key: 'updated_at',
      header: 'Waiting',
      sortable: true,
      width: '130px',
      render: (row) => (
        <span className="text-muted text-xs">{formatRelative(row.updated_at)}</span>
      ),
    },
    {
      key: 'actions',
      header: '',
      width: '120px',
      render: (row) => (
        <Link
          to={`/risk/case/${row.id}`}
          className="btn btn-secondary btn-sm"
          onClick={(e) => e.stopPropagation()}
        >
          Breakdown
        </Link>
      ),
    },
  ];

  const rowClassName = (row: any) => {
    const rank = riskRank(row.risk_level);
    if (rank >= 4) return 'row-critical';
    if (rank >= 3) return 'row-high';
    if (rank >= 2) return 'row-medium';
    return 'row-low';
  };

  const total = data?.total ?? 0;

  return (
    <div className="stack">
      <PageHeader
        title="Risk Review"
        description="Cases the rule engine has routed to a human. Sorted by score so the queue is worked worst-first."
      />

      <Tabs
        tabs={REVIEW_TABS.map((t) => ({
          ...t,
          count: t.id === status ? total : undefined,
        }))}
        value={status}
        onChange={setStatus}
      />

      {loading ? (
        <LoadingState label="Loading review queue…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.cases.length === 0 ? (
        <EmptyState
          title="Nothing in this queue"
          description="No case currently sits in this state. Cases arrive here when the deterministic assessment routes them to a human."
          icon={CheckCircle2}
        />
      ) : (
        <Card
          title={`${total} case(s)`}
          subtitle="Select a row to open the case, or use Breakdown for the score arithmetic."
          padded={false}
        >
          <DataTable
            columns={columns}
            data={data.cases}
            keyExtractor={(r) => r.id}
            rowClassName={rowClassName}
            defaultSort={{ key: 'risk_score', direction: 'desc' }}
            onRowClick={(row) => navigate(`/cases/${row.id}`)}
          />
        </Card>
      )}
    </div>
  );
}

// ==================== Case breakdown ====================

function CaseRiskView({ caseId }: { caseId: number }) {
  const { data, loading, error, reload } = useApi(
    () => riskApi.caseView(caseId),
    [caseId]
  );

  if (loading) return <LoadingState label="Loading risk breakdown…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="Case not found" />;

  if (!data.current) {
    return (
      <div className="stack">
        <PageHeader
          breadcrumb={
            <Link to="/risk" className="row" style={{ gap: '4px' }}>
              <ArrowLeft size={12} /> Back to Risk Review
            </Link>
          }
          title={data.case_number || `Case #${caseId}`}
        />
        <EmptyState
          title="Not assessed yet"
          description="This case has no risk assessment. Run the assessment from the case page to produce a deterministic score."
          icon={AlertTriangle}
        />
      </div>
    );
  }

  const attribution = data.attribution;
  const sumsMatch = attribution.sum_check === attribution.total;

  return (
    <div className="stack">
      <PageHeader
        breadcrumb={
          <Link to="/risk" className="row" style={{ gap: '4px' }}>
            <ArrowLeft size={12} /> Back to Risk Review
          </Link>
        }
        title={data.case_number || `Case #${caseId}`}
        description={
          <span className="row wrap" style={{ gap: 'var(--space-2)' }}>
            <WorkflowStatusBadge status={data.workflow_status} />
            <RiskBadge level={data.risk_level} />
            <span className="text-muted">Assessed {formatDateTime(data.current.created_at)}</span>
          </span>
        }
        actions={
          <Link to={`/cases/${caseId}`} className="btn btn-secondary">
            Open case
          </Link>
        }
      />

      <Card
        title="Deterministic score"
        subtitle="Produced by the rule engine. The language model neither sets nor adjusts this number."
      >
        <div className="row-between wrap" style={{ gap: 'var(--space-5)' }}>
          <div>
            <div className="metric-value">
              {data.risk_score}
              <span className="text-muted" style={{ fontSize: 'var(--text-base)' }}>
                {' '}
                / 100
              </span>
            </div>
            <div className="row mt-2" style={{ gap: 'var(--space-2)' }}>
              <RiskBadge level={data.risk_level} />
              {data.current.recommended_action && (
                <Badge tone="info">
                  Route: {humanize(data.current.recommended_action)}
                </Badge>
              )}
            </div>
          </div>
          <div style={{ minWidth: '260px', flex: 1 }}>
            <div
              className={`callout ${sumsMatch ? 'callout-info' : 'callout-warning'}`}
            >
              <Info size={15} />
              <div>
                <div className="callout-title">
                  {attribution.factor_count} contributing factor
                  {attribution.factor_count === 1 ? '' : 's'}
                </div>
                <div className="callout-body">
                  Components sum to {attribution.sum_check}
                  {sumsMatch
                    ? `, matching the headline score of ${attribution.total}.`
                    : `, against a headline score of ${attribution.total}. The difference is worth investigating.`}
                </div>
              </div>
            </div>
          </div>
        </div>

        {data.explanation && (
          <p className="text-sm mt-4" style={{ color: 'var(--color-text-muted)' }}>
            {data.explanation}
          </p>
        )}
      </Card>

      <Card
        title="Score components"
        subtitle="Every point in the total is attributable to a line here."
        padded={false}
      >
        {data.components.length === 0 ? (
          <EmptyState
            title="No components"
            description="No rule contributed points in the latest assessment."
            icon={CheckCircle2}
          />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: '80px', textAlign: 'right' }}>Points</th>
                  <th style={{ width: '230px' }}>Factor</th>
                  <th style={{ width: '110px' }}>Severity</th>
                  <th>Evidence</th>
                  <th style={{ width: '150px' }}>Code</th>
                </tr>
              </thead>
              <tbody>
                {data.components.map((c, i) => (
                  <tr key={`${c.code}-${i}`}>
                    <td className="font-mono" style={{ textAlign: 'right' }}>
                      +{c.points}
                    </td>
                    <td>{c.label}</td>
                    <td>
                      <SeverityBadge severity={c.severity} />
                    </td>
                    <td className="text-sm text-muted">
                      {c.evidence_summary || '—'}
                    </td>
                    <td className="mono-sm text-muted">{c.code}</td>
                  </tr>
                ))}
                <tr>
                  <td className="font-mono" style={{ textAlign: 'right', fontWeight: 700 }}>
                    {attribution.sum_check}
                  </td>
                  <td colSpan={4} className="text-muted text-xs">
                    Sum of components
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Signals"
        subtitle="Conditions detected against this case. A signal does not always become an exception — it is evidence, not a verdict."
        padded={false}
      >
        {data.signals.length === 0 ? (
          <EmptyState title="No signals" icon={CheckCircle2} />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: '110px' }}>Severity</th>
                  <th style={{ width: '220px' }}>Signal</th>
                  <th>Description</th>
                  <th style={{ width: '130px' }}>Source</th>
                  <th style={{ width: '120px' }}>Status</th>
                  <th style={{ width: '120px' }}>Detected</th>
                </tr>
              </thead>
              <tbody>
                {data.signals.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <SeverityBadge severity={s.severity} />
                    </td>
                    <td className="mono-sm">{s.type}</td>
                    <td className="text-sm">{s.description}</td>
                    <td className="text-muted text-xs">{s.source || '—'}</td>
                    <td>
                      <Badge tone={s.status === 'resolved' ? 'success' : 'medium'}>
                        {humanize(s.status)}
                      </Badge>
                    </td>
                    <td className="text-muted text-xs">
                      {s.detected_at ? formatRelative(s.detected_at) : '—'}
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

function riskColor(level?: string): string {
  switch ((level || '').toLowerCase()) {
    case 'critical':
      return 'var(--color-critical)';
    case 'high':
      return 'var(--color-high)';
    case 'medium':
      return 'var(--color-medium)';
    case 'low':
      return 'var(--color-low)';
    default:
      return 'var(--color-text)';
  }
}
