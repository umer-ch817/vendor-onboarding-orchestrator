"""Vendor risk analysis prompt.

Version: 2.1.0

Changelog:
  2.0.0 - Rewritten to separate evidence-gathering from decision-making
  2.1.0 - Added policy context slot and explicit "insufficient evidence" output

DESIGN NOTE
-----------
This prompt deliberately does NOT ask the model for a risk score. Scoring is
deterministic and lives in app/rules/risk_scoring.py. What we want from the
model is the thing deterministic rules are bad at: noticing that two facts
interact, summarising a body of evidence, and flagging what context is missing.

The model returns candidate signals. Those signals are then filtered against
the rule engine's findings before anything reaches a human, so the model
cannot manufacture a risk finding out of nothing.
"""

PROMPT_VERSION = "2.1.0"

SYSTEM_PROMPT = """You are a vendor risk analyst assisting a procurement compliance team.

You examine a vendor's document evidence and identify risk signals that a
reviewer should know about. You do NOT make the final compliance decision and
you do NOT assign a risk score - a separate deterministic system does that.

Return ONLY a JSON object. No prose, no markdown fences.

WHAT COUNTS AS A RISK SIGNAL
----------------------------
- Contradictions between documents that were not caught by string comparison
  (e.g. a policy period that predates the company's incorporation date)
- Facts that are internally consistent but commercially unusual
  (e.g. payment terms of 120 days for a new vendor)
- Gaps in the evidence that prevent a confident assessment
  (e.g. no beneficial ownership disclosed for an entity)
- Combinations that are individually benign but jointly concerning
- A document that is present but does not appear to be authentic in substance
  (e.g. an insurance certificate with no insurer contact details)

WHAT IS NOT A RISK SIGNAL
-------------------------
- Surface formatting differences. Those are already normalized downstream.
- Generic observations with no supporting evidence ("vendor seems new").
- Anything you cannot point to a specific document for.

EVIDENCE RULES
--------------
Every signal you report MUST cite the document(s) it came from. If you cannot
cite a document, do not report the signal. A short list of well-evidenced
signals is far more useful than a long list of speculation.

If the evidence is insufficient to assess the vendor at all, say so explicitly
by returning an empty risk_signals array and explaining what is missing in the
summary. Returning nothing is a valid and useful answer.
"""


def build_risk_prompt(
    vendor_context: dict,
    document_summary: list[dict],
    policy_excerpts: list[str] | None = None,
) -> str:
    """Build the user-side prompt for vendor risk analysis.

    Args:
        vendor_context: Vendor profile dict (name, country, industry, etc).
        document_summary: One entry per document, with extracted fields.
        policy_excerpts: Relevant policy passages retrieved for this vendor.
            Passing these grounds the model's reasoning in the company's own
            stated requirements rather than its general priors.
    """
    vendor_lines = "\n".join(
        f"  {key}: {value}" for key, value in vendor_context.items()
    )

    doc_blocks = []
    for doc in document_summary:
        fields = doc.get("fields", {})
        field_lines = "\n".join(
            f"      {name}: {value if value is not None else '(not present)'}"
            for name, value in fields.items()
        )
        confidence = doc.get("confidence")
        confidence_note = (
            f" (extraction confidence {confidence:.2f})"
            if isinstance(confidence, (int, float))
            else ""
        )
        doc_blocks.append(
            f"  DOCUMENT: {doc.get('document_type')}{confidence_note}\n"
            f"    status: {doc.get('status', 'unknown')}\n"
            f"    fields:\n{field_lines or '      (no fields extracted)'}"
        )

    documents_section = "\n\n".join(doc_blocks) or "  (no documents available)"

    if policy_excerpts:
        policy_section = "\n\n".join(
            f'  [{i + 1}] "{excerpt}"' for i, excerpt in enumerate(policy_excerpts)
        )
    else:
        policy_section = "  (no specific policy context retrieved)"

    return f"""Analyse this vendor's onboarding evidence.

VENDOR
------
{vendor_lines}

DOCUMENT EVIDENCE
-----------------
{documents_section}

RELEVANT COMPANY POLICY
-----------------------
{policy_section}

RESPONSE FORMAT
---------------
{{
  "risk_signals": [
    {{
      "type": "<SCREAMING_SNAKE_CASE signal type>",
      "severity": "low" | "medium" | "high" | "critical",
      "description": "<what the concern is, in one or two sentences>",
      "evidence": "<which document(s) and which values support this>",
      "confidence": <0.0 to 1.0>
    }}
  ],
  "summary": "<2-4 sentences summarising the overall state of this vendor's evidence. State plainly if evidence is insufficient.>",
  "missing_context": ["<specific information a reviewer would need to reach a conclusion>"],
  "recommended_action": "AUTO_APPROVE" | "HUMAN_REVIEW" | "REQUEST_INFORMATION" | "ESCALATE",
  "confidence": <0.0 to 1.0, your confidence in this overall assessment>
}}

Remember: cite evidence for every signal, and prefer an empty signal list over speculation.
"""
