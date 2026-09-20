"""Deterministic rule engine.

This module is the heart of the system's reliability story. Everything it
produces is reproducible: given the same inputs it always returns the same
findings, with no model in the loop.

WHY THIS EXISTS SEPARATELY FROM THE AI LAYER
--------------------------------------------
A reviewer must be able to answer "why was this vendor flagged?" with a
sentence that is true six months later. Model output cannot provide that
guarantee -- the model may be upgraded, the prompt changed, or the provider
swapped. Rules can. The AI layer contributes observations; this layer
contributes findings that can be audited and regression-tested.

Each rule is a small class with an ``evaluate`` method. Adding a rule means
adding a class and registering it; nothing else changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Optional

from app.config import settings
from app.rules.types import (
    DocumentEvidence,
    EmployeeVendorContext,
    RequirementSpec,
    RuleEvaluation,
    RuleFinding,
)
from app.utils.countries import normalise_country
from app.utils.logging import get_logger
from app.utils.normalization import (
    addresses_are_equivalent,
    names_are_equivalent,
    normalize_tax_id,
)

logger = get_logger(__name__)

# Countries subject to additional onboarding scrutiny. In a real deployment
# this would be sourced from a sanctions list; here it is configuration.
HIGH_RISK_COUNTRIES = {"KP", "IR", "SY", "CU", "RU", "BY", "MM", "AF"}


class Rule(ABC):
    """Base class for all rules."""

    code: str = "UNKNOWN_RULE"
    description: str = ""

    @abstractmethod
    def evaluate(
        self,
        vendor: EmployeeVendorContext,
        documents: list[DocumentEvidence],
        requirements: list[RequirementSpec],
        today: date,
    ) -> list[RuleFinding]:
        """Return zero or more findings. Never raise for missing data."""


# ---------------------------------------------------------------------------
# Requirement rules
# ---------------------------------------------------------------------------

class MissingDocumentRule(Rule):
    """A mandatory document required for this vendor category was not supplied."""

    code = "DOCUMENT_MISSING"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        present_types = {d.document_type for d in documents if d.status != "failed"}

        for requirement in requirements:
            if not requirement.is_mandatory:
                continue
            if requirement.document_type in present_types:
                continue

            findings.append(
                RuleFinding(
                    code=self.code,
                    severity="high",
                    title=f"Required document not received: {requirement.name}",
                    description=(
                        f"The requirement '{requirement.name}' applies to this vendor but no "
                        f"{requirement.document_type.replace('_', ' ')} was received. "
                        f"Onboarding cannot complete until it is supplied."
                    ),
                    evidence={
                        "requirement_code": requirement.code,
                        "requirement_name": requirement.name,
                        "expected_document_type": requirement.document_type,
                        "documents_received": sorted(present_types),
                    },
                    risk_points=settings.RISK_WEIGHT_MISSING_DOCUMENT,
                )
            )
        return findings


class ExpiredDocumentRule(Rule):
    """A document on file has passed its expiration date.

    Also raises a lower-severity finding when a document is approaching
    expiry, so the case can be handled proactively rather than after
    coverage has already lapsed.
    """

    code = "DOCUMENT_EXPIRED"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        warning_days = settings.RULE_INSURANCE_EXPIRY_WARNING_DAYS

        for document in documents:
            if document.expiration_date is None:
                continue

            days_remaining = (document.expiration_date - today).days

            if days_remaining < 0:
                findings.append(
                    RuleFinding(
                        code="DOCUMENT_EXPIRED",
                        severity="high",
                        title=f"Expired document: {document.document_type.replace('_', ' ')}",
                        description=(
                            f"The {document.document_type.replace('_', ' ')} on file expired on "
                            f"{document.expiration_date.isoformat()} "
                            f"({abs(days_remaining)} days ago). It no longer evidences current coverage."
                        ),
                        evidence={
                            "document_type": document.document_type,
                            "filename": document.filename,
                            "expiration_date": document.expiration_date.isoformat(),
                            "days_expired": abs(days_remaining),
                        },
                        risk_points=settings.RISK_WEIGHT_EXPIRED_DOCUMENT,
                        related_document_id=document.document_id,
                    )
                )
            elif days_remaining <= warning_days:
                findings.append(
                    RuleFinding(
                        code="DOCUMENT_EXPIRING_SOON",
                        severity="medium",
                        title=f"Document expiring soon: {document.document_type.replace('_', ' ')}",
                        description=(
                            f"The {document.document_type.replace('_', ' ')} expires on "
                            f"{document.expiration_date.isoformat()}, in {days_remaining} days. "
                            f"Renewal should be requested before coverage lapses."
                        ),
                        evidence={
                            "document_type": document.document_type,
                            "filename": document.filename,
                            "expiration_date": document.expiration_date.isoformat(),
                            "days_remaining": days_remaining,
                            "warning_window_days": warning_days,
                        },
                        risk_points=settings.RISK_WEIGHT_EXPIRING_SOON,
                        related_document_id=document.document_id,
                    )
                )

        return findings


class TaxInformationRule(Rule):
    """Tax identification information is absent or malformed."""

    code = "TAX_INFORMATION_MISSING"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []

        w9_docs = [d for d in documents if d.document_type == "w9"]
        if not w9_docs:
            return findings  # covered by the missing-document rule

        tin_found = False
        for document in w9_docs:
            tin_raw = document.value("tin")
            if normalize_tax_id(tin_raw):
                tin_found = True
                break

        vendor_tin = normalize_tax_id(vendor.tax_id)
        if vendor_tin:
            tin_found = True

        if not tin_found:
            findings.append(
                RuleFinding(
                    code=self.code,
                    severity="high",
                    title="Tax identification number is missing",
                    description=(
                        "A W-9 is on file but no Taxpayer Identification Number could be read "
                        "from it, and no tax ID is recorded on the vendor profile. Payment "
                        "cannot be configured without a valid TIN."
                    ),
                    evidence={
                        "documents_checked": [d.filename for d in w9_docs],
                        "vendor_tax_id_present": bool(vendor_tin),
                    },
                    risk_points=settings.RISK_WEIGHT_MISSING_DOCUMENT,
                )
            )

        return findings


# ---------------------------------------------------------------------------
# Cross-document consistency rules
# ---------------------------------------------------------------------------

class EntityNameConsistencyRule(Rule):
    """Legal names differ materially across documents.

    This is the rule that most needs normalization to work. "Supplies LLC"
    and "Supplies, L.L.C." are the same entity; "Supplies LLC" and "Supply
    LLC" are not. Only the second should raise a finding.
    """

    code = "ENTITY_NAME_MISMATCH"

    FIELD_BY_TYPE = {
        "w9": "legal_name",
        "certificate_of_insurance": "insured_name",
        "business_registration": "legal_name",
        "master_services_agreement": "party_b",
        "supplier_questionnaire": "company_name",
        # NOTE: banking_confirmation is deliberately absent. Comparing the
        # account holder here as well would double-count a single underlying
        # fact -- the same mismatch would raise both ENTITY_NAME_MISMATCH and
        # BANKING_NAME_MISMATCH, inflating the risk score and showing a
        # reviewer two findings where there is one problem. The dedicated
        # BankingNameConsistencyRule owns that comparison, at a higher weight,
        # because a payee/account-holder mismatch is a materially different
        # (and more serious) concern than a name inconsistency.
    }

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        threshold = settings.RULE_VENDOR_NAME_SIMILARITY_THRESHOLD

        # Collect one name per document type.
        observed: list[tuple[str, str, str]] = []  # (doc_type, filename, name)
        for document in documents:
            field_name = self.FIELD_BY_TYPE.get(document.document_type)
            if not field_name:
                continue
            name = document.value(field_name)
            if name and str(name).strip():
                observed.append((document.document_type, document.filename, str(name).strip()))

        if len(observed) < 2:
            return findings

        # Compare each pair once.
        seen_pairs: set[tuple[int, int]] = set()
        for i in range(len(observed)):
            for j in range(i + 1, len(observed)):
                if (i, j) in seen_pairs:
                    continue
                seen_pairs.add((i, j))

                type_a, file_a, name_a = observed[i]
                type_b, file_b, name_b = observed[j]

                equivalent, score = names_are_equivalent(name_a, name_b, threshold)
                if equivalent:
                    continue

                findings.append(
                    RuleFinding(
                        code=self.code,
                        severity="high",
                        title="Legal name differs between documents",
                        description=(
                            f"The entity name on the {type_a.replace('_', ' ')} "
                            f"('{name_a}') does not match the name on the "
                            f"{type_b.replace('_', ' ')} ('{name_b}'). "
                            f"Similarity after normalization was {score:.2f}, below the "
                            f"{threshold:.2f} match threshold."
                        ),
                        evidence={
                            "comparison": [
                                {
                                    "document_type": type_a,
                                    "filename": file_a,
                                    "raw_value": name_a,
                                },
                                {
                                    "document_type": type_b,
                                    "filename": file_b,
                                    "raw_value": name_b,
                                },
                            ],
                            "similarity_score": score,
                            "threshold": threshold,
                            "normalization_applied": "company_name",
                        },
                        risk_points=settings.RISK_WEIGHT_ENTITY_MISMATCH,
                    )
                )

        return findings


class AddressConsistencyRule(Rule):
    """Address differs between documents beyond normalization tolerance.

    Severity is deliberately lower than a name mismatch: a differing suite
    number is noise, but a wholly different street address suggests the
    documents may describe different entities.
    """

    code = "ADDRESS_MISMATCH"

    FIELD_BY_TYPE = {
        "w9": "address",
        "certificate_of_insurance": None,  # COIs often omit the address entirely
        "business_registration": "address",
        "banking_confirmation": None,
    }

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []

        observed: list[tuple[str, str, str]] = []
        for document in documents:
            field_name = self.FIELD_BY_TYPE.get(document.document_type)
            if not field_name:
                continue
            address = document.value(field_name)
            if address and str(address).strip():
                observed.append((document.document_type, document.filename, str(address).strip()))

        if vendor.address_line1:
            observed.append(("vendor_profile", "vendor record", vendor.address_line1))

        if len(observed) < 2:
            return findings

        seen_pairs: set[tuple[int, int]] = set()
        for i in range(len(observed)):
            for j in range(i + 1, len(observed)):
                if (i, j) in seen_pairs:
                    continue
                seen_pairs.add((i, j))

                type_a, file_a, addr_a = observed[i]
                type_b, file_b, addr_b = observed[j]

                equivalent, score = addresses_are_equivalent(addr_a, addr_b)
                if equivalent:
                    continue

                findings.append(
                    RuleFinding(
                        code=self.code,
                        severity="low",
                        title="Address differs between documents",
                        description=(
                            f"The address on the {type_a.replace('_', ' ')} ('{addr_a}') differs "
                            f"from the address on the {type_b.replace('_', ' ')} ('{addr_b}'). "
                            f"These did not normalize to a common value."
                        ),
                        evidence={
                            "comparison": [
                                {"document_type": type_a, "filename": file_a, "raw_value": addr_a},
                                {"document_type": type_b, "filename": file_b, "raw_value": addr_b},
                            ],
                            "similarity_score": score,
                            "normalization_applied": "address",
                        },
                        risk_points=5,
                    )
                )

        return findings


class BankingNameConsistencyRule(Rule):
    """Bank account holder does not match the vendor's legal name.

    Weighted heavily and always escalated, because a bank account in a
    different name is a known payment-redirection fraud pattern.
    """

    code = "BANKING_NAME_MISMATCH"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        threshold = settings.RULE_VENDOR_NAME_SIMILARITY_THRESHOLD

        bank_docs = [d for d in documents if d.document_type == "banking_confirmation"]
        if not bank_docs:
            return findings

        reference_name = (
            vendor.documented_account_holder
            or vendor.legal_name
            or next(
                (d.value("legal_name") for d in documents if d.has("legal_name")),
                "",
            )
        )
        if not reference_name:
            return findings

        for document in bank_docs:
            holder = document.value("account_holder")
            if not holder or not str(holder).strip():
                continue

            equivalent, score = names_are_equivalent(
                str(holder), str(reference_name), threshold
            )
            if equivalent:
                continue

            findings.append(
                RuleFinding(
                    code=self.code,
                    severity="critical",
                    title="Bank account holder does not match vendor legal name",
                    description=(
                        f"The banking confirmation names '{holder}' as the account holder, but "
                        f"the vendor's legal name is '{reference_name}'. A mismatch between the "
                        f"payee and the account holder is a known payment-redirection risk and "
                        f"must be verified before any payment is configured."
                    ),
                    evidence={
                        "bank_document": document.filename,
                        "account_holder": str(holder),
                        "expected_name": str(reference_name),
                        "similarity_score": score,
                        "threshold": threshold,
                        "normalization_applied": "company_name",
                    },
                    risk_points=settings.RISK_WEIGHT_BANKING_MISMATCH,
                    related_document_id=document.document_id,
                )
            )

        return findings


# ---------------------------------------------------------------------------
# Confidence and completeness rules
# ---------------------------------------------------------------------------

class LowConfidenceExtractionRule(Rule):
    """Extraction confidence is too low to act on automatically."""

    code = "LOW_CONFIDENCE_EXTRACTION"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        threshold = settings.CONFIDENCE_MEDIUM

        for document in documents:
            if document.status not in {"extracted", "processing"}:
                continue
            if document.extraction_confidence >= threshold:
                continue

            findings.append(
                RuleFinding(
                    code=self.code,
                    severity="medium",
                    title=f"Low extraction confidence: {document.document_type.replace('_', ' ')}",
                    description=(
                        f"The {document.document_type.replace('_', ' ')} was processed with an "
                        f"overall confidence of {document.extraction_confidence:.2f}, below the "
                        f"{threshold:.2f} threshold required for automatic processing. A human "
                        f"must verify the extracted values before they are relied upon."
                    ),
                    evidence={
                        "document_type": document.document_type,
                        "filename": document.filename,
                        "extraction_confidence": document.extraction_confidence,
                        "threshold": threshold,
                        "warnings": document.warnings,
                    },
                    risk_points=settings.RISK_WEIGHT_LOW_CONFIDENCE,
                    related_document_id=document.document_id,
                )
            )

        return findings


class ExtractionFailureRule(Rule):
    """Extraction could not be completed at all for a document."""

    code = "EXTRACTION_FAILED"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        for document in documents:
            if document.status != "failed":
                continue
            findings.append(
                RuleFinding(
                    code=self.code,
                    severity="high",
                    title=f"Document could not be processed: {document.document_type.replace('_', ' ')}",
                    description=(
                        f"The {document.document_type.replace('_', ' ')} could not be processed "
                        f"automatically. The document may be corrupt, scanned at low quality, or "
                        f"in an unsupported format. Manual entry is required."
                    ),
                    evidence={
                        "document_type": document.document_type,
                        "filename": document.filename,
                        "warnings": document.warnings,
                    },
                    risk_points=settings.RISK_WEIGHT_LOW_CONFIDENCE,
                    related_document_id=document.document_id,
                )
            )
        return findings


class InsuranceCoverageRule(Rule):
    """Insurance coverage limits fall below the configured minimum."""

    code = "INSURANCE_BELOW_MINIMUM"

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []
        minimum = settings.RULE_INSURANCE_MIN_COVERAGE

        for document in documents:
            if document.document_type != "certificate_of_insurance":
                continue

            raw_amount = document.value("coverage_amount")
            if raw_amount is None:
                continue

            amount = _parse_currency(raw_amount)
            if amount is None:
                continue

            if amount < minimum:
                findings.append(
                    RuleFinding(
                        code=self.code,
                        severity="high",
                        title="Insurance coverage below required minimum",
                        description=(
                            f"The certificate of insurance states coverage of "
                            f"${amount:,.0f}, which is below the required minimum of "
                            f"${minimum:,.0f} for this vendor category."
                        ),
                        evidence={
                            "document_type": document.document_type,
                            "filename": document.filename,
                            "stated_coverage": amount,
                            "required_minimum": minimum,
                        },
                        risk_points=settings.RISK_WEIGHT_MISSING_DOCUMENT,
                        related_document_id=document.document_id,
                    )
                )

        return findings


class HighRiskGeographyRule(Rule):
    """Vendor is domiciled in a jurisdiction requiring enhanced scrutiny."""

    code = "HIGH_RISK_GEOGRAPHY"

    def evaluate(self, vendor, documents, requirements, today):
        if not vendor.country:
            return []
        # "Russia" and "RU" have to agree: the stored value may be spelled
        # out even though the watchlist is written in alpha-2 codes.
        country = normalise_country(vendor.country)
        if not country or country not in HIGH_RISK_COUNTRIES:
            return []

        return [
            RuleFinding(
                code=self.code,
                severity="high",
                title=f"Vendor located in a jurisdiction requiring enhanced review: {country}",
                description=(
                    f"The vendor is domiciled in {country}, which is on the configured list of "
                    f"jurisdictions requiring enhanced due diligence. Compliance review is "
                    f"required before onboarding."
                ),
                evidence={
                    "country": country,
                    "watchlist": sorted(HIGH_RISK_COUNTRIES),
                    "source": "configured high-risk geography list",
                },
                risk_points=settings.RISK_WEIGHT_HIGH_RISK_GEOGRAPHY,
            )
        ]


class OwnershipDisclosureRule(Rule):
    """Beneficial ownership information was not disclosed."""

    code = "INCOMPLETE_OWNERSHIP_INFORMATION"

    def evaluate(self, vendor, documents, requirements, today):
        if vendor.ownership_disclosed:
            return []

        # Only raise this if an entity that would normally disclose ownership
        # is actually present. A case with no questionnaire at all is already
        # covered by the missing-document rule, and double-counting it would
        # inflate the score without adding information.
        questionnaire_docs = [
            d for d in documents if d.document_type == "supplier_questionnaire"
        ]
        if not questionnaire_docs:
            return []

        for document in questionnaire_docs:
            if document.has("beneficial_owners"):
                return []

        return [
            RuleFinding(
                code=self.code,
                severity="medium",
                title="Beneficial ownership information not disclosed",
                description=(
                    "The supplier questionnaire was received but does not disclose beneficial "
                    "ownership. Ownership information is required to complete due diligence on "
                    "this entity."
                ),
                evidence={
                    "documents_checked": [d.filename for d in questionnaire_docs],
                    "field_expected": "beneficial_owners",
                },
                risk_points=settings.RISK_WEIGHT_INCOMPLETE_OWNERSHIP,
            )
        ]


class UnusualPaymentTermsRule(Rule):
    """Requested payment terms fall outside the standard range."""

    code = "UNUSUAL_PAYMENT_TERMS"

    MAX_STANDARD_DAYS = 60

    def evaluate(self, vendor, documents, requirements, today):
        findings: list[RuleFinding] = []

        terms_days = vendor.payment_terms_days
        if terms_days is None:
            for document in documents:
                raw = document.value("payment_terms")
                if raw:
                    terms_days = _parse_payment_terms(raw)
                    if terms_days is not None:
                        break

        if terms_days is None or terms_days <= self.MAX_STANDARD_DAYS:
            return findings

        return [
            RuleFinding(
                code=self.code,
                severity="medium",
                title=f"Unusual payment terms requested: {terms_days} days",
                description=(
                    f"The vendor's documentation requests payment terms of {terms_days} days, "
                    f"which exceeds the standard maximum of {self.MAX_STANDARD_DAYS} days. "
                    f"Longer terms materially affect working capital and should be confirmed "
                    f"commercially before approval."
                ),
                evidence={
                    "requested_terms_days": terms_days,
                    "standard_maximum_days": self.MAX_STANDARD_DAYS,
                },
                risk_points=10,
                creates_exception=False,
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_currency(value: Any) -> Optional[float]:
    """Parse '$2,000,000' / '2000000' / '2M' into a number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower().replace(",", "").replace("$", "")
    text = text.replace("usd", "").strip()

    multiplier = 1.0
    if text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]

    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _parse_payment_terms(value: Any) -> Optional[int]:
    """Parse 'Net 30', 'net 120 days', '30' into an integer day count."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    import re

    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[Rule] = [
    MissingDocumentRule(),
    ExpiredDocumentRule(),
    TaxInformationRule(),
    EntityNameConsistencyRule(),
    AddressConsistencyRule(),
    BankingNameConsistencyRule(),
    LowConfidenceExtractionRule(),
    ExtractionFailureRule(),
    InsuranceCoverageRule(),
    HighRiskGeographyRule(),
    OwnershipDisclosureRule(),
    UnusualPaymentTermsRule(),
]


class RuleEngine:
    """Runs every registered rule against a case and collects the findings."""

    def __init__(self, rules: Optional[list[Rule]] = None):
        self.rules = rules if rules is not None else list(DEFAULT_RULES)

    def evaluate(
        self,
        vendor: EmployeeVendorContext,
        documents: list[DocumentEvidence],
        requirements: list[RequirementSpec],
        today: Optional[date] = None,
    ) -> RuleEvaluation:
        """Evaluate all rules. A rule that raises is logged and skipped.

        One badly-behaved rule must not take down the whole evaluation: the
        remaining rules still produce findings, and the failure is recorded.
        """
        today = today or date.today()
        evaluation = RuleEvaluation(
            thresholds_used={
                "name_similarity": settings.RULE_VENDOR_NAME_SIMILARITY_THRESHOLD,
                "insurance_min_coverage": settings.RULE_INSURANCE_MIN_COVERAGE,
                "insurance_expiry_warning_days": settings.RULE_INSURANCE_EXPIRY_WARNING_DAYS,
                "confidence_required": settings.CONFIDENCE_MEDIUM,
                "auto_approve_max_risk": settings.RULE_AUTO_APPROVE_MAX_RISK,
            }
        )

        for rule in self.rules:
            try:
                evaluation.findings.extend(
                    rule.evaluate(vendor, documents, requirements, today)
                )
            except Exception as exc:  # noqa: BLE001 - isolate rule failures
                logger.error(
                    "rule_evaluation_failed",
                    extra={"rule": rule.code, "error": str(exc)},
                )

        logger.info(
            "rule_evaluation_complete",
            extra={
                "vendor_id": vendor.vendor_id,
                "finding_count": len(evaluation.findings),
                "total_risk_points": evaluation.total_risk_points,
                "codes": evaluation.codes,
            },
        )

        return evaluation
