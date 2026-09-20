/** Domain-specific badges.
 *
 * These wrap the generic <Badge> with the mapping from a domain enum to a
 * colour tone, so the "is this good or bad" decision lives in one place rather
 * than being re-guessed on each page.
 */

import { Badge, BadgeTone, humanize } from './index';
import type { ExceptionSeverity, RiskLevel } from '../../types';

function riskTone(level?: string | null): BadgeTone {
  switch ((level || '').toLowerCase()) {
    case 'critical':
      return 'critical';
    case 'high':
      return 'high';
    case 'medium':
      return 'medium';
    case 'low':
      return 'low';
    default:
      return 'neutral';
  }
}

export function RiskBadge({ level }: { level?: RiskLevel | string | null }) {
  if (!level) return <Badge tone="neutral">Unscored</Badge>;
  return <Badge tone={riskTone(level)}>{humanize(level)}</Badge>;
}

export function SeverityBadge({
  severity,
}: {
  severity?: ExceptionSeverity | string | null;
}) {
  if (!severity) return <Badge tone="neutral">Unrated</Badge>;
  return <Badge tone={riskTone(severity)}>{humanize(severity)}</Badge>;
}

/**
 * Workflow status tone.
 *
 * Note that "rejected" and "blocked" are not failures of the system — they are
 * terminal-ish states a reviewer deliberately produced. They are coloured for
 * urgency, not for error.
 */
export function WorkflowStatusBadge({ status }: { status?: string | null }) {
  const s = (status || '').toLowerCase();
  let tone: BadgeTone = 'neutral';

  if (s === 'onboarding_complete') tone = 'success';
  else if (s === 'approved') tone = 'success';
  else if (s === 'rejected') tone = 'critical';
  else if (s === 'blocked') tone = 'high';
  else if (s === 'review_required') tone = 'high';
  else if (s === 'approval_pending') tone = 'medium';
  else if (s === 'risk_analysis') tone = 'info';
  else if (s === 'validation') tone = 'info';
  else if (s === 'extraction') tone = 'info';
  else if (s === 'document_collection') tone = 'info';
  else if (s === 'submitted') tone = 'medium';
  else if (s === 'draft') tone = 'neutral';

  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

export function ExceptionStatusBadge({ status }: { status?: string | null }) {
  const s = (status || '').toLowerCase();
  let tone: BadgeTone = 'neutral';
  if (s === 'open') tone = 'medium';
  else if (s === 'in_progress') tone = 'high';
  else if (s === 'escalated') tone = 'critical';
  else if (s === 'resolved') tone = 'success';
  else if (s === 'closed') tone = 'neutral';
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

export function ApprovalStatusBadge({ status }: { status?: string | null }) {
  const s = (status || '').toLowerCase();
  let tone: BadgeTone = 'neutral';
  if (s === 'pending') tone = 'medium';
  else if (s === 'approved') tone = 'success';
  else if (s === 'rejected') tone = 'critical';
  else if (s === 'escalated') tone = 'high';
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

export function DocumentStatusBadge({ status }: { status?: string | null }) {
  const s = (status || '').toLowerCase();
  let tone: BadgeTone = 'neutral';
  if (s === 'verified') tone = 'success';
  else if (s === 'extracted') tone = 'info';
  else if (s === 'processing') tone = 'medium';
  else if (s === 'pending') tone = 'medium';
  else if (s === 'failed') tone = 'critical';
  else if (s === 'expired') tone = 'high';
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

export function ActorTypeBadge({ actorType }: { actorType?: string | null }) {
  const s = (actorType || '').toLowerCase();
  let tone: BadgeTone = 'neutral';
  if (s === 'ai') tone = 'info';
  else if (s === 'n8n') tone = 'medium';
  else if (s === 'user') tone = 'success';
  else if (s === 'system') tone = 'neutral';
  return <Badge tone={tone} title={`Recorded actor: ${humanize(actorType)}`}>
    {s === 'ai' ? 'AI' : s === 'n8n' ? 'n8n' : humanize(actorType)}
  </Badge>;
}

/** Renders a numeric risk score with its level as a tone. */
export function RiskScore({
  score,
  level,
}: {
  score?: number | null;
  level?: string | null;
}) {
  if (score === null || score === undefined) {
    return <span className="text-muted">—</span>;
  }
  const tone = riskTone(level);
  const color =
    tone === 'critical'
      ? 'var(--color-critical)'
      : tone === 'high'
      ? 'var(--color-high)'
      : tone === 'medium'
      ? 'var(--color-medium)'
      : tone === 'low'
      ? 'var(--color-low)'
      : 'var(--color-text)';
  return (
    <span
      className="font-mono"
      style={{ color, fontWeight: 600 }}
      title={level ? `Risk level: ${humanize(level)}` : undefined}
    >
      {score}
    </span>
  );
}

/** Inline note used where a value is missing because nothing has measured it. */
export function NotMeasured({ reason }: { reason: string }) {
  return (
    <span className="text-muted" title={reason}>
      Not measured
    </span>
  );
}
