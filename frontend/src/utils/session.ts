/** Acting-user identity for the prototype.
 *
 * THIS IS A PROTOTYPE PLACEHOLDER FOR AUTHENTICATION.
 *
 * The API takes an explicit ``actor_user_id`` on every mutating call so that
 * the audit trail can record who decided what. In production that value must
 * come from the authenticated session, never from the client, because a client
 * that can name itself can name anyone. Here it is a declared value the
 * reviewer sets in Settings, and the UI labels it as declared rather than
 * authenticated wherever a decision is recorded.
 *
 * The backend's own checks -- role authority, separation of duties -- still run
 * against whatever id is supplied, so the control flow is real even though the
 * identity is not yet proven.
 */

const STORAGE_KEY = 'vendor_orch_acting_user_id';

export const DEFAULT_ACTING_USER_ID = 1;

export function getActingUserId(): number {
  const raw = localStorage.getItem(STORAGE_KEY);
  const parsed = raw === null ? NaN : Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_ACTING_USER_ID;
}

export function setActingUserId(id: number): void {
  if (Number.isFinite(id) && id > 0) {
    localStorage.setItem(STORAGE_KEY, String(id));
  }
}

export const AUTH_DISCLAIMER =
  'Prototype only: the acting user is declared in the client, not authenticated. ' +
  'In production this value must come from the server-side session.';
