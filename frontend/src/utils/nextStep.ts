/** "What happens next" wording, and the risk-score wording.
 *
 * Both are pure lookups with no component logic, so the copy can be changed in
 * one place and tested without rendering anything. The approved wording lives
 * in docs/ui-copy.md; this is where it becomes code.
 */

export type StepOwner = 'you' | 'system' | 'reviewer' | 'approver' | 'none';

export interface NextStep {
  headline: string;
  detail: string;
  owner: StepOwner;
}

const OWNER_LABELS: Record<StepOwner, string> = {
  you: 'Waiting on you',
  system: 'Running automatically',
  reviewer: 'Waiting on a reviewer',
  approver: 'Waiting on an approver',
  none: 'Nothing needed',
};

/** Unknown status: say what we know rather than inventing progress. */
const UNKNOWN: NextStep = {
  headline: 'Status unknown.',
  detail: 'This case has a status the interface does not recognise yet.',
  owner: 'none',
};

const STEPS: Record<string, NextStep> = {
  draft: {
    headline: "Add the vendor's details to begin.",
    detail: 'Fill in the form, then press Start onboarding.',
    owner: 'you',
  },
  submitted: {
    headline: 'Automation is running.',
    detail: 'Usually under a minute. Nothing to do.',
    owner: 'system',
  },
  document_collection: {
    headline: 'Waiting on documents.',
    detail: 'Upload the documents still needed, listed below.',
    owner: 'you',
  },
  extraction: {
    headline: 'Reading the uploaded documents.',
    detail: 'This finishes on its own.',
    owner: 'system',
  },
  validation: {
    headline: 'Checking the details against each other.',
    detail: 'This finishes on its own.',
    owner: 'system',
  },
  risk_analysis: {
    headline: 'Scoring risk.',
    detail: 'This finishes on its own.',
    owner: 'system',
  },
  blocked: {
    headline: "This can't continue yet.",
    detail: 'Fix the reason below — it is usually a missing document.',
    owner: 'you',
  },
  review_required: {
    headline: "Needs a person's decision.",
    detail: 'Resolve the open issues listed below.',
    owner: 'reviewer',
  },
  approval_pending: {
    headline: 'Waiting for an approver.',
    detail: 'Someone with authority approves or declines.',
    owner: 'approver',
  },
  approved: {
    headline: 'Approved — being set up.',
    detail: 'Nothing left to do.',
    owner: 'none',
  },
  rejected: {
    headline: 'Declined.',
    detail: 'Close it, or start again with corrected details.',
    owner: 'you',
  },
  onboarding_complete: {
    headline: 'Done — this vendor is live.',
    detail: 'Nothing left to do.',
    owner: 'none',
  },
};

export function nextStepFor(status?: string | null): NextStep {
  return STEPS[(status || '').toLowerCase()] ?? UNKNOWN;
}

export function ownerLabel(owner: StepOwner): string {
  return OWNER_LABELS[owner];
}

/** The band sentence from docs/ui-copy.md. Thresholds: 25 / 50 / 75. */
export function riskBandSentence(level?: string | null): string {
  switch ((level || '').toLowerCase()) {
    case 'low':
      return 'Low risk. This can be fast-tracked.';
    case 'medium':
      return 'Medium risk. Compliance should look at this.';
    case 'high':
      return 'High risk. A person must review it before onboarding.';
    case 'critical':
      return 'Critical risk. This needs escalation.';
    default:
      return 'Not scored yet.';
  }
}

/** Pluralise a count with a noun, because "1 documents" reads as a bug. */
export function countNoun(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
