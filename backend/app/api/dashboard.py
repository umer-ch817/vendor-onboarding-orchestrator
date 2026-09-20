"""Dashboard endpoints.

Operational metrics for the landing page. Two things matter here:

**Every number is defined, not just named.** ``definitions`` travels with the
response so the UI can put a real explanation behind each figure, and so a
reader cannot mistake a prototype metric for a benchmark. A dashboard that
shows "automation rate 68%" without saying what counted as automated is
decoration, not instrumentation.

**Nothing here is estimated.** Each metric is a count or a mean over rows that
actually exist. ``avg_onboarding_time_days`` is computed over completed cases
only; if none have completed it returns ``None`` rather than 0.0, because
"zero days" and "no data" are different claims.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Exception as ExceptionModel,
    ExceptionStatus,
    OnboardingCase,
    RiskLevel,
    Vendor,
    WorkflowStatus,
)
from app.schemas import DashboardMetrics
from app.services import ExceptionService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# A case is "in flight" until it reaches one of these. Everything else is
# somewhere in the pipeline and counts as active work.
TERMINAL_STATUSES = {
    WorkflowStatus.ONBOARDING_COMPLETE,
    WorkflowStatus.REJECTED,
}

# Statuses that mean a person is the bottleneck right now.
REVIEW_STATUSES = {
    WorkflowStatus.REVIEW_REQUIRED,
    WorkflowStatus.APPROVAL_PENDING,
    WorkflowStatus.BLOCKED,
}

METRIC_DEFINITIONS: dict[str, str] = {
    "total_vendors": "All vendor records, in any status. Demo Dataset.",
    "active_cases": "Onboarding cases not yet complete or rejected.",
    "pending_reviews": (
        "Cases sitting in review, approval or blocked. These are waiting on a "
        "person, not on the system."
    ),
    "open_exceptions": "Exceptions in open or in-progress status.",
    "high_risk_vendors": "Vendors whose assessed risk level is high or critical.",
    "avg_onboarding_time_days": (
        "Mean elapsed days from case creation to completion, over completed "
        "cases only. Null when no case has completed yet."
    ),
    "automation_rate": (
        "Share of completed onboardings that ran start to finish without any "
        "exception ever being raised against the case. Prototype Metric - this "
        "is a straight-through-processing rate for this synthetic dataset, not "
        "a benchmark."
    ),
    "cases_this_month": "Cases created since the first of the current month.",
    "completed_this_month": "Cases completed since the first of the current month.",
}


@router.get("/metrics", response_model=DashboardMetrics)
async def get_metrics(db: AsyncSession = Depends(get_db)) -> DashboardMetrics:
    """Typed metric payload. See ``/dashboard/`` for the annotated version."""
    computed = await _compute_metrics(db)
    return DashboardMetrics(**computed)


@router.get("/")
async def get_dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    """Metrics plus distributions plus the definition of every figure.

    Returned as a plain document rather than a response model so the
    definitions can travel with the numbers they explain.
    """
    computed = await _compute_metrics(db)

    status_rows = await db.execute(
        select(OnboardingCase.workflow_status, func.count())
        .group_by(OnboardingCase.workflow_status)
    )
    by_status = {
        _value(status): count for status, count in status_rows.all()
    }

    risk_rows = await db.execute(
        select(OnboardingCase.risk_level, func.count())
        .where(OnboardingCase.workflow_status.notin_(list(TERMINAL_STATUSES)))
        .group_by(OnboardingCase.risk_level)
    )
    risk_distribution = {level.value: 0 for level in RiskLevel}
    for level, count in risk_rows.all():
        risk_distribution[_value(level)] = count

    exception_service = ExceptionService(db)
    exception_counts = await exception_service.summary_counts()

    # Cases that need attention now, newest first. The dashboard's job is to
    # point at the next thing to look at, so this is deliberately short.
    attention_rows = await db.execute(
        select(OnboardingCase)
        .where(OnboardingCase.workflow_status.in_(list(REVIEW_STATUSES)))
        .order_by(OnboardingCase.updated_at.desc())
        .limit(10)
    )
    needs_attention = [
        {
            "case_id": case.id,
            "case_number": case.case_number,
            "workflow_status": _value(case.workflow_status),
            "risk_score": case.risk_score,
            "risk_level": _value(case.risk_level),
            "priority": case.priority,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        }
        for case in attention_rows.scalars().all()
    ]

    return {
        **computed,
        "by_status": by_status,
        "risk_distribution": risk_distribution,
        "exceptions_by_severity": exception_counts,
        "needs_attention": needs_attention,
        "definitions": METRIC_DEFINITIONS,
        "dataset_label": "Demo Dataset - synthetic vendors, no real organisations.",
    }


async def _compute_metrics(db: AsyncSession) -> dict:
    """Run the counts. Shared by both dashboard endpoints."""
    total_vendors = await _count(db, select(func.count()).select_from(Vendor))

    active_cases = await _count(
        db,
        select(func.count())
        .select_from(OnboardingCase)
        .where(OnboardingCase.workflow_status.notin_(list(TERMINAL_STATUSES))),
    )

    pending_reviews = await _count(
        db,
        select(func.count())
        .select_from(OnboardingCase)
        .where(OnboardingCase.workflow_status.in_(list(REVIEW_STATUSES))),
    )

    open_exceptions = await _count(
        db,
        select(func.count())
        .select_from(ExceptionModel)
        .where(
            ExceptionModel.status.in_(
                [ExceptionStatus.OPEN, ExceptionStatus.IN_PROGRESS]
            )
        ),
    )

    high_risk_vendors = await _count(
        db,
        select(func.count())
        .select_from(Vendor)
        .where(Vendor.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL])),
    )

    month_start = datetime.utcnow().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    cases_this_month = await _count(
        db,
        select(func.count())
        .select_from(OnboardingCase)
        .where(OnboardingCase.created_at >= month_start),
    )

    completed_this_month = await _count(
        db,
        select(func.count())
        .select_from(OnboardingCase)
        .where(
            and_(
                OnboardingCase.completed_at.isnot(None),
                OnboardingCase.completed_at >= month_start,
            )
        ),
    )

    # Elapsed time is averaged in Python rather than in SQL: the arithmetic
    # differs between Postgres and SQLite, and a dashboard that breaks on the
    # local demo database is worse than one that reads a few hundred rows.
    completed_rows = await db.execute(
        select(OnboardingCase.created_at, OnboardingCase.completed_at)
        .where(OnboardingCase.completed_at.isnot(None))
    )
    durations = [
        (completed - created).total_seconds() / 86400.0
        for created, completed in completed_rows.all()
        if created and completed
    ]
    avg_onboarding_time_days: Optional[float] = (
        round(sum(durations) / len(durations), 1) if durations else None
    )
    completed_count = len(durations)

    # Straight-through processing: completed cases with no exception history.
    automation_rate: Optional[float] = None
    if completed_count:
        flagged_rows = await db.execute(
            select(ExceptionModel.case_id).distinct()
        )
        flagged_case_ids = {row[0] for row in flagged_rows.all()}
        clean = await db.execute(
            select(OnboardingCase.id).where(
                OnboardingCase.workflow_status == WorkflowStatus.ONBOARDING_COMPLETE
            )
        )
        completed_ids = [row[0] for row in clean.all()]
        if completed_ids:
            straight_through = [
                case_id for case_id in completed_ids if case_id not in flagged_case_ids
            ]
            automation_rate = round(len(straight_through) / len(completed_ids), 3)

    return {
        "total_vendors": total_vendors,
        "active_cases": active_cases,
        "pending_reviews": pending_reviews,
        "open_exceptions": open_exceptions,
        "high_risk_vendors": high_risk_vendors,
        "avg_onboarding_time_days": avg_onboarding_time_days,
        "automation_rate": automation_rate,
        "cases_this_month": cases_this_month,
        "completed_this_month": completed_this_month,
    }


async def _count(db: AsyncSession, query) -> int:
    result = await db.execute(query)
    return int(result.scalar() or 0)


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)
