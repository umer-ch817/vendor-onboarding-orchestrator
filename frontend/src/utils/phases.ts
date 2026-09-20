/** The four phases a person sees, and the twelve statuses the backend stores.
 *
 * Twelve states is the right number for a state machine and the wrong number
 * for a human. Nobody scanning a queue wants to weigh `document_collection`
 * against `validation`. These four collapse them; the raw status is never
 * discarded, it is one tooltip away.
 *
 * Wording lives in docs/ui-copy.md and is deliberately not duplicated here as
 * prose -- this module owns the mapping only.
 */

export type PhaseId = 'setup' | 'collect' | 'score' | 'signoff';

export interface Phase {
  id: PhaseId;
  label: string;
  /** Internal statuses behind this phase, in the order they occur. */
  statuses: string[];
}

export const PHASES: Phase[] = [
  { id: 'setup', label: 'Set up', statuses: ['draft', 'submitted'] },
  {
    id: 'collect',
    label: 'Collect',
    statuses: ['document_collection', 'extraction', 'validation', 'blocked'],
  },
  { id: 'score', label: 'Score', statuses: ['risk_analysis', 'review_required'] },
  {
    id: 'signoff',
    label: 'Sign-off',
    statuses: ['approval_pending', 'approved', 'rejected', 'onboarding_complete'],
  },
];

export type StepState = 'done' | 'current' | 'upcoming' | 'declined';

/** How a case ended, once it has ended. Null while it is still moving. */
export type CaseOutcome = 'live' | 'declined' | null;

function normalise(status?: string | null): string {
  return (status || '').toLowerCase();
}

/** Index into PHASES, or -1 for an unknown status. */
export function phaseIndexForStatus(status?: string | null): number {
  const s = normalise(status);
  return PHASES.findIndex((phase) => phase.statuses.includes(s));
}

export function phaseForStatus(status?: string | null): Phase | null {
  const index = phaseIndexForStatus(status);
  return index === -1 ? null : PHASES[index];
}

/**
 * `blocked` sits in Collect rather than being a fifth phase: every blocking
 * finding in the rules engine concerns a document or tax information, so a
 * case is never blocked for a scoring reason.
 */
export function isBlocked(status?: string | null): boolean {
  return normalise(status) === 'blocked';
}

/**
 * Statuses that close their phase even though they sit inside it.
 *
 * `submitted` lives in Set up, but it means the case has left the user's hands
 * and the orchestrator has taken over. Rendering it as "still setting up" would
 * make the Submit button look like it did nothing -- and in a demo that reads
 * as broken. So Set up is drawn complete and Collect becomes current, which is
 * where the workflow goes next.
 *
 * Deliberately not generalised to "any non-first status closes its phase":
 * `extraction` is the second status in Collect but is still collecting, so that
 * rule would wrongly jump the case to Score.
 */
const PHASE_CLOSING = new Set(['submitted']);

export function caseOutcome(status?: string | null): CaseOutcome {
  const s = normalise(status);
  if (s === 'approved' || s === 'onboarding_complete') return 'live';
  if (s === 'rejected') return 'declined';
  return null;
}

/**
 * Per-step state for the stepper.
 *
 * A terminal case marks Sign-off done rather than current, except `rejected`,
 * which is drawn as its own state: showing a declined case as a completed
 * fourth step would claim it advanced, when the truth is it stopped.
 */
export function stepStates(status?: string | null): StepState[] {
  const s = normalise(status);
  const current = phaseIndexForStatus(s);

  if (current === -1) return PHASES.map(() => 'upcoming');

  if (s === 'rejected') {
    return PHASES.map((_, i) =>
      i < current ? 'done' : i === current ? 'declined' : 'upcoming',
    );
  }

  // Which step the case is on. Normally the step containing its status, but a
  // phase-closing status advances past the phase it lives in.
  const active = PHASE_CLOSING.has(s) ? current + 1 : current;

  const settled = s === 'approved' || s === 'onboarding_complete';
  const reached = settled ? PHASES.length : active;

  return PHASES.map((_, i) =>
    i < reached ? 'done' : i === reached ? 'current' : 'upcoming',
  );
}
