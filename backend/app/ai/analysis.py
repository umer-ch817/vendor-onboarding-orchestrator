"""AI-backed risk analysis and exception triage services.

Both services follow the same discipline: the model produces *candidates*
and *recommendations*, never decisions. Recommendations are persisted
alongside the deterministic rule output so a reviewer can see where the two
agree and where they diverge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.ai.guardrails import AIValidationFailure, call_with_validation
from app.ai.provider import LLMProvider, LLMUnavailableError, get_provider
from app.ai.schemas import (
    AIAnalysisRecord,
    ExceptionTriageResult,
    RiskAnalysisResult,
)
from app.utils.logging import get_logger
from prompts import (
    EXCEPTION_PROMPT_VERSION,
    EXCEPTION_SYSTEM_PROMPT,
    RISK_PROMPT_VERSION,
    RISK_SYSTEM_PROMPT,
    build_exception_prompt,
    build_risk_prompt,
)

logger = get_logger(__name__)


@dataclass
class AnalysisOutcome:
    """Generic outcome wrapper for AI analysis calls.

    ``degraded`` is set when the model was unavailable or produced unusable
    output. The pipeline continues in that case -- a vendor is never blocked
    merely because the AI layer failed -- but the case is flagged so the
    reviewer knows the AI contribution is missing rather than absent-by-design.
    """

    success: bool
    result: Optional[Any] = None
    analysis: Optional[AIAnalysisRecord] = None
    degraded: bool = False
    failure_reason: Optional[str] = None
    validation_errors: list[str] = field(default_factory=list)


class VendorRiskAnalysisService:
    """Produces evidence-grounded risk observations for a vendor case."""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or get_provider()

    async def analyse(
        self,
        vendor_context: dict[str, Any],
        document_summary: list[dict[str, Any]],
        policy_excerpts: Optional[list[str]] = None,
    ) -> AnalysisOutcome:
        user_prompt = build_risk_prompt(
            vendor_context, document_summary, policy_excerpts
        )

        try:
            result, response, repaired = await call_with_validation(
                self.provider,
                RISK_SYSTEM_PROMPT,
                user_prompt,
                RiskAnalysisResult,
                prompt_version=RISK_PROMPT_VERSION,
            )
        except AIValidationFailure as exc:
            logger.warning(
                "risk_analysis_invalid",
                extra={"errors": exc.validation_errors},
            )
            return AnalysisOutcome(
                success=False,
                degraded=True,
                failure_reason=(
                    "The AI risk analysis returned unsupported output and was discarded. "
                    "Deterministic rule findings are unaffected."
                ),
                validation_errors=exc.validation_errors,
            )
        except LLMUnavailableError as exc:
            logger.error("risk_analysis_unavailable", extra={"error": str(exc)})
            return AnalysisOutcome(
                success=False,
                degraded=True,
                failure_reason=(
                    "The AI risk analysis service was unavailable. The case has been "
                    "assessed using deterministic rules only."
                ),
            )

        analysis = AIAnalysisRecord(
            provider=response.provider,
            model=response.model,
            prompt_version=response.prompt_version,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            repair_attempted=repaired,
        )

        return AnalysisOutcome(success=True, result=result, analysis=analysis)


class ExceptionTriageService:
    """Helps an operator decide what to do about a specific exception."""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or get_provider()

    async def triage(
        self,
        exception: dict[str, Any],
        vendor_context: dict[str, Any],
        related_evidence: Optional[list[dict[str, Any]]] = None,
    ) -> AnalysisOutcome:
        user_prompt = build_exception_prompt(
            exception, vendor_context, related_evidence
        )

        try:
            result, response, repaired = await call_with_validation(
                self.provider,
                EXCEPTION_SYSTEM_PROMPT,
                user_prompt,
                ExceptionTriageResult,
                prompt_version=EXCEPTION_PROMPT_VERSION,
            )
        except AIValidationFailure as exc:
            logger.warning(
                "exception_triage_invalid",
                extra={"exception_type": exception.get("type"), "errors": exc.validation_errors},
            )
            return AnalysisOutcome(
                success=False,
                degraded=True,
                failure_reason="Automated triage suggestions were unavailable for this exception.",
                validation_errors=exc.validation_errors,
            )
        except LLMUnavailableError as exc:
            logger.error("exception_triage_unavailable", extra={"error": str(exc)})
            return AnalysisOutcome(
                success=False,
                degraded=True,
                failure_reason="The exception triage service was unavailable.",
            )

        analysis = AIAnalysisRecord(
            provider=response.provider,
            model=response.model,
            prompt_version=response.prompt_version,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            repair_attempted=repaired,
        )

        return AnalysisOutcome(success=True, result=result, analysis=analysis)
