"""Country normalisation.

Every country value in this codebase -- the seed data, the requirement
catalogue, the high-risk geography lists -- is an ISO-3166 alpha-2 code
("US", "SG", "DE"). But a person filling in a vendor record does not type
"US"; they type "United States".

Comparing those literally is how a US vendor ended up being asked for the
non-US tax certificate and never asked for a W-9: the value matched neither
the "US" condition nor the guard that was supposed to exempt it.

This module lives in ``app.utils`` rather than beside the requirement
catalogue because both the rules engine and the requirement resolver need
it, and ``app.rules.__init__`` imports the engine -- so a direct import
between those two would form a cycle.

The alias map is deliberately short, and mirrors the honesty of the
high-risk lists: it covers the countries this prototype actually
references. Anything unrecognised is passed through unchanged, so an
unknown country still matches a condition written the same way. The map
can only ever help; it can never silently drop a match.
"""
from __future__ import annotations

from typing import Optional

COUNTRY_ALIASES = {
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "USA": "US",
    "U.S.A.": "US",
    "U.S.": "US",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "UK": "GB",
    "U.K.": "GB",
    "SINGAPORE": "SG",
    "GERMANY": "DE",
    "FRANCE": "FR",
    "JAPAN": "JP",
    "AUSTRALIA": "AU",
    "CANADA": "CA",
    "NETHERLANDS": "NL",
    "THE NETHERLANDS": "NL",
    "HOLLAND": "NL",
    "SOUTH KOREA": "KR",
    "IRELAND": "IE",
    "SWITZERLAND": "CH",
    "SPAIN": "ES",
    "ITALY": "IT",
    "BRAZIL": "BR",
    "INDIA": "IN",
    "CHINA": "CN",
    "MEXICO": "MX",
    "RUSSIA": "RU",
    "RUSSIAN FEDERATION": "RU",
    "BELARUS": "BY",
    "IRAN": "IR",
    "SYRIA": "SY",
    "CUBA": "CU",
    "VENEZUELA": "VE",
    "NORTH KOREA": "KP",
    "MYANMAR": "MM",
    "BURMA": "MM",
    "AFGHANISTAN": "AF",
}


def normalise_country(country: Optional[str]) -> Optional[str]:
    """Canonicalise a country to ISO-3166 alpha-2, or pass it through.

    "United States" -> "US"; "us" -> "US"; "sg" -> "SG". Whitespace is
    collapsed so "United  States" also resolves. An unrecognised value is
    returned trimmed but otherwise unchanged, so callers degrade to the old
    literal behaviour instead of losing the country entirely.
    """
    if not country:
        return None
    cleaned = " ".join(str(country).split()).strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    return COUNTRY_ALIASES.get(upper, cleaned)
