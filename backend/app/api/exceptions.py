"""Exception queue endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ExceptionSeverity, ExceptionStatus
from app.schemas import (
    ExceptionResponse,
    ExceptionListResponse,
    ExceptionResolve,
)
from app.services import ExceptionService, ApprovalError
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/", response_model=ExceptionListResponse)
async def list_exceptions(
    severity: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    assigned_to_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ExceptionListResponse:
    """List open exceptions with filters.

    Results are ordered by severity (critical first) then by age.
    """
    service = ExceptionService(db)
    exceptions, total = await service.list_open(
        severity=severity,
        exception_type=exception_type,
        assigned_to_id=assigned_to_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ExceptionListResponse(
        exceptions=[ExceptionResponse.model_validate(e) for e in exceptions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary")
async def exception_summary(
    db: AsyncSession = Depends(get_db),
):
    """Get counts by severity for the dashboard."""
    service = ExceptionService(db)
    counts = await service.summary_counts()
    return counts


@router.get("/case/{case_id}")
async def list_case_exceptions(
    case_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List all exceptions for a specific case, newest first.

    Declared before ``/{exception_id}`` on purpose: FastAPI matches routes in
    declaration order, so a literal prefix registered after a path parameter
    is unreachable - ``/exceptions/case/7`` would be parsed as an
    ``exception_id`` of "case" and rejected.
    """
    from app.models import Exception as ExceptionModel
    from sqlalchemy import select

    result = await db.execute(
        select(ExceptionModel)
        .where(ExceptionModel.case_id == case_id)
        .order_by(ExceptionModel.created_at.desc())
    )
    exceptions = result.scalars().all()
    return {
        "case_id": case_id,
        "exceptions": [ExceptionResponse.model_validate(e) for e in exceptions],
    }


@router.get("/{exception_id}", response_model=ExceptionResponse)
async def get_exception(
    exception_id: int,
    db: AsyncSession = Depends(get_db),
) -> ExceptionResponse:
    """Retrieve a single exception with its evidence and triage suggestions."""
    service = ExceptionService(db)
    exception = await service.get(exception_id)
    if exception is None:
        raise HTTPException(status_code=404, detail="Exception not found")
    return ExceptionResponse.model_validate(exception)


@router.post("/{exception_id}/assign")
async def assign_exception(
    exception_id: int,
    user_id: int,
    actor_user_id: int,
    actor_user_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Assign an exception to a reviewer."""
    service = ExceptionService(db)
    try:
        exception = await service.assign(
            exception_id,
            user_id,
            actor_user_id=actor_user_id,
            actor_user_name=actor_user_name,
        )
        return ExceptionResponse.model_validate(exception)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{exception_id}/resolve")
async def resolve_exception(
    exception_id: int,
    resolution_data: ExceptionResolve,
    actor_user_id: int,
    actor_user_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Resolve an exception.

    Only a human can resolve an exception. The AI's triage suggestions are
    advisory and stored in the exception's evidence for the reviewer to
    consider, but they do not close the exception automatically.
    """
    service = ExceptionService(db)
    try:
        exception = await service.resolve(
            exception_id,
            resolution=resolution_data.resolution,
            resolution_type=resolution_data.resolution_type,
            actor_user_id=actor_user_id,
            actor_user_name=actor_user_name,
        )
        await db.commit()
        return ExceptionResponse.model_validate(exception)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{exception_id}/triage")
async def triage_exception(
    exception_id: int,
    requesting_user_id: Optional[int] = None,
    requesting_user_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Request AI triage suggestions for an exception.

    The suggestions are stored in the exception's evidence and returned in
    the response. They are advisory only and must not be treated as
    decisions.
    """
    service = ExceptionService(db)
    try:
        exception, outcome = await service.triage(
            exception_id,
            requesting_user_id=requesting_user_id,
            requesting_user_name=requesting_user_name,
        )
        await db.commit()
        return {
            "exception_id": exception_id,
            "success": outcome.success,
            "degraded": outcome.degraded,
            "failure_reason": outcome.failure_reason,
            "triage": (
                outcome.result.model_dump() if outcome.success and outcome.result else None
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))