"""Exception triage prompt.

Version: 1.2.0

Changelog:
  1.0.0 - Initial exception framing
  1.2.0 - Added resolution-options constraint and reviewer-facing tone

DESIGN NOTE
-----------
When an exception fires, the reviewer's real question is not "what is wrong"
- the system already told them that. The real question is "what do I need to
do about it, and how urgently". This prompt exists to answer that question
and to draft the outbound clarification request when one is needed.

The model may *draft* the message the vendor receives. It may never send it.
"""

PROMPT_VERSION = "1.2.0"

SYSTEM_PROMPT = """You help a procurement operations team triage vendor onboarding exceptions.

You are given one exception that the deterministic rule engine has already
raised, plus the surrounding case context. Your job is to help a human decide
what to do about it.

Return ONLY a JSON object. No prose, no markdown fences.

You must NOT:
- claim the underlying facts are different from what is stated
- suggest overriding a compliance rule
- invent information the vendor did not provide

You may:
- explain the likely root cause of the exception
- rank the practical resolution options
- draft a message the operator could send to the vendor asking for what is missing
"""


def build_exception_prompt(
    exception: dict,
    vendor_context: dict,
    related_evidence: list[dict] | None = None,
) -> str:
    """Build the user-side prompt for exception triage."""

    evidence_lines = []
    for item in related_evidence or []:
        evidence_lines.append(
            f"  - {item.get('label', 'evidence')}: "
            f"{item.get('value', '(no value)')} "
            f"[from {item.get('source', 'unknown source')}]"
        )
    evidence_section = "\n".join(evidence_lines) or "  (no additional evidence attached)"

    return f"""Triage this exception.

EXCEPTION
---------
  type: {exception.get('type')}
  severity: {exception.get('severity')}
  title: {exception.get('title')}
  description: {exception.get('description')}
  raised by: {exception.get('source', 'rules_engine')}

VENDOR
------
  legal name: {vendor_context.get('legal_name')}
  country: {vendor_context.get('country')}
  vendor type: {vendor_context.get('vendor_type')}
  risk level: {vendor_context.get('risk_level')}

SUPPORTING EVIDENCE
-------------------
{evidence_section}

RESPONSE FORMAT
---------------
{{
  "likely_root_cause": "<one or two sentences>",
  "resolution_options": [
    {{
      "action": "RESOLVE" | "REQUEST_INFORMATION" | "ESCALATE" | "OVERRIDE",
      "description": "<what the operator would do>",
      "recommended": true | false,
      "rationale": "<why this is or is not the best option>"
    }}
  ],
  "vendor_message_draft": "<a short, polite message to the vendor asking for what is needed, or null if no vendor contact is warranted>",
  "reviewer_notes": "<anything the operator should check before acting>",
  "urgency": "low" | "medium" | "high"
}}
"""
