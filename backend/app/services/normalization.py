"""Field-aware normalization.

``app.utils.normalization`` knows *how* to canonicalize a company name or an
address. This module knows *which* normalizer applies to *which* extracted
field, and applies it.

The distinction matters because a field name is the only reliable signal we
have at this point: the model returns ``{"legal_name": "..."}`` and it is this
layer's job to decide that "legal_name" is an entity name and must therefore
be suffix-stripped, while "account_identifier" is a bank identifier and must
therefore be masked rather than compared in full.

Everything here is deterministic. No model is involved, and none should be:
the entire purpose of normalization is to make comparisons reproducible.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.utils.normalization import (
    mask_account_number,
    normalize_address,
    normalize_company_name,
    normalize_date,
    normalize_phone,
    normalize_tax_id,
    normalize_text,
)

# Field names that hold an entity or person name.
COMPANY_NAME_FIELDS = {
    "legal_name",
    "business_name",
    "company_name",
    "insured_name",
    "account_holder",
    "party_a",
    "party_b",
}

# Field names that hold a street address.
ADDRESS_FIELDS = {"address", "address_line1", "street_address"}

# Field names that hold a raw identifier which must be reduced to digits.
TAX_ID_FIELDS = {"tin", "tax_id", "ein", "tax_identifier"}

# Field names holding a bank account identifier, which is masked, not compared.
BANK_ACCOUNT_FIELDS = {"account_identifier", "account_number", "bank_account_number"}

# Field names holding a phone number.
PHONE_FIELDS = {"phone", "contact_phone", "telephone"}

# Field names holding a date.
DATE_FIELDS = {
    "effective_date",
    "expiration_date",
    "registration_date",
    "document_date",
    "issue_date",
    "date_of_birth",
}


def normalize_value(field_name: str, value: Any) -> str:
    """Return the canonical string form of an extracted field value.

    Unknown fields fall back to base text normalization, which is lossy but
    safe: it will never claim two different values are identical, only that
    superficial differences (case, spacing, punctuation) do not matter.
    """
    if value is None:
        return ""

    if isinstance(value, bool):
        return "true" if value else "false"

    name = (field_name or "").strip().lower()

    if name in COMPANY_NAME_FIELDS:
        return normalize_company_name(str(value))

    if name in ADDRESS_FIELDS:
        return normalize_address(str(value))

    if name in TAX_ID_FIELDS:
        return normalize_tax_id(str(value))

    if name in BANK_ACCOUNT_FIELDS:
        # Masking rather than normalizing is deliberate: two documents that
        # disagree on the full number must still be compared on the part a
        # reviewer is allowed to see.
        return mask_account_number(str(value))

    if name in PHONE_FIELDS:
        return normalize_phone(str(value))

    if name in DATE_FIELDS:
        return normalize_date(str(value)) or normalize_text(str(value))

    if isinstance(value, (int, float)):
        return _normalize_number(value)

    return normalize_text(str(value))


def _normalize_number(value: Any) -> str:
    """Render a number without a trailing ``.0`` so 5 and 5.0 compare equal."""
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return normalize_text(str(value))

    if decimal_value == decimal_value.to_integral_value():
        return str(int(decimal_value))
    return format(decimal_value.normalize(), "f")


def parse_amount(value: Any) -> Optional[float]:
    """Parse a monetary value from a human-written string.

    The model is instructed to return amounts verbatim -- "$2,000,000.00",
    "2M", "1.5 million" -- so parsing belongs here rather than in the prompt.
    Returns None when the value is absent or genuinely unparseable, so callers
    can distinguish "no coverage stated" from "coverage of zero".
    """
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        return float(value)

    text = str(value).strip().lower()
    if not text:
        return None

    # Strip currency symbols, separators and unit words.
    text = text.replace(",", "").replace("$", "").replace("usd", "").strip()

    multiplier = 1.0
    if "billion" in text or text.endswith("b"):
        multiplier = 1_000_000_000.0
        text = text.replace("billion", "").rstrip("b").strip()
    elif "million" in text or text.endswith("m"):
        multiplier = 1_000_000.0
        text = text.replace("million", "").rstrip("m").strip()
    elif "thousand" in text or text.endswith("k"):
        multiplier = 1_000.0
        text = text.replace("thousand", "").rstrip("k").strip()

    # Keep only the leading numeric portion.
    numeric = ""
    seen_dot = False
    for char in text:
        if char.isdigit():
            numeric += char
        elif char == "." and not seen_dot:
            numeric += char
            seen_dot = True
        elif numeric:
            break

    if not numeric:
        return None

    try:
        return float(numeric) * multiplier
    except ValueError:
        return None


def parse_payment_terms_days(value: Any) -> Optional[int]:
    """Extract a payment-terms period in days from free text.

    Handles "Net 30", "net-60", "45 days", "2/10 net 30" (the longest period
    is the contract term, which is what matters for risk purposes).
    """
    if value is None:
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)

    import re

    text = str(value).lower()
    if not text.strip():
        return None

    matches = [int(m) for m in re.findall(r"\b(\d{1,3})\s*(?:days|day)?\b", text)]
    candidates = [m for m in matches if 0 < m <= 365]
    if not candidates:
        return None
    return max(candidates)
