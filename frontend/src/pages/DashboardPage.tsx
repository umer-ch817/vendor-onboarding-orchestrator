/** Dashboard - the operational entry point.
 *
 * Answers three questions in order: what is the state of the pipeline, where is
 * risk concentrated, and what needs a human right now. Every number is paired
 * with the backend's own definition (shipped in `definitions`) so the page
 * cannot drift from what the API actually computes.
 */

import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FolderKanban,
  Gauge,
  ShieldAlert,
  Users,
  Zap,
} from 'lucide-react';
import { dashboardApi } from '../utils/api';
import { useApi } from '../hooks/useApi';
import {
  Card,
  ErrorState,
  LoadingState,
  MetricCard,
  EmptyState,
  ProgressBar,
  humanize,
} from '../components/ui';
import { RiskBadge, RiskScore, WorkflowStatusBadge } from '../components/ui/badges';
import { formatDays, formatRelative } from '../utils/format';

function DistributionBars({
  title,
  counts,
  order,
  toneFor,
}: {
  title: string;
  counts: Record<string, number>;
  order?: string[];
  toneFor?: (key: string) => 'neutral' | 'danger' | 'warning' | 'success';
}) {
  const keys = Object.keys(counts || {});
  const ordered = order ? order.filter((k) => keys.includes(k)) : keys.sort();
  const max = Math.max(1, ...ordered.map((k) => counts[k] || 0));

  if (ordered.length === 0) {
    return (
      <Card title={title}>
        <EmptyState title="No data yet" description="The distribution appears once cases exist." />
      </Card>
    );
  }

  return (
    <Card title={title}>
      <div className="stack" style={{ gap: 'var(--space-3)' }}>
        {ordered.map((key) => {
          const count = counts[key] || 0;
          return (
            <ProgressBar
              key={key}
              value={count}
              max={max}
              tone={toneFor ? toneFor(key) : 'neutral'}
              label={`${humanize(key)} — ${count}`}
            />
          );
        })}
      </div>
    </Card>
  );
}

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low'];

function severityTone(key: string): 'danger' | 'warning' | 'neutral' | 'success' {
  if (key === 'critical') return 'danger';
  if (key === 'high') return 'warning';
  if (key === 'low') return 'success';
  return 'neutral';
}

export function DashboardPage() {
  const { data, loading, error, reload } = useApi(() => dashboardApi.full());

  if (loading) return <LoadingState label="Loading dashboard metrics…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="No metrics available" />;

  const definitions = data.definitions || {};
  const needsAttention = data.needs_attention || [];

  return (
    <div className="stack">
      <div className="row-between wrap">
        <div>
          <h1 className="page-title">Operations Dashboard</h1>
          <p className="page-description">
            Live state of the vendor onboarding pipeline.{' '}
            <span className="text-muted">
              {data.dataset_label || 'Demo Dataset'} — figures are computed from
              synthetic records, not production traffic.
            </span>
          </p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={reload}>
          Refresh
        </button>
      </div>

      <div className="grid grid-4">
        <MetricCard
          label="Active Cases"
          value={data.active_cases}
          icon={FolderKanban}
          tone="info"
          hint="Not yet complete or rejected"
          definition={definitions.active_cases}
        />
        <MetricCard
          label="Pending Reviews"
          value={data.pending_reviews}
          icon={AlertTriangle}
          tone={data.pending_reviews > 0 ? 'high' : 'neutral'}
          hint="Awaiting a human decision"
          definition={definitions.pending_reviews}
        />
        <MetricCard
          label="Open Exceptions"
          value={data.open_exceptions}
          icon={ShieldAlert}
          tone={data.open_exceptions > 0 ? 'critical' : 'neutral'}
          hint="Rule or AI findings not closed"
          definition={definitions.open_exceptions}
        />
        <MetricCard
          label="High Risk Vendors"
          value={data.high_risk_vendors}
          icon={Users}
          tone={data.high_risk_vendors > 0 ? 'critical' : 'neutral'}
          hint="High or critical risk level"
          definition={definitions.high_risk_vendors}
        />
      </div>

      <div className="grid grid-4">
        <MetricCard
          label="Avg Onboarding Time"
          value={
            data.avg_onboarding_time_days === null ||
            data.avg_onboarding_time_days === undefined ? (
              <span className="text-muted" style={{ fontSize: 'var(--text-lg)' }}>
                Not yet measured
              </span>
            ) : (
              formatDays(data.avg_onboarding_time_days)
            )
          }
          icon={Clock}
          hint="Completed cases only"
          definition={definitions.avg_onboarding_time_days}
        />
        <MetricCard
          label="Automation Rate"
          value={
            data.automation_rate === null || data.automation_rate === undefined
              ? '—'
              : `${Math.round(data.automation_rate * 100)}%`
          }
          icon={Zap}
          hint="Completed with no exception raised"
          definition={definitions.automation_rate}
        />
        <MetricCard
          label="Cases This Month"
          value={data.cases_this_month}
          icon={Gauge}
          hint="Opened in the current calendar month"
          definition={definitions.cases_this_month}
        />
        <MetricCard
          label="Completed This Month"
          value={data.completed_this_month}
          icon={CheckCircle2}
          tone="low"
          hint="Reached onboarding_complete"
          definition={definitions.completed_this_month}
        />
      </div>

      <Card
        title="Needs Attention"
        subtitle="Cases sitting in a review state, newest first."
        padded={false}
      >
        {needsAttention.length === 0 ? (
          <EmptyState
            title="Nothing waiting on a human"
            description="No case is currently in review_required, approval_pending or blocked."
            icon={CheckCircle2}
          />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th style={{ textAlign: 'right' }}>Risk Score</th>
                  <th>Level</th>
                  <th>Last Updated</th>
                </tr>
              </thead>
              <tbody>
                {needsAttention.map((item) => (
                  <tr key={item.case_id}>
                    <td>
                      <Link to={`/cases/${item.case_id}`} className="mono-sm">
                        {item.case_number}
                      </Link>
                    </td>
                    <td>
                      <WorkflowStatusBadge status={item.workflow_status} />
                    </td>
                    <td>{humanize(item.priority)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <RiskScore score={item.risk_score} level={item.risk_level} />
                    </td>
                    <td>
                      <RiskBadge level={item.risk_level} />
                    </td>
                    <td className="text-muted text-xs">
                      {formatRelative(item.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-3">
        <DistributionBars
          title="Cases by Workflow Status"
          counts={data.by_status || {}}
        />
        <DistributionBars
          title="Risk Distribution"
          counts={data.risk_distribution || {}}
          order={['critical', 'high', 'medium', 'low']}
          toneFor={severityTone}
        />
        <DistributionBars
          title="Exceptions by Severity"
          counts={data.exceptions_by_severity || {}}
          order={SEVERITY_ORDER}
          toneFor={severityTone}
        />
      </div>

      <Card
        title="How these numbers are defined"
        subtitle="Shipped by the API alongside the metrics so the dashboard cannot drift from the backend."
      >
        <dl className="definition-list">
          {Object.entries(definitions).map(([key, text]) => (
            <div className="definition-row" key={key}>
              <dt>{humanize(key)}</dt>
              <dd>{text}</dd>
            </div>
          ))}
          {Object.keys(definitions).length === 0 && (
            <div className="text-muted text-sm">
              The backend did not return metric definitions.
            </div>
          )}
        </dl>
      </Card>
    </div>
  );
}
