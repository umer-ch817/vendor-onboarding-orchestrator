/** Approval Queue - the gate every vendor passes through before onboarding.
 *
 * Two things distinguish this queue from the exception queue. First, it is
 * ordered oldest-first: an approval queue sorted newest-first quietly starves
 * the oldest request. Second, the decision buttons are disabled with a stated
 * reason when the acting user lacks the authority, rather than letting them
 * click and receive a 403. The authority list is fetched from the API so the UI
 * cannot disagree with the server about who may decide what.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Check, Info, X } from 'lucide-react';
import { approvalsApi } from '../utils/api';
import { useApi, useMutation } from '../hooks/useApi';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  PageHeader,
  humanize,
} from '../components/ui';
import { ApprovalStatusBadge } from '../components/ui/badges';
import { formatRelative } from '../utils/format';
import { AUTH_DISCLAIMER, getActingUserId } from '../utils/session';
import type { Approval, ApprovalDecision } from '../types';

function DecisionModal({
  approval,
  mode,
  onClose,
  onDecided,
}: {
  approval: Approval | null;
  mode: 'decide' | 'escalate';
  onClose: () => void;
  onDecided: () => void;
}) {
  const [decision, setDecision] = useState<'approved' | 'rejected' | 'escalated'>(
    mode === 'escalate' ? 'escalated' : 'approved'
  );
  const [comments, setComments] = useState('');
  const [escalationReason, setEscalationReason] = useState('');
  const [escalateTo, setEscalateTo] = useState<number | ''>('');

  const actingUserId = getActingUserId();

  // Only fetched while an approval is open; the empty fallback keeps the hook
  // unconditional without issuing a wasted request on first paint.
  const reviewers = useApi<{
    approval_type: string;
    reviewers: Array<{ id: number; name: string; email: string; role: string }>;
  }>(
    () =>
      approval
        ? approvalsApi.reviewers(approval.approval_type)
        : Promise.resolve({ data: { approval_type: '', reviewers: [] } }),
    [approval?.approval_type, approval?.id]
  );

  const decide = useMutation((id: number, payload: ApprovalDecision) =>
    approvalsApi.decide(id, payload, actingUserId)
  );
  const escalate = useMutation((id: number, payload: ApprovalDecision) =>
    approvalsApi.escalate(id, payload, actingUserId)
  );

  if (!approval) return null;

  const isEscalating = mode === 'escalate';
  const needsReason = isEscalating && escalationReason.trim().length < 10;
  const rejectionNeedsComment = decision === 'rejected' && comments.trim().length < 5;
  const canSubmit = !needsReason && !rejectionNeedsComment;

  const submit = async () => {
    const payload: ApprovalDecision = isEscalating
      ? {
          decision: 'escalated',
          escalation_reason: escalationReason,
          escalate_to_id: escalateTo ? Number(escalateTo) : undefined,
          comments: comments || undefined,
        }
      : { decision, comments: comments || undefined };

    const result = await (isEscalating
      ? escalate.run(approval.id, payload)
      : decide.run(approval.id, payload));

    if (result !== null) {
      setComments('');
      setEscalationReason('');
      onDecided();
      onClose();
    }
  };

  const activeError = isEscalating ? escalate.error : decide.error;
  const pending = isEscalating ? escalate.pending : decide.pending;

  return (
    <Modal
      open
      title={
        isEscalating
          ? `Escalate: ${humanize(approval.approval_type)} approval`
          : `Decide: ${humanize(approval.approval_type)} approval`
      }
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={!canSubmit || pending}
          >
            {pending
              ? 'Recording…'
              : isEscalating
              ? 'Escalate'
              : decision === 'approved'
              ? 'Approve'
              : 'Reject'}
          </button>
        </>
      }
    >
      {activeError && (
        <div className="callout callout-critical mb-4">
          <div className="callout-body">{activeError}</div>
        </div>
      )}

      <div className="definition-list mb-4">
        <div className="definition-row">
          <dt>Approval type</dt>
          <dd>
            <Badge tone="info">{humanize(approval.approval_type)}</Badge>
          </dd>
        </div>
        <div className="definition-row">
          <dt>Case</dt>
          <dd>
            <Link to={`/cases/${approval.case_id}`} className="mono-sm">
              #{approval.case_id}
            </Link>
          </dd>
        </div>
        <div className="definition-row">
          <dt>Requested from</dt>
          <dd className="mono-sm">user #{approval.requested_from_id}</dd>
        </div>
        <div className="definition-row">
          <dt>Requested</dt>
          <dd>{formatRelative(approval.created_at)}</dd>
        </div>
      </div>

      {!isEscalating && (
        <div className="form-group">
          <label className="form-label">Decision</label>
          <div className="row" style={{ gap: 'var(--space-3)' }}>
            <label className="row" style={{ gap: 'var(--space-1)' }}>
              <input
                type="radio"
                name="decision"
                checked={decision === 'approved'}
                onChange={() => setDecision('approved')}
              />
              Approve
            </label>
            <label className="row" style={{ gap: 'var(--space-1)' }}>
              <input
                type="radio"
                name="decision"
                checked={decision === 'rejected'}
                onChange={() => setDecision('rejected')}
              />
              Reject
            </label>
          </div>
        </div>
      )}

      {isEscalating && (
        <>
          <div className="form-group">
            <label className="form-label" htmlFor="escalation-reason">
              Why is this leaving your desk?
            </label>
            <textarea
              id="escalation-reason"
              className="form-textarea"
              value={escalationReason}
              onChange={(e) => setEscalationReason(e.target.value)}
              placeholder="What makes this decision above your authority, or outside your remit?"
            />
            {escalationReason.trim().length > 0 && needsReason && (
              <div className="form-error">
                Escalation needs a reason of at least 10 characters.
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="escalate-to">
              Escalate to (optional)
            </label>
            <select
              id="escalate-to"
              className="form-select"
              value={escalateTo}
              onChange={(e) =>
                setEscalateTo(e.target.value ? Number(e.target.value) : '')
              }
            >
              <option value="">Leave unassigned</option>
              {(reviewers.data?.reviewers || []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {humanize(r.role)}
                </option>
              ))}
            </select>
          </div>
        </>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor="decision-comments">
          Comments {decision === 'rejected' && !isEscalating && '(required)'}
        </label>
        <textarea
          id="decision-comments"
          className="form-textarea"
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="Context for the record…"
        />
        {rejectionNeedsComment && comments.length > 0 && (
          <div className="form-error">
            A rejection needs a comment so the requester knows what to change.
          </div>
        )}
      </div>

      <p className="text-xs text-muted">
        Recording as user #{actingUserId}. {AUTH_DISCLAIMER} The server still
        enforces role authority, separation of duties, and blocking exceptions —
        a decision that fails those checks is refused regardless of this form.
      </p>
    </Modal>
  );
}

export function ApprovalQueuePage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [approvalType, setApprovalType] = useState('');
  const [selected, setSelected] = useState<Approval | null>(null);
  const [mode, setMode] = useState<'decide' | 'escalate'>('decide');

  const actingUserId = getActingUserId();

  const { data, loading, error, reload } = useApi(
    () =>
      approvalsApi.list({
        page,
        page_size: pageSize,
        approval_type: approvalType || undefined,
      }),
    [page, pageSize, approvalType]
  );

  const authority = useApi(() => approvalsApi.authority(), []);

  const columns: Column<Approval>[] = [
    {
      key: 'approval_type',
      header: 'Type',
      sortable: true,
      width: '130px',
      render: (row) => <Badge tone="info">{humanize(row.approval_type)}</Badge>,
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
      key: 'requested_from_id',
      header: 'Requested from',
      sortable: true,
      width: '150px',
      render: (row) => (
        <span className="mono-sm">
          user #{row.requested_from_id}
          {row.requested_from_id === actingUserId && (
            <span className="text-muted"> (you)</span>
          )}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      width: '120px',
      render: (row) => <ApprovalStatusBadge status={row.status} />,
    },
    {
      key: 'created_at',
      header: 'Waiting',
      sortable: true,
      width: '130px',
      render: (row) => (
        <span className="text-muted text-xs">{formatRelative(row.created_at)}</span>
      ),
    },
    {
      key: 'actions',
      header: '',
      width: '210px',
      render: (row) => {
        const isSelf = row.requested_from_id === actingUserId;
        return (
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <button
              className="btn btn-primary btn-sm"
              disabled={isSelf}
              title={
                isSelf
                  ? 'Separation of duties: you cannot decide an approval you requested'
                  : undefined
              }
              onClick={(e) => {
                e.stopPropagation();
                setMode('decide');
                setSelected(row);
              }}
            >
              <Check size={14} />
              Decide
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                setMode('escalate');
                setSelected(row);
              }}
            >
              <ArrowUpRight size={14} />
              Escalate
            </button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Approval Queue"
        description="Pending approvals, oldest first. No vendor is onboarded without a human decision here — the automation can route a case to this queue, but it cannot clear it."
      />

      <div className="callout callout-info">
        <Info size={16} />
        <div>
          <div className="callout-title">
            Separation of duties is enforced, not suggested
          </div>
          <div className="callout-body">
            You cannot decide an approval you requested. The button is disabled
            with the reason stated, and the server refuses the same action
            independently.
          </div>
        </div>
      </div>

      <Card title="Filters" subtitle={`${data?.total ?? 0} pending`}>
        <div className="row wrap" style={{ gap: 'var(--space-3)' }}>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '200px' }}
            value={approvalType}
            onChange={(e) => {
              setApprovalType(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Approval Types</option>
            {Object.keys(authority.data?.authority || {}).map((type) => (
              <option key={type} value={type}>
                {humanize(type)}
              </option>
            ))}
          </select>
          {approvalType && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setApprovalType('');
                setPage(1);
              }}
            >
              <X size={14} />
              Clear
            </button>
          )}
          <span className="text-xs text-muted">
            Acting as user #{actingUserId}
          </span>
        </div>
      </Card>

      {loading ? (
        <LoadingState label="Loading approvals…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.approvals.length === 0 ? (
        <EmptyState
          title="No approvals waiting"
          description="Cases routed to the standard approval step appear here. The queue is empty when every request has been decided."
        />
      ) : (
        <Card padded={false}>
          <DataTable
            columns={columns}
            data={data.approvals}
            keyExtractor={(r) => r.id}
            pagination={{
              page,
              pageSize,
              total: data.total,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        </Card>
      )}

      <Card
        title="Who may grant what"
        subtitle="Read from the API so the interface cannot disagree with the server about authority."
      >
        {authority.loading ? (
          <LoadingState label="Loading authority matrix…" />
        ) : authority.error ? (
          <ErrorState message={authority.error} onRetry={authority.reload} />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Approval type</th>
                  <th>Roles that may decide</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(authority.data?.authority || {}).map(
                  ([type, roles]) => (
                    <tr key={type}>
                      <td>
                        <Badge tone="info">{humanize(type)}</Badge>
                      </td>
                      <td>
                        <div className="row wrap" style={{ gap: 'var(--space-2)' }}>
                          {roles.map((role) => (
                            <Badge key={role} tone="neutral">
                              {humanize(role)}
                            </Badge>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <DecisionModal
        key={`${mode}-${selected?.id ?? 'none'}`}
        approval={selected}
        mode={mode}
        onClose={() => setSelected(null)}
        onDecided={reload}
      />

      <p className="text-xs text-muted">
        Decisions are append-only. An approval that has been decided cannot be
        re-decided — it must be escalated, or a new approval raised.
      </p>
    </div>
  );
}
