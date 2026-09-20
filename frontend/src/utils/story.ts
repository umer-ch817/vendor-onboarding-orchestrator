/** Story wording for audit events.
 *
 * The audit trail is written for an auditor: precise, technical, complete. It
 * is not written for someone trying to answer "what happened to this vendor".
 * This module keeps the auditor's record untouched and supplies a second,
 * plainer reading of the same events.
 *
 * Unknown events fall back to the backend's own description, so a new event
 * type shows up as something readable rather than as a blank row.
 */

export interface StoryLine {
  text: string;
  /** Events produced by the model, so the UI can label them as such. */
  isAi: boolean;
}

const PLAIN: Record<string, string> = {
  CASE_CREATED: 'Case opened.',
  WORKFLOW_TRIGGERED: 'Automation started.',
  CASE_SUBMITTED: 'Submitted for checking.',
  DOCUMENT_UPLOADED: 'A document was uploaded.',
  DOCUMENT_PROCESSING_DISPATCHED: 'A document was sent for reading.',
  DOCUMENT_PROCESSED: 'A document was read.',
  DOCUMENT_VERIFIED: 'A document was checked.',
  DOCUMENT_EXPIRING_SOON: 'A document is about to expire.',
  DOCUMENT_EXPIRED: 'A document has expired.',
  ASSESSMENT_COMPLETED: 'Checks finished.',
  AI_RISK_ANALYSIS: 'The AI reviewed this case.',
  AI_UNCERTAINTY: 'The AI flagged a document as unclear.',
  CASE_ROUTED: 'Sent on to the next stage.',
  EXCEPTION_TRIAGE: 'An issue was raised.',
  EXCEPTION_ASSIGNED: 'Someone picked this up.',
  EXCEPTION_RESOLVED: 'An issue was closed.',
  APPROVAL_OPENED: 'Approval was requested.',
  APPROVAL_DECIDED: 'A decision was recorded.',
  APPROVAL_ESCALATED: 'Escalated to a higher authority.',
  SLA_WARNING: 'Deadline approaching.',
  SLA_ESCALATED: 'Deadline passed, so this was escalated.',
  WORKFLOW_COMPLETED: 'Automation finished.',
  WORKFLOW_FAILED:
    'Automation stopped with an error. Nothing was lost — you can start it again.',
  NOTIFICATION_SENT: 'The reviewer was notified.',
  NOTIFICATION_FAILED: 'The reviewer could not be notified.',
  RETRY_EXHAUSTED: 'A downstream call failed and no retries remain.',
};

const AI_EVENTS = new Set(['AI_RISK_ANALYSIS', 'AI_UNCERTAINTY']);

export function storyLine(eventType?: string | null, description?: string | null): StoryLine {
  const type = (eventType || '').toUpperCase();
  const text = PLAIN[type] || description || 'Something was recorded.';
  return { text, isAi: AI_EVENTS.has(type) };
}
