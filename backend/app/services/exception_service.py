"""Exception queue operations.

An exception is the system saying "a human needs to look at this". Two rules
shape everything in this module:

1. **An exception is never closed by the AI.** The model may suggest a
   resolution; only a user's action closes the exception. Suggestions are
   stored alongside the exception so the reviewer can accept or ignore them,
   but ``status`` only ever moves because a person moved it.
2. **Resolution is recorded, not deleted.** Closing an exception writes who
   decided, what they decided, and why. The exception stays in the case
   history forever.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis import AnalysisOutcome, ExceptionTriageService
from app.models import (
    Exception as ExceptionModel,
    ExceptionSeverity,
    ExceptionStatus,
    OnboardingCase,
    User,
    Vendor,
)
from app.services.audit_service import AuditService
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Resolution types a reviewer can apply, and what each implies.
RESOLUTION_TYPES = {
    "resolved": "The underlying problem was fixed and the exception no longer applies.",
    "override": "A reviewer accepted the risk and waived this exception. Requires a reason.",
    "dismissed": "The exception was raised in error.",
    "escalated": "The exception needs a higher authority to decide.",
}


class ExceptionService:
    """Reads and mutates the exception queue."""

    def __init__(
        self,
        db: AsyncSession,
        triage_service: Optional[ExceptionTriageService] = None,
    ):
        self.db = db
        self.triage_service = triage_service or ExceptionTriageService()
        self.audit = AuditService(db)

    # -- reads -------------------------------------------------------------

    async def get(self, exception_id: int) -> Optional[ExceptionModel]:
        result = await self.db.execute(
            select(ExceptionModel).where(ExceptionModel.id == exception_id)
        )
        return result.scalar_one_or_none()

    async def list_open(
        self,
        *,
        severity: Optional[str] = None,
        exception_type: Optional[str] = None,
        assigned_to_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ExceptionModel], int]:
        query = select(ExceptionModel).where(
            ExceptionModel.status.in_(
                [ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]
            )
        )

        if severity:
            query = query.where(ExceptionModel.severity == ExceptionSeverity(severity))
        if exception_type:
            query = query.where(ExceptionModel.type == exception_type)
        if assigned_to_id:
            query = query.where(ExceptionModel.assigned_to_id == assigned_to_id)

        total_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar() or 0

        # Severity first, then age. An operator works the queue top-down, so
        # the ordering has to match how urgently something needs attention,
        # not merely when it arrived.
        severity_rank = {
            ExceptionSeverity.CRITICAL: 0,
            ExceptionSeverity.HIGH: 1,
            ExceptionSeverity.MEDIUM: 2,
            ExceptionSeverity.LOW: 3,
        }
        result = await self.db.execute(query.limit(limit).offset(offset))
        rows = sorted(
            result.scalars().all(),
            key=lambda e: (severity_rank.get(e.severity, 9), e.created_at or datetime.min),
        )
        return rows, total

    async def summary_counts(self) -> dict[str, int]:
        """Counts by severity for the open queue, used by the dashboard."""
        result = await self.db.execute(
            select(ExceptionModel.severity, func.count())
            .where(
                ExceptionModel.status.in_(
                    [ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]
                )
            )
            .group_by(ExceptionModel.severity)
        )
        counts = {severity.value: 0 for severity in ExceptionSeverity}
        for severity, count in result.all():
            key = severity.value if hasattr(severity, "value") else str(severity)
            counts[key] = count
        counts["total"] = sum(v for k, v in counts.items() if k != "total")
        return counts

    # -- AI assistance -----------------------------------------------------

    async def triage(
        self,
        exception_id: int,
        *,
        requesting_user_id: Optional[int] = None,
        requesting_user_name: Optional[str] = None,
    ) -> tuple[Optional[ExceptionModel], AnalysisOutcome]:
        """Ask the model for likely causes and resolution options.

        The suggestions are attached to the exception's evidence under a
        ``triage`` key so the UI can render them next to the actions a
        reviewer is actually able to take. Nothing is applied automatically.
        """
        exception = await self.get(exception_id)
        if exception is None:
            raise ValueError(f"Exception {exception_id} not found")

        context = await self._vendor_context(exception.case_id)

        outcome = await self.triage_service.triage(
            exception={
                "type": exception.type,
                "severity": _enum_value(exception.severity),
                "title": exception.title,
                "description": exception.description,
                "evidence": exception.evidence or {},
            },
            vendor_context=context,
        )

        await self.audit.record_ai(
            "EXCEPTION_TRIAGE",
            (
                "Automated triage suggestions generated for reviewer consideration."
                if outcome.success
                else f"Automated triage unavailable: {outcome.failure_reason}"
            ),
            analysis=outcome.analysis,
            case_id=exception.case_id,
            output_snapshot=(
                outcome.result.model_dump() if outcome.success and outcome.result else None
            ),
            metadata={"exception_id": exception_id},
        )

        if outcome.success and outcome.result:
            evidence = dict(exception.evidence or {})
            evidence["triage"] = {
                "likely_root_cause": outcome.result.likely_root_cause,
                "resolution_options": [
                    option.model_dump() for option in outcome.result.resolution_options
                ],
                "vendor_message_draft": outcome.result.vendor_message_draft,
                "reviewer_notes": outcome.result.reviewer_notes,
                "urgency": outcome.result.urgency,
                "generated_at": datetime.utcnow().isoformat(),
                "prompt_version": (
                    outcome.analysis.prompt_version if outcome.analysis else None
                ),
                # Stated explicitly in the payload so nothing downstream can
                # mistake a suggestion for a decision.
                "advisory_only": True,
            }
            exception.evidence = evidence
            await self.db.flush()

        return exception, outcome

    # -- mutation ----------------------------------------------------------

    async def assign(
        self,
        exception_id: int,
        user_id: int,
        *,
        actor_user_id: int,
        actor_user_name: Optional[str] = None,
    ) -> ExceptionModel:
        exception = await self._require(exception_id)
        user = await self.db.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        previous = exception.assigned_to_id
        exception.assigned_to_id = user_id
        if exception.status == ExceptionStatus.OPEN:
            exception.status = ExceptionStatus.IN_PROGRESS
        exception.updated_at = datetime.utcnow()

        await self.audit.record_user(
            "EXCEPTION_ASSIGNED",
            f"Exception assigned to {user.name}.",
            user_id=actor_user_id,
            user_name=actor_user_name,
            case_id=exception.case_id,
            input_snapshot={"previously_assigned_to": previous},
            output_snapshot={"assigned_to": user_id},
        )
        await self.db.flush()
        return exception

    async def resolve(
        self,
        exception_id: int,
        *,
        resolution: str,
        resolution_type: str,
        actor_user_id: int,
        actor_user_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ExceptionModel:
        """Close an exception. Only a human can do this."""
        if resolution_type not in RESOLUTION_TYPES:
            raise ValueError(
                f"Unknown resolution type '{resolution_type}'. "
                f"Expected one of: {', '.join(RESOLUTION_TYPES)}"
            )
        if not resolution or not resolution.strip():
            raise ValueError("A resolution explanation is required")

        # An override is accepting a known risk, which is a materially
        # different act from fixing the problem. Requiring a reason makes the
        # audit trail useful rather than merely present.
        if resolution_type == "override" and len(resolution.strip()) < 20:
            raise ValueError(
                "Overriding a risk exception requires a substantive justification "
                "(at least 20 characters)"
            )

        exception = await self._require(exception_id)
        if exception.status in (ExceptionStatus.RESOLVED, ExceptionStatus.CLOSED):
            raise ValueError("This exception is already closed")

        exception.status = (
            ExceptionStatus.ESCALATED
            if resolution_type == "escalated"
            else ExceptionStatus.RESOLVED
        )
        exception.resolution = resolution
        exception.resolution_type = resolution_type
        exception.resolved_at = datetime.utcnow()
        exception.updated_at = datetime.utcnow()

        await self.audit.record_user(
            "EXCEPTION_RESOLVED",
            f"Exception '{exception.title}' was {resolution_type}.",
            user_id=actor_user_id,
            user_name=actor_user_name,
            case_id=exception.case_id,
            input_snapshot={
                "exception_type": exception.type,
                "severity": _enum_value(exception.severity),
            },
            output_snapshot={
                "resolution_type": resolution_type,
                "resolution": resolution,
                "notes": notes,
            },
        )
        await self.db.flush()
        return exception

    # -- helpers -----------------------------------------------------------

    async def _require(self, exception_id: int) -> ExceptionModel:
        exception = await self.get(exception_id)
        if exception is None:
            raise ValueError(f"Exception {exception_id} not found")
        return exception

    async def _vendor_context(self, case_id: int) -> dict[str, Any]:
        """Minimal vendor context for the triage prompt.

        Identifiers and banking details are excluded: the model is being asked
        to suggest next steps, and it does not need account numbers to do that.
        """
        result = await self.db.execute(
            select(OnboardingCase, Vendor)
            .join(Vendor, OnboardingCase.vendor_id == Vendor.id)
            .where(OnboardingCase.id == case_id)
        )
        row = result.first()
        if row is None:
            return {}

        case, vendor = row
        return {
            "legal_name": vendor.legal_name,
            "country": vendor.country,
            "vendor_type": vendor.vendor_type,
            "industry": vendor.industry,
            "case_number": case.case_number,
            "workflow_status": _enum_value(case.workflow_status),
            "risk_level": _enum_value(case.risk_level),
            "risk_score": case.risk_score,
        }


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else (str(value) if value is not None else "")
