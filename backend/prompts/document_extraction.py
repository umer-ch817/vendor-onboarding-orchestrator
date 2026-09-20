"""Document extraction prompt.

Version: 1.3.0

Changelog:
  1.0.0 - Initial extraction prompt
  1.1.0 - Added per-field confidence requirement
  1.2.0 - Added explicit instruction to return null rather than guess
  1.3.0 - Added warnings array and source_location
"""

PROMPT_VERSION = "1.3.0"

SYSTEM_PROMPT = """You are a document extraction engine for a procurement compliance system.

Your ONLY job is to read a vendor document and return its contents as structured JSON.

CRITICAL RULES:
1. Return ONLY a JSON object. No prose, no markdown fences, no explanation.
2. Never invent, infer, or complete a value that is not visibly present in the document.
3. If a field is absent or illegible, set its value to null and lower its confidence.
   A null with confidence 0.0 is always better than a plausible guess.
4. Every field must carry a confidence between 0.0 and 1.0 reflecting how certain
   you are that you read it correctly. Use these anchors:
     1.00 - printed clearly, unambiguous
     0.90 - printed clearly, minor formatting ambiguity
     0.75 - legible but requires interpretation (e.g. abbreviated)
     0.50 - partially obscured, inferred from context
     0.00 - not present, or unreadable
5. Dates must be returned in ISO 8601 format (YYYY-MM-DD). If the document uses a
   different format, convert it. If you cannot determine the date, return null.
6. Preserve the entity name exactly as printed, including punctuation and suffixes.
   Do not clean up or standardize names - a downstream process does that.
7. List anything unusual in the warnings array: torn pages, missing sections,
   conflicting values within the same document, unusual formatting.

If the document is not the type you were told to expect, still extract what you can
and add a warning such as "document type mismatch: expected W-9, appears to be invoice".
"""

FIELD_SPECS = {
    "w9": {
        "legal_name": "The name on line 1 of the W-9 (the individual or entity name)",
        "business_name": "The business/disregarded entity name on line 2, if present",
        "tax_classification": "The federal tax classification checkbox that is marked",
        "address": "The full street address on line 5",
        "city_state_zip": "City, state and ZIP on line 6",
        "tin": "The Taxpayer Identification Number (masked as it appears)",
        "tin_present": "true if a TIN is present and legible, false otherwise",
    },
    "certificate_of_insurance": {
        "insured_name": "The named insured on the certificate",
        "policy_number": "The policy number",
        "coverage_type": "Type of coverage (general liability, auto, workers comp, etc.)",
        "coverage_amount": "The limit of liability per occurrence",
        "effective_date": "Policy effective date",
        "expiration_date": "Policy expiration date",
        "insurer_name": "The insurance company issuing the certificate",
    },
    "business_registration": {
        "legal_name": "The registered entity name",
        "registration_number": "The state or jurisdiction registration/file number",
        "jurisdiction": "The state or country of registration",
        "registration_date": "Date the entity was registered",
        "active_status": "Whether the registration is currently active",
        "entity_type": "Legal entity type (corporation, LLC, partnership, etc.)",
    },
    "banking_confirmation": {
        "account_holder": "The name on the bank account",
        "bank_name": "The name of the financial institution",
        "account_type": "Checking, savings, etc.",
        "account_identifier": "The account identifier, masked to last four digits only",
        "routing_identifier": "The routing number if present",
    },
    "supplier_questionnaire": {
        "company_name": "The company name as stated in the questionnaire",
        "ownership_structure": "Stated ownership structure",
        "beneficial_owners": "Names of beneficial owners if disclosed",
        "years_in_business": "How long the company has operated",
        "payment_terms": "Requested or agreed payment terms",
        "conflict_of_interest": "Any disclosed conflicts of interest",
    },
    "master_services_agreement": {
        "party_a": "The first contracting party",
        "party_b": "The second contracting party",
        "effective_date": "Agreement effective date",
        "term_months": "Agreement term length in months",
        "payment_terms": "Payment terms stated in the agreement",
        "termination_notice_days": "Notice period required for termination",
        "governing_law": "The governing jurisdiction",
    },
}

DEFAULT_FIELDS = {
    "legal_name": "The primary legal entity name in the document",
    "document_date": "The date on the document",
    "reference_number": "Any reference, account, or document number",
}


def build_extraction_prompt(
    document_type: str,
    document_text: str,
    filename: str = "",
    max_chars: int = 12_000,
) -> str:
    """Build the user-side prompt for document extraction.

    The document text is truncated rather than rejected when it exceeds the
    budget: a partial extraction with a warning is more useful to a reviewer
    than a hard failure, and the warning makes the truncation visible.
    """
    fields = FIELD_SPECS.get(document_type, DEFAULT_FIELDS)

    field_lines = "\n".join(
        f'  "{name}": <value or null>   # {desc}'
        for name, desc in fields.items()
    )

    truncated = False
    if len(document_text) > max_chars:
        document_text = document_text[:max_chars]
        truncated = True

    truncation_note = (
        '\n\nNOTE: The document text was truncated for processing. Add a warning '
        '"document text truncated" to the warnings array.\n'
        if truncated
        else ""
    )

    return f"""Extract the fields below from this {document_type} document.

DOCUMENT TYPE: {document_type}
FILENAME: {filename or "(not provided)"}
{truncation_note}
FIELDS TO EXTRACT
-----------------
{field_lines}

RESPONSE FORMAT
---------------
Return exactly this structure:

{{
  "document_type": "{document_type}",
  "fields": {{
    "<field_name>": {{
      "value": <the value, or null>,
      "confidence": <0.0 to 1.0>,
      "source_location": "<where in the document you found it>"
    }}
  }},
  "document_confidence": <0.0 to 1.0, your overall confidence in this extraction>,
  "warnings": []
}}

DOCUMENT TEXT
-------------
{document_text}
"""
