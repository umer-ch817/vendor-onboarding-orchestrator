"""Onboarding case management service"""
from typing import Optional, List
from datetime import datetime
import uuid

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    OnboardingCase, WorkflowStatus, Document, DocumentStatus,
    Vendor, VendorStatus, RiskLevel
)
from app.schemas import OnboardingCaseCreate, OnboardingCaseUpdate


class OnboardingService:
    """Service for onboarding case management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _generate_case_number(self) -> str:
        """Generate unique case number"""
        year = datetime.utcnow().year
        unique_id = str(uuid.uuid4())[:6].upper()
        return f"VO-{year}-{unique_id}"

    async def create(self, case_data: OnboardingCaseCreate) -> OnboardingCase:
        """Create a new onboarding case"""
        # Get vendor to validate
        result = await self.db.execute(
            select(Vendor).where(Vendor.id == case_data.vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if not vendor:
            raise ValueError(f"Vendor {case_data.vendor_id} not found")

        case = OnboardingCase(
            case_number=self._generate_case_number(),
            **case_data.model_dump(),
            workflow_status=WorkflowStatus.DRAFT,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            completion_percentage=0
        )
        self.db.add(case)
        await self.db.flush()
        # Re-select instead of refresh: OnboardingCaseResponse embeds the
        # vendor, and touching `case.vendor` lazily outside a greenlet raises
        # MissingGreenlet under the async driver.
        result = await self.db.execute(
            select(OnboardingCase)
            .options(selectinload(OnboardingCase.vendor))
            .where(OnboardingCase.id == case.id)
        )
        return result.scalar_one()

    async def get(self, case_id: int) -> Optional[OnboardingCase]:
        """Get onboarding case by ID"""
        # vendor is eager-loaded for the same reason as in create(): callers
        # serialize the case into a response that embeds it.
        result = await self.db.execute(
            select(OnboardingCase)
            .options(selectinload(OnboardingCase.vendor))
            .where(OnboardingCase.id == case_id)
        )
        return result.scalar_one_or_none()

    async def get_by_number(self, case_number: str) -> Optional[OnboardingCase]:
        """Get onboarding case by case number"""
        result = await self.db.execute(
            select(OnboardingCase).where(OnboardingCase.case_number == case_number)
        )
        return result.scalar_one_or_none()

    async def get_with_details(self, case_id: int) -> Optional[OnboardingCase]:
        """Get case with all related data"""
        result = await self.db.execute(
            select(OnboardingCase)
            .options(
                selectinload(OnboardingCase.vendor),
                selectinload(OnboardingCase.documents),
                selectinload(OnboardingCase.risk_signals),
                selectinload(OnboardingCase.exceptions),
                selectinload(OnboardingCase.approvals),
                selectinload(OnboardingCase.audit_events)
            )
            .where(OnboardingCase.id == case_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[WorkflowStatus] = None,
        risk_level: Optional[RiskLevel] = None,
        search: Optional[str] = None
    ) -> tuple[List[OnboardingCase], int]:
        """List onboarding cases with pagination and filters"""
        query = select(OnboardingCase).options(selectinload(OnboardingCase.vendor))

        if status:
            query = query.where(OnboardingCase.workflow_status == status)

        if risk_level:
            query = query.where(OnboardingCase.risk_level == risk_level)

        if search:
            query = query.where(
                OnboardingCase.case_number.ilike(f"%{search}%")
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        query = query.offset((page - 1) * page_size).limit(page_size)
        query = query.order_by(desc(OnboardingCase.updated_at))

        result = await self.db.execute(query)
        cases = result.scalars().all()

        return cases, total

    async def update(self, case_id: int, case_data: OnboardingCaseUpdate) -> Optional[OnboardingCase]:
        """Update onboarding case"""
        case = await self.get(case_id)
        if not case:
            return None

        for field, value in case_data.model_dump(exclude_unset=True).items():
            setattr(case, field, value)

        case.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def update_status(self, case_id: int, status: WorkflowStatus) -> Optional[OnboardingCase]:
        """Update workflow status"""
        case = await self.get(case_id)
        if not case:
            return None

        case.workflow_status = status
        case.updated_at = datetime.utcnow()

        if status == WorkflowStatus.ONBOARDING_COMPLETE:
            case.completed_at = datetime.utcnow()
            case.completion_percentage = 100

        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def update_progress(self, case_id: int) -> Optional[OnboardingCase]:
        """Update completion percentage based on documents"""
        case = await self.get_with_details(case_id)
        if not case:
            return None

        if case.documents_required > 0:
            case.completion_percentage = int(
                (case.documents_received / case.documents_required) * 100
            )

        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def update_risk(self, case_id: int, risk_score: int, risk_level: RiskLevel) -> Optional[OnboardingCase]:
        """Update risk assessment"""
        case = await self.get(case_id)
        if not case:
            return None

        case.risk_score = risk_score
        case.risk_level = risk_level
        case.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def get_workflow_summary(self) -> dict:
        """Get summary of cases by workflow status"""
        result = await self.db.execute(
            select(OnboardingCase.workflow_status, func.count())
            .group_by(OnboardingCase.workflow_status)
        )
        return dict(result.all())

    async def get_risk_summary(self) -> dict:
        """Get summary of cases by risk level"""
        result = await self.db.execute(
            select(OnboardingCase.risk_level, func.count())
            .group_by(OnboardingCase.risk_level)
        )
        return dict(result.all())