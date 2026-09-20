"""Approval queue endpoints.

Approvals are where a human decision becomes a state change, so the guards
live in ``ApprovalService`` and this module's only job is to translate the
service's machine-readable refusal reasons into the right HTTP semantics. A
refusal that a reviewer can fix (clear a blocking exception) is different from
one they cannot (their role does not carry the authority), and the status code
should say which.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ApprovalStatus, User
from app.schemas import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalResponse,
)
from app.services import ApprovalError, ApprovalService
from app.services.approval_service import APPROVAL_AUTHORITY
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Refusal reason -> HTTP status. Grouped by what the caller can do about it:
#   403 "you are not permitted"          - a different person must act
#   404 "the thing does not exist"        - the request is aimed at nothing
#   409 "the current state forbids this"  - someone must change state first
#   422 "the request itself is malformed" - fix the payload and retry
_REASON_STATUS: dict[str, int] = {
    # authority / identity
    "lacks_authority": 403,
    "reviewer_lacks_authority": 403,
    "separation_of_duties": 403,
    "actor_inactive": 403,
    # existence
    "not_found": 404,
    "case_not_found": 404,
    "reviewer_not_found": 404,
    "actor_not_found": 404,
    "target_not_found": 404,
    # state
    "open_blockers": 409,
    "case_blocked": 409,
    "not_decidable": 409,
    "already_decided": 409,
    # payload
    "unknown_approval_type": 422,
    "invalid_decision": 422,
    "reason_required": 422,
}


def _http_error(exc: ApprovalError) -> HTTPException:
    """Convert a service refusal into an HTTP error that explains itself."""
    status = _REASON_STATUS.get(exc.reason, 400)
    return HTTPException(
        status_code=status,
        detail={"reason": exc.reason, "message": exc.message},
    )


@router.get("/", response_model=ApprovalListResponse)
async def list_pending_approvals(
    reviewer_id: Optional[int] = Query(None),
    approval_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApprovalListResponse:
    """List approvals awaiting a decision, oldest first.

    Oldest-first is deliberate. An approval queue sorted newest-first quietly
    starves the requests that have been waiting longest.
    """
    service = ApprovalService(db)
    approvals, total = await service.list_pending(
        reviewer_id=reviewer_id,
        approval_type=approval_type,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ApprovalListResponse(
        approvals=[ApprovalResponse.model_validate(a) for a in approvals],
        total=total,
    )


@router.get("/authority")
async def approval_authority():
    """Which roles may grant which approval type.

    Exposed so the UI can show a reviewer why a button is disabled instead of
    letting them click it and receive a 403.
    """
    return {
        "authority": {
            approval_type: sorted(role.value for role in roles)
            for approval_type, roles in APPROVAL_AUTHORITY.items()
        }
    }


@router.get("/reviewers")
async def list_eligible_reviewers(
    approval_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List active users who could decide an approval of this type."""
    roles = APPROVAL_AUTHORITY.get(approval_type)
    if roles is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown approval type '{approval_type}'",
        )

    result = await db.execute(
        select(User).where(User.role.in_(list(roles)), User.is_active.is_(True))
    )
    users = result.scalars().all()
    return {
        "approval_type": approval_type,
        "reviewers": [
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
            }
            for user in users
        ],
    }


@router.get("/case/{case_id}", response_model=ApprovalListResponse)
async def list_case_approvals(
    case_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApprovalListResponse:
    """Every approval ever raised for a case, oldest first."""
    service = ApprovalService(db)
    approvals = await service.list_for_case(case_id)
    return ApprovalListResponse(
        approvals=[ApprovalResponse.model_validate(a) for a in approvals],
        total=len(approvals),
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Retrieve a single approval."""
    service = ApprovalService(db)
    approval = await service.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return ApprovalResponse.model_validate(approval)


@router.post("/", response_model=ApprovalResponse, status_code=201)
async def request_approval(
    approval_data: ApprovalCreate,
    actor_user_id: Optional[int] = None,
    actor_user_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Raise a pending approval against a reviewer.

    The reviewer's role is checked at request time, not just at decision time.
    Routing a request to someone who cannot grant it is a bug in the caller,
    and it is cheaper to catch here than to let it sit in their queue.
    """
    service = ApprovalService(db)
    try:
        approval = await service.request(
            case_id=approval_data.case_id,
            approval_type=approval_data.approval_type,
            reviewer_id=approval_data.requested_from_id,
            actor_user_id=actor_user_id,
            actor_user_name=actor_user_name,
        )
        await db.commit()
        return ApprovalResponse.model_validate(approval)
    except ApprovalError as exc:
        await db.rollback()
        raise _http_error(exc)


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: int,
    decision_data: ApprovalDecision,
    actor_user_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Approve or reject a pending approval.

    All four controls run inside ``ApprovalService.decide``: role authority,
    separation of duties, blocking exceptions, and case state. Approving a
    'manager' approval is the only action in the entire system that completes
    an onboarding, and it is audited as ``ONBOARDING_COMPLETED``.
    """
    if decision_data.decision not in {"approved", "rejected"}:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "invalid_decision",
                "message": "This endpoint accepts 'approved' or 'rejected'. "
                "Use the /escalate endpoint to escalate.",
            },
        )

    service = ApprovalService(db)
    try:
        approval = await service.decide(
            approval_id,
            decision=decision_data.decision,
            actor_user_id=actor_user_id,
            comments=decision_data.comments,
        )
        await db.commit()
        logger.info(
            "approval_decided",
            extra={
                "approval_id": approval_id,
                "decision": decision_data.decision,
                "actor_user_id": actor_user_id,
            },
        )
        return ApprovalResponse.model_validate(approval)
    except ApprovalError as exc:
        await db.rollback()
        raise _http_error(exc)


@router.post("/{approval_id}/escalate", response_model=ApprovalResponse)
async def escalate_approval(
    approval_id: int,
    escalation: ApprovalDecision,
    actor_user_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """Escalate a decision to a higher authority.

    Escalation is not a rejection and does not close the case. It records that
    the decision left this reviewer's desk, and why.
    """
    service = ApprovalService(db)
    try:
        approval = await service.escalate(
            approval_id,
            reason=escalation.escalation_reason or escalation.comments or "",
            actor_user_id=actor_user_id,
            escalate_to_id=escalation.escalate_to_id,
        )
        await db.commit()
        logger.info(
            "approval_escalated",
            extra={"approval_id": approval_id, "actor_user_id": actor_user_id},
        )
        return ApprovalResponse.model_validate(approval)
    except ApprovalError as exc:
        await db.rollback()
        raise _http_error(exc)
