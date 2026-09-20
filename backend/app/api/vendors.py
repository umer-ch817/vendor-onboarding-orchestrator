"""Vendor CRUD endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RiskLevel, VendorStatus
from app.schemas import (
    VendorCreate,
    VendorUpdate,
    VendorResponse,
    VendorListResponse,
)
from app.services import VendorService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/", response_model=VendorResponse, status_code=201)
async def create_vendor(
    vendor_data: VendorCreate,
    db: AsyncSession = Depends(get_db),
) -> VendorResponse:
    """Create a new vendor record.

    The vendor starts in PENDING status with a risk score of zero. The risk
    assessment happens when documents are processed, not at creation time.
    """
    service = VendorService(db)
    try:
        vendor = await service.create(vendor_data)
        logger.info("vendor_created", extra={"vendor_id": vendor.id, "legal_name": vendor.legal_name})
        return VendorResponse.model_validate(vendor)
    except Exception as exc:
        logger.error("vendor_create_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
) -> VendorResponse:
    """Retrieve a vendor by ID."""
    service = VendorService(db)
    vendor = await service.get(vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return VendorResponse.model_validate(vendor)


@router.get("/", response_model=VendorListResponse)
async def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[VendorStatus] = Query(None),
    risk_level: Optional[RiskLevel] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> VendorListResponse:
    """List vendors with pagination and filters."""
    service = VendorService(db)
    vendors, total = await service.list(
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        risk_level=risk_level,
    )
    return VendorListResponse(
        vendors=[VendorResponse.model_validate(v) for v in vendors],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    vendor_data: VendorUpdate,
    db: AsyncSession = Depends(get_db),
) -> VendorResponse:
    """Update vendor details.

    Risk score and level are not editable here; they are derived from the
    assessment and changing them manually would break the audit chain.
    """
    service = VendorService(db)
    vendor = await service.update(vendor_id, vendor_data)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    logger.info("vendor_updated", extra={"vendor_id": vendor.id})
    return VendorResponse.model_validate(vendor)


@router.get("/{vendor_id}/cases")
async def get_vendor_cases(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List all onboarding cases for a vendor."""
    service = VendorService(db)
    vendor = await service.get_with_cases(vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {
        "vendor_id": vendor_id,
        "legal_name": vendor.legal_name,
        "cases": [
            {
                "id": case.id,
                "case_number": case.case_number,
                "workflow_status": case.workflow_status.value if case.workflow_status else None,
                "risk_score": case.risk_score,
                "risk_level": case.risk_level.value if case.risk_level else None,
                "created_at": case.created_at.isoformat() if case.created_at else None,
            }
            for case in vendor.onboarding_cases
        ],
    }
