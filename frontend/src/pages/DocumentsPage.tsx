/** Document Review - the document intake and verification queue.
 *
 * Lists every document with its extraction state and lets a reviewer upload a
 * new one or trigger extraction. Verification itself happens on the document
 * detail page, where the extracted fields are visible next to the source.
 */

import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Search, Upload, X } from 'lucide-react';
import { documentsApi, onboardingApi } from '../utils/api';
import { useApi, useMutation } from '../hooks/useApi';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  PageHeader,
  humanize,
} from '../components/ui';
import { DocumentStatusBadge } from '../components/ui/badges';
import { formatConfidence, formatFileSize, formatRelative } from '../utils/format';

const STATUS_OPTIONS = [
  'pending',
  'processing',
  'extracted',
  'verified',
  'failed',
  'expired',
];

const TYPE_OPTIONS = [
  'certificate_of_insurance',
  'business_registration',
  'banking_confirmation',
  'supplier_questionnaire',
  'master_services_agreement',
  'voided_check',
  'tax_certificate',
  'other',
];

function UploadModal({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [caseId, setCaseId] = useState<number | ''>('');
  const [docType, setDocType] = useState('other');
  const [file, setFile] = useState<File | null>(null);

  // Only cases that can still accept documents are offered. Attaching a
  // document to a closed case would create a record with no workflow meaning.
  const cases = useApi(
    () => onboardingApi.list({ page_size: 100 }),
    [open]
  );

  const upload = useMutation(
    (vendorId: number, targetCaseId: number, f: File, type: string) =>
      documentsApi.upload(vendorId, targetCaseId, f, type)
  );

  const selectedCase = cases.data?.cases.find((c) => c.id === Number(caseId));

  const submit = async () => {
    if (!file || !selectedCase) return;
    const result = await upload.run(
      selectedCase.vendor_id,
      selectedCase.id,
      file,
      docType
    );
    if (result !== null) {
      setFile(null);
      setCaseId('');
      setDocType('other');
      if (fileInput.current) fileInput.current.value = '';
      onUploaded();
      onClose();
    }
  };

  return (
    <Modal
      open={open}
      title="Upload a document"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={!file || !selectedCase || upload.pending}
          >
            {upload.pending ? 'Uploading…' : 'Upload'}
          </button>
        </>
      }
    >
      {upload.error && (
        <div className="callout callout-critical mb-4">
          <div className="callout-body">{upload.error}</div>
        </div>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor="upload-case">
          Case
        </label>
        <select
          id="upload-case"
          className="form-select"
          value={caseId}
          onChange={(e) => setCaseId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">Select the case this belongs to…</option>
          {(cases.data?.cases || []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.case_number} — {c.vendor?.legal_name || `vendor #${c.vendor_id}`}
            </option>
          ))}
        </select>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="upload-type">
          Document type
        </label>
        <select
          id="upload-type"
          className="form-select"
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
        >
          {TYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {humanize(t)}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted mt-2">
          The type determines which fields extraction looks for and which
          requirements it satisfies.
        </p>
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="upload-file">
          File
        </label>
        <input
          id="upload-file"
          ref={fileInput}
          type="file"
          className="form-input"
          accept=".pdf,.png,.jpg,.jpeg,.txt"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        {file && (
          <p className="text-xs text-muted mt-2">
            {file.name} — {formatFileSize(file.size)}
          </p>
        )}
      </div>

      <p className="text-xs text-muted">
        Uploading stores the file and records it against the case. Extraction
        runs as a separate step, so it can be retried without re-uploading.
      </p>
    </Modal>
  );
}

export function DocumentsPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState('');
  const [documentType, setDocumentType] = useState('');
  const [showUpload, setShowUpload] = useState(false);

  const { data, loading, error, reload } = useApi(
    () =>
      documentsApi.list({
        page,
        page_size: pageSize,
        status: status || undefined,
        document_type: documentType || undefined,
      }),
    [page, pageSize, status, documentType]
  );

  const columns = useMemo<Column<any>[]>(
    () => [
      {
        key: 'filename',
        header: 'File',
        sortable: true,
        render: (row) => (
          <Link
            to={`/documents/${row.id}`}
            className="row"
            style={{ gap: 'var(--space-2)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <FileText size={15} className="text-muted" />
            <span className="truncate" style={{ maxWidth: '280px' }}>
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
        key: 'case_id',
        header: 'Case',
        sortable: true,
        width: '110px',
        render: (row) => (
          <Link to={`/cases/${row.case_id}`} className="mono-sm">
            #{row.case_id}
          </Link>
        ),
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
        key: 'verification_status',
        header: 'Verified',
        sortable: true,
        render: (row) => humanize(row.verification_status),
      },
      {
        key: 'file_size',
        header: 'Size',
        sortable: true,
        align: 'right',
        render: (row) => formatFileSize(row.file_size),
      },
      {
        key: 'uploaded_at',
        header: 'Uploaded',
        sortable: true,
        render: (row) => (
          <span className="text-muted text-xs">
            {formatRelative(row.uploaded_at)}
          </span>
        ),
      },
    ],
    []
  );

  const hasFilters = Boolean(status || documentType);

  return (
    <div className="stack">
      <PageHeader
        title="Documents"
        description="Every document in the system, with its extraction state. Low extraction confidence is the signal to look closer, not a failure on its own."
        actions={
          <button className="btn btn-primary" onClick={() => setShowUpload(true)}>
            <Upload size={16} />
            Upload
          </button>
        }
      />

      <Card title="Filters" subtitle={`${data?.total ?? 0} document(s) matching`}>
        <div className="row wrap" style={{ gap: 'var(--space-3)' }}>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '170px' }}
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
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
            style={{ width: 'auto', minWidth: '220px' }}
            value={documentType}
            onChange={(e) => {
              setDocumentType(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Document Types</option>
            {TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {humanize(t)}
              </option>
            ))}
          </select>
          {hasFilters && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setStatus('');
                setDocumentType('');
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
        <LoadingState label="Loading documents…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.documents.length === 0 ? (
        <EmptyState
          title="No documents"
          description={
            hasFilters
              ? 'No document matches these filters.'
              : 'Upload the first document to begin collection.'
          }
          icon={FileText}
        />
      ) : (
        <Card padded={false}>
          <DataTable
            columns={columns}
            data={data.documents}
            keyExtractor={(r) => r.id}
            defaultSort={{ key: 'uploaded_at', direction: 'desc' }}
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

      <p className="text-xs text-muted row" style={{ gap: 'var(--space-2)' }}>
        <Search size={13} />
        Tip: open a document to compare its extracted fields against the source
        and record a verification decision.
      </p>

      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onUploaded={reload}
      />
    </div>
  );
}
