"""Risk analysis and review endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import RiskAssessmentResponse, RiskSignalResponse
from app.services import RiskService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/case/{case_id}")
async def get_case_risk_view(
    case_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the complete risk picture for a case.

    Returns the current score, its components, the signal list, and the
    AI commentary if available. This is what the Risk Review page renders.
    """
    service = RiskService(db)
    view = await service.build_case_risk_view(case_id)
    if not view.get("case_number"):
        raise HTTPException(status_code=404, detail="Case not found")
    return view


@router.get("/case/{case_id}/assessment", response_model=RiskAssessmentResponse)
async def get_latest_assessment(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> RiskAssessmentResponse:
    """Get the most recent risk assessment for a case."""
    service = RiskService(db)
    assessment = await service.latest_assessment(case_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="No assessment found for this case")
    return RiskAssessmentResponse.model_validate(assessment)


@router.get("/case/{case_id}/history")
async def get_assessment_history(
    case_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get all assessments for a case, newest first.

    History shows how the risk picture evolved as documents were added
    or corrected.
    """
    service = RiskService(db)
    assessments = await service.assessment_history(case_id, limit=limit)
    return {
        "case_id": case_id,
        "assessments": [
            {
                "id": a.id,
                "score": a.overall_score,
                "level": a.risk_level.value if a.risk_level else None,
                "recommended_action": a.recommended_action,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "factors": a.risk_factors or [],
            }
            for a in assessments
        ],
    }


@router.get("/case/{case_id}/signals")
async def get_case_signals(
    case_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all risk signals for a case."""
    service = RiskService(db)
    signals = await service.signals(case_id)
    return {
        "case_id": case_id,
        "signals": [RiskSignalResponse.model_validate(s) for s in signals],
    }


@router.post("/signal/{signal_id}/acknowledge")
async def acknowledge_signal(
    signal_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge a risk signal without resolving it.

    Acknowledgement means "I have seen this and it does not require immediate
    action" - useful for informational signals that a reviewer wants to mark
    as read without closing.
    """
    from app.models import RiskSignal
    from datetime import datetime

    signal = await db.get(RiskSignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")

    signal.status = "acknowledged"
    await db.flush()

    logger.info("signal_acknowledged", extra={"signal_id": signal_id})
    return {
        "signal_id": signal_id,
        "status": signal.status,
    }


@router.post("/signal/{signal_id}/resolve")
async def resolve_signal(
    signal_id: int,
    resolution_notes: str,
    db: AsyncSession = Depends(get_db),
):
    """Mark a risk signal as resolved.

    This is separate from exception resolution because a signal may be
    informational (it does not always create an exception), but a reviewer
    can still mark it as addressed.
    """
    from app.models import RiskSignal
    from datetime import datetime

    signal = await db.get(RiskSignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")

    signal.status = "resolved"
    signal.resolution_notes = resolution_notes
    signal.resolved_at = datetime.utcnow()
    await db.flush()

    logger.info("signal_resolved", extra={"signal_id": signal_id})
    return {
        "signal_id": signal_id,
        "status": signal.status,
        "resolved_at": signal.resolved_at.isoformat(),
    }
