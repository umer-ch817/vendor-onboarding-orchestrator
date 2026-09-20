"""Requirement resolution: what does *this* vendor actually have to provide?

A single hard-coded document checklist is the most common way a vendor
onboarding system becomes wrong. A domestic software supplier and an
offshore contractor do not owe the same paperwork, and a system that asks
for both is one that reviewers learn to ignore.

Requirements are therefore data, not code. Each row carries applicability
conditions (vendor type, country, industry, risk level) and the resolver
returns the subset that applies to a given case. The conditions are
evaluated deterministically so that "why was this document requested?" always
has a concrete answer.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentType, Requirement
from app.rules.types import RequirementSpec
from app.utils.countries import normalise_country
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Higher-risk jurisdictions. Kept deliberately short and explicit rather than
# derived from a live watchlist: this is a prototype, and a fabricated
# authoritative-looking list would be worse than a small honest one.
HIGH_RISK_COUNTRIES = {"RU", "BY", "IR", "KP", "SY", "CU", "VE"}


# Country values are ISO-3166 alpha-2 codes, but a person filling in a vendor
# record types "United States". Matching that literally against "US" is how a
# US vendor came to be asked for the non-US tax certificate and never asked
# for a W-9. The normaliser lives in app.utils.countries because the rules
# engine needs it too, and importing it from there would form a cycle.


# The default catalogue, seeded on first run. Codes are stable identifiers so
# that findings, exceptions and UI links can reference them.
DEFAULT_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "code": "REQ-W9",
        "name": "Completed W-9",
        "description": "IRS Form W-9 establishing the vendor's tax identity.",
        "document_type": DocumentType.W9,
        "is_mandatory": True,
        "vendor_types": ["supplier", "contractor", "consultant", "service_provider"],
        "countries": ["US"],
        "industries": None,
        "risk_levels": None,
        "validation_rules": {"require_tin": True},
    },
    {
        "code": "REQ-TAX-CERT",
        "name": "Tax registration certificate",
        "description": "Local tax registration, required for non-US vendors.",
        "document_type": DocumentType.TAX_CERTIFICATE,
        "is_mandatory": True,
        "vendor_types": None,
        "countries": None,  # applies everywhere the W-9 does not
        "industries": None,
        "risk_levels": None,
        "validation_rules": {},
    },
    {
        "code": "REQ-COI",
        "name": "Certificate of insurance",
        "description": (
            "Evidence of general liability coverage at or above the "
            "configured minimum."
        ),
        "document_type": DocumentType.CERTIFICATE_OF_INSURANCE,
        "is_mandatory": True,
        "vendor_types": ["supplier", "contractor", "service_provider"],
        "countries": None,
        "industries": None,
        "risk_levels": None,
        "validation_rules": {"min_coverage": 2_000_000},
    },
    {
        "code": "REQ-BUSREG",
        "name": "Business registration",
        "description": "Proof the entity is legally registered and active.",
        "document_type": DocumentType.BUSINESS_REGISTRATION,
        "is_mandatory": True,
        "vendor_types": ["supplier", "service_provider"],
        "countries": None,
        "industries": None,
        "risk_levels": None,
        "validation_rules": {},
    },
    {
        "code": "REQ-BANK",
        "name": "Banking confirmation",
        "description": (
            "Bank letter or voided check confirming the account holder name. "
            "Required before any payment can be released."
        ),
        "document_type": DocumentType.BANKING_CONFIRMATION,
        "is_mandatory": True,
        "vendor_types": None,
        "countries": None,
        "industries": None,
        "risk_levels": None,
        "validation_rules": {},
    },
    {
        "code": "REQ-SUPPLIER-Q",
        "name": "Supplier questionnaire",
        "description": (
            "Ownership and conflict-of-interest disclosure. Mandatory for "
            "high-risk vendors or those in sensitive industries."
        ),
        "document_type": DocumentType.SUPPLIER_QUESTIONNAIRE,
        "is_mandatory": False,
        "vendor_types": None,
        "countries": None,
        "industries": ["defense", "healthcare", "financial_services"],
        "risk_levels": ["high", "critical"],
        "validation_rules": {"require_ownership_disclosure": True},
    },
]


class RequirementService:
    """Resolves the document requirements applicable to a case."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def seed_defaults(self) -> int:
        """Insert the default catalogue if the table is empty.

        Returns the number of rows inserted. Idempotent: existing rows are
        never overwritten, because an operator may have tuned them.
        """
        existing = await self.db.execute(select(Requirement.code))
        known = {row[0] for row in existing.all()}

        inserted = 0
        for spec in DEFAULT_REQUIREMENTS:
            if spec["code"] in known:
                continue
            self.db.add(Requirement(is_active=True, **spec))
            inserted += 1

        if inserted:
            await self.db.flush()
            logger.info("requirements_seeded", extra={"count": inserted})

        return inserted

    async def resolve(
        self,
        *,
        vendor_type: Optional[str] = None,
        country: Optional[str] = None,
        industry: Optional[str] = None,
        risk_level: Optional[str] = None,
    ) -> list[RequirementSpec]:
        """Return the requirements applicable to these vendor attributes."""
        result = await self.db.execute(
            select(Requirement).where(Requirement.is_active.is_(True))
        )
        rows = result.scalars().all()

        applicable = [
            row
            for row in rows
            if _applies(row, vendor_type, country, industry, risk_level)
        ]

        return [
            RequirementSpec(
                code=row.code,
                name=row.name,
                document_type=_enum_value(row.document_type),
                is_mandatory=bool(row.is_mandatory),
                description=row.description or "",
            )
            for row in applicable
        ]


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else (str(value) if value else "")


