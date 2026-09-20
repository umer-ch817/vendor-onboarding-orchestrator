/** The project's jargon, translated.
 *
 * Every system grows a private vocabulary. It is efficient for the people who
 * built it and a wall for everyone else. None of these words are wrong — they
 * are just unexplained, and an unexplained word reads as a thing you are
 * supposed to already know.
 *
 * This is the short glossary promised by item 2.7. It is shown on the Story
 * tab, which is the default view, so it is there the first time someone opens
 * a case rather than hidden behind a help icon.
 */

export interface GlossaryEntry {
  term: string;
  plain: string;
  meaning: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    term: 'Exception',
    plain: 'Issue',
    meaning: 'A specific problem found on this case that someone has to close.',
  },
  {
    term: 'Risk signal',
    plain: 'Something we noticed',
    meaning: 'One thing that made this vendor look more or less risky.',
  },
  {
    term: 'Route',
    plain: 'Where it was sent',
    meaning:
      'What happens next: fast-track, compliance review, senior review, escalation, or blocked.',
  },
  {
    term: 'SLA',
    plain: 'Deadline',
    meaning: 'How long a case may sit before it is automatically escalated.',
  },
  {
    term: 'Triage',
    plain: 'Sorting',
    meaning: 'Deciding what needs attention first.',
  },
  {
    term: 'Extraction',
    plain: 'Reading',
    meaning: 'The step where a document is read and its details pulled out.',
  },
  {
    term: 'Verdict',
    plain: 'Suggestion',
    meaning:
      "The AI's opinion. It is advice only — it does not change the risk score.",
  },
  {
    term: 'Blocked',
    plain: "Can't continue",
    meaning:
      'Something required is missing or unreadable, so the case cannot move on until it is fixed.',
  },
];

export function glossaryFor(term: string): GlossaryEntry | undefined {
  return GLOSSARY.find((entry) => entry.term.toLowerCase() === term.toLowerCase());
}
