# Plain-language UI copy — Phase B

**Status: draft for review. No code written against this yet.**

These are the words the interface will use. Editing this file is free; changing
a built component is not. React to anything here before it becomes code.

---

## Ground truth

Everything below is derived from the code, not invented, so the wording cannot
promise something the system does not do.

| Thing | Values | Source |
|---|---|---|
| Internal statuses (12) | `draft`, `submitted`, `document_collection`, `extraction`, `validation`, `risk_analysis`, `review_required`, `approval_pending`, `approved`, `rejected`, `onboarding_complete`, `blocked` | `backend/app/models/__init__.py:39` |
| Routes (5) | `auto_approve`, `compliance_review`, `senior_review`, `escalate`, `blocked` | `backend/app/rules/risk_scoring.py:271` |
| Score bands | `low` ≤ 25, `medium` ≤ 50, `high` ≤ 75, `critical` > 75 | `risk_scoring.py:156`, thresholds in `config.py:70` |
| Auto-approve ceiling | score ≤ 25 | `config.py:78` |
| Blocking codes | `DOCUMENT_MISSING`, `EXTRACTION_FAILED`, `TAX_INFORMATION_MISSING` | `risk_scoring.py:305` |
| AI verdicts | `AUTO_APPROVE`, `HUMAN_REVIEW`, `REQUEST_INFORMATION`, `ESCALATE` | `backend/app/ai/schemas.py:19` |
| Exception severity | `low`, `medium`, `high`, `critical` | `models/__init__.py:75` |

---

## 2.1 — The four phases

**Decided: Set up → Collect → Score → Sign-off**

Chosen over *Register → Gather → Assess → Approve* and *Set up → Collect →
Check → Decide*. Reasoning:

- **Set up** beats *Register* — it covers `draft` as well as `submitted`.
- **Score** beats *Assess* and *Check*. The phase contains `risk_analysis` and
  `review_required`; the artefact a user actually sees at the end of it is a
  number out of 100, so naming the phase after that number is honest and plain.
  *Assess* is vaguer, and *Check* collides with the cross-checking that already
  happens back in Collect.
- **Sign-off** beats *Approve* and *Decide*. The phase also contains `rejected`,
  and "Approve" would be a lie in that case. "Sign-off" reads as *a person takes
  responsibility either way*, which is the project's stated principle.

| Phase | Internal statuses behind it | Tooltip (for developers) |
|---|---|---|
| **Set up** | `draft`, `submitted` | `draft · submitted` |
| **Collect** | `document_collection`, `extraction`, `validation`, `blocked` | `document_collection · extraction · validation · blocked` |
| **Score** | `risk_analysis`, `review_required` | `risk_analysis · review_required` |
| **Sign-off** | `approval_pending`, `approved`, `rejected`, `onboarding_complete` | `approval_pending · approved · rejected · onboarding_complete` |

**Why `blocked` sits in Collect.** All three blocking codes concern documents or
tax information — nothing blocks a case for a scoring reason. So a blocked case
is shown as Collect, marked *Blocked*, not as a fifth phase.

**Step states:** Done (tick) → Current (filled) → Not started (outline). A
skipped or reversed step is never drawn as an error; the stepper shows where the
case is now, not a promise about the path.

**Never shown to a normal user:** `DOCUMENT_COLLECTION`, `review_required`,
`onboarding_complete`. Available on hover for anyone who needs the real state.

---

## 2.2 — The Story tab

Default view on a case. One sentence per event, newest last, no jargon.

| Event | Sentence |
|---|---|
| Case created | "Case opened for {vendor}." |
| `WORKFLOW_TRIGGERED` | "Automation started." |
| Case submitted | "Submitted for checking." |
| `DOCUMENT_PROCESSING_DISPATCHED` | "{filename} sent for reading." |
| Extraction finished | "{filename} read — {n} details found." |
| Extraction failed | "{filename} could not be read. A clearer copy is needed." |
| `AI_UNCERTAINTY` | "The AI flagged this document as unclear." |
| `ASSESSMENT_COMPLETED` | "Checks finished — {n} issues found." |
| `AI_RISK_ANALYSIS` | "The AI reviewed the case and suggested: {verdict}." |
| `CASE_ROUTED` | "Sent for {route}." |
| `EXCEPTION_TRIAGE` | "Issue raised: {title}." |
| `EXCEPTION_ASSIGNED` | "{actor} picked this up." |
| `EXCEPTION_RESOLVED` | "Issue closed: {title}." |
| `APPROVAL_OPENED` | "Approval requested from {authority}." |
| `APPROVAL_DECIDED` | "{actor} approved this vendor." / "{actor} declined this vendor." |
| `APPROVAL_ESCALATED` | "Escalated to {authority}." |
| `SLA_WARNING` | "Deadline approaching — {time} left." |
| `SLA_ESCALATED` | "Deadline passed, so this was escalated." |
| `WORKFLOW_COMPLETED` | "Automation finished." |
| `WORKFLOW_FAILED` | "Automation stopped with an error. Nothing was lost — you can start it again." |
| `NOTIFICATION_SENT` | "The reviewer was notified." |

