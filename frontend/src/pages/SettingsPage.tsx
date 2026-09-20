/** Settings - configuration that is honest about what the prototype does not have.
 *
 * Three things live here: the declared acting identity, the API connection, and
 * a read-only view of the backend's metric definitions. The first exists because
 * the API needs an actor id on every mutating call and this prototype has no
 * authentication; the page says so plainly rather than implying a login.
 */

import { useState } from 'react';
import { KeyRound, ShieldAlert, UserCog } from 'lucide-react';
import { dashboardApi } from '../utils/api';
import { useApi } from '../hooks/useApi';
import {
  Badge,
  Card,
  DefinitionList,
  ErrorState,
  LoadingState,
  PageHeader,
  humanize,
} from '../components/ui';
import {
  AUTH_DISCLAIMER,
  DEFAULT_ACTING_USER_ID,
  getActingUserId,
  setActingUserId,
} from '../utils/session';

export function SettingsPage() {
  const [userId, setUserId] = useState<number>(getActingUserId());
  const [apiKey, setApiKey] = useState<string>(
    localStorage.getItem('vendor_orch_api_key') || ''
  );
  const [saved, setSaved] = useState<string | null>(null);

  const metrics = useApi(() => dashboardApi.full(), []);

  const saveIdentity = () => {
    setActingUserId(userId);
    setSaved('Acting user updated.');
  };

  const saveApiKey = () => {
    if (apiKey.trim()) {
      localStorage.setItem('vendor_orch_api_key', apiKey.trim());
    } else {
      localStorage.removeItem('vendor_orch_api_key');
    }
    setSaved('API key updated. It is sent as the X-API-Key header on every request.');
  };

  return (
    <div className="stack">
      <PageHeader
        title="Settings"
        description="Configuration for this prototype deployment. Nothing here changes how the backend behaves — it changes who the interface says it is."
      />

      {saved && (
        <div className="callout callout-info">
          <div className="callout-body">{saved}</div>
        </div>
      )}

      <Card
        title={
          <span className="row" style={{ gap: 'var(--space-2)' }}>
            <UserCog size={16} />
            Acting user
          </span>
        }
        subtitle="Recorded against every decision made from this browser."
      >
        <div className="callout callout-warning mb-4">
          <ShieldAlert size={16} />
          <div>
            <div className="callout-title">Prototype security, not production security</div>
            <div className="callout-body">{AUTH_DISCLAIMER}</div>
          </div>
        </div>

        <div className="row wrap" style={{ gap: 'var(--space-3)' }}>
          <div className="form-group" style={{ marginBottom: 0, minWidth: '220px' }}>
            <label className="form-label" htmlFor="acting-user">
              Acting user id
            </label>
            <input
              id="acting-user"
              type="number"
              min={1}
              className="form-input"
              value={userId}
              onChange={(e) => setUserId(Number(e.target.value))}
            />
          </div>
          <button
            className="btn btn-primary"
            onClick={saveIdentity}
            disabled={!Number.isFinite(userId) || userId < 1}
            style={{ alignSelf: 'flex-end' }}
          >
            Save
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setUserId(DEFAULT_ACTING_USER_ID);
              setActingUserId(DEFAULT_ACTING_USER_ID);
              setSaved('Reset to the default acting user.');
            }}
            style={{ alignSelf: 'flex-end' }}
          >
            Reset to default ({DEFAULT_ACTING_USER_ID})
          </button>
        </div>

        <p className="text-xs text-muted mt-4">
          The server enforces role authority and separation of duties against
          this id, so the controls are real even though the identity is not
          proven. In production the id must come from the authenticated session
          and must never be supplied by the client.
        </p>
      </Card>

      <Card
        title={
          <span className="row" style={{ gap: 'var(--space-2)' }}>
            <KeyRound size={16} />
            API access
          </span>
        }
        subtitle="Optional. Sent as the X-API-Key header on every request."
      >
        <div className="form-group">
          <label className="form-label" htmlFor="api-key">
            API key
          </label>
          <input
            id="api-key"
            type="password"
            className="form-input"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Leave blank if the backend has no key configured"
            autoComplete="off"
          />
        </div>
        <div className="row" style={{ gap: 'var(--space-2)' }}>
          <button className="btn btn-primary btn-sm" onClick={saveApiKey}>
            Save key
          </button>
        </div>
        <p className="text-xs text-muted mt-4">
          Stored in this browser only and never committed. In production a
          browser-held key is not an acceptable credential — this exists so the
          prototype can talk to a key-protected backend during a demo.
        </p>
      </Card>

      <Card
        title="Metric definitions"
        subtitle="Read from the API, which ships these alongside the numbers so the dashboard and the backend cannot drift apart."
      >
        {metrics.loading ? (
          <LoadingState label="Loading definitions…" />
        ) : metrics.error ? (
          <ErrorState message={metrics.error} onRetry={metrics.reload} />
        ) : (
          <>
            <div className="row wrap mb-4" style={{ gap: 'var(--space-2)' }}>
              <Badge tone="neutral">
                {metrics.data?.dataset_label || 'Demo Dataset'}
              </Badge>
              <span className="text-xs text-muted">
                Figures are computed from synthetic records, not production
                traffic.
              </span>
            </div>
            <DefinitionList
              items={Object.entries(metrics.data?.definitions || {}).map(
                ([key, text]) => ({ label: humanize(key), value: text })
              )}
            />
            {Object.keys(metrics.data?.definitions || {}).length === 0 && (
              <p className="text-sm text-muted">
                The backend did not return metric definitions.
              </p>
            )}
          </>
        )}
      </Card>

      <Card
        title="What this prototype does not have"
        subtitle="Stated here so it is not mistaken for an oversight."
      >
        <DefinitionList
          items={[
            {
              label: 'Authentication',
              value:
                'None. Identity is declared in the browser. The backend enforces authority against the declared id, but cannot prove it.',
            },
            {
              label: 'Secret management',
              value:
                'Environment variables only, with no secret store. No production provider keys are committed to the repository.',
            },
            {
              label: 'Deployment',
              value:
                'Single-host Docker Compose. No TLS termination, no managed database, no backup story.',
            },
            {
              label: 'AI cost control',
              value:
                'A deterministic mock provider runs by default so the demo needs no API key. A real provider is opt-in via configuration.',
            },
          ]}
        />
      </Card>
    </div>
  );
}
