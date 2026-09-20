/** Dashboard — the operational entry point.
 *
 * Reordered around the question someone actually arrives with: "what do I need
 * to do?" Counts tell you about the database; a worklist tells you about your
 * day. So the worklist comes first and the counts follow it.
 *
 * Every number is still paired with the backend's own definition (shipped in
 * `definitions`), so the page cannot drift from what the API computes. The
 * definitions moved into a collapsed section because they are reference
 * material, not something to read every morning.
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
import { RiskBadge, RiskScore } from '../components/ui/badges';
import { PhaseStepper } from '../components/ui/PhaseStepper';
import { FirstRunTour } from '../components/ui/FirstRunTour';
import { formatDays, formatRelative } from '../utils/format';
import { nextStepFor, ownerLabel } from '../utils/nextStep';
import { PHASES } from '../utils/phases';
import './DashboardPage.css';

function DistributionBars({
  title,
  counts,
  order,
  toneFor,
  labelFor,
}: {
  title: string;
  counts: Record<string, number>;
  order?: string[];
  toneFor?: (key: string) => 'neutral' | 'danger' | 'warning' | 'success';
  labelFor?: (key: string) => string;
}) {
  const keys = Object.keys(counts || {});
  const ordered = order ? order.filter((k) => keys.includes(k)) : keys.sort();
  const max = Math.max(1, ...ordered.map((k) => counts[k] || 0));
  const label = (key: string) => (labelFor ? labelFor(key) : humanize(key));

  if (ordered.length === 0) {
    return (
      <Card title={title}>
        <EmptyState
          title="No data yet"
          description="This distribution appears once cases exist."
        />
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
              label={`${label(key)} — ${count}`}
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

/** Collapse the twelve internal statuses into the four phases a person sees. */
function phaseCounts(byStatus: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const phase of PHASES) {
    out[phase.id] = phase.statuses.reduce(
      (sum, status) => sum + (byStatus[status] || 0),
      0,
    );
  }
  return out;
}

export function DashboardPage() {
  const { data, loading, error, reload } = useApi(() => dashboardApi.full());

  if (loading) return <LoadingState label="Loading dashboard…" />;
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
            {needsAttention.length === 0
              ? 'Nothing is waiting on a person right now.'
              : `${needsAttention.length} ${
                  needsAttention.length === 1 ? 'case needs' : 'cases need'
                } someone.`}{' '}
            <span className="text-muted">
              {data.dataset_label || 'Demo Dataset'} — figures are computed from the
              records in this database.
            </span>
          </p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={reload}>
          Refresh
        </button>
      </div>

      <FirstRunTour />

      <Card
        title={
          needsAttention.length === 0
            ? 'Nothing needs you'
            : `These ${needsAttention.length} need you`
        }
        subtitle="Why each one is waiting, and who it is waiting on."
        padded={false}
      >
        {needsAttention.length === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title="Nothing waiting on a human"
            description="No case is currently waiting for a decision. Ones that do will appear here."
          />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Why it is waiting</th>
                  <th>Stage</th>
                  <th style={{ textAlign: 'right' }}>Risk</th>
                  <th>Level</th>
                  <th>Waiting on</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {needsAttention.map((item) => {
                  const step = nextStepFor(item.workflow_status);
                  return (
                    <tr key={item.case_id}>
                      <td>
                        <Link to={`/cases/${item.case_id}`} className="mono-sm">
                          {item.case_number}
                        </Link>
                      </td>
                      <td>{step.headline}</td>
                      <td>
                        <PhaseStepper status={item.workflow_status} compact />
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <RiskScore score={item.risk_score} level={item.risk_level} />
                      </td>
                      <td>
                        <RiskBadge level={item.risk_level} />
                      </td>
                      <td className="text-xs">{ownerLabel(step.owner)}</td>
                      <td className="text-muted text-xs">
                        {formatRelative(item.updated_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-4">
        <MetricCard
          label="Active cases"
          value={data.active_cases}
          icon={FolderKanban}
          tone="info"
          hint="Not yet complete or declined"
          definition={definitions.active_cases}
        />
        <MetricCard
          label="Need a decision"
          value={data.pending_reviews}
          icon={AlertTriangle}
          tone={data.pending_reviews > 0 ? 'high' : 'neutral'}
          hint="Waiting on a person"
          definition={definitions.pending_reviews}
        />
        <MetricCard
          label="Open issues"
          value={data.open_exceptions}
          icon={ShieldAlert}
          tone={data.open_exceptions > 0 ? 'critical' : 'neutral'}
          hint="Findings not yet closed"
          definition={definitions.open_exceptions}
        />
        <MetricCard
          label="High-risk vendors"
          value={data.high_risk_vendors}
          icon={Users}
          tone={data.high_risk_vendors > 0 ? 'critical' : 'neutral'}
          hint="High or critical risk level"
          definition={definitions.high_risk_vendors}
        />
      </div>

      <div className="grid grid-3 dashboard-dist">
        <DistributionBars
          title="Cases by stage"
          counts={phaseCounts(data.by_status || {})}
          order={PHASES.map((p) => p.id)}
          labelFor={(key) =>
            PHASES.find((p) => p.id === key)?.label ?? humanize(key)
          }
        />
        <DistributionBars
          title="Risk distribution"
          counts={data.risk_distribution || {}}
          order={['critical', 'high', 'medium', 'low']}
          toneFor={severityTone}
        />
        <DistributionBars
          title="Issues by severity"
          counts={data.exceptions_by_severity || {}}
          order={SEVERITY_ORDER}
          toneFor={severityTone}
        />
      </div>

      <details className="dashboard-more">
        <summary>More numbers</summary>
        <div className="grid grid-4" style={{ marginTop: 'var(--space-4)' }}>
          <MetricCard
            label="Avg onboarding time"
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
            label="Automation rate"
            value={
              data.automation_rate === null || data.automation_rate === undefined
                ? '—'
                : `${Math.round(data.automation_rate * 100)}%`
            }
            icon={Zap}
            hint="Completed with no issue raised"
            definition={definitions.automation_rate}
          />
          <MetricCard
            label="Cases this month"
            value={data.cases_this_month}
            icon={Gauge}
            hint="Opened in the current calendar month"
            definition={definitions.cases_this_month}
          />
          <MetricCard
            label="Completed this month"
            value={data.completed_this_month}
            icon={CheckCircle2}
            tone="low"
            hint="Reached onboarding complete"
            definition={definitions.completed_this_month}
          />
        </div>
      </details>

      <details className="dashboard-more">
        <summary>How these numbers are defined</summary>
        <dl className="definition-list" style={{ marginTop: 'var(--space-4)' }}>
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
      </details>
    </div>
  );
}
