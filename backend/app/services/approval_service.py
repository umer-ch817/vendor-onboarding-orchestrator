"""The approval layer: where a human decision actually changes state.

This is the most safety-critical module in the system, because it is the only
one that can result in a vendor being onboarded or rejected. Three
properties are enforced here and nowhere else:

**Separation of duties.** The person who requested a vendor cannot approve
it. An approval whose approver is the requester is not a control, it is a
formality, and the system refuses it rather than recording it.

**Role authority.** Each approval type maps to the roles permitted to grant
it. A procurement analyst cannot grant a compliance approval, no matter how
the request was routed.

**No approval over an unresolved blocker.** If any exception of blocking
severity is still open, the approval is refused with an explanation of what
must happen first. This is what stops a well-meaning manager from approving
around a missing document.

The AI is absent from this module by design. There is no code path in which a
model's output moves a case to ``ONBOARDING_COMPLETE``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Approval,
    ApprovalStatus,
    Exception as ExceptionModel,
    ExceptionStatus,
    OnboardingCase,
    OnboardingCase as _Case,
    User,
    UserRole,
    Vendor,
    VendorStatus,
    WorkflowStatus,
)
from app.services.audit_service import AuditService
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Which roles may grant which approval type.
APPROVAL_AUTHORITY: dict[str, set[UserRole]] = {
    "manager": {UserRole.PROCUREMENT_MANAGER, UserRole.ADMIN},
    "compliance": {
        UserRole.COMPLIANCE_REVIEWER,
        UserRole.PROCUREMENT_MANAGER,
        UserRole.ADMIN,
    },
    "finance": {UserRole.FINANCE_REVIEWER, UserRole.ADMIN},
    "legal": {UserRole.ADMIN},
}

# Exception severities that must be cleared before an approval can be granted.
BLOCKING_SEVERITIES = {"critical"}

# Workflow statuses from which a decision is possible.
DECIDABLE_STATUSES = {
    WorkflowStatus.APPROVAL_PENDING,
    WorkflowStatus.REVIEW_REQUIRED,
}

# Escalation target for each approval type, used when a reviewer declines to
# decide. Escalation moves the decision up, never sideways and never down.
ESCALATION_PATH: dict[str, UserRole] = {
    "manager": UserRole.PROCUREMENT_MANAGER,
    "compliance": UserRole.COMPLIANCE_REVIEWER,
    "finance": UserRole.FINANCE_REVIEWER,
    "legal": UserRole.ADMIN,
}


class ApprovalError(Exception):
    """Raised when an approval action is not permitted.

    Carries a machine-readable ``reason`` so the API can return a specific
    message rather than a generic 400.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


