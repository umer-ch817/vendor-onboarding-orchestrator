"""Onboarding case endpoints.

Route declaration order matters in this module. FastAPI matches in the order
routes are registered, so the literal collection-level paths
(``/workflow-summary``, ``/risk-summary``) are declared *before*
``/{case_id}``. Registered the other way round they are unreachable - FastAPI
would try to parse "workflow-summary" as a case id and return a 422 before it
ever reaches the handler.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RiskLevel, WorkflowStatus
from app.schemas import (
    OnboardingCaseCreate,
    OnboardingCaseUpdate,
    OnboardingCaseResponse,
    OnboardingCaseListResponse,
    OnboardingCaseDetail,
)
from app.services import OnboardingService, OnboardingPipeline
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# The statuses from which a fresh assessment is meaningful. Re-assessing a
# completed or rejected case would overwrite the record of the decision that
# was actually made.
ASSESSABLE_STATUSES = {
    WorkflowStatus.DRAFT,
    WorkflowStatus.SUBMITTED,
    WorkflowStatus.DOCUMENT_COLLECTION,
    WorkflowStatus.EXTRACTION,
    WorkflowStatus.VALIDATION,
    WorkflowStatus.RISK_ANALYSIS,
    WorkflowStatus.REVIEW_REQUIRED,
}


@router.post("/", response_model=OnboardingCaseResponse, status_code=201)
async def create_case(
    case_data: OnboardingCaseCreate,
    db: AsyncSession = Depends(get_db),
) -> OnboardingCaseResponse:
    """Create a new onboarding case.

    The case starts in DRAFT. Move it forward with ``/submit``, which begins
    document collection.
    """
    service = OnboardingService(db)
    try:
        case = await service.create(case_data)
        logger.info("case_created", extra={"case_id": case.id, "case_number": case.case_number})
        return OnboardingCaseResponse.model_validate(case)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/", response_model=OnboardingCaseListResponse)
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[WorkflowStatus] = Query(None),
    risk_level: Optional[RiskLevel] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> OnboardingCaseListResponse:
    """List onboarding cases with pagination and filters."""
    service = OnboardingService(db)
    cases, total = await service.list(
        page=page,
        page_size=page_size,
        status=status,
        risk_level=risk_level,
        search=search,
    )
    return OnboardingCaseListResponse(
        cases=[OnboardingCaseResponse.model_validate(c) for c in cases],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/workflow-summary")
async def workflow_summary(
    db: AsyncSession = Depends(get_db),
):
    """Counts of cases by workflow status, across all cases.

    This is a collection-level summary, not a per-case one, which is why it
    takes no case id.
    """
    service = OnboardingService(db)
    summary = await service.get_workflow_summary()
    return {
        "by_status": {_value(k): v for k, v in summary.items()},
    }


@router.get("/risk-summary")
async def risk_summary(
    db: AsyncSession = Depends(get_db),
):
    """Counts of cases by risk level, across all cases."""
    service = OnboardingService(db)
    summary = await service.get_risk_summary()
    return {
        "by_risk_level": {_value(k): v for k, v in summary.items()},
    }


@router.get("/{case_id}", response_model=OnboardingCaseDetail)
async def get_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> OnboardingCaseDetail:
    """Retrieve a case with all related data for the detail view."""
    service = OnboardingService(db)
    case = await service.get_with_details(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return OnboardingCaseDetail.model_validate(case)


@router.patch("/{case_id}", response_model=OnboardingCaseResponse)
async def update_case(
    case_id: int,
    case_data: OnboardingCaseUpdate,
    db: AsyncSession = Depends(get_db),
) -> OnboardingCaseResponse:
    """Update case metadata.

    Status transitions and risk values are not editable here. They move
    through dedicated endpoints so the audit trail records how a case reached
    its current state.
    """
    service = OnboardingService(db)
    case = await service.update(case_id, case_data)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    logger.info("case_updated", extra={"case_id": case.id})
    return OnboardingCaseResponse.model_validate(case)


@router.post("/{case_id}/submit")
async def submit_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Move a case from DRAFT into DOCUMENT_COLLECTION.

    This is the point at which the case stops being a draft and starts
    accumulating documents and findings.
    """
    service = OnboardingService(db)
    case = await service.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.workflow_status != WorkflowStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "not_draft",
                "message": (
                    f"Case is in '{_value(case.workflow_status)}' status. "
                    f"Only a DRAFT case can be submitted."
                ),
            },
        )

    case = await service.update_status(case_id, WorkflowStatus.DOCUMENT_COLLECTION)
    logger.info("case_submitted", extra={"case_id": case_id})
    return {
        "case_id": case_id,
        "status": _value(case.workflow_status),
        "message": "Case submitted for document collection",
    }


@router.post("/{case_id}/assess")
async def assess_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Run the full assessment pipeline for a case.

    The pipeline runs the deterministic assessment first and persists it, then
    asks the model for an advisory opinion. The AI never feeds back into the
    score, the level, or the route. Re-running this endpoint is safe: findings
    that have cleared are closed, findings that still apply are left to the
    reviewer who already picked them up.
    """
    service = OnboardingService(db)
    case = await service.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if case.workflow_status not in ASSESSABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "not_assessable",
                "message": (
                    f"Case is in '{_value(case.workflow_status)}' status and cannot be "
                    f"re-assessed. Assessment would overwrite the record of the "
                    f"decision already taken."
                ),
            },
        )

    pipeline = OnboardingPipeline(db)
    try:
        result = await pipeline.run(case_id)
        await db.commit()
        logger.info(
            "case_assessed",
            extra={
                "case_id": case_id,
                "route": result.route,
                "score": result.score_total,
            },
        )
        return result.to_dict()
    except Exception as exc:
        await db.rollback()
        logger.error("case_assessment_failed", extra={"case_id": case_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Assessment failed: {exc}")


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)
