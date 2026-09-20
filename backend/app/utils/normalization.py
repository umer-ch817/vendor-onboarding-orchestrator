"""Text normalization utilities.

This module is the foundation of cross-document consistency checking. The
core problem it solves: two documents can describe the same real-world
entity while being textually different.

    "Northstar Industrial Supplies LLC"
    "Northstar Industrial Supplies, L.L.C."
    "NORTHSTAR INDUSTRIAL SUPPLIES L.L.C"

All three must resolve to the same canonical form, otherwise the system
generates false-positive mismatch exceptions and erodes reviewer trust.

Design principle: normalization is *lossy by design*. We therefore always
store the raw value alongside the normalized value so a reviewer can audit
what the system actually compared.
"""
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional

from dateutil import parser as date_parser

# ---------------------------------------------------------------------------
# Company suffix handling
# ---------------------------------------------------------------------------

# Suffixes that carry no distinguishing information for entity matching.
# Order matters: longer forms must be replaced before shorter ones so that
# "L.L.C." is not partially consumed by the "LLC" rule.
COMPANY_SUFFIXES = [
    "limited liability company",
    "limited liability partnership",
    "limited partnership",
    "incorporated",
    "corporation",
    "company",
    "limited",
    "holdings",
    "group",
    "l.l.c.",
    "l.l.p.",
    "l.p.",
    "llc",
    "llp",
    "inc.",
    "inc",
    "corp.",
    "corp",
    "co.",
    "co",
    "ltd.",
    "ltd",
    "gmbh",
    "s.a.",
    "s.a.s.",
    "s.l.",
    "b.v.",
    "n.v.",
    "pty",
    "plc",
    "ag",
    "sa",
    "sas",
    "bv",
]

# Address tokens that are functionally equivalent.
ADDRESS_ABBREVIATIONS = {
    "street": "st",
    "avenue": "ave",
    "boulevard": "blvd",
    "drive": "dr",
    "road": "rd",
    "lane": "ln",
    "court": "ct",
    "place": "pl",
    "parkway": "pkwy",
    "highway": "hwy",
    "suite": "ste",
    "apartment": "apt",
    "building": "bldg",
    "floor": "fl",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
}

# Directional/unit noise that adds no matching value.
ADDRESS_NOISE = {"ste", "suite", "apt", "apartment", "unit", "bldg", "building", "fl", "floor"}

# Tokens that are *labels* rather than content. When one of these appears,
# the numeric token that follows it is a unit/floor number and is dropped
# too -- "Suite 400" and "" must compare equal.
ADDRESS_UNIT_LABELS = {"ste", "suite", "apt", "apartment", "unit", "bldg", "building", "fl", "floor"}

# Corporate noise words that frequently appear or vanish between documents.
CORPORATE_NOISE = {"the", "and", "of", "for", "a", "an"}


def _strip_diacritics(value: str) -> str:
    """Convert accented characters to their ASCII base form."""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value: Optional[str]) -> str:
    """Base normalization: lowercase, strip punctuation, collapse whitespace.

    This is the shared first pass for every other normalizer.
    """
    if value is None:
        return ""
    text = _strip_diacritics(str(value))
    text = text.lower().strip()
    # Replace any non-alphanumeric (keeping spaces) with a space.
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Collapse runs of whitespace.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _collapse_dotted_acronyms(value: str) -> str:
    """Collapse dotted legal forms so they survive punctuation stripping.

    ``normalize_text`` replaces every non-alphanumeric character with a
    space, which turns "L.L.C." into "l l c" and destroys the suffix. We
    therefore fuse dotted acronyms *before* the base normalization pass.

    >>> _collapse_dotted_acronyms("Supplies, L.L.C.")
    'Supplies, LLC'
    >>> _collapse_dotted_acronyms("S.A.S.")
    'SAS'
    """
    # Three-letter forms first: L.L.C. -> LLC, L.L.P. -> LLP, S.A.S. -> SAS
    text = re.sub(r"\b([A-Za-z])\.([A-Za-z])\.([A-Za-z])\.?", r"\1\2\3", value)
    # Then two-letter forms: L.P. -> LP, S.A. -> SA, B.V. -> BV, N.V. -> NV
    text = re.sub(r"\b([A-Za-z])\.([A-Za-z])\.", r"\1\2", text)
    return text


def normalize_company_name(value: Optional[str]) -> str:
    """Reduce a company name to a canonical, comparable form.

    Steps:
      1. Collapse dotted legal acronyms (L.L.C. -> LLC).
      2. Base text normalization (case, punctuation, whitespace).
      3. Remove corporate noise words.
      4. Strip legal suffixes (LLC, Inc, GmbH, ...).
      5. Re-collapse whitespace.

    >>> normalize_company_name("Northstar Industrial Supplies, L.L.C.")
    'northstar industrial supplies'
    >>> normalize_company_name("NORTHSTAR INDUSTRIAL SUPPLY LLC")
    'northstar industrial supply'
    """
    if value is None:
        return ""
    text = normalize_text(_collapse_dotted_acronyms(str(value)))
    if not text:
        return ""

    # Remove noise words as whole tokens.
    tokens = [t for t in text.split() if t not in CORPORATE_NOISE]
    text = " ".join(tokens)

    # Strip a trailing legal suffix. Applied repeatedly to handle
    # "Company, Inc." style constructions.
    changed = True
    while changed:
        changed = False
        for suffix in COMPANY_SUFFIXES:
            pattern = r"(^|\s)" + re.escape(suffix) + r"(\s|$)"
            if re.search(pattern, text):
                text = re.sub(pattern, " ", text)
                changed = True
                break

    text = re.sub(r"\s+", " ", text).strip()

    # A name consisting only of suffixes normalizes to empty; fall back to
    # the un-suffixed base text so we never compare against "".
    return text or normalize_text(value)


