/** Exception Queue - every open finding that needs a human decision.
 *
 * The queue is ordered by severity then age by the API, and that order is
 * preserved rather than re-sorted client-side: a critical exception raised a
 * minute ago outranks a medium one raised last week, and the backend is the
 * place that encodes it.
 *
 * Resolution carries a type, and the type is not decorative. "Resolved" means
 * the condition no longer applies. "Override" means it still applies and the
 * reviewer is accepting it anyway — a materially different act that the
 * backend requires a justification for.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, X } from 'lucide-react';
import { exceptionsApi } from '../utils/api';
import { useApi, useMutation } from '../hooks/useApi';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  Modal,
  PageHeader,
  humanize,
} from '../components/ui';
import { ExceptionStatusBadge, SeverityBadge } from '../components/ui/badges';
import { formatRelative } from '../utils/format';
import { AUTH_DISCLAIMER, getActingUserId } from '../utils/session';
import type { ExceptionResolve, Exception, ExceptionResolutionType } from '../types';

const SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low'];

const RESOLUTION_TYPES: Array<{
  id: ExceptionResolutionType;
  label: string;
  description: string;
}> = [
  {
    id: 'resolved',
    label: 'Resolved',
    description:
      'The condition no longer applies — for example the document arrived, or the field was corrected.',
  },
  {
    id: 'override',
    label: 'Override',
    description:
      'The condition still applies and you are accepting it anyway. Requires a justification: this is the act the audit trail exists to record.',
  },
  {
    id: 'dismissed',
    label: 'Dismissed',
    description:
      'The finding is not applicable to this vendor. Use when the rule fired on a false positive.',
  },
  {
    id: 'escalated',
    label: 'Escalated',
    description:
      'You are not the right person to decide this. It leaves your queue and goes up.',
  },
];

function ResolveModal({
  exception,
  onClose,
  onResolved,
}: {
  exception: Exception | null;
  onClose: () => void;
  onResolved: () => void;
}) {
  const [resolutionType, setResolutionType] =
    useState<ExceptionResolutionType>('resolved');
  const [resolution, setResolution] = useState('');

  const actingUserId = getActingUserId();
  const resolve = useMutation(
    (id: number, payload: ExceptionResolve) =>
      exceptionsApi.resolve(id, payload, actingUserId)
  );

  if (!exception) return null;

  const needsJustification = resolutionType === 'override';
  const canSubmit =
    resolution.trim().length > 0 && (!needsJustification || resolution.trim().length >= 20);

  const submit = async () => {
    const result = await resolve.run(exception.id, {
      resolution,
      resolution_type: resolutionType,
    });
    if (result !== null) {
      setResolution('');
      setResolutionType('resolved');
      onResolved();
      onClose();
    }
  };

  return (
    <Modal
      open
      title={`Resolve: ${exception.title}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={!canSubmit || resolve.pending}>
            {resolve.pending ? 'Recording…' : 'Record resolution'}
          </button>
        </>
      }
    >
      {resolve.error && (
        <div className="callout callout-critical mb-4">
          <div className="callout-body">{resolve.error}</div>
        </div>
      )}

      <div className="callout mb-4">
        <div>
          <div className="callout-title">{exception.title}</div>
          <div className="callout-body">{exception.description}</div>
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">How is this being closed?</label>
        <div className="stack" style={{ gap: 'var(--space-2)' }}>
          {RESOLUTION_TYPES.map((type) => (
            <label
              key={type.id}
              className="callout"
              style={{
                cursor: 'pointer',
                borderColor:
                  resolutionType === type.id
                    ? 'var(--color-primary)'
                    : 'var(--color-border)',
                background:
                  resolutionType === type.id
                    ? 'var(--color-primary-bg)'
                    : undefined,
              }}
            >
              <input
                type="radio"
                name="resolution-type"
                checked={resolutionType === type.id}
                onChange={() => setResolutionType(type.id)}
                style={{ marginTop: '3px' }}
              />
              <div>
                <div className="callout-title">{type.label}</div>
                <div className="callout-body text-sm">{type.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="resolution-text">
          {needsJustification ? 'Justification (at least 20 characters)' : 'What did you do?'}
        </label>
        <textarea
          id="resolution-text"
          className="form-textarea"
          value={resolution}
          onChange={(e) => setResolution(e.target.value)}
          placeholder={
            needsJustification
              ? 'Explain why this condition is being accepted rather than fixed…'
              : 'Describe the action taken…'
          }
        />
        {needsJustification && resolution.trim().length > 0 && resolution.trim().length < 20 && (
          <div className="form-error">
            An override needs a substantive justification. {20 - resolution.trim().length} more
            character(s).
          </div>
        )}
      </div>

      <p className="text-xs text-muted">
        Recording as user #{actingUserId}. {AUTH_DISCLAIMER}
      </p>
    </Modal>
  );
}

interface TriageResponse {
  exception_id: number;
  success: boolean;
  degraded: boolean;
  failure_reason?: string;
  triage?: { recommended_action?: string } | null;
}

function TriagePanel({ exception }: { exception: Exception }) {
  const triage = useMutation(() => exceptionsApi.triage(exception.id));
  // useMutation exposes pending/error but not the payload, so the response is
  // captured from run() and held here for rendering after the click.
  const [result, setResult] = useState<TriageResponse | null>(null);

  if (!result) {
    return (
      <button
        className="btn btn-secondary btn-sm"
        onClick={async (e) => {
          e.stopPropagation();
          const response = await triage.run();
          if (response) setResult(response.data);
        }}
        disabled={triage.pending}
      >
        <Sparkles size={14} />
        {triage.pending ? 'Triaging…' : 'Ask AI for triage'}
      </button>
    );
  }

  if (result.degraded || !result.success) {
    return (
      <span className="text-xs text-muted" title={result.failure_reason}>
        Triage unavailable — decide manually
      </span>
    );
  }

  return (
    <div className="text-xs">
      <div className="text-muted">AI suggestion (advisory only)</div>
      <div>{String(result.triage?.recommended_action || 'See detail')}</div>
    </div>
  );
}

export function ExceptionQueuePage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [severity, setSeverity] = useState('');
  const [assignee, setAssignee] = useState<number | ''>('');
  const [selected, setSelected] = useState<Exception | null>(null);

  const { data, loading, error, reload } = useApi(
    () =>
      exceptionsApi.list({
        page,
        page_size: pageSize,
        severity: severity || undefined,
        assigned_to_id: assignee || undefined,
      }),
    [page, pageSize, severity, assignee]
  );

  const summary = useApi(() => exceptionsApi.summary(), []);
  const actingUserId = getActingUserId();

  const assignToMe = useMutation((id: number) =>
    exceptionsApi.assign(id, actingUserId)
  );

  const columns: Column<Exception>[] = [
    {
      key: 'severity',
      header: 'Severity',
      sortable: true,
      width: '110px',
      render: (row) => <SeverityBadge severity={row.severity} />,
    },
    {
      key: 'title',
      header: 'Exception',
      sortable: true,
      render: (row) => (
        <div>
          <div style={{ fontWeight: 500 }}>{row.title}</div>
          <div className="text-xs text-muted truncate" style={{ maxWidth: '420px' }}>
            {row.description}
          </div>
        </div>
      ),
    },
    {
      key: 'type',
      header: 'Rule',
      sortable: true,
      width: '190px',
      render: (row) => <span className="mono-sm text-muted">{row.type}</span>,
    },
    {
      key: 'case_id',
      header: 'Case',
      sortable: true,
      width: '110px',
      render: (row) => (
        <Link
          to={`/cases/${row.case_id}`}
          className="mono-sm"
          onClick={(e) => e.stopPropagation()}
        >
          #{row.case_id}
        </Link>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      width: '130px',
      render: (row) => <ExceptionStatusBadge status={row.status} />,
    },
    {
      key: 'assigned_to_id',
      header: 'Assigned',
      sortable: true,
      width: '110px',
      render: (row) =>
        row.assigned_to_id ? (
          <span className="mono-sm">user #{row.assigned_to_id}</span>
        ) : (
          <span className="text-muted">Unassigned</span>
        ),
    },
    {
      key: 'created_at',
      header: 'Age',
      sortable: true,
      width: '120px',
      render: (row) => (
        <span className="text-muted text-xs">{formatRelative(row.created_at)}</span>
      ),
    },
    {
      key: 'actions',
      header: '',
      width: '230px',
      render: (row) => (
        <div className="row" style={{ gap: 'var(--space-2)' }}>
          <button
            className="btn btn-primary btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setSelected(row);
            }}
          >
            Resolve
          </button>
          {!row.assigned_to_id && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={async (e) => {
                e.stopPropagation();
                const ok = await assignToMe.run(row.id);
                if (ok !== null) reload();
              }}
              disabled={assignToMe.pending}
            >
              Assign to me
            </button>
          )}
          <TriagePanel exception={row} />
        </div>
      ),
    },
  ];

  const rowClassName = (row: Exception) => {
    if (row.severity === 'critical') return 'row-critical';
    if (row.severity === 'high') return 'row-high';
    if (row.severity === 'medium') return 'row-medium';
    return 'row-low';
  };

  const counts = summary.data || {};

  return (
    <div className="stack">
      <PageHeader
        title="Exception Queue"
        description="Open findings awaiting a decision. Resolving an exception records what was decided and by whom; it never edits the underlying evidence."
      />

      {!summary.loading && Object.keys(counts).length > 0 && (
        <div className="grid grid-4">
          {SEVERITY_OPTIONS.map((level) => (
            <MetricCard
              key={level}
              label={humanize(level)}
              value={counts[level] ?? 0}
              tone={
                level === 'critical'
                  ? 'critical'
                  : level === 'high'
                  ? 'high'
                  : level === 'medium'
                  ? 'medium'
                  : 'low'
              }
              hint="Open exceptions at this severity"
            />
          ))}
        </div>
      )}

      <Card title="Filters" subtitle={`${data?.total ?? 0} exception(s) matching`}>
        <div className="row wrap" style={{ gap: 'var(--space-3)' }}>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '160px' }}
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Severities</option>
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '170px' }}
            value={assignee}
            onChange={(e) => {
              setAssignee(e.target.value ? Number(e.target.value) : '');
              setPage(1);
            }}
          >
            <option value="">Anyone</option>
            <option value={actingUserId}>Assigned to me (user #{actingUserId})</option>
          </select>
          {(severity || assignee) && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setSeverity('');
                setAssignee('');
                setPage(1);
              }}
            >
              <X size={14} />
              Clear filters
            </button>
          )}
        </div>
      </Card>

      {assignToMe.error && (
        <div className="callout callout-critical">
          <div className="callout-body">{assignToMe.error}</div>
        </div>
      )}

      {loading ? (
        <LoadingState label="Loading exceptions…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.exceptions.length === 0 ? (
        <EmptyState
          title="Queue is clear"
          description="No open exceptions match these filters. New findings appear here when an assessment raises one."
        />
      ) : (
        <Card padded={false}>
          <DataTable
            columns={columns}
            data={data.exceptions}
            keyExtractor={(r) => r.id}
            rowClassName={rowClassName}
            pagination={{
              page: data.page,
              pageSize: data.page_size,
              total: data.total,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        </Card>
      )}

      <ResolveModal
        exception={selected}
        onClose={() => setSelected(null)}
        onResolved={reload}
      />
    </div>
  );
}
