/** "What happens next" — and why the score is what it is.
 *
 * The single most useful thing on a case page: where it is, what is stopping
 * it, and which action clears it. The risk explanation sits here rather than in
 * the Risk tab because a score you have to go looking for is a score nobody
 * checks.
 *
 * The AI is shown separately and labelled as advice. During a recorded demo a
 * model really is running, and an AI whose opinion is indistinguishable from
 * the score invites the question "who decided this?" — which is a fair question
 * that the interface should answer before it is asked.
 */

import { Card } from './index';
import { RiskBadge } from './badges';
import { countNoun, nextStepFor, ownerLabel, riskBandSentence } from '../../utils/nextStep';
import type { CurrentAssessment, RiskScoreComponent } from '../../types';
import './NextStepPanel.css';

export function NextStepPanel({
  status,
  riskScore,
  riskLevel,
  components = [],
  explanation,
  assessment,
  openExceptions = 0,
  failedDocuments = 0,
  busy = false,
  busyLabel,
}: {
  status?: string | null;
  riskScore?: number | null;
  riskLevel?: string | null;
  components?: RiskScoreComponent[];
  explanation?: string | null;
  assessment?: CurrentAssessment | null;
  openExceptions?: number;
  failedDocuments?: number;
  busy?: boolean;
  busyLabel?: string;
}) {
  const step = nextStepFor(status);

  const blockers: string[] = [];
  if (failedDocuments > 0) {
    blockers.push(
      countNoun(failedDocuments, 'document could not be read', 'documents could not be read'),
    );
  }
  if (openExceptions > 0) {
    blockers.push(countNoun(openExceptions, 'open issue', 'open issues'));
  }

  // Already ordered largest-first by the backend.
  const top = components.slice(0, 3);
  const rest = Math.max(0, components.length - top.length);
  const scored = typeof riskScore === 'number';

  return (
    <Card title="What happens next" subtitle={busy ? 'Working' : ownerLabel(step.owner)}>
      {busy ? (
        <p className="next-step-working">
          <span className="next-step-spinner" aria-hidden="true" />
          {busyLabel || 'Working…'} — the AI takes about 30 seconds. Leave this page open.
        </p>
      ) : (
        <>
          <p className="next-step-headline">{step.headline}</p>
          <p className="next-step-detail">{step.detail}</p>
        </>
      )}

      {blockers.length > 0 && (
        <ul className="next-step-blockers">
          {blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      )}

      {scored && (
        <div className="next-step-risk">
          <div className="next-step-risk-head">
            <span className="next-step-score">{riskScore}/100</span>
            <RiskBadge level={riskLevel} />
            <span className="next-step-band">{riskBandSentence(riskLevel)}</span>
          </div>

          {top.length > 0 ? (
            <ul className="next-step-drivers">
              {top.map((component) => (
                <li key={component.code}>
                  <span>{component.label}</span>
                  <span className="next-step-points">+{component.points}</span>
                </li>
              ))}
              {rest > 0 && <li className="next-step-more">and {rest} more</li>}
            </ul>
          ) : (
            explanation && <p className="next-step-explanation">{explanation}</p>
          )}

          <p className="next-step-rules">
            The score is calculated by fixed rules. The AI&rsquo;s note is advice —
            it does not change the number.
          </p>
        </div>
      )}

      {assessment && (
        <div className="next-step-ai">
          {assessment.ai_model ? (
            <>
              <div className="next-step-ai-head">
                <span className="next-step-ai-label">AI suggestion</span>
                <span className="next-step-ai-model">{assessment.ai_model}</span>
              </div>
              <p className="next-step-ai-text">
                {assessment.recommended_action || 'No suggestion was recorded.'}
              </p>
            </>
          ) : (
            <p className="next-step-ai-text">
              No AI suggestion is recorded for this case. The score comes from the
              rules alone.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
