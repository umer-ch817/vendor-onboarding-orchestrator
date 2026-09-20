/** First-run tour.
 *
 * Three sentences, shown once, dismissible. The point is to stop someone
 * staring at a dashboard with no idea what any of it is. It is deliberately not
 * a modal and not a multi-screen walkthrough: nobody doing this job daily wants
 * to click through a tutorial, and a tour that cannot be dismissed becomes
 * wallpaper.
 *
 * Dismissal is remembered in localStorage. If storage is unavailable (private
 * mode, blocked cookies) the banner simply shows again rather than failing.
 */

import { useState } from 'react';
import { X } from 'lucide-react';
import './FirstRunTour.css';

const STORAGE_KEY = 'vor.tour.dismissed';

const STEPS = [
  {
    title: 'A vendor is the company',
    body: 'Everything here belongs to a company you are thinking of working with.',
  },
  {
    title: 'A case is one onboarding run',
    body: 'A vendor can have several cases. Each one moves through four stages: Set up, Collect, Score, Sign-off.',
  },
  {
    title: 'Press Start onboarding',
    body: 'That hands the case to the automation, which collects documents, scores risk and routes it. The decisions stay with people.',
  },
];

export function FirstRunTour() {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  });

  if (dismissed) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(STORAGE_KEY, '1');
    } catch {
      // Storage blocked: the banner shows again next time, which is harmless.
    }
    setDismissed(true);
  };

  return (
    <section className="tour" aria-label="Getting started">
      <div className="tour-head">
        <h2 className="tour-title">How this works</h2>
        <button
          type="button"
          className="tour-close"
          onClick={dismiss}
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      </div>

      <ol className="tour-steps">
        {STEPS.map((step, index) => (
          <li key={step.title}>
            <span className="tour-num">{index + 1}</span>
            <div>
              <p className="tour-step-title">{step.title}</p>
              <p className="tour-step-body">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <button type="button" className="btn btn-secondary btn-sm" onClick={dismiss}>
        Got it
      </button>
    </section>
  );
}
