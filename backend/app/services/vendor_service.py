"""Vendor management service"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Vendor, VendorStatus, RiskLevel
from app.schemas import VendorCreate, VendorUpdate


class VendorService:
    """Service for vendor CRUD operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, vendor_data: VendorCreate) -> Vendor:
        """Create a new vendor"""
        vendor = Vendor(
            **vendor_data.model_dump(),
            status=VendorStatus.PENDING,
            risk_level=RiskLevel.LOW,
            risk_score=0
        )
        self.db.add(vendor)
        await self.db.flush()
        await self.db.refresh(vendor)
        return vendor

    async def get(self, vendor_id: int) -> Optional[Vendor]:
        """Get vendor by ID"""
        result = await self.db.execute(
            select(Vendor).where(Vendor.id == vendor_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, legal_name: str) -> Optional[Vendor]:
        """Find vendor by legal name (case-insensitive)"""
        result = await self.db.execute(
            select(Vendor).where(Vendor.legal_name.ilike(legal_name))
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status: Optional[VendorStatus] = None,
        risk_level: Optional[RiskLevel] = None
    ) -> tuple[List[Vendor], int]:
        """List vendors with pagination and filters"""
        query = select(Vendor)

        if search:
            query = query.where(
                or_(
                    Vendor.legal_name.ilike(f"%{search}%"),
                    Vendor.trade_name.ilike(f"%{search}%"),
                    Vendor.contact_email.ilike(f"%{search}%")
                )
            )

        if status:
            query = query.where(Vendor.status == status)

        if risk_level:
            query = query.where(Vendor.risk_level == risk_level)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        query = query.offset((page - 1) * page_size).limit(page_size)
        query = query.order_by(Vendor.updated_at.desc())

        result = await self.db.execute(query)
        vendors = result.scalars().all()

        return vendors, total

    async def update(self, vendor_id: int, vendor_data: VendorUpdate) -> Optional[Vendor]:
        """Update vendor"""
        vendor = await self.get(vendor_id)
        if not vendor:
            return None

        for field, value in vendor_data.model_dump(exclude_unset=True).items():
            setattr(vendor, field, value)

        vendor.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(vendor)
        return vendor

    async def update_risk(self, vendor_id: int, risk_score: int, risk_level: RiskLevel) -> Optional[Vendor]:
        """Update vendor risk assessment"""
        vendor = await self.get(vendor_id)
        if not vendor:
            return None

        vendor.risk_score = risk_score
        vendor.risk_level = risk_level
        vendor.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(vendor)
        return vendor

    async def mark_onboarded(self, vendor_id: int) -> Optional[Vendor]:
        """Mark vendor as fully onboarded"""
        vendor = await self.get(vendor_id)
        if not vendor:
            return None

        vendor.status = VendorStatus.ACTIVE
        vendor.onboarding_completed_at = datetime.utcnow()
        vendor.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(vendor)
        return vendor

    async def get_with_cases(self, vendor_id: int) -> Optional[Vendor]:
        """Get vendor with all onboarding cases"""
        result = await self.db.execute(
            select(Vendor)
            .options(selectinload(Vendor.onboarding_cases))
            .where(Vendor.id == vendor_id)
        )
        return result.scalar_one_or_none()