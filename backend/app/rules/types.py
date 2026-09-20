"""Shared types for the deterministic rule engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass
class FieldEvidence:
    """A single extracted field, with everything needed to compare it."""

    name: str
    raw_value: Any
    normalized_value: str
    confidence: float
    document_id: Optional[int] = None
    document_type: Optional[str] = None
    manually_corrected: bool = False

    @property
    def is_present(self) -> bool:
        if self.raw_value is None:
            return False
        if isinstance(self.raw_value, str) and not self.raw_value.strip():
            return False
        return True


@dataclass
class DocumentEvidence:
    """One document plus its extracted fields, as seen by the rule engine."""

    document_id: Optional[int]
    document_type: str
    filename: str = ""
    status: str = "pending"
    extraction_confidence: float = 0.0
    expiration_date: Optional[date] = None
    document_date: Optional[date] = None
    fields: dict[str, FieldEvidence] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def value(self, field_name: str) -> Any:
        """Raw value of a field, or None."""
        field = self.fields.get(field_name)
        return field.raw_value if field else None

    def normalized(self, field_name: str) -> str:
        """Normalized value of a field, or empty string."""
        field = self.fields.get(field_name)
        return field.normalized_value if field else ""

    def confidence_of(self, field_name: str) -> float:
        field = self.fields.get(field_name)
        return field.confidence if field else 0.0

    def has(self, field_name: str) -> bool:
        field = self.fields.get(field_name)
        return bool(field and field.is_present)


@dataclass
class RequirementSpec:
    """A document requirement applicable to this case."""

    code: str
    name: str
    document_type: str
    is_mandatory: bool = True
    description: str = ""


@dataclass
class EmployeeVendorContext:
    """Everything the rule engine needs to evaluate a case.

    Deliberately a plain dataclass rather than an ORM object so the rule
    engine is unit-testable without a database.
    """

    vendor_id: Optional[int]
    legal_name: str = ""
    trade_name: str = ""
    country: str = ""
    state: str = ""
    industry: str = ""
    vendor_type: str = ""
    tax_id: str = ""
    address_line1: str = ""
    city: str = ""
    postal_code: str = ""
    bank_name: str = ""
    documented_account_holder: str = ""
    ownership_disclosed: bool = False
    payment_terms_days: Optional[int] = None


@dataclass
class RuleFinding:
    """A single deterministic finding.

    ``risk_points`` is the finding's contribution to the risk score. Keeping
    it on the finding rather than in a separate table is what makes the score
    explainable: the score *is* the sum of the findings a reviewer can read.
    """

    code: str
    severity: str
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    risk_points: int = 0
    source: str = "rules_engine"
    related_document_id: Optional[int] = None
    creates_exception: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "risk_points": self.risk_points,
            "source": self.source,
            "related_document_id": self.related_document_id,
            "creates_exception": self.creates_exception,
        }


@dataclass
class RuleEvaluation:
    """Complete output of one rule engine pass."""

    findings: list[RuleFinding] = field(default_factory=list)
    thresholds_used: dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=datetime.utcnow)

    def by_code(self, code: str) -> list[RuleFinding]:
        return [f for f in self.findings if f.code == code]

    def has_code(self, code: str) -> bool:
        return any(f.code == code for f in self.findings)

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]

    @property
    def total_risk_points(self) -> int:
        return sum(f.risk_points for f in self.findings)

    @property
    def highest_severity(self) -> str:
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if not self.findings:
            return "low"
        return max(self.findings, key=lambda f: order.get(f.severity, 0)).severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "total_risk_points": self.total_risk_points,
            "highest_severity": self.highest_severity,
            "thresholds_used": self.thresholds_used,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
