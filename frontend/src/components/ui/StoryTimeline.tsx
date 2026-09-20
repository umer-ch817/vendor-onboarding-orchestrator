/** The Story view: a plain-language account of one case.
 *
 * Same events as the audit trail, read differently. The audit tab stays as it
 * is — precise and technical — because that is what an auditor needs. This is
 * the answer to "what happened to this vendor", which is what everyone else
 * needs.
 */

import { Card, EmptyState } from './index';
import { formatDateTime } from '../../utils/format';
import { storyLine } from '../../utils/story';
import { GLOSSARY } from '../../utils/glossary';
import './StoryTimeline.css';

export interface StoryEvent {
  id: number;
  timestamp: string;
  event_type: string;
  description?: string | null;
}

export function StoryTimeline({ events }: { events: StoryEvent[] }) {
  const timeline =
    events.length === 0 ? (
      <EmptyState
        title="Nothing has happened yet"
        description="Press Start onboarding on this case. Each step will then appear here in plain language."
      />
    ) : (
      <Card
        title="What happened"
      subtitle="Oldest first, in plain language. The raw event name is available on hover."
    >
      <ol className="story">
        {events.map((event) => {
          const line = storyLine(event.event_type, event.description);
          return (
            <li key={event.id} className="story-row">
              <span className="story-marker" aria-hidden="true" />
              <div className="story-body">
                <p className="story-text" title={event.event_type}>
                  {line.text}
                  {line.isAi && <span className="story-ai">AI</span>}
                </p>
                <span className="story-when">{formatDateTime(event.timestamp)}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );

  return (
    <>
      {timeline}
      <details className="glossary">
        <summary>Plain English — the words this app uses</summary>
        <dl className="definition-list">
          {GLOSSARY.map((entry) => (
            <div className="definition-row" key={entry.term}>
              <dt>
                {entry.term} <span className="text-muted">— {entry.plain}</span>
              </dt>
              <dd>{entry.meaning}</dd>
            </div>
          ))}
        </dl>
      </details>
    </>
  );
}
