"""Deterministic, explainable risk scoring.

The score is a *sum of the findings a reviewer can read*. That property is
the whole point: when a case is marked HIGH risk, an operator can point at
the specific line items that produced the number.

We deliberately do not ask a model for a score. A model-generated score
cannot be regression-tested, cannot be explained six months later, and
drifts silently when the provider changes. Findings can be all three.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import settings
from app.rules.types import RuleEvaluation, RuleFinding


@dataclass
class ScoreComponent:
    """One contributing factor, preserved for display in the UI."""

    code: str
    label: str
    points: int
    severity: str
    evidence_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "points": self.points,
            "severity": self.severity,
            "evidence_summary": self.evidence_summary,
        }


@dataclass
class RiskScoreResult:
    """The scored result, with full attribution."""

    score: int
    level: str
    components: list[ScoreComponent] = field(default_factory=list)
    explanation: str = ""
    thresholds_used: dict[str, int] = field(default_factory=dict)
    capped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "components": [c.to_dict() for c in self.components],
            "explanation": self.explanation,
            "thresholds_used": self.thresholds_used,
            "capped": self.capped,
        }


# Human-readable labels for each finding code, used in the score breakdown.
FINDING_LABELS = {
    "DOCUMENT_MISSING": "Required document not received",
    "DOCUMENT_EXPIRED": "Document has expired",
    "DOCUMENT_EXPIRING_SOON": "Document expiring soon",
    "TAX_INFORMATION_MISSING": "Tax identification missing",
    "ENTITY_NAME_MISMATCH": "Legal name inconsistency",
    "ADDRESS_MISMATCH": "Address inconsistency",
    "BANKING_NAME_MISMATCH": "Bank account holder mismatch",
    "LOW_CONFIDENCE_EXTRACTION": "Low extraction confidence",
    "EXTRACTION_FAILED": "Document could not be processed",
    "INSURANCE_BELOW_MINIMUM": "Insurance below required minimum",
    "HIGH_RISK_GEOGRAPHY": "High-risk jurisdiction",
    "INCOMPLETE_OWNERSHIP_INFORMATION": "Beneficial ownership not disclosed",
    "UNUSUAL_PAYMENT_TERMS": "Unusual payment terms",
    # AI-sourced codes, which carry no points but appear in the breakdown.
    "INSURANCE_EXPIRY_UNKNOWN": "Insurance expiry undetermined",
}


class RiskScoringService:
    """Turns rule findings into a scored, attributed risk level."""

    def __init__(self, max_score: int = 100):
        self.max_score = max_score

    def score(self, evaluation: RuleEvaluation) -> RiskScoreResult:
        """Compute a risk score from a completed rule evaluation."""
        components = self._build_components(evaluation.findings)

        raw_total = sum(c.points for c in components)
        capped = raw_total > self.max_score
        total = min(raw_total, self.max_score)

        level = self.level_for_score(total)

        # Elevate the displayed level when the severity of an individual
        # finding warrants more concern than the arithmetic does. See
        # SEVERITY_LEVEL_FLOOR for the rationale.
        severity_floor = SEVERITY_LEVEL_FLOOR.get(
            evaluation.highest_severity, "low"
        )
        elevated = LEVEL_RANK.get(severity_floor, 0) > LEVEL_RANK.get(level, 0)
        if elevated:
            level = severity_floor

        return RiskScoreResult(
            score=total,
            level=level,
            components=components,
            explanation=self._explain(total, level, components, capped, elevated),
            thresholds_used={
                "low_max": settings.RISK_THRESHOLD_LOW,
                "medium_max": settings.RISK_THRESHOLD_MEDIUM,
                "high_max": settings.RISK_THRESHOLD_HIGH,
            },
            capped=capped,
        )

    def _build_components(self, findings: list[RuleFinding]) -> list[ScoreComponent]:
        """Convert findings to components, aggregating duplicates.

        Repeated instances of the same code (three missing documents, say)
        are collapsed into one component whose points are the sum. Listing
        the same line three times would make the breakdown harder to read
        without changing the total.
        """
        aggregated: dict[str, ScoreComponent] = {}

        for finding in findings:
            if finding.risk_points <= 0:
                continue

            existing = aggregated.get(finding.code)
            if existing is None:
                aggregated[finding.code] = ScoreComponent(
                    code=finding.code,
                    label=FINDING_LABELS.get(
                        finding.code, finding.code.replace("_", " ").title()
                    ),
                    points=finding.risk_points,
                    severity=finding.severity,
                    evidence_summary=finding.title,
                )
            else:
                existing.points += finding.risk_points
                # Keep the most severe severity seen for this code.
                order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
                if order.get(finding.severity, 0) > order.get(existing.severity, 0):
                    existing.severity = finding.severity

        # Present largest contributors first.
        return sorted(aggregated.values(), key=lambda c: c.points, reverse=True)

    def level_for_score(self, score: int) -> str:
        """Map a numeric score to a risk level."""
        if score <= settings.RISK_THRESHOLD_LOW:
            return "low"
        if score <= settings.RISK_THRESHOLD_MEDIUM:
            return "medium"
        if score <= settings.RISK_THRESHOLD_HIGH:
            return "high"
        return "critical"

    def _explain(
        self,
        score: int,
        level: str,
        components: list[ScoreComponent],
        capped: bool,
        elevated: bool = False,
    ) -> str:
        """Produce a plain-language explanation of the score."""
        if not components:
            return (
                f"Risk score is {score}/100 ({level.upper()}). No risk factors were "
                f"identified by the rule engine."
            )

        driving = ", ".join(
            f"{c.label.lower()} (+{c.points})" for c in components[:3]
        )

        explanation = (
            f"Risk score is {score}/100, placing this vendor at {level.upper()} risk. "
            f"The score is the sum of {len(components)} identified factor"
            f"{'s' if len(components) != 1 else ''}: {driving}."
        )

        if elevated:
            explanation += (
                f" The level was raised above what the numeric score alone implies "
                f"because a finding of {components[0].severity} severity is present."
            )

        if capped:
            explanation += (
                f" The uncapped total exceeded {self.max_score} and was capped, which "
                f"means multiple serious issues are present."
            )

        if level in {"high", "critical"}:
            explanation += " Human review is required before onboarding can proceed."
        elif level == "medium":
            explanation += " Compliance review is recommended."

        return explanation


# Route ordering, weakest to strongest intervention.
ROUTE_RANK = {
    "auto_approve": 0,
    "compliance_review": 1,
    "senior_review": 2,
    "escalate": 3,
    "blocked": 4,
}

# Minimum route implied by the most severe finding present, independent of
# the numeric score.
#
# WHY THIS EXISTS
# ---------------
# A purely additive score lets a small number of serious findings hide below
# the auto-approve ceiling. Concretely: an expired insurance certificate is
# worth 25 points, and 25 is also the LOW/MEDIUM boundary -- so scoring alone
# would auto-approve a vendor with lapsed coverage. The same is true of a
# vendor in a high-risk jurisdiction (15 points) or one carrying coverage
# half the required minimum (15 points).
#
# The numeric score answers "how much is wrong". Severity answers "how bad
# is the worst thing". A routing decision needs both, and the worse of the
# two wins.
SEVERITY_ROUTE_FLOOR = {
    "low": "auto_approve",
    "medium": "compliance_review",
    "high": "senior_review",
    "critical": "escalate",
}


def _worse_route(a: str, b: str) -> str:
    """Return whichever route represents the stronger intervention."""
    return a if ROUTE_RANK.get(a, 0) >= ROUTE_RANK.get(b, 0) else b


# Risk levels ordered weakest to strongest, so two levels can be compared.
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# The lowest risk level a finding of a given severity can justify.
#
# This mirrors SEVERITY_ROUTE_FLOOR for the *displayed* label. Without it, a
# vendor with an expired insurance certificate scores 25 points, lands on the
# LOW/MEDIUM boundary, and is labelled "Low risk" on the dashboard while
# simultaneously being routed to senior review. A label that contradicts the
# routing is worse than no label: an operator scanning the case list would
# reasonably skip it.
SEVERITY_LEVEL_FLOOR = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}


def route_for_score(
    score: int,
    has_blocking: bool = False,
    highest_severity: str = "low",
) -> str:
    """Decide the workflow route for a scored case.

    Returns one of: auto_approve, compliance_review, senior_review,
    escalate, blocked.

    Three inputs are combined, and the most conservative outcome wins:

    1. **Blocking findings.** A missing mandatory document or an unreadable
       tax form makes the case impossible to complete regardless of how
       benign everything else is, so it short-circuits to ``blocked``.
    2. **The numeric score.** Accumulated weight of all findings.
    3. **The highest severity present.** A floor that prevents a serious
       finding from being diluted by the arithmetic. See
       ``SEVERITY_ROUTE_FLOOR`` for why this is necessary.
    """
    if has_blocking:
        return "blocked"

    if score <= settings.RULE_AUTO_APPROVE_MAX_RISK:
        score_route = "auto_approve"
    elif score <= settings.RISK_THRESHOLD_MEDIUM:
        score_route = "compliance_review"
    elif score <= settings.RISK_THRESHOLD_HIGH:
        score_route = "senior_review"
    else:
        score_route = "escalate"

    severity_route = SEVERITY_ROUTE_FLOOR.get(highest_severity, "auto_approve")

    return _worse_route(score_route, severity_route)


# Finding codes that make a case impossible to complete until resolved.
BLOCKING_CODES = {
    "DOCUMENT_MISSING",
    "EXTRACTION_FAILED",
    "TAX_INFORMATION_MISSING",
}


def has_blocking_findings(evaluation: RuleEvaluation) -> bool:
    """Whether any finding prevents automatic completion."""
    return any(f.code in BLOCKING_CODES for f in evaluation.findings)
