/** Document Review - one document, its extracted fields, and the verify action.
 *
 * The page is built around a single comparison: what the model read, and how
 * sure it was. Fields below the configured threshold are the ones a reviewer
 * should look at first, so confidence is rendered per field rather than as a
 * single headline number.
 */

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, BadgeCheck, RefreshCw, ShieldQuestion } from 'lucide-react';
import { documentsApi } from '../utils/api';
import { useApi, useMutation } from '../hooks/useApi';
import {
  Badge,
  Card,
  DefinitionList,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  PageHeader,
  humanize,
} from '../components/ui';
import { DocumentStatusBadge } from '../components/ui/badges';
import {
  formatConfidence,
  formatDate,
  formatDateTime,
  formatFileSize,
  textOrDash,
} from '../utils/format';

/** Matches CONFIDENCE_HIGH in the backend config. Kept as a display constant
 * only -- thresholds that gate behaviour must come from the backend. */
const CONFIDENCE_DISPLAY_HIGH = 0.9;
const CONFIDENCE_DISPLAY_MEDIUM = 0.75;

function confidenceTone(value?: number | null): 'success' | 'medium' | 'critical' | 'neutral' {
  if (value === null || value === undefined) return 'neutral';
  if (value >= CONFIDENCE_DISPLAY_HIGH) return 'success';
  if (value >= CONFIDENCE_DISPLAY_MEDIUM) return 'medium';
  return 'critical';
}

