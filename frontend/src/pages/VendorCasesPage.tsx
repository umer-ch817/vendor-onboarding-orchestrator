/** Vendor Cases - the main operational queue.
 *
 * Filterable, paginated list with an inline create flow. This is a reviewer's
 * first stop for "what is on my plate today".
 */

import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Filter, Plus, Search, X } from 'lucide-react';
import { onboardingApi, vendorsApi } from '../utils/api';
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
import { WorkflowStatusBadge, RiskBadge } from '../components/ui/badges';
import { formatRelative, riskRank } from '../utils/format';
import type { OnboardingCaseCreate } from '../types';

type WorkflowStatus =
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

const STATUS_OPTIONS: WorkflowStatus[] = [
  'draft',
  'submitted',
  'document_collection',
  'extraction',
  'validation',
  'risk_analysis',
  'review_required',
  'approval_pending',
  'approved',
  'rejected',
  'onboarding_complete',
  'blocked',
];

const RISK_OPTIONS = ['critical', 'high', 'medium', 'low'];
const PRIORITY_OPTIONS = ['low', 'normal', 'high', 'urgent'];

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

/** Create form. Kept local to the queue because it is only used here. */
function NewCaseModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [vendorId, setVendorId] = useState<number | ''>('');
  const [requesterName, setRequesterName] = useState('');
  const [requesterEmail, setRequesterEmail] = useState('');
  const [department, setDepartment] = useState('');
  const [priority, setPriority] = useState('normal');

  const vendors = useApi(() => vendorsApi.list({ page_size: 100 }), [open]);

  const create = useMutation((payload: OnboardingCaseCreate) =>
    onboardingApi.create(payload)
  );

  const submit = async () => {
    if (!vendorId) return;
    const result = await create.run({
      vendor_id: Number(vendorId),
      requester_name: requesterName || undefined,
      requester_email: requesterEmail || undefined,
      requester_department: department || undefined,
      priority,
    });
    if (result) {
      setVendorId('');
      setRequesterName('');
      setRequesterEmail('');
      setDepartment('');
      setPriority('normal');
      onCreated();
      onClose();
    }
  };

  return (
    <Modal
      open={open}
      title="Open an onboarding case"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={!vendorId || create.pending}
          >
            {create.pending ? 'Creating…' : 'Create case'}
          </button>
        </>
      }
    >
      {create.error && (
        <div className="callout callout-critical mb-4">
          <div className="callout-body">{create.error}</div>
        </div>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor="new-case-vendor">
          Vendor
        </label>
        <select
          id="new-case-vendor"
          className="form-select"
          value={vendorId}
          onChange={(e) =>
            setVendorId(e.target.value ? Number(e.target.value) : '')
          }
        >
          <option value="">Select a vendor…</option>
          {(vendors.data?.vendors || []).map((v) => (
            <option key={v.id} value={v.id}>
              {v.legal_name}
            </option>
          ))}
        </select>
        {vendors.loading && (
          <div className="text-xs text-muted mt-2">Loading vendors…</div>
        )}
      </div>

      <div className="grid grid-2">
        <div className="form-group">
          <label className="form-label" htmlFor="new-case-requester">
            Requester name
          </label>
          <input
            id="new-case-requester"
            className="form-input"
            value={requesterName}
            onChange={(e) => setRequesterName(e.target.value)}
          />
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="new-case-email">
            Requester email
          </label>
          <input
            id="new-case-email"
            className="form-input"
            type="email"
            value={requesterEmail}
            onChange={(e) => setRequesterEmail(e.target.value)}
          />
        </div>
      </div>

      <div className="grid grid-2">
        <div className="form-group">
          <label className="form-label" htmlFor="new-case-dept">
            Department
          </label>
          <input
            id="new-case-dept"
            className="form-input"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          />
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="new-case-priority">
            Priority
          </label>
          <select
            id="new-case-priority"
            className="form-select"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
          >
            {PRIORITY_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {humanize(p)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="text-xs text-muted">
        Creating a case does not start any automated decision. The case begins in
        draft and only advances when a reviewer submits it.
      </p>
    </Modal>
  );
}

export function VendorCasesPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<WorkflowStatus | ''>('');
  const [riskLevel, setRiskLevel] = useState<string>('');
  const [search, setSearch] = useState('');
  const [showNew, setShowNew] = useState(false);

  const { data, loading, error, reload } = useApi(
    () =>
      onboardingApi.list({
        page,
        page_size: pageSize,
        status: status || undefined,
        risk_level: riskLevel || undefined,
        search: search || undefined,
      }),
    [page, pageSize, status, riskLevel, search]
  );

  const columns = useMemo<Column<any>[]>(
    () => [
      {
        key: 'case_number',
        header: 'Case #',
        sortable: true,
        width: '130px',
        render: (row) => (
          <Link
            to={`/cases/${row.id}`}
            className="font-mono text-sm"
            onClick={(e) => e.stopPropagation()}
          >
            {row.case_number}
          </Link>
        ),
      },
      {
        key: 'vendor',
        header: 'Vendor',
        sortable: false,
        width: '220px',
        render: (row) => (
          <div>
            <div className="truncate" style={{ maxWidth: '200px', fontWeight: 500 }}>
              {row.vendor?.legal_name || '—'}
            </div>
            {row.vendor?.trade_name && (
              <div
                className="text-xs text-muted truncate"
                style={{ maxWidth: '200px' }}
              >
                {row.vendor.trade_name}
              </div>
            )}
          </div>
        ),
      },
      {
        key: 'workflow_status',
        header: 'Status',
        sortable: true,
        width: '170px',
        render: (row) => <WorkflowStatusBadge status={row.workflow_status} />,
      },
      {
        key: 'priority',
        header: 'Priority',
        sortable: true,
        width: '100px',
        render: (row) => {
          const p = (row.priority || '').toLowerCase();
          const tone = p === 'urgent' ? 'critical' : p === 'high' ? 'high' : 'neutral';
          return <Badge tone={tone as any}>{humanize(row.priority)}</Badge>;
        },
      },
      {
        key: 'risk_score',
        header: 'Risk Score',
        sortable: true,
        width: '110px',
        align: 'right',
        render: (row) => (
          <span
            className="font-mono"
            style={{ color: riskColor(row.risk_level), fontWeight: 600 }}
          >
            {row.risk_score}
          </span>
        ),
      },
      {
        key: 'risk_level',
        header: 'Risk Level',
        sortable: true,
        width: '110px',
        render: (row) => <RiskBadge level={row.risk_level} />,
      },
      {
        key: 'completion_percentage',
        header: 'Completion',
        sortable: true,
        width: '150px',
        render: (row) => (
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <div className="progress-track" style={{ flex: 1, minWidth: '70px' }}>
              <div
                className="progress-fill"
                style={{ width: `${row.completion_percentage}%` }}
              />
            </div>
            <span className="text-xs mono-sm">{row.completion_percentage}%</span>
          </div>
        ),
      },
      {
        key: 'documents_received',
        header: 'Docs',
        sortable: true,
        width: '90px',
        align: 'center',
        render: (row) => (
          <Badge
            tone={
              row.documents_received >= row.documents_required
                ? 'success'
                : 'medium'
            }
          >
            {row.documents_received}/{row.documents_required}
          </Badge>
        ),
      },
      {
        key: 'updated_at',
        header: 'Last Updated',
        sortable: true,
        width: '140px',
        render: (row) => (
          <span className="text-muted text-xs mono-sm">
            {formatRelative(row.updated_at)}
          </span>
        ),
      },
    ],
    []
  );

  const rowClassName = (row: any) => {
    const rank = riskRank(row.risk_level);
    if (rank >= 4) return 'row-critical';
    if (rank >= 3) return 'row-high';
    if (rank >= 2) return 'row-medium';
    if (rank >= 1) return 'row-low';
    return '';
  };

  const hasActiveFilters = Boolean(status || riskLevel || search);

  return (
    <div className="stack">
      <PageHeader
        title="Vendor Cases"
        description="All onboarding cases across the pipeline. Filter by status or risk level to focus your queue."
        actions={
          <button className="btn btn-primary" onClick={() => setShowNew(true)}>
            <Plus size={16} />
            New Case
          </button>
        }
      />

      <Card
        title="Filters"
        subtitle={`${data?.total ?? 0} case(s) matching`}
      >
        <div className="row wrap" style={{ gap: 'var(--space-3)' }}>
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <Search size={16} className="text-muted" />
            <input
              type="text"
              className="form-input"
              placeholder="Search case number or vendor…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              style={{ width: '280px' }}
            />
          </div>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '180px' }}
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as WorkflowStatus | '');
              setPage(1);
            }}
          >
            <option value="">All Statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '160px' }}
            value={riskLevel}
            onChange={(e) => {
              setRiskLevel(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Risk Levels</option>
            {RISK_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {humanize(r)}
              </option>
            ))}
          </select>
          {hasActiveFilters && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setStatus('');
                setRiskLevel('');
                setSearch('');
                setPage(1);
              }}
            >
              <X size={14} />
              Clear filters
            </button>
          )}
        </div>
      </Card>

      {loading ? (
        <LoadingState label="Loading cases…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.cases.length === 0 ? (
        <EmptyState
          title="No cases found"
          description={
            hasActiveFilters
              ? 'No case matches these filters. Try clearing them.'
              : 'Open the first onboarding case to get started.'
          }
          icon={Filter}
        />
      ) : (
        <Card padded={false}>
          <DataTable
            columns={columns}
            data={data.cases}
            keyExtractor={(r) => r.id}
            rowClassName={rowClassName}
            defaultSort={{ key: 'updated_at', direction: 'desc' }}
            pagination={{
              page: data.page,
              pageSize: data.page_size,
              total: data.total,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
            onRowClick={(row) => navigate(`/cases/${row.id}`)}
          />
        </Card>
      )}

      <NewCaseModal
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={reload}
      />
    </div>
  );
}
