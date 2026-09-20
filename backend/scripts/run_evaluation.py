#!/usr/bin/env python3
"""Evaluate the deterministic rule engine and risk scorer.

What this measures, and what it does not
----------------------------------------
This harness constructs 50 synthetic onboarding cases, runs each one through
``RuleEngine`` and ``RiskScoringService`` exactly as the API does, and compares
the resulting route against a label.

The labels are derived from the *same written policy the engine implements* --
an expired certificate of insurance requires senior review, a missing mandatory
document blocks the case, and so on. That is a deliberate choice and it bounds
what the numbers mean: this measures **implementation fidelity**, not real-world
detection precision. It answers "does the code do what the policy says", not
"would this catch fraud at a real company". The second question needs labelled
production data, which a prototype does not have.

Two things make the exercise worth running anyway:

  * **Safety checks.** Some failures are unacceptable regardless of accuracy.
    A case that should block being auto-approved is one of them. Those are
    asserted, not scored, and a failure exits non-zero.
  * **Negative controls.** Half the clean cases are written with the kind of
    textual variation real documents have ("L.L.C." against "LLC", "Suite 400"
    against nothing). A rule engine that flags those produces false positives
    and trains reviewers to ignore it.

Every number in the output is computed here. Nothing is typed in by hand.

Usage
-----
    python3 backend/scripts/run_evaluation.py
    python3 backend/scripts/run_evaluation.py --json     # machine-readable only
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import types
from dataclasses import dataclass, field
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def install_sandbox_shims() -> list[str]:
    """Stand in for third-party libraries when they are not importable.

    This environment has no package registry, so ``pydantic`` and
    ``python-dateutil`` cannot be installed. The rule engine itself is pure
    first-party code -- it imports ``app.config`` for its thresholds and
    ``app.utils.normalization`` for text comparison -- so the only obstacle is
    that ``app.config`` is written against pydantic-settings.

    Rather than duplicate the thresholds (which would mean evaluating a copy of
    the policy instead of the policy), these shims satisfy the imports and let
    the real modules load. ``BaseSettings`` reads none of the class defaults
    away: they are ordinary class attributes, so the engine sees exactly the
    values declared in ``app/config.py``.

    The shims are only installed when the genuine package is missing, and the
    names of any that were installed are returned so the report can say so out
    loud. Shimming a dependency and not mentioning it would make the published
    numbers harder to reproduce than they look.
    """
    shimmed: list[str] = []

    try:  # pragma: no cover - depends on the environment
        import pydantic  # noqa: F401
    except ImportError:
        pydantic = types.ModuleType("pydantic")

        def Field(default=None, **kwargs):  # noqa: N802 - mirrors pydantic's name
            return default

        def field_validator(*args, **kwargs):
            def decorate(function):
                return function

            return decorate

        pydantic.Field = Field
        pydantic.field_validator = field_validator
        sys.modules["pydantic"] = pydantic
        shimmed.append("pydantic")

    try:  # pragma: no cover - depends on the environment
        import pydantic_settings  # noqa: F401
    except ImportError:
        pydantic_settings = types.ModuleType("pydantic_settings")

        class BaseSettings:
            """Enough of a settings base for ``app.config.Settings`` to load."""

        def SettingsConfigDict(**kwargs):  # noqa: N802
            return kwargs

        pydantic_settings.BaseSettings = BaseSettings
        pydantic_settings.SettingsConfigDict = SettingsConfigDict
        sys.modules["pydantic_settings"] = pydantic_settings
        shimmed.append("pydantic-settings")

    try:  # pragma: no cover - depends on the environment
        from dateutil import parser  # noqa: F401
    except ImportError:
        dateutil = types.ModuleType("dateutil")
        parser_module = types.ModuleType("dateutil.parser")

        def parse(value, **kwargs):
            # No date parsing is exercised on the rule-engine path; the
            # normalizer only reaches for it in normalize_date, which returns
            # None on an unparseable value anyway.
            raise ValueError("date parsing is not available in the sandbox")

        parser_module.parse = parse
        dateutil.parser = parser_module
        sys.modules["dateutil"] = dateutil
        sys.modules["dateutil.parser"] = parser_module
        shimmed.append("python-dateutil")

    return shimmed


SHIMMED_DEPENDENCIES = install_sandbox_shims()

from app.rules.engine import RuleEngine  # noqa: E402
from app.rules.risk_scoring import (  # noqa: E402
    RiskScoringService,
    has_blocking_findings,
    route_for_score,
)
from app.rules.types import (  # noqa: E402
    DocumentEvidence,
    EmployeeVendorContext,
    FieldEvidence,
    RequirementSpec,
)
from app.utils.normalization import normalize_text  # noqa: E402

TODAY = date(2026, 9, 19)

REQUIREMENTS = [
    RequirementSpec("REQ_W9", "W-9", "w9"),
    RequirementSpec("REQ_COI", "Certificate of Insurance", "certificate_of_insurance"),
    RequirementSpec("REQ_BUSREG", "Business Registration", "business_registration"),
    RequirementSpec("REQ_BANK", "Banking Confirmation", "banking_confirmation"),
]

# Routes ordered weakest to strongest, used for the confusion matrix.
ROUTES = ["auto_approve", "compliance_review", "senior_review", "escalate", "blocked"]


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """One synthetic case plus the label it should produce."""

    case_id: str
    family: str
    expected_route: str
    vendor: EmployeeVendorContext
    documents: list[DocumentEvidence] = field(default_factory=list)
    requirements: list[RequirementSpec] = field(default_factory=lambda: list(REQUIREMENTS))
    note: str = ""
    # True when the case is written specifically to test that a *similar* input
    # is not flagged. These are the cases that fail if normalization regresses.
    negative_control: bool = False


def field(name: str, value) -> FieldEvidence:
    return FieldEvidence(
        name=name,
        raw_value=value,
        normalized_value=normalize_text(str(value)),
        confidence=0.95,
    )


def document(
    document_type: str,
    fields: dict,
    *,
    expiration: date | None = None,
    status: str = "extracted",
    confidence: float = 0.95,
) -> DocumentEvidence:
    return DocumentEvidence(
        document_id=abs(hash((document_type, tuple(sorted(fields))))) % 10_000,
        document_type=document_type,
        filename=f"{document_type}.pdf",
        status=status,
        extraction_confidence=confidence,
        expiration_date=expiration,
        fields={name: field(name, value) for name, value in fields.items()},
    )


def base_documents(
    name: str,
    *,
    coi_expiry: date | None = None,
    coi_insured: str | None = None,
    busreg_name: str | None = None,
    bank_holder: str | None = None,
    bulleted_variation: bool = False,
    coverage: int = 2_000_000,
    omit: set[str] | None = None,
) -> list[DocumentEvidence]:
    """Build the standard document set, with controlled defects.

    ``bulleted_variation`` writes the names and address with the punctuation
    and unit-number variation that real documents exhibit -- the negative
    control that proves normalization is doing its job.
    """
    omit = omit or set()
    docs: list[DocumentEvidence] = []

    w9_name = name if not bulleted_variation else name
    busreg_name = busreg_name or (
        name.replace("LLC", ", L.L.C.") if bulleted_variation else name
    )
    coi_insured = coi_insured or name
    bank_holder = bank_holder or name
    address = "100 Innovation Drive, Suite 400" if bulleted_variation else "100 Innovation Drive"
    busreg_address = "100 Innovation Dr" if bulleted_variation else "100 Innovation Drive"

    if "w9" not in omit:
        docs.append(
            document(
                "w9",
                {"legal_name": w9_name, "tin": "12-3456789", "address": address},
            )
        )
    if "certificate_of_insurance" not in omit:
        docs.append(
            document(
                "certificate_of_insurance",
                {"insured_name": coi_insured, "coverage_amount": coverage},
                expiration=coi_expiry or (TODAY + timedelta(days=200)),
            )
        )
    if "business_registration" not in omit:
        docs.append(
            document(
                "business_registration",
                {"legal_name": busreg_name, "address": busreg_address},
            )
        )
    if "banking_confirmation" not in omit:
        docs.append(document("banking_confirmation", {"account_holder": bank_holder}))
    if "supplier_questionnaire" not in omit:
        docs.append(
            document(
                "supplier_questionnaire",
                {"company_name": name, "beneficial_owners": "J. Smith 40%; A. Doe 35%"},
            )
        )

    return docs


def vendor_context(name: str, *, country: str = "US", address: str = "100 Innovation Drive") -> EmployeeVendorContext:
    return EmployeeVendorContext(
        vendor_id=abs(hash(name)) % 1000,
        legal_name=name,
        trade_name=name.replace(" LLC", ""),
        country=country,
        state="TX",
        industry="manufacturing",
        vendor_type="supplier",
        tax_id="12-3456789",
        address_line1=address,
        city="Austin",
        postal_code="78701",
        bank_name="First National Bank",
        documented_account_holder="",
        ownership_disclosed=True,
        payment_terms_days=30,
    )


NAMES = [
    "Apex Industrial Solutions LLC",
    "Blue Ridge Contracting LLC",
    "Catalyst Consulting Group LLC",
    "Delta Manufacturing LLC",
    "Echelon Software Services LLC",
    "Frontier Logistics Partners LLC",
    "Glacier Peak Wholesale LLC",
    "Harbor View Supplies LLC",
    "Ironclad Construction LLC",
    "Jasper Ridge Analytics LLC",
    "Keystone Professional Services LLC",
    "Lighthouse Tech Solutions LLC",
    "Meridian Global Trading LLC",
    "Nexus Engineering Group LLC",
    "Olympus Materials LLC",
    "Pinnacle Advisory LLC",
    "Quantum Systems Integrators LLC",
    "Riverstone Distribution LLC",
    "Summit Compliance Partners LLC",
    "Terraforma Design Studio LLC",
]

DIFFERENT_NAME = "Ridgeway Holdings LLC"
DIFFERENT_BANK_HOLDER = "Northgate Capital Partners LLC"
HIGH_RISK_COUNTRY = "RU"


def build_cases() -> list[Case]:
    """The 50-case evaluation set.

    Composition, by family:

      clean_us_supplier       10   expected auto_approve (5 with textual variation)
      expiring_insurance       8   expected compliance_review
      missing_mandatory        8   expected blocked
      high_risk_geography      6   expected senior_review
      entity_mismatch          4   expected senior_review
      banking_mismatch         4   expected escalate
      expired_documents        5   expected senior_review
      clean_renewal            5   expected auto_approve
    """
    cases: list[Case] = []
    counter = 0

    def next_id(family: str) -> str:
        nonlocal counter
        counter += 1
        return f"{family}-{counter:03d}"

    # --- clean_us_supplier (10) -------------------------------------------
    for index in range(10):
        name = NAMES[index]
        variation = index >= 5  # half exercise the normalizer's tolerance
        cases.append(
            Case(
                case_id=next_id("clean"),
                family="clean_us_supplier",
                expected_route="auto_approve",
                vendor=vendor_context(
                    name,
                    address="100 Innovation Dr" if variation else "100 Innovation Drive",
                ),
                documents=base_documents(name, bulleted_variation=variation),
                note="textual variation, must not be flagged" if variation else "canonical",
                negative_control=variation,
            )
        )

    # --- expiring_insurance (8) -------------------------------------------
    for index in range(8):
        name = NAMES[index]
        cases.append(
            Case(
                case_id=next_id("expiring"),
                family="expiring_insurance",
                expected_route="compliance_review",
                vendor=vendor_context(name),
                documents=base_documents(name, coi_expiry=TODAY + timedelta(days=15)),
                note="coverage lapses inside the 30-day warning window",
            )
        )

    # --- missing_mandatory (8) --------------------------------------------
    for index in range(8):
        name = NAMES[index]
        omit = {"w9"} if index % 2 == 0 else {"business_registration"}
        cases.append(
            Case(
                case_id=next_id("missing"),
                family="missing_mandatory",
                expected_route="blocked",
                vendor=vendor_context(name),
                documents=base_documents(name, omit=omit),
                note=f"missing {sorted(omit)[0]}",
            )
        )

    # --- high_risk_geography (6) ------------------------------------------
    for index in range(6):
        name = NAMES[index]
        cases.append(
            Case(
                case_id=next_id("geo"),
                family="high_risk_geography",
                expected_route="senior_review",
                vendor=vendor_context(name, country=HIGH_RISK_COUNTRY),
                documents=base_documents(name),
                note=f"domiciled in {HIGH_RISK_COUNTRY}",
            )
        )

    # --- entity_mismatch (4) ----------------------------------------------
    for index in range(4):
        name = NAMES[index]
        cases.append(
            Case(
                case_id=next_id("entity"),
                family="entity_mismatch",
                expected_route="senior_review",
                vendor=vendor_context(name),
                documents=base_documents(name, busreg_name=DIFFERENT_NAME),
                note="registration names a different entity",
            )
        )

    # --- banking_mismatch (4) ---------------------------------------------
    for index in range(4):
        name = NAMES[index]
        cases.append(
            Case(
                case_id=next_id("banking"),
                family="banking_mismatch",
                expected_route="escalate",
                vendor=vendor_context(name),
                documents=base_documents(name, bank_holder=DIFFERENT_BANK_HOLDER),
                note="payee and account holder differ",
            )
        )

    # --- expired_documents (5) --------------------------------------------
    for index in range(5):
        name = NAMES[index]
        cases.append(
            Case(
                case_id=next_id("expired"),
                family="expired_documents",
                expected_route="senior_review",
                vendor=vendor_context(name),
                documents=base_documents(name, coi_expiry=TODAY - timedelta(days=30)),
                note="coverage already lapsed",
            )
        )

    # --- clean_renewal (5) -------------------------------------------------
    for index in range(5):
        name = NAMES[10 + index]
        cases.append(
            Case(
                case_id=next_id("renewal"),
                family="clean_renewal",
                expected_route="auto_approve",
                vendor=vendor_context(name),
                documents=base_documents(name),
                note="renewal with current documents",
            )
        )

    return cases


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_case(case: Case) -> dict:
    engine = RuleEngine()
    scorer = RiskScoringService()

    evaluation = engine.evaluate(
        vendor=case.vendor,
        documents=case.documents,
        requirements=case.requirements,
        today=TODAY,
    )
    result = scorer.score(evaluation)
    blocking = has_blocking_findings(evaluation)
    route = route_for_score(
        score=result.score,
        has_blocking=blocking,
        highest_severity=evaluation.highest_severity,
    )

    return {
        "case_id": case.case_id,
        "family": case.family,
        "note": case.note,
        "negative_control": case.negative_control,
        "expected_route": case.expected_route,
        "actual_route": route,
        "correct": route == case.expected_route,
        "score": result.score,
        "level": result.level,
        "severity": evaluation.highest_severity,
        "blocking": blocking,
        "findings": [
            {"code": f.code, "severity": f.severity, "points": f.risk_points}
            for f in evaluation.findings
        ],
        "codes": sorted({f.code for f in evaluation.findings}),
    }


def compute_metrics(results: list[dict]) -> dict:
    """Every number below is derived from ``results``."""
    total = len(results)
    exact = sum(1 for r in results if r["correct"])

    matrix = {expected: {actual: 0 for actual in ROUTES} for expected in ROUTES}
    for result in results:
        matrix[result["expected_route"]][result["actual_route"]] += 1

    per_class: dict[str, dict] = {}
    for route in ROUTES:
        tp = matrix[route][route]
        fn = sum(matrix[route][a] for a in ROUTES if a != route)
        fp = sum(matrix[e][route] for e in ROUTES if e != route)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else None
        )
        per_class[route] = {
            "support": tp + fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    # Binary view: "does this case need a human to look at it?" A case needs
    # attention when it is anything other than auto_approve. This is the
    # decision that actually matters operationally -- sending a case to the
    # wrong *human* queue is a routing nuisance; sending it to no queue at all
    # is the failure that lets risk through.
    attention_tp = attention_fp = attention_tn = attention_fn = 0
    for result in results:
        expected_attention = result["expected_route"] != "auto_approve"
        actual_attention = result["actual_route"] != "auto_approve"
        if expected_attention and actual_attention:
            attention_tp += 1
        elif not expected_attention and actual_attention:
            attention_fp += 1
        elif not expected_attention and not actual_attention:
            attention_tn += 1
        else:
            attention_fn += 1

    attention_precision = (
        attention_tp / (attention_tp + attention_fp) if (attention_tp + attention_fp) else None
    )
    attention_recall = (
        attention_tp / (attention_tp + attention_fn) if (attention_tp + attention_fn) else None
    )
    attention_f1 = (
        2 * attention_precision * attention_recall / (attention_precision + attention_recall)
        if attention_precision and attention_recall
        else None
    )

    # A case that should have blocked or been escalated, auto-approved, is
    # categorically unsafe. It is reported on its own line, not averaged in.
    unsafe_auto_approvals = [
        r["case_id"]
        for r in results
        if r["actual_route"] == "auto_approve" and r["expected_route"] != "auto_approve"
    ]

    blocking_cases = [r for r in results if r["expected_route"] == "blocked"]
    blocking_recall = (
        sum(1 for r in blocking_cases if r["actual_route"] == "blocked") / len(blocking_cases)
        if blocking_cases
        else None
    )

    # False positives on the negative controls: clean cases that were flagged.
    clean_cases = [r for r in results if r["expected_route"] == "auto_approve"]
    clean_false_positives = [
        r["case_id"] for r in clean_cases if r["actual_route"] != "auto_approve"
    ]

    # Normalization controls. The two halves have to be read together: the
    # first is only meaningful because the second proves the rule *can* fire.
    # A normalizer that has been over-tuned into "never reports a mismatch"
    # would score 0 flagged here and 0 detected there.
    negative_controls = [r for r in results if r["negative_control"]]
    negative_controls_flagged = [r["case_id"] for r in negative_controls if r["codes"]]
    genuine_mismatches = [
        r
        for r in results
        if r["family"] in {"entity_mismatch", "banking_mismatch"}
    ]
    genuine_mismatches_detected = [
        r["case_id"]
        for r in genuine_mismatches
        if {"ENTITY_NAME_MISMATCH", "BANKING_NAME_MISMATCH"} & set(r["codes"])
    ]

    scores = [r["score"] for r in results]
    firing: dict[str, int] = {}
    for result in results:
        for code in result["codes"]:
            firing[code] = firing.get(code, 0) + 1

    by_family: dict[str, dict] = {}
    for result in results:
        entry = by_family.setdefault(
            result["family"], {"count": 0, "correct": 0, "expected": result["expected_route"]}
        )
        entry["count"] += 1
        entry["correct"] += 1 if result["correct"] else 0

    return {
        "dataset": {
            "case_count": total,
            "label_source": (
                "Labels are derived from the written onboarding policy that the rule "
                "engine implements. This measures implementation fidelity, not "
                "real-world detection precision."
            ),
            "synthetic": True,
        },
        "accuracy": {
            "exact_route": exact,
            "exact_route_rate": exact / total if total else None,
            "unsafe_auto_approvals": len(unsafe_auto_approvals),
            "unsafe_auto_approval_cases": unsafe_auto_approvals,
            "blocking_recall": blocking_recall,
            "clean_false_positives": len(clean_false_positives),
            "clean_false_positive_cases": clean_false_positives,
            "clean_false_positive_rate": (
                len(clean_false_positives) / len(clean_cases) if clean_cases else None
            ),
        },
        "human_attention_classification": {
            "positive_class": "route != auto_approve",
            "true_positive": attention_tp,
            "false_positive": attention_fp,
            "true_negative": attention_tn,
            "false_negative": attention_fn,
            "precision": attention_precision,
            "recall": attention_recall,
            "f1": attention_f1,
        },
        "normalization_controls": {
            "similar_inputs_tested": len(negative_controls),
            "similar_inputs_flagged": len(negative_controls_flagged),
            "similar_inputs_flagged_cases": negative_controls_flagged,
            "genuine_mismatches_tested": len(genuine_mismatches),
            "genuine_mismatches_detected": len(genuine_mismatches_detected),
            "genuine_mismatches_detected_cases": genuine_mismatches_detected,
        },
        "confusion_matrix": matrix,
        "per_route": per_class,
        "by_family": by_family,
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "mean": round(statistics.fmean(scores), 2) if scores else None,
            "median": statistics.median(scores) if scores else None,
        },
        "rule_firing_counts": dict(sorted(firing.items(), key=lambda kv: -kv[1])),
    }


# ---------------------------------------------------------------------------
# Assertions -- failures that no accuracy figure can excuse
# ---------------------------------------------------------------------------


def run_safety_checks(results: list[dict], metrics: dict) -> list[str]:
    """Return a list of failures. Empty means the run is acceptable."""
    failures: list[str] = []

    if metrics["accuracy"]["unsafe_auto_approvals"]:
        failures.append(
            f"{metrics['accuracy']['unsafe_auto_approvals']} case(s) that require human "
            f"review were auto-approved: {metrics['accuracy']['unsafe_auto_approval_cases']}"
        )

    if metrics["accuracy"]["blocking_recall"] != 1.0:
        failures.append(
            f"blocking recall is {metrics['accuracy']['blocking_recall']}, expected 1.0"
        )

    if metrics["accuracy"]["clean_false_positives"]:
        failures.append(
            f"{metrics['accuracy']['clean_false_positives']} clean case(s) were flagged, "
            "which is a false positive: "
            f"{metrics['accuracy']['clean_false_positive_cases']}"
        )

    return failures


def run_severity_floor_regression() -> dict:
    """The specific bug the severity floor exists to prevent.

    An expired certificate of insurance contributes 25 points, and 25 is also
    the LOW/MEDIUM boundary. A purely additive scorer therefore auto-approves a
    vendor with lapsed coverage. This runs that exact case and asserts the
    routing does not auto-approve.
    """
    name = "Ironclad Construction LLC"
    case = Case(
        case_id="regression-expired-insurance",
        family="regression",
        expected_route="senior_review",
        vendor=vendor_context(name),
        documents=base_documents(name, coi_expiry=TODAY - timedelta(days=1)),
        note="expired insurance is the only finding; must not auto-approve",
    )
    result = evaluate_case(case)

    additive_only_route = (
        "auto_approve" if result["score"] <= 25 else "not_auto_approve"
    )
    passed = result["actual_route"] != "auto_approve"

    return {
        "case_id": case.case_id,
        "score": result["score"],
        "highest_severity": result["severity"],
        "route": result["actual_route"],
        "additive_score_alone_would_route_to": additive_only_route,
        "passed": passed,
        "explanation": (
            "An expired insurance certificate scores 25 points, which sits exactly on "
            "the auto-approve ceiling. Without a severity floor the case would be "
            "auto-approved."
        ),
    }


def run_determinism_check(cases: list[Case]) -> dict:
    """Same input twice must produce identical output.

    This is the property that makes the engine reviewable six months later.
    """
    first = [evaluate_case(case) for case in cases]
    second = [evaluate_case(case) for case in cases]
    identical = all(
        a["actual_route"] == b["actual_route"]
        and a["score"] == b["score"]
        and a["codes"] == b["codes"]
        for a, b in zip(first, second)
    )
    return {"deterministic": identical, "cases_compared": len(first)}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_report(metrics: dict, regression: dict, determinism: dict, failures: list[str]) -> str:
    accuracy = metrics["accuracy"]
    attention = metrics["human_attention_classification"]
    matrix = metrics["confusion_matrix"]
    distribution = metrics["score_distribution"]

    lines: list[str] = []
    lines.append("# Evaluation Report — Vendor Onboarding & Risk Orchestrator")
    lines.append("")
    lines.append(
        "*Prototype Metrics — computed by `backend/scripts/run_evaluation.py` over a "
        "50-case synthetic dataset. No figure here was entered by hand.*"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## What this measures")
    lines.append("")
    lines.append(
        "The 50 cases are synthetic and their labels are derived from the same written "
        "policy the rule engine implements. This is a statement about **implementation "
        "fidelity** — whether the code does what the policy says — and not about "
        "real-world detection precision, which would require labelled production data."
    )
    lines.append("")
    lines.append(
        "Two properties are asserted rather than scored, because no accuracy figure "
        "excuses them: no case requiring human review may be auto-approved, and no clean "
        "case may be flagged."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(
        f"| Exact route accuracy | {accuracy['exact_route']}/{metrics['dataset']['case_count']} "
        f"({format_rate(accuracy['exact_route_rate'])}) |"
    )
    lines.append(
        f"| Human-attention precision | {format_rate(attention['precision'])} |"
    )
    lines.append(
        f"| Human-attention recall | {format_rate(attention['recall'])} |"
    )
    lines.append(f"| Human-attention F1 | {format_rate(attention['f1'])} |")
    lines.append(
        f"| Unsafe auto-approvals | {accuracy['unsafe_auto_approvals']} |"
    )
    lines.append(f"| Blocking recall | {format_rate(accuracy['blocking_recall'])} |")
    lines.append(
        f"| Clean false positives | {accuracy['clean_false_positives']} "
        f"({format_rate(accuracy['clean_false_positive_rate'])}) |"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Confusion matrix — expected route (rows) against produced route (columns)")
    lines.append("")
    header = "| expected \\ produced | " + " | ".join(ROUTES) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(ROUTES) + 1))
    for expected in ROUTES:
        row = [str(matrix[expected][actual]) for actual in ROUTES]
        lines.append(f"| **{expected}** | " + " | ".join(row) + " |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-route precision and recall")
    lines.append("")
    lines.append("| Route | Support | Precision | Recall | F1 |")
    lines.append("|-------|---------|-----------|--------|----|")
    for route in ROUTES:
        entry = metrics["per_route"][route]
        lines.append(
            f"| {route} | {entry['support']} | {format_rate(entry['precision'])} | "
            f"{format_rate(entry['recall'])} | {format_rate(entry['f1'])} |"
        )
    lines.append("")
    lines.append(
        "A route with no support is omitted from precision and recall rather than "
        "reported as zero: dividing by an empty set is undefined, and printing 0.000 "
        "would read as a failure."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Accuracy by scenario family")
    lines.append("")
    lines.append("| Family | Cases | Correct | Expected route |")
    lines.append("|--------|-------|---------|----------------|")
    for family, entry in sorted(metrics["by_family"].items()):
        lines.append(
            f"| {family} | {entry['count']} | {entry['correct']} | `{entry['expected']}` |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Score distribution")
    lines.append("")
    lines.append(
        f"Minimum {distribution['min']}, median {distribution['median']}, "
        f"mean {distribution['mean']}, maximum {distribution['max']} (scale 0–100)."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Normalization controls")
    lines.append("")
    controls = metrics["normalization_controls"]
    lines.append(
        "Every clean case above carries identical names and addresses across its "
        "documents, so on its own it proves only that the engine stays quiet on trivial "
        "input. These two measurements are the ones that show the comparison logic is "
        "actually working, and they have to be read as a pair."
    )
    lines.append("")
    lines.append("| Measurement | Cases | Result |")
    lines.append("|-------------|-------|--------|")
    lines.append(
        f"| Same entity written differently (`L.L.C.` vs `LLC`, `Suite 400` vs nothing) "
        f"| {controls['similar_inputs_tested']} | "
        f"{controls['similar_inputs_flagged']} flagged (expected 0) |"
    )
    lines.append(
        f"| Genuinely different entity or account holder "
        f"| {controls['genuine_mismatches_tested']} | "
        f"{controls['genuine_mismatches_detected']} detected (expected "
        f"{controls['genuine_mismatches_tested']}) |"
    )
    lines.append("")
    lines.append(
        "A normalizer tuned to never report a mismatch would score zero on the first row "
        "and zero on the second, which is why the second row is reported alongside it."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Rule firing counts")
    lines.append("")
    lines.append("| Rule code | Cases that raised it |")
    lines.append("|-----------|----------------------|")
    for code, count in metrics["rule_firing_counts"].items():
        lines.append(f"| `{code}` | {count} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Severity-floor regression test")
    lines.append("")
    lines.append(
        f"A vendor whose only finding is an expired insurance certificate scores "
        f"**{regression['score']}** points, which sits exactly on the auto-approve ceiling "
        f"of 25. The case was routed to **`{regression['route']}`**."
    )
    lines.append("")
    lines.append(f"- Highest severity present: `{regression['highest_severity']}`")
    lines.append(
        f"- Additive score alone would have routed to: `{regression['additive_score_alone_would_route_to']}`"
    )
    lines.append(f"- **Result: {'PASS' if regression['passed'] else 'FAIL'}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Determinism")
    lines.append("")
    lines.append(
        f"The full dataset was evaluated twice and compared case by case. "
        f"Identical results: **{determinism['deterministic']}** over "
        f"{determinism['cases_compared']} cases."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Safety checks")
    lines.append("")
    if failures:
        for failure in failures:
            lines.append(f"- **FAIL** — {failure}")
    else:
        lines.append("All safety checks passed:")
        lines.append("")
        lines.append("- No case requiring human review was auto-approved.")
        lines.append("- Every case that should block did block.")
        lines.append("- No clean case was flagged.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Reproducing this")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 backend/scripts/run_evaluation.py")
    lines.append("```")
    lines.append("")
    lines.append(
        "The run is deterministic: the same command produces the same numbers. "
        "`evaluation/results.json` holds the per-case detail, including the findings "
        "that drove each route."
    )
    lines.append("")
    if SHIMMED_DEPENDENCIES:
        lines.append(
            "This run stood in for the following third-party packages, which could not be "
            "installed in the evaluation sandbox: "
            + ", ".join(f"`{name}`" for name in SHIMMED_DEPENDENCIES)
            + ". The rule engine, the risk scorer and the normalizer are all first-party "
            "code and ran unmodified; the shims exist only so that `app.config` — written "
            "against pydantic-settings — could be imported. Because the thresholds are "
            "ordinary class attributes, the values used are exactly those declared in "
            "`backend/app/config.py`."
        )
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "The dataset is synthetic and constructed to cover the policy, so the accuracy "
        "figures describe agreement between the code and the policy it encodes. They are "
        "not a measurement of fraud detection in production. The AI layer is excluded "
        "from this evaluation on purpose: it contributes advisory signals only and cannot "
        "change a route, so including it would add noise to a measurement of the "
        "deterministic path."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Evaluation Report — Prototype Metrics, synthetic dataset. Generated by `backend/scripts/run_evaluation.py`.*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()

    cases = build_cases()
    results = [evaluate_case(case) for case in cases]
    metrics = compute_metrics(results)
    regression = run_severity_floor_regression()
    determinism = run_determinism_check(cases)
    failures = run_safety_checks(results, metrics)

    if not regression["passed"]:
        failures.append(
            "severity-floor regression: expired insurance was auto-approved, which is "
            "the exact defect the floor exists to prevent"
        )
    if not determinism["deterministic"]:
        failures.append("determinism: identical input produced different output")

    output = os.path.join(os.path.dirname(BACKEND), "evaluation")
    os.makedirs(output, exist_ok=True)

    payload = {
        "metrics": metrics,
        "severity_floor_regression": regression,
        "determinism": determinism,
        "safety_checks": {"passed": not failures, "failures": failures},
        "cases": results,
    }

    with open(os.path.join(output, "results.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    report = render_report(metrics, regression, determinism, failures)
    with open(os.path.join(output, "REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(report)

    if args.json:
        print(json.dumps(payload["metrics"], indent=2))
    else:
        print(report)

    if failures:
        print("\nSAFETY CHECK FAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"\nEvaluation complete: {metrics['dataset']['case_count']} cases, "
        f"route accuracy {metrics['accuracy']['exact_route_rate']:.3f}, "
        f"{metrics['accuracy']['unsafe_auto_approvals']} unsafe auto-approvals."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