export function DocumentDetailPage() {
  const { documentId: idParam } = useParams<{ documentId: string }>();
  const documentId = Number(idParam);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [verified, setVerified] = useState(true);
  const [notes, setNotes] = useState('');

  const { data, loading, error, reload } = useApi(
    () => documentsApi.get(documentId),
    [documentId]
  );

  const process = useMutation(() => documentsApi.process(documentId));
  const verify = useMutation(() =>
    documentsApi.verify(documentId, verified, notes || undefined)
  );

  if (!Number.isFinite(documentId)) {
    return <ErrorState message="That document id is not valid." />;
  }
  if (loading) return <LoadingState label="Loading document…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="Document not found" />;

  const fields = data.extracted_fields || [];
  const lowConfidence = fields.filter(
    (f) => f.confidence !== null && f.confidence !== undefined && f.confidence < CONFIDENCE_DISPLAY_MEDIUM
  );

  const runVerify = async () => {
    const result = await verify.run();
    if (result !== null) {
      setVerifyOpen(false);
      setNotes('');
      reload();
    }
  };

  return (
    <div className="stack">
      <PageHeader
        breadcrumb={
          <Link to="/documents" className="row" style={{ gap: '4px' }}>
            <ArrowLeft size={12} /> Back to Documents
          </Link>
        }
        title={data.filename}
        description={
          <span className="row wrap" style={{ gap: 'var(--space-2)' }}>
            <DocumentStatusBadge status={data.status} />
            <Badge tone="neutral">{humanize(data.document_type)}</Badge>
            {data.extraction_confidence !== null &&
              data.extraction_confidence !== undefined && (
                <Badge tone={confidenceTone(data.extraction_confidence)}>
                  Extraction {formatConfidence(data.extraction_confidence)}
                </Badge>
              )}
          </span>
        }
        actions={
          <>
            <button
              className="btn btn-secondary"
              onClick={async () => {
                const ok = await process.run();
                if (ok !== null) reload();
              }}
              disabled={process.pending}
            >
              <RefreshCw size={15} />
              {process.pending ? 'Extracting…' : 'Re-run extraction'}
            </button>
            <button className="btn btn-primary" onClick={() => setVerifyOpen(true)}>
              <BadgeCheck size={15} />
              Record verification
            </button>
          </>
        }
      />

      {(process.error || verify.error) && (
        <div className="callout callout-critical">
          <div className="callout-body">{process.error || verify.error}</div>
        </div>
      )}

      {lowConfidence.length > 0 && (
        <div className="callout callout-warning">
          <ShieldQuestion size={16} />
          <div>
            <div className="callout-title">
              {lowConfidence.length} field
              {lowConfidence.length === 1 ? '' : 's'} below the medium confidence
              threshold
            </div>
            <div className="callout-body">
              These were read with less than {Math.round(CONFIDENCE_DISPLAY_MEDIUM * 100)}%
              confidence and are worth checking against the source document
              before this document is relied upon.
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-2">
        <Card title="Document">
          <DefinitionList
            items={[
              { label: 'Filename', value: data.filename },
              { label: 'Type', value: humanize(data.document_type) },
              { label: 'Case', value: <Link to={`/cases/${data.case_id}`} className="mono-sm">#{data.case_id}</Link> },
              { label: 'Vendor', value: <span className="mono-sm">#{data.vendor_id}</span> },
              { label: 'MIME type', value: textOrDash(data.mime_type) },
              { label: 'Size', value: formatFileSize(data.file_size) },
            ]}
          />
        </Card>

        <Card title="Processing">
          <DefinitionList
            items={[
              { label: 'Status', value: <DocumentStatusBadge status={data.status} /> },
              { label: 'Extraction confidence', value: formatConfidence(data.extraction_confidence) },
              { label: 'Verification', value: humanize(data.verification_status) },
              { label: 'Document date', value: data.document_date ? formatDate(data.document_date) : '—' },
              { label: 'Expiration', value: data.expiration_date ? formatDate(data.expiration_date) : '—' },
              { label: 'Uploaded', value: formatDateTime(data.uploaded_at) },
              { label: 'Processed', value: data.processed_at ? formatDateTime(data.processed_at) : 'Not processed' },
            ]}
          />
          {data.verification_notes && (
            <div className="callout mt-4">
              <div>
                <div className="callout-title">Verification note</div>
                <div className="callout-body">{data.verification_notes}</div>
              </div>
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Extracted fields"
        subtitle="What the model read from this document, with the normalised form the rule engine compares against."
        padded={false}
      >
        {fields.length === 0 ? (
          <EmptyState
            title="Nothing extracted yet"
            description="Run extraction to populate the fields this document contributes to the assessment."
            icon={ShieldQuestion}
          />
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Extracted value</th>
                  <th>Normalised</th>
                  <th style={{ textAlign: 'right' }}>Confidence</th>
                  <th>Valid</th>
                  <th>Corrected</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.id}>
                    <td className="mono-sm">{f.field_name}</td>
                    <td>{textOrDash(f.field_value)}</td>
                    <td className="text-muted text-sm">
                      {textOrDash(f.normalized_value)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <Badge tone={confidenceTone(f.confidence)}>
                        {formatConfidence(f.confidence)}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={f.is_valid ? 'success' : 'critical'}>
                        {f.is_valid ? 'Valid' : 'Invalid'}
                      </Badge>
                    </td>
                    <td>
                      {f.manually_corrected ? (
                        <Badge tone="info">Corrected</Badge>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={verifyOpen}
        title="Record a verification decision"
        onClose={() => setVerifyOpen(false)}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setVerifyOpen(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={runVerify}
              disabled={verify.pending}
            >
              {verify.pending ? 'Recording…' : 'Record'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label className="form-label">Decision</label>
          <div className="row" style={{ gap: 'var(--space-3)' }}>
            <label className="row" style={{ gap: 'var(--space-1)' }}>
              <input
                type="radio"
                checked={verified}
                onChange={() => setVerified(true)}
              />
              Verified — the document is acceptable
            </label>
            <label className="row" style={{ gap: 'var(--space-1)' }}>
              <input
                type="radio"
                checked={!verified}
                onChange={() => setVerified(false)}
              />
              Rejected — the document is not acceptable
            </label>
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="verify-notes">
            Notes
          </label>
          <textarea
            id="verify-notes"
            className="form-textarea"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={
              verified
                ? 'Optional — what you checked.'
                : 'Required when rejecting — what is wrong with it.'
            }
          />
        </div>

        <p className="text-xs text-muted">
          Verification records who decided and when. It does not delete or alter
          the extracted fields, so the audit trail keeps both the machine's
          reading and the reviewer's judgement.
        </p>
      </Modal>
    </div>
  );
}