def _applies(
    requirement: Requirement,
    vendor_type: Optional[str],
    country: Optional[str],
    industry: Optional[str],
    risk_level: Optional[str],
) -> bool:
    """Evaluate one requirement's applicability conditions.

    Every condition is opt-in: a null or empty condition list means "applies
    to everyone", which keeps the catalogue readable and avoids an ever-
    growing list of exclusions.

    The tax certificate is the one special case. It is the non-US counterpart
    of the W-9, and both are in the catalogue unconditionally, so without a
    guard a US vendor would be asked for both. We resolve that here rather
    than encoding "not US" as a condition no one will remember.
    """
    code = normalise_country(country)

    if requirement.code == "REQ-TAX-CERT" and code == "US":
        return False
    if requirement.code == "REQ-W9" and code and code != "US":
        return False

    if not _matches(requirement.vendor_types, vendor_type):
        return False
    if not _country_matches(requirement.countries, code):
        return False
    if not _matches(requirement.industries, industry):
        return False
    if not _matches(requirement.risk_levels, risk_level):
        return False

    return True


def _matches(condition: Optional[Iterable[str]], value: Optional[str]) -> bool:
    """Whether ``value`` satisfies a condition list.

    An empty or absent list matches everything. Comparison is case-insensitive
    so that "Supplier" and "supplier" do not silently diverge.
    """
    if condition is None:
        return True
    values = list(condition)
    if not values:
        return True
    if not value:
        return False
    lowered = {str(v).strip().lower() for v in values}
    return str(value).strip().lower() in lowered


def _country_matches(condition: Optional[Iterable[str]], code: Optional[str]) -> bool:
    """Whether a normalised country code satisfies a country condition list.

    Separate from ``_matches`` because both sides must be canonicalised to
    alpha-2 before comparing: a catalogue entry of "US" has to match a vendor
    recorded as "United States", and neither side can be trusted to already
    be in code form.
    """
    if condition is None:
        return True
    values = list(condition)
    if not values:
        return True
    if not code:
        return False
    wanted = {(normalise_country(v) or "").lower() for v in values}
    return code.lower() in wanted


def is_high_risk_country(country: Optional[str]) -> bool:
    """Whether a country is on the prototype's high-risk list.

    Accepts either an alpha-2 code or a spelled-out name, so "Russia" and
    "RU" agree.
    """
    if not country:
        return False
    code = normalise_country(country)
    return code in HIGH_RISK_COUNTRIES if code else False
