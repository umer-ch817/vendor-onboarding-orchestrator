"""The onboarding pipeline: extract -> normalise -> validate -> score -> route.

This is the module that ties the system together, and it is deliberately the
only place where the parts are allowed to know about each other. Everything
beneath it -- the rule engine, the normalisers, the scoring service -- is
pure and database-free. Everything above it -- the API routes -- is a thin
adapter.

ORDER MATTERS
-------------
The deterministic assessment runs *first* and the AI analysis runs *second*,
and the AI never feeds back into the score. If the model is unavailable, the
case is still fully assessed, still routed, and still auditable; the only
difference is that the reviewer sees a note saying the AI commentary is
missing. The reverse ordering -- AI first, rules second -- would make the
whole system's latency and availability depend on a third party, for no
benefit.

IDEMPOTENCY
-----------
Running the pipeline twice on an unchanged case must not double the
exception queue. Exceptions and risk signals are therefore *synchronised*
against the current findings: new ones are created, ones that no longer
apply are auto-resolved with a note, and ones that still apply are left
alone so a reviewer's in-progress work is not thrown away.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis import AnalysisOutcome, VendorRiskAnalysisService
from app.config import settings
from app.models import (
    AuditEvent,
    Exception as ExceptionModel,
    ExceptionSeverity,
    ExceptionStatus,
    OnboardingCase,
    RiskAssessment,
    RiskLevel,
    RiskSignal,
    Vendor,
    WorkflowStatus,
)
from app.rules.engine import RuleEngine
from app.rules.risk_scoring import (
    RiskScoreResult,
    RiskScoringService,
    has_blocking_findings,
    route_for_score,
)
from app.rules.types import (
    DocumentEvidence,
    EmployeeVendorContext,
    RequirementSpec,
    RuleEvaluation,
    RuleFinding,
)
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.services.requirement_service import RequirementService
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Which workflow status each route leads to.
#
# Note that auto_approve does NOT mean "onboarded". It means "no human review
# of the risk assessment is required", so the case moves straight to the
# standard approval step. Final approval is always a human action -- there is
# no code path in this system that onboards a vendor without one.
ROUTE_TO_STATUS = {
    "auto_approve": WorkflowStatus.APPROVAL_PENDING,
    "compliance_review": WorkflowStatus.REVIEW_REQUIRED,
    "senior_review": WorkflowStatus.REVIEW_REQUIRED,
    "escalate": WorkflowStatus.REVIEW_REQUIRED,
    "blocked": WorkflowStatus.BLOCKED,
}

# Which approval a route requires once review is done.
ROUTE_TO_APPROVAL_TYPE = {
    "auto_approve": "manager",
    "compliance_review": "compliance",
    "senior_review": "compliance",
    "escalate": "compliance",
    "blocked": "manager",
}


@dataclass
class PipelineResult:
    """Everything the pipeline produced, for the caller and the audit log."""

    case_id: int
    evaluation: RuleEvaluation
    score: RiskScoreResult
    route: str
    workflow_status: WorkflowStatus
    exceptions_created: int = 0
    exceptions_resolved: int = 0
    signals_created: int = 0
    ai_outcome: Optional[AnalysisOutcome] = None
    ai_degraded: bool = False
    blocking: bool = False

    @property
    def score_total(self) -> int:
        return self.score.score

    @property
    def risk_level(self) -> str:
        return self.score.level

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "route": self.route,
            "workflow_status": _enum_value(self.workflow_status),
            "risk_score": self.score.score,
            "risk_level": self.score.level,
            "explanation": self.score.explanation,
            "components": [c.to_dict() for c in self.score.components],
            "findings": [f.to_dict() for f in self.evaluation.findings],
            "highest_severity": self.evaluation.highest_severity,
            "blocking": self.blocking,
            "exceptions_created": self.exceptions_created,
            "exceptions_resolved": self.exceptions_resolved,
            "signals_created": self.signals_created,
            "ai_degraded": self.ai_degraded,
            "ai_failure_reason": (
                self.ai_outcome.failure_reason if self.ai_outcome else None
            ),
            "ai_recommendation": (
                _enum_value(getattr(self.ai_outcome.result, "recommended_action", None))
                if self.ai_outcome and self.ai_outcome.result
                else None
            ),
            "thresholds_used": self.score.thresholds_used,
        }


class OnboardingPipeline:
    """Runs the full assessment for one onboarding case."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        rule_engine: Optional[RuleEngine] = None,
        scorer: Optional[RiskScoringService] = None,
        document_service: Optional[DocumentService] = None,
        risk_analysis: Optional[VendorRiskAnalysisService] = None,
        run_ai_analysis: bool = True,
    ):
        self.db = db
        self.engine = rule_engine or RuleEngine()
        self.scorer = scorer or RiskScoringService()
        self.documents = document_service or DocumentService(db)
        self.requirements = RequirementService(db)
        self.risk_analysis = risk_analysis or VendorRiskAnalysisService()
        self.audit = AuditService(db)
        self.run_ai_analysis = run_ai_analysis

    # -- entry point -------------------------------------------------------

    async def run(
        self,
        case_id: int,
        *,
        actor_user_id: Optional[int] = None,
        actor_name: Optional[str] = None,
    ) -> PipelineResult:
        """Assess a case end to end and persist the outcome."""
        case = await self._load_case(case_id)
        vendor = case.vendor

        document_evidence = await self.documents.build_evidence(case_id)
        requirement_specs = await self.requirements.resolve(
            vendor_type=vendor.vendor_type,
            country=vendor.country,
            industry=vendor.industry,
            risk_level=_enum_value(case.risk_level),
        )

        context = self._build_context(vendor, document_evidence)

        started = datetime.utcnow()
        evaluation = self.engine.evaluate(context, document_evidence, requirement_specs)
        score = self.scorer.score(evaluation)
        blocking = has_blocking_findings(evaluation)
        route = route_for_score(score.score, blocking, evaluation.highest_severity)

        await self.audit.record_system(
            "ASSESSMENT_COMPLETED",
            (
                f"Deterministic assessment completed: {len(evaluation.findings)} finding(s), "
                f"risk score {score.score}/100 ({score.level.upper()}), route '{route}'."
            ),
            case_id=case_id,
            output_snapshot={
                "findings": [f.code for f in evaluation.findings],
                "score": score.score,
                "level": score.level,
                "route": route,
                "blocking": blocking,
            },
            metadata={"duration_ms": _ms_since(started)},
        )

        # AI commentary, after the deterministic result is already fixed.
        ai_outcome = await self._run_ai(vendor, document_evidence, case_id)

        exceptions_created, exceptions_resolved = await self._sync_exceptions(
            case_id, evaluation
        )
        signals_created = await self._sync_signals(case_id, vendor.id, evaluation)
        await self._persist_assessment(case, evaluation, score, route, ai_outcome)

        result = PipelineResult(
            case_id=case_id,
            evaluation=evaluation,
            score=score,
            route=route,
            workflow_status=case.workflow_status,
            exceptions_created=exceptions_created,
            exceptions_resolved=exceptions_resolved,
            signals_created=signals_created,
            ai_outcome=ai_outcome,
            ai_degraded=bool(ai_outcome and ai_outcome.degraded),
            blocking=blocking,
        )

        await self._record_route(result, actor_user_id, actor_name)
        await self.db.flush()

        logger.info(
            "pipeline_completed",
            extra={
                "case_id": case_id,
                "route": route,
                "score": score.score,
                "findings": len(evaluation.findings),
                "ai_degraded": result.ai_degraded,
            },
        )
        return result

    # -- loading -----------------------------------------------------------

    async def _load_case(self, case_id: int) -> OnboardingCase:
        from sqlalchemy.orm import selectinload

        result = await self.db.execute(
            select(OnboardingCase)
            .where(OnboardingCase.id == case_id)
            .options(selectinload(OnboardingCase.vendor))
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise ValueError(f"Onboarding case {case_id} not found")
        if case.vendor is None:
            raise ValueError(f"Onboarding case {case_id} has no vendor")
        return case

    # -- context building --------------------------------------------------

    @staticmethod
    def _build_context(
        vendor: Vendor,
        documents: list[DocumentEvidence],
    ) -> EmployeeVendorContext:
        """Assemble the vendor facts the rule engine needs.

        Facts that live on uploaded documents (documented account holder,
        ownership disclosure, payment terms) are lifted here so the rules do
        not each have to know how to find them. Where a vendor record and a
        document disagree, the vendor record wins -- it is the system of
        record, and the disagreement is itself something the rules surface.
        """
        documented_holder = ""
        for document in documents:
            if document.document_type == "banking_confirmation" and document.has(
                "account_holder"
            ):
                documented_holder = str(document.value("account_holder"))
                break

        ownership_disclosed = any(
            d.document_type == "supplier_questionnaire"
            and (
                d.has("beneficial_owners")
                or (d.value("ownership_structure") not in (None, "", "not disclosed"))
            )
            for d in documents
        )

        payment_terms_days = None
        for document in documents:
            if document.document_type in {
                "master_services_agreement",
                "supplier_questionnaire",
            }:
                raw = document.value("payment_terms")
                if raw:
                    from app.services.normalization import parse_payment_terms_days

                    payment_terms_days = parse_payment_terms_days(raw)
                    if payment_terms_days is not None:
                        break

        return EmployeeVendorContext(
            vendor_id=vendor.id,
            legal_name=vendor.legal_name or "",
            trade_name=vendor.trade_name or "",
            country=vendor.country or "",
            state=vendor.state or "",
            industry=vendor.industry or "",
            vendor_type=vendor.vendor_type or "",
            tax_id=vendor.tax_id or "",
            address_line1=vendor.address_line1 or "",
            city=vendor.city or "",
            postal_code=vendor.postal_code or "",
            bank_name=vendor.bank_name or "",
            documented_account_holder=documented_holder,
            ownership_disclosed=ownership_disclosed,
            payment_terms_days=payment_terms_days,
        )

    # -- AI ----------------------------------------------------------------

    async def _run_ai(
        self,
        vendor: Vendor,
        documents: list[DocumentEvidence],
        case_id: int,
    ) -> Optional[AnalysisOutcome]:
        """Run the AI commentary. Failure degrades, it does not abort."""
        if not self.run_ai_analysis:
            return None

        vendor_context = {
            "legal_name": vendor.legal_name,
            "trade_name": vendor.trade_name,
            "country": vendor.country,
            "industry": vendor.industry,
            "vendor_type": vendor.vendor_type,
            "city": vendor.city,
            # Deliberately no tax id and no bank details: the model does not
            # need identifiers to reason about risk, and sending them would
            # widen the blast radius of a prompt-injection attempt inside an
            # uploaded document.
        }

        document_summary = [
            {
                "type": d.document_type,
                "filename": d.filename,
                "status": d.status,
                "extraction_confidence": d.extraction_confidence,
                "expired": bool(
                    d.expiration_date and d.expiration_date < date.today()
                ),
                "warnings": d.warnings,
            }
            for d in documents
        ]

        started = datetime.utcnow()
        outcome = await self.risk_analysis.analyse(vendor_context, document_summary)

        await self.audit.record_ai(
            "AI_RISK_ANALYSIS",
            (
                "AI risk commentary produced."
                if outcome.success
                else f"AI risk commentary unavailable: {outcome.failure_reason}"
            ),
            analysis=outcome.analysis,
            case_id=case_id,
            output_snapshot=(
                {
                    "signals": [
                        s.model_dump() for s in outcome.result.risk_signals
                    ],
                    "summary": outcome.result.summary,
                    "recommended_action": outcome.result.recommended_action,
                    "confidence": outcome.result.confidence,
                }
                if outcome.success and outcome.result
                else None
            ),
            metadata={"duration_ms": _ms_since(started), "degraded": outcome.degraded},
        )
        return outcome

    # -- persistence -------------------------------------------------------

    async def _sync_exceptions(
        self,
        case_id: int,
        evaluation: RuleEvaluation,
    ) -> tuple[int, int]:
        """Create exceptions for new findings; auto-resolve ones that cleared."""
        wanted: dict[tuple[str, Optional[int]], RuleFinding] = {}
        for finding in evaluation.findings:
            if not finding.creates_exception:
                continue
            wanted[(finding.code, finding.related_document_id)] = finding

        existing = await self.db.execute(
            select(ExceptionModel).where(
                ExceptionModel.case_id == case_id,
                ExceptionModel.status.in_(
                    [ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]
                ),
            )
        )
        open_exceptions = list(existing.scalars().all())

        # An exception is "the same" as a finding when type and document match.
        existing_keys = {
            (exc.type, (exc.evidence or {}).get("related_document_id"))
            for exc in open_exceptions
        }

        created = 0
        for key, finding in wanted.items():
            if key in existing_keys:
                continue
            self.db.add(
                ExceptionModel(
                    case_id=case_id,
                    type=finding.code,
                    severity=_severity(finding.severity),
                    title=finding.title[:255],
                    description=finding.description,
                    evidence={**finding.evidence, "related_document_id": key[1]},
                    status=ExceptionStatus.OPEN,
                )
            )
            created += 1

        resolved = 0
        for exc in open_exceptions:
            key = (exc.type, (exc.evidence or {}).get("related_document_id"))
            if key in wanted:
                continue
            exc.status = ExceptionStatus.CLOSED
            exc.resolution_type = "auto_resolved"
            exc.resolution = (
                "This condition is no longer present in the latest assessment, so the "
                "exception was closed automatically. If a reviewer had already begun work "
                "on it, the earlier notes remain in the audit trail."
            )
            exc.resolved_at = datetime.utcnow()
            resolved += 1

        await self.db.flush()
        return created, resolved

    async def _sync_signals(
        self,
        case_id: int,
        vendor_id: int,
        evaluation: RuleEvaluation,
    ) -> int:
        """Refresh the rule-engine risk signals attached to a case."""
        from sqlalchemy import delete

        # Signals are a derived view of the current assessment, so the
        # rule-sourced ones are replaced wholesale. Acknowledged or resolved
        # signals are left alone -- a reviewer's judgement outranks a re-run.
        await self.db.execute(
            delete(RiskSignal).where(
                RiskSignal.case_id == case_id,
                RiskSignal.source == "rules_engine",
                RiskSignal.status == "open",
            )
        )

        created = 0
        for finding in evaluation.findings:
            self.db.add(
                RiskSignal(
                    vendor_id=vendor_id,
                    case_id=case_id,
                    signal_type=finding.code,
                    severity=_severity(finding.severity),
                    description=finding.description,
                    evidence=finding.evidence,
                    source="rules_engine",
                    status="open",
                    detected_at=datetime.utcnow(),
                )
            )
            created += 1

        await self.db.flush()
        return created

    async def _persist_assessment(
        self,
        case: OnboardingCase,
        evaluation: RuleEvaluation,
        score: RiskScoreResult,
        route: str,
        ai_outcome: Optional[AnalysisOutcome],
    ) -> None:
        """Write the assessment row and move the case and vendor forward."""
        self.db.add(
            RiskAssessment(
                case_id=case.id,
                overall_score=score.score,
                risk_level=_risk_level(score.level),
                confidence=None,
                reasoning=score.explanation,
                risk_factors=[c.to_dict() for c in score.components],
                recommended_action=route,
                ai_model=(
                    ai_outcome.analysis.model
                    if ai_outcome and ai_outcome.analysis
                    else None
                ),
                ai_prompt_version=(
                    ai_outcome.analysis.prompt_version
                    if ai_outcome and ai_outcome.analysis
                    else None
                ),
                created_at=datetime.utcnow(),
            )
        )

        case.risk_score = score.score
        case.risk_level = _risk_level(score.level)
        case.workflow_status = ROUTE_TO_STATUS.get(route, WorkflowStatus.REVIEW_REQUIRED)
        case.updated_at = datetime.utcnow()

        # The vendor's headline risk reflects its most recent case. This is a
        # convenience for list views, not the system of record -- the
        # assessment rows are.
        case.vendor.risk_score = score.score
        case.vendor.risk_level = _risk_level(score.level)

        await self.db.flush()

    async def _record_route(
        self,
        result: PipelineResult,
        actor_user_id: Optional[int],
        actor_name: Optional[str],
    ) -> None:
        """Audit the routing decision and notify the right queue."""
        description = _route_description(result)
        if actor_user_id:
            await self.audit.record_user(
                "CASE_ROUTED",
                description,
                user_id=actor_user_id,
                user_name=actor_name,
                case_id=result.case_id,
                output_snapshot=result.to_dict(),
            )
        else:
            await self.audit.record_system(
                "CASE_ROUTED",
                description,
                case_id=result.case_id,
                output_snapshot=result.to_dict(),
            )

    # -- helpers -----------------------------------------------------------

    async def recent_events(self, case_id: int, limit: int = 100) -> list[AuditEvent]:
        return list(await self.audit.list_for_case(case_id, limit=limit))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _route_description(result: PipelineResult) -> str:
    if result.route == "blocked":
        return (
            "Case blocked: one or more findings prevent completion until they are "
            "resolved. A reviewer must act before the case can progress."
        )
    if result.route == "escalate":
        return (
            f"Case escalated for senior review with a risk score of "
            f"{result.score.score}/100. Multiple or severe findings are present."
        )
    if result.route == "senior_review":
        return (
            f"Case routed to senior review with a risk score of {result.score.score}/100."
        )
    if result.route == "compliance_review":
        return (
            f"Case routed to compliance review with a risk score of "
            f"{result.score.score}/100."
        )
    return (
        f"Case cleared automatic checks with a risk score of {result.score.score}/100 "
        f"and moved to the standard approval queue. A human approval is still required."
    )


def _severity(value: str) -> ExceptionSeverity:
    try:
        return ExceptionSeverity(value)
    except ValueError:
        return ExceptionSeverity.MEDIUM


def _risk_level(value: str) -> RiskLevel:
    try:
        return RiskLevel(value)
    except ValueError:
        return RiskLevel.LOW


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else (str(value) if value is not None else "")


def _ms_since(started: datetime) -> int:
    return int((datetime.utcnow() - started).total_seconds() * 1000)