class ApprovalService:
    """Creates, lists and decides approvals."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = AuditService(db)

    # -- reads -------------------------------------------------------------

    async def get(self, approval_id: int) -> Optional[Approval]:
        result = await self.db.execute(
            select(Approval)
            .where(Approval.id == approval_id)
            .options(
                selectinload(Approval.case).selectinload(OnboardingCase.vendor),
                selectinload(Approval.reviewer),
            )
        )
        return result.scalar_one_or_none()

    async def list_pending(
        self,
        *,
        reviewer_id: Optional[int] = None,
        approval_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[Approval], int]:
        query = select(Approval).where(Approval.status == ApprovalStatus.PENDING)
        if reviewer_id:
            query = query.where(Approval.requested_from_id == reviewer_id)
        if approval_type:
            query = query.where(Approval.approval_type == approval_type)

        total_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar() or 0

        result = await self.db.execute(
            query.order_by(Approval.created_at.asc()).limit(limit).offset(offset)
        )
        return result.scalars().all(), total

    async def list_for_case(self, case_id: int) -> Sequence[Approval]:
        result = await self.db.execute(
            select(Approval)
            .where(Approval.case_id == case_id)
            .order_by(Approval.created_at.asc())
        )
        return result.scalars().all()

    # -- creation ----------------------------------------------------------

    async def request(
        self,
        *,
        case_id: int,
        approval_type: str,
        reviewer_id: int,
        actor_user_id: Optional[int] = None,
        actor_user_name: Optional[str] = None,
    ) -> Approval:
        """Create a pending approval and record who asked for it."""
        if approval_type not in APPROVAL_AUTHORITY:
            raise ApprovalError(
                "unknown_approval_type",
                f"Unknown approval type '{approval_type}'",
            )

        reviewer = await self.db.get(User, reviewer_id)
        if reviewer is None:
            raise ApprovalError("reviewer_not_found", f"User {reviewer_id} not found")

        if reviewer.role not in APPROVAL_AUTHORITY[approval_type]:
            raise ApprovalError(
                "reviewer_lacks_authority",
                f"{reviewer.name} ({reviewer.role.value}) cannot grant a "
                f"'{approval_type}' approval.",
            )

        case = await self._load_case(case_id)

        # Reuse an existing pending request rather than stacking duplicates.
        existing = await self.db.execute(
            select(Approval).where(
                Approval.case_id == case_id,
                Approval.approval_type == approval_type,
                Approval.status == ApprovalStatus.PENDING,
            )
        )
        already = existing.scalars().first()
        if already is not None:
            return already

        approval = Approval(
            case_id=case_id,
            approval_type=approval_type,
            requested_from_id=reviewer_id,
            status=ApprovalStatus.PENDING,
        )
        self.db.add(approval)
        await self.db.flush()

        await self.audit.record_system(
            "APPROVAL_REQUESTED",
            f"A '{approval_type}' approval was requested from {reviewer.name}.",
            case_id=case_id,
            output_snapshot={
                "approval_id": approval.id,
                "approval_type": approval_type,
                "reviewer_id": reviewer_id,
                "requested_by": actor_user_id,
            },
        )
        return approval

    # -- decisions ---------------------------------------------------------

    async def decide(
        self,
        approval_id: int,
        *,
        decision: str,
        actor_user_id: int,
        comments: Optional[str] = None,
    ) -> Approval:
        """Approve or reject. Every guard in this module runs here."""
        if decision not in {"approved", "rejected"}:
            raise ApprovalError(
                "invalid_decision", f"Decision must be 'approved' or 'rejected'"
            )

        approval = await self.get(approval_id)
        if approval is None:
            raise ApprovalError("not_found", f"Approval {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalError(
                "already_decided",
                f"This approval was already {approval.status.value}.",
            )

        actor = await self.db.get(User, actor_user_id)
        if actor is None:
            raise ApprovalError("actor_not_found", f"User {actor_user_id} not found")

        if not actor.is_active:
            raise ApprovalError("actor_inactive", "This user account is not active.")

        if actor.role not in APPROVAL_AUTHORITY[approval.approval_type]:
            raise ApprovalError(
                "lacks_authority",
                f"Your role ({actor.role.value}) cannot grant a "
                f"'{approval.approval_type}' approval.",
            )

        case = approval.case or await self._load_case(approval.case_id)

        # Separation of duties.
        if case.requester_email and actor.email and (
            case.requester_email.strip().lower() == actor.email.strip().lower()
        ):
            raise ApprovalError(
                "separation_of_duties",
                "You requested this vendor and cannot also approve it. "
                "A different authorised reviewer must make this decision.",
            )

        if decision == "approved":
            await self._assert_no_blockers(approval.case_id, case)

        approval.status = (
            ApprovalStatus.APPROVED
            if decision == "approved"
            else ApprovalStatus.REJECTED
        )
        approval.decision = decision
        approval.comments = comments
        approval.decided_at = datetime.utcnow()
        approval.updated_at = datetime.utcnow()

        await self.audit.record_user(
            "APPROVAL_DECIDED",
            f"{actor.name} {decision} the '{approval.approval_type}' approval.",
            user_id=actor_user_id,
            user_name=actor.name,
            case_id=approval.case_id,
            input_snapshot={
                "approval_id": approval_id,
                "approval_type": approval.approval_type,
                "actor_role": actor.role.value,
            },
            output_snapshot={"decision": decision, "comments": comments},
        )

        if decision == "approved" and approval.approval_type == "manager":
            # The final, human, irreversible step. Recording it as a distinct
            # event type means the audit trail can be searched for exactly the
            # decisions that let a vendor into the system.
            await self._complete_onboarding(case, actor)

        await self.db.flush()
        return approval

    async def escalate(
        self,
        approval_id: int,
        *,
        reason: str,
        actor_user_id: int,
        escalate_to_id: Optional[int] = None,
    ) -> Approval:
        """Send a decision to a higher authority.

        Escalation is not a rejection. The case keeps moving and the original
        approval is marked escalated so the queue shows it left the desk.
        """
        if not reason or len(reason.strip()) < 10:
            raise ApprovalError(
                "reason_required", "Escalation requires a reason of at least 10 characters."
            )

        approval = await self.get(approval_id)
        if approval is None:
            raise ApprovalError("not_found", f"Approval {approval_id} not found")
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalError("already_decided", "This approval is already closed.")

        actor = await self.db.get(User, actor_user_id)
        if actor is None:
            raise ApprovalError("actor_not_found", f"User {actor_user_id} not found")

        target = None
        if escalate_to_id:
            target = await self.db.get(User, escalate_to_id)
            if target is None:
                raise ApprovalError("target_not_found", f"User {escalate_to_id} not found")

        approval.status = ApprovalStatus.ESCALATED
        approval.escalated_to_id = escalate_to_id
        approval.escalation_reason = reason
        approval.updated_at = datetime.utcnow()

        await self.audit.record_user(
            "APPROVAL_ESCALATED",
            f"{actor.name} escalated the '{approval.approval_type}' approval.",
            user_id=actor_user_id,
            user_name=actor.name,
            case_id=approval.case_id,
            output_snapshot={
                "reason": reason,
                "escalated_to": escalate_to_id,
                "suggested_role": ESCALATION_PATH.get(approval.approval_type, UserRole.ADMIN).value,
            },
        )
        await self.db.flush()
        return approval

    # -- guards ------------------------------------------------------------

    async def _assert_no_blockers(self, case_id: int, case: OnboardingCase) -> None:
        """Refuse approval while blocking conditions remain open."""
        result = await self.db.execute(
            select(ExceptionModel).where(
                ExceptionModel.case_id == case_id,
                ExceptionModel.status.in_(
                    [ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]
                ),
            )
        )
        open_exceptions = list(result.scalars().all())

        blockers = [
            exc
            for exc in open_exceptions
            if _enum_value(exc.severity) in BLOCKING_SEVERITIES
        ]

        if blockers:
            titles = "; ".join(exc.title for exc in blockers[:3])
            raise ApprovalError(
                "open_blockers",
                f"{len(blockers)} critical exception(s) must be resolved before this "
                f"case can be approved: {titles}",
            )

        if case.workflow_status == WorkflowStatus.BLOCKED:
            raise ApprovalError(
                "case_blocked",
                "This case is blocked. Resolve the blocking findings before approving.",
            )

        if case.workflow_status not in DECIDABLE_STATUSES:
            raise ApprovalError(
                "not_decidable",
                f"This case is in status '{_enum_value(case.workflow_status)}' and is not "
                f"awaiting a decision.",
            )

    # -- completion --------------------------------------------------------

    async def _complete_onboarding(self, case: OnboardingCase, actor: User) -> None:
        """Mark the vendor onboarded. The only path that does so."""
        vendor = case.vendor or await self.db.get(Vendor, case.vendor_id)

        case.workflow_status = WorkflowStatus.ONBOARDING_COMPLETE
        case.completed_at = datetime.utcnow()
        case.completion_percentage = 100
        case.updated_at = datetime.utcnow()

        if vendor is not None:
            vendor.status = VendorStatus.ACTIVE
            vendor.onboarding_completed_at = datetime.utcnow()

        await self.audit.record_user(
            "ONBOARDING_COMPLETED",
            (
                f"Onboarding completed for {vendor.legal_name if vendor else case.case_number}. "
                f"Approved by {actor.name} ({actor.role.value})."
            ),
            user_id=actor.id,
            user_name=actor.name,
            case_id=case.id,
            output_snapshot={
                "vendor_id": case.vendor_id,
                "completed_at": case.completed_at.isoformat(),
                "approved_by_role": actor.role.value,
            },
        )

        logger.info(
            "onboarding_completed",
            extra={"case_id": case.id, "vendor_id": case.vendor_id, "actor_id": actor.id},
        )

    async def _load_case(self, case_id: int) -> OnboardingCase:
        result = await self.db.execute(
            select(OnboardingCase)
            .where(OnboardingCase.id == case_id)
            .options(selectinload(OnboardingCase.vendor))
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise ApprovalError("case_not_found", f"Case {case_id} not found")
        return case


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else (str(value) if value is not None else "")
