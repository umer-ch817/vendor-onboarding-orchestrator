"""Document classification prompt.

Version: 1.1.0

Changelog:
  1.0.0 - Initial classification prompt
  1.1.0 - Added explicit "unknown" handling and confidence floor guidance
"""

PROMPT_VERSION = "1.1.0"

SYSTEM_PROMPT = """You classify vendor onboarding documents into known categories.

Return ONLY a JSON object. No prose, no markdown fences.

Categories:
  w9                          - US IRS Form W-9 or equivalent tax form
  certificate_of_insurance    - Proof of insurance coverage
  business_registration       - Articles of incorporation, state registration, etc.
  banking_confirmation        - Bank letter, voided check, ACH form
  supplier_questionnaire      - Completed vendor questionnaire or intake form
  master_services_agreement   - Contract or services agreement
  voided_check                - A voided cheque used for bank verification
  tax_certificate             - Tax residency or exemption certificate
  other                       - None of the above

Rules:
- If the document does not clearly match a category, return "other" with a low
  confidence. Do not force a match.
- Return "confidence" as 0.0-1.0 reflecting how certain you are.
- If the document is truncated or illegible, say so in "reasoning".
- Never guess a category from the filename alone; classify from the content.
"""


def build_classification_prompt(
    document_text: str,
    filename: str = "",
    max_chars: int = 6_000,
) -> str:
    """Build the user-side prompt for document classification."""
    truncated = False
    if len(document_text) > max_chars:
        document_text = document_text[:max_chars]
        truncated = True

    truncation_note = (
        "\n(Note: the text below was truncated before classification.)\n"
        if truncated
        else ""
    )

    return f"""Classify the following vendor document.

FILENAME: {filename or "(not provided)"}
{truncation_note}
RESPONSE FORMAT
---------------
{{
  "document_type": "<one of the categories>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one short sentence explaining the classification>",
  "detected_identifiers": ["<any obvious form numbers, headers, or titles you relied on>"]
}}

DOCUMENT TEXT
-------------
{document_text}
"""