def normalize_address(value: Optional[str]) -> str:
    """Normalize a street address into a canonical, comparable form.

    Handles the common case where one document writes "Avenue" and another
    writes "Ave", and where unit numbers are inconsistently present.

    >>> normalize_address("100 Industrial Avenue, Suite 400")
    '100 industrial ave'
    >>> normalize_address("100 Industrial Ave")
    '100 industrial ave'
    """
    text = normalize_text(_collapse_dotted_acronyms(str(value)))
    if not text:
        return ""

    tokens: list[str] = []
    drop_next_if_numeric = False

    for token in text.split():
        if drop_next_if_numeric:
            drop_next_if_numeric = False
            # The number attached to a unit label ("Suite 400", "Bldg 2").
            if token.isdigit():
                continue

        canonical = ADDRESS_ABBREVIATIONS.get(token, token)

        if canonical in ADDRESS_UNIT_LABELS:
            # Emit nothing, and suppress the unit number that follows.
            drop_next_if_numeric = True
            continue

        tokens.append(canonical)

    return " ".join(tokens).strip()


def normalize_phone(value: Optional[str]) -> str:
    """Reduce a phone number to digits only, keeping a leading country code.

    >>> normalize_phone("(555) 123-4567")
    '5551234567'
    >>> normalize_phone("+1 555.123.4567")
    '15551234567'
    """
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits


def normalize_tax_id(value: Optional[str]) -> str:
    """Normalize a US TIN/EIN to bare digits.

    >>> normalize_tax_id("12-3456789")
    '123456789'
    """
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def normalize_date(value: Optional[str]) -> Optional[str]:
    """Parse a date written in almost any common format into ISO YYYY-MM-DD.

    Returns None when the value cannot be parsed, so callers can distinguish
    "no date" from "unparseable date" rather than silently comparing strings.
    """
    if value is None or str(value).strip() == "":
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    text = str(value).strip()
    try:
        parsed = date_parser.parse(text, fuzzy=True)
        return parsed.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def similarity_ratio(a: Optional[str], b: Optional[str]) -> float:
    """Return a 0..1 similarity ratio between two raw strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, str(a), str(b)).ratio()


def _token_overlap_ratio(a: str, b: str) -> float:
    """Jaccard-style token overlap between two token sets."""
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def names_are_equivalent(
    name_a: Optional[str],
    name_b: Optional[str],
    threshold: float = 0.92,
) -> tuple[bool, float]:
    """Decide whether two company names refer to the same entity.

    Two independent signals are combined because either alone produces
    false positives:

      * token overlap catches word-order and suffix differences
      * sequence similarity catches abbreviation and typo differences

    Returns a tuple of (is_equivalent, confidence) so the caller can record
    *why* it believed the names matched, rather than a bare boolean.

    >>> names_are_equivalent("Northstar Industrial Supplies LLC",
    ...                      "Northstar Industrial Supplies, L.L.C.")[0]
    True
    >>> names_are_equivalent("Northstar Industrial Supplies LLC",
    ...                      "Northstar Industrial Supply LLC")[0]
    False
    """
    norm_a = normalize_company_name(name_a)
    norm_b = normalize_company_name(name_b)

    if not norm_a or not norm_b:
        return False, 0.0

    if norm_a == norm_b:
        return True, 1.0

    overlap = _token_overlap_ratio(norm_a, norm_b)
    sequence = SequenceMatcher(None, norm_a, norm_b).ratio()

    # Weighted blend: token overlap is the stronger signal for names.
    combined = (overlap * 0.6) + (sequence * 0.4)

    return combined >= threshold, round(combined, 4)


def addresses_are_equivalent(
    address_a: Optional[str],
    address_b: Optional[str],
    threshold: float = 0.90,
) -> tuple[bool, float]:
    """Decide whether two addresses describe the same location.

    This is the false-positive guard described in demo Scenario 6:
    "100 Industrial Avenue, Suite 400" and "100 Industrial Ave" must be
    treated as equivalent.

    >>> addresses_are_equivalent("100 Industrial Avenue", "100 Industrial Ave")[0]
    True
    """
    norm_a = normalize_address(address_a)
    norm_b = normalize_address(address_b)

    if not norm_a or not norm_b:
        return False, 0.0

    if norm_a == norm_b:
        return True, 1.0

    overlap = _token_overlap_ratio(norm_a, norm_b)
    sequence = SequenceMatcher(None, norm_a, norm_b).ratio()
    combined = (overlap * 0.5) + (sequence * 0.5)

    return combined >= threshold, round(combined, 4)


def mask_account_number(value: Optional[str]) -> str:
    """Return only the last four digits of an account identifier.

    The demo dataset only ever contains synthetic account numbers, but the
    masking behaviour is implemented for real because it is the correct
    default: the system has no legitimate need to store a full account
    number in order to compare two documents.
    """
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) <= 4:
        return digits
    return digits[-4:]
