/** Audit Timeline - the system's own record of what it did and why.
 *
 * Deliberately read-only in the interface as well as the API. There is no edit
 * or delete affordance anywhere on this page, because "an audit trail an
 * application can edit is not an audit trail".
 *
 * The filter menu is populated from `/audit/types`, which reads the distinct
 * event types out of the data rather than a hard-coded list, so it cannot drift
 * away from the events actually being written.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { auditApi } from '../utils/api';
import { useApi } from '../hooks/useApi';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from '../components/ui';
import { ActorTypeBadge } from '../components/ui/badges';
import { formatDateTime, formatRelative } from '../utils/format';

const LIMIT_OPTIONS = [25, 50, 100, 200];

function SnapshotBlock({ title, value }: { title: string; value: unknown }) {
  if (!value || (typeof value === 'object' && Object.keys(value as object).length === 0)) {
    return null;
  }
  return (
    <details className="mt-2">
      <summary className="text-xs text-muted" style={{ cursor: 'pointer' }}>
        {title}
      </summary>
      <pre
        className="mono-sm"
        style={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-sm)',
          padding: 'var(--space-3)',
          marginTop: 'var(--space-2)',
          maxHeight: '340px',
          overflow: 'auto',
        }}
      >
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

export function AuditTimelinePage() {
  const [eventType, setEventType] = useState('');
  const [limit, setLimit] = useState(50);

  const { data, loading, error, reload } = useApi(
    () => auditApi.recent(limit, eventType || undefined),
    [limit, eventType]
  );

  const types = useApi(() => auditApi.types(), []);

  return (
    <div className="stack">
      <PageHeader
        title="Audit Timeline"
        description="Every recorded action, newest first. Deterministic assessments, AI events, human decisions and n8n callbacks are all written to the same trail so a reviewer can read one story."
        actions={
          <button className="btn btn-secondary" onClick={reload}>
            <RefreshCw size={15} />
            Refresh
          </button>
        }
      />

      <div className="callout">
        <div>
          <div className="callout-title">This view is read-only by design</div>
          <div className="callout-body">
            The audit endpoints accept no writes, and nothing in this interface
            offers to edit or remove an event. AI events carry model metadata —
            provider, model, prompt version, latency, token counts — and a
            structured summary of what was produced. They do not carry the
            model's private reasoning.
          </div>
        </div>
      </div>

      <Card title="Filters" subtitle={`${data?.total ?? 0} event(s)`}>
        <div className="row wrap" style={{ gap: 'var(--space-3)' }}>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '260px' }}
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
          >
            <option value="">All Event Types</option>
            {(types.data?.event_types || []).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select
            className="form-select"
            style={{ width: 'auto', minWidth: '140px' }}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                Last {n} events
              </option>
            ))}
          </select>
          {eventType && (
            <button className="btn btn-ghost btn-sm" onClick={() => setEventType('')}>
              Clear
            </button>
          )}
        </div>
      </Card>

      {loading ? (
        <LoadingState label="Loading audit events…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.events.length === 0 ? (
        <EmptyState
          title="No events"
          description={
            eventType
              ? `Nothing has been recorded with the type "${eventType}".`
              : 'The audit trail is empty. Events appear as cases are worked.'
          }
        />
      ) : (
        <Card padded={false}>
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: '170px' }}>When</th>
                  <th style={{ width: '110px' }}>Actor</th>
                  <th style={{ width: '210px' }}>Event</th>
                  <th>Description</th>
                  <th style={{ width: '110px' }}>Case</th>
                </tr>
              </thead>
              <tbody>
                {data.events.map((event) => (
                  <tr key={event.id}>
                    <td className="nowrap">
                      <div className="mono-sm">{formatDateTime(event.timestamp)}</div>
                      <div className="text-xs text-muted">
                        {formatRelative(event.timestamp)}
                      </div>
                    </td>
                    <td>
                      <ActorTypeBadge actorType={String(event.actor_type)} />
                      {event.actor_name && (
                        <div className="text-xs text-muted truncate" style={{ maxWidth: '100px' }}>
                          {event.actor_name}
                        </div>
                      )}
                    </td>
                    <td>
                      <Badge tone="neutral">{event.event_type}</Badge>
                    </td>
                    <td>
                      <div className="text-sm">{event.description}</div>
                      <SnapshotBlock title="Input snapshot" value={event.input_snapshot} />
                      <SnapshotBlock title="Output snapshot" value={event.output_snapshot} />
                      {event.metadata && (
                        <SnapshotBlock
                          title={`Model metadata${
                            event.metadata.model ? ` — ${String(event.metadata.model)}` : ''
                          }`}
                          value={event.metadata}
                        />
                      )}
                    </td>
                    <td>
                      {event.case_id ? (
                        <Link to={`/cases/${event.case_id}`} className="mono-sm">
                          #{event.case_id}
                        </Link>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {types.error && (
        <p className="text-xs text-muted">
          Could not load the event type list ({types.error}), so the filter may
          be incomplete. The events below are unaffected.
        </p>
      )}
    </div>
  );
}
