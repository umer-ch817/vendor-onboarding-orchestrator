"""Read-side risk views for the Risk Review page.

The write path for risk lives in the rules engine, the scoring service and
the pipeline. This module only shapes what those produced into something a
reviewer can read: the current score with its attribution, the history of
assessments, the signals behind it, and what the AI said alongside it.

Keeping the read path separate matters for one reason above the others: the
reviewer must be able to see the deterministic score and the AI's opinion as
two distinct things. Merging them into a single "risk view" would erase the
line the whole architecture is built to protect.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OnboardingCase,
    RiskAssessment,
    RiskSignal,
    Vendor,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RiskService:
    """Assembles the risk picture for a case."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def latest_assessment(self, case_id: int) -> Optional[RiskAssessment]:
        result = await self.db.execute(
            select(RiskAssessment)
            .where(RiskAssessment.case_id == case_id)
            .order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def assessment_history(
        self, case_id: int, limit: int = 20
    ) -> Sequence[RiskAssessment]:
        """All assessments for a case, newest first.

        History is retained rather than overwritten because a score that fell
        from 90 to 20 after new documents arrived is meaningful information --
        it shows the reviewer that the earlier concerns were addressed.
        """
        result = await self.db.execute(
            select(RiskAssessment)
            .where(RiskAssessment.case_id == case_id)
            .order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def signals(self, case_id: int) -> Sequence[RiskSignal]:
        result = await self.db.execute(
            select(RiskSignal)
            .where(RiskSignal.case_id == case_id)
            .order_by(RiskSignal.detected_at.desc())
        )
        return result.scalars().all()

    async def build_case_risk_view(self, case_id: int) -> dict[str, Any]:
        """Everything the Risk Review page needs, in one payload."""
        assessment = await self.latest_assessment(case_id)

        case_result = await self.db.execute(
            select(OnboardingCase)
            .where(OnboardingCase.id == case_id)
            .limit(1)
        )
        case = case_result.scalar_one_or_none()

        signals = await self.signals(case_id)

        return {
            "case_id": case_id,
            "case_number": case.case_number if case else None,
            "workflow_status": _enum_value(case.workflow_status) if case else None,
            "risk_score": case.risk_score if case else 0,
            "risk_level": _enum_value(case.risk_level) if case else "low",
            "current": _assessment_payload(assessment),
            "components": (assessment.risk_factors if assessment else []) or [],
            "explanation": assessment.reasoning if assessment else "",
            "recommended_action": assessment.recommended_action if assessment else None,
            "signals": [
                {
                    "id": signal.id,
                    "type": signal.signal_type,
                    "severity": _enum_value(signal.severity),
                    "description": signal.description,
                    "evidence": signal.evidence or {},
                    "source": signal.source,
                    "status": signal.status,
                    "detected_at": _iso(signal.detected_at),
                }
                for signal in signals
            ],
            "attribution": self._attribution_summary(assessment),
        }

    @staticmethod
    def _attribution_summary(assessment: Optional[RiskAssessment]) -> dict[str, Any]:
        """Summarise where the points came from, for the reviewer's header.

        The dashboard shows a score; this shows the arithmetic behind it. A
        reviewer who disagrees with the number should be able to point at the
        line item they disagree with, and that requires the sum to be
        decomposed rather than asserted.
        """
        if assessment is None:
            return {"total": 0, "factor_count": 0, "largest_factor": None}

        factors = assessment.risk_factors or []
        largest = None
        if factors:
            largest = max(factors, key=lambda f: f.get("points", 0))

        return {
            "total": assessment.overall_score,
            "factor_count": len(factors),
            "largest_factor": largest,
            "sum_check": sum(f.get("points", 0) for f in factors),
        }


def _assessment_payload(assessment: Optional[RiskAssessment]) -> Optional[dict[str, Any]]:
    if assessment is None:
        return None
    return {
        "id": assessment.id,
        "score": assessment.overall_score,
        "level": _enum_value(assessment.risk_level),
        "reasoning": assessment.reasoning,
        "recommended_action": assessment.recommended_action,
        "risk_factors": assessment.risk_factors or [],
        "ai_model": assessment.ai_model,
        "ai_prompt_version": assessment.ai_prompt_version,
        "created_at": _iso(assessment.created_at),
    }


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else (str(value) if value is not None else "")


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value else None