**Verdicts, in words:** `AUTO_APPROVE` → "this looks fine to approve" ·
`HUMAN_REVIEW` → "a person should look at this" · `REQUEST_INFORMATION` → "ask
the vendor for more information" · `ESCALATE` → "escalate this".

**Routes, in words:** `auto_approve` → "fast-track" · `compliance_review` →
"compliance review" · `senior_review` → "senior review" · `escalate` →
"escalation" · `blocked` → "blocked".

---

## 2.3 — "What happens next"

Always answers three things: where is it, what's stopping it, what clears it.

| Status | Headline | Who acts | What clears it |
|---|---|---|---|
| `draft` | "Add the vendor's details to begin." | You | Fill in the form, then press Start onboarding. |
| `submitted` | "Automation is running." | The system | Usually under a minute. Nothing to do. |
| `document_collection` | "Waiting on documents." | You or the vendor | Upload the documents listed below. |
| `extraction` | "Reading the uploaded documents." | The system | Finishes on its own. |
| `validation` | "Checking the details against each other." | The system | Finishes on its own. |
| `risk_analysis` | "Scoring risk." | The system | Finishes on its own. |
| `blocked` | "This can't continue yet." | You | Fix the reason shown below — usually a missing document. |
| `review_required` | "Needs a person's decision." | A reviewer | Resolve the open issues. |
| `approval_pending` | "Waiting for an approver." | An approver | Someone with authority approves or declines. |
| `approved` | "Approved — being set up." | The system | Nothing. |
| `rejected` | "Declined." | You | Close it, or start again with corrected details. |
| `onboarding_complete` | "Done — this vendor is live." | — | Nothing. |

**Empty version of the panel (nothing blocking):** "Nothing is waiting on you
right now."

---

## 2.4 — Explaining the risk score

**Finding: the backend already writes this sentence.** `risk_scoring.py:166`
builds it — *"Risk score is 53/100, placing this vendor at HIGH risk. The score
is the sum of 4 identified factors: …"* — it is returned by
`risk_service.py:92`, and `RiskReviewPage.tsx:305` and `VendorDetailPage.tsx:477`
already render it. So 2.4 is mostly **presentation**, not new writing: promote it
out of the risk tab and onto the default view.

**Bands, as words:**

| Score | Word | Sentence |
|---|---|---|
| 0–25 | Low | "Low risk. This can be fast-tracked." |
| 26–50 | Medium | "Medium risk. Compliance should look at this." |
| 51–75 | High | "High risk. A person must review it before onboarding." |
| 76–100 | Critical | "Critical risk. This needs escalation." |

**The three-driver line:** show the top three contributing findings with their
points, largest first: "Missing W-9 (+20) · Insurance below minimum (+15) ·
Adverse media (+10)". Everything else collapses behind "and 1 more".

**The line that must always be present, because the real AI runs in your demo:**

> The score is calculated by fixed rules. The AI's note is advice — it does not
> change the number.

**What to say when it was capped:** "Several serious issues were found, so the
total was capped at 100."

---

## Words to drop (feeds Phase C item 2.8, listed here for awareness)

| Don't say | Say |
|---|---|
| Exception | Issue |
| Risk signal | Something we noticed |
| Route | Where it was sent |
| Triage | Sorting |
| SLA | Deadline |
| Extraction | Reading |
| Verdict | Suggestion |

---

## Decided (was open)

1. **Phase names: Set up → Collect → Score → Sign-off.** Reasoning above.
2. **"Score", not "Assess".** Reasoning above.
3. **`rejected` and `onboarding_complete` are an end-state badge, not a finished
   fourth step.**

   A stepper implies forward progress. Drawing `rejected` as a completed fourth
   step would tell the viewer the case advanced, when the truth is it stopped and
   went backwards. So:

   - `approval_pending` → Sign-off step is *current*.
   - `approved` or `onboarding_complete` → badge: **"Approved — this vendor is
     live"** (green).
   - `rejected` → badge: **"Declined"** (red).

   The badge sits beside the stepper rather than inside it, so the stepper keeps
   meaning "how far along", and the badge means "how it ended".

4. **2.6 (make the AI visible and honest) moves from Phase C into Phase B**,
   because the real AI runs in the recorded demo. Added below.

## 2.6 — Making the AI visible (moved into Phase B)

Two obligations, since a real model runs during the recording:

**While it runs.** Show that the delay is work, not a hang: *"AI is reading
{docname}…"* with a spinner, and *"AI is reviewing this case…"* before the risk
assessment. Right now the page sits still for 30-40 seconds with no feedback,
which reads as broken.

**When it reports.** Its output is a clearly-labelled advisory note, never
presented as the decision:

> **AI suggestion** — {verdict, in words}
> The score is calculated by fixed rules. This note does not change it.

**When it fails.** `LLM_PROVIDER` degradation already falls back silently
(`ai_degraded`). The UI must say so rather than implying the AI had no opinion:
*"AI was unavailable, so this case was scored on rules alone."*

**Never:** present an AI verdict as the score, or show the score without the
fixed-rules line.
