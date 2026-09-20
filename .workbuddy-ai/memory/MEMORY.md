
# Project decisions (2026-09-20)

## Layman-first redesign: approved scope
Building phases **A then B now**. **C and D deferred** to later phases.

**Phase A** = runnable: start.bat, stop.bat, setup script, README quickstart,
auto-import of n8n workflows. **Phase B** = legible: 4-phase status stepper,
Story tab on the case page, "what happens next" panel, explained risk score,
plus a cleaner/more minimal dashboard.

**Layer 3 skipped** (no live-updating after Start, no AI progress indicator).
Means: after pressing Start the page does not change for 30-40s. Add back when
recording a demo.

## UI/UX standing direction from the user
- Designing for a layman must **not** degrade it. Keep it credible and
  professional -- plain language, not dumbed down.
- Dashboard should be **minimal and clean**.
- Charts/graphs: only implement where the project **actually needs** them, and
  make them **translucent**. Do not add decorative charts.
- UI/UX work is not confined to one phase; it spans all of them.

## Settled from the earlier plan
- Item 2 (case page full rebuild vs. tabs + panel) -> **tabs + panel**, Story tab
  first. Decided by 2.2/2.3.
- The old plan itself is superseded; the pasted A-D plan (1.1-1.5, 2.1-2.9) is
  the operative one.

## Decisions recorded 2026-09-20 (all now answered)
- **Demo timing**: the user records the demo themselves, no fixed date. So there
  is no deadline driving the order of work.
- **Real AI in the demo: YES.** Their API key is in play during recording. This
  means the AI must be *visible and correctly attributed* in the UI -- an
  unexplained AI is worse than no AI. Raises the priority of 2.6 (AI visibility),
  currently parked in Phase C.
- **Copy-first for 2.1-2.4**: write the plain-language wording and get a reaction
  before building components. Copy is cheap to change; a built stepper is not.

## Working method they asked for
Keep a live task list, one task per plan item, using their numbering. They want
to check progress and catch drift.

## Auto-advance through the phases (2026-09-20)
"after phase 2 start phase 3 and 4 automatically but do the testing for each
phase ... when everything is implemented write that somewhere for now so you can
remember what I said"

So: build B, then C, then D without stopping to ask, but **test each phase
before moving on**. The user is away on a break and will review on return.
Do NOT take down the running backend/frontend while doing this unless a test
genuinely requires it -- warn instead.

Numbering follows their pasted plan: B = 2.1 stepper, 2.2 Story tab, 2.3
what-happens-next, 2.4 explained risk score, 2.5 AI visibility (pulled forward
from C). C = 2.6 worklist dashboard, 2.7 jargon, 2.8 empty states. D = 2.9
first-run tour.

## Layman-path landmine found 2026-09-20
Without `.env`, app/config.py falls back to Docker hostnames (`postgres:5432`,
`http://n8n:5678`) that a natively-run backend cannot resolve -- it boots, then
cannot reach its database. The Windows quickstart never created `.env`.
setup.bat now copies `.env.example` -> `.env`; start.bat stops with a message
if `.env` is missing.
