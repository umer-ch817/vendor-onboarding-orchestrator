/** The four-phase stepper.
 *
 * Shows where a case is without exposing the state machine. Each step carries
 * the internal statuses behind it as a tooltip, so the raw value is available
 * to anyone debugging without being the first thing a reviewer reads.
 */

import { Check, X } from 'lucide-react';

import {
  PHASES,
  caseOutcome,
  isBlocked,
  stepStates,
  type CaseOutcome,
  type StepState,
} from '../../utils/phases';
import './PhaseStepper.css';

function outcomeLabel(outcome: NonNullable<CaseOutcome>): string {
  return outcome === 'live' ? 'Approved — this vendor is live' : 'Declined';
}

function marker(state: StepState, index: number) {
  if (state === 'done') return <Check size={12} strokeWidth={3} />;
  if (state === 'declined') return <X size={12} strokeWidth={3} />;
  return index + 1;
}

export function PhaseStepper({
  status,
  compact = false,
}: {
  status?: string | null;
  compact?: boolean;
}) {
  const states = stepStates(status);
  const blocked = isBlocked(status);
  const outcome = caseOutcome(status);

  return (
    <div
      className={`phase-stepper${compact ? ' phase-stepper-compact' : ''}`}
      role="list"
      aria-label="Case progress"
    >
      {PHASES.map((phase, index) => {
        const state = states[index];
        const blockedHere = blocked && phase.id === 'collect';

        return (
          <div
            key={phase.id}
            role="listitem"
            aria-current={state === 'current' ? 'step' : undefined}
            className={`phase-step phase-step-${state}${
              blockedHere ? ' phase-step-blocked' : ''
            }`}
            title={`${phase.label} — ${phase.statuses.join(' · ')}`}
          >
            <span className="phase-step-marker" aria-hidden="true">
              {marker(state, index)}
            </span>
            <span className="phase-step-label">
              {phase.label}
              {blockedHere && <span className="phase-step-flag">Blocked</span>}
            </span>
          </div>
        );
      })}

      {outcome && (
        <span className={`phase-outcome phase-outcome-${outcome}`}>
          {outcomeLabel(outcome)}
        </span>
      )}
    </div>
  );
}
