/** Formatting helpers shared by the operational views.
 *
 * Deliberate defaults: an absent value renders as an em dash rather than "0"
 * or "Invalid Date". A reviewer scanning a queue must be able to tell "we have
 * no data for this" apart from "the value is zero".
 */

import { format, formatDistanceToNowStrict, isValid, parseISO } from 'date-fns';

export const EM_DASH = '—';

/** Parses an ISO timestamp, tolerating a missing trailing timezone. */
function toDate(value?: string | null): Date | null {
  if (!value) return null;
  const parsed = parseISO(value);
  return isValid(parsed) ? parsed : null;
}

export function formatDate(value?: string | null): string {
  const date = toDate(value);
  return date ? format(date, 'd MMM yyyy') : EM_DASH;
}

export function formatDateTime(value?: string | null): string {
  const date = toDate(value);
  return date ? format(date, 'd MMM yyyy, HH:mm') : EM_DASH;
}

export function formatTime(value?: string | null): string {
  const date = toDate(value);
  return date ? format(date, 'HH:mm:ss') : EM_DASH;
}

export function formatRelative(value?: string | null): string {
  const date = toDate(value);
  if (!date) return EM_DASH;
  return `${formatDistanceToNowStrict(date)} ago`;
}

/** Formats a 0–1 confidence as a percentage. Null is "not scored", not 0%. */
export function formatConfidence(value?: number | null): string {
  if (value === null || value === undefined) return EM_DASH;
  return `${Math.round(value * 100)}%`;
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined) return EM_DASH;
  return value.toLocaleString('en-US');
}

/** Days with one decimal, because a 0.4-day difference still matters. */
export function formatDays(value?: number | null): string {
  if (value === null || value === undefined) return 'Not yet measured';
  return `${value.toFixed(1)} days`;
}

export function formatFileSize(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return EM_DASH;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Truncates a long id/hash for display without lying about its length. */
export function shortHash(value?: string | null, head = 10): string {
  if (!value) return EM_DASH;
  return value.length <= head + 2 ? value : `${value.slice(0, head)}…`;
}

export function textOrDash(value?: string | number | null): string {
  if (value === null || value === undefined || value === '') return EM_DASH;
  return String(value);
}

/** Risks are "worse" in a fixed order; used to pick a row's accent colour. */
export function riskRank(level?: string | null): number {
  switch ((level || '').toLowerCase()) {
    case 'critical':
      return 4;
    case 'high':
      return 3;
    case 'medium':
      return 2;
    case 'low':
      return 1;
    default:
      return 0;
  }
}
