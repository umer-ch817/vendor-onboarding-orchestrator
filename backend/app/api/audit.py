"""Audit trail endpoints.

The audit view is read-only by construction. There is no POST here, and there
should never be one: an audit trail that an application can edit is not an
audit trail.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditEvent
from app.schemas import AuditEventResponse, AuditEventListResponse
from app.services import AuditService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/", response_model=AuditEventListResponse)
async def list_recent_events(
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> AuditEventListResponse:
    """Most recent events across all cases, newest first.

    This is the "what has the system been doing" view, as opposed to the
    per-case timeline.
    """
    service = AuditService(db)
    events = await service.list_recent(limit=limit, event_type=event_type)
    return AuditEventListResponse(
        events=[AuditEventResponse.from_event(e) for e in events],
        total=len(events),
    )


@router.get("/types")
async def list_event_types(db: AsyncSession = Depends(get_db)) -> dict:
    """Distinct event types present in the trail.

    Populated from the data rather than a hard-coded list, so a filter menu
    built from this cannot drift away from the events actually being written.
    """
    result = await db.execute(
        select(AuditEvent.event_type).distinct().order_by(AuditEvent.event_type)
    )
    return {"event_types": [row[0] for row in result.all()]}


@router.get("/case/{case_id}", response_model=AuditEventListResponse)
async def get_case_timeline(
    case_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> AuditEventListResponse:
    """A case's full history, oldest first.

    The timeline reads as a narrative - documents uploaded, findings raised,
    AI advisory notes, reviewer decisions, completion - so it is ordered
    forward in time rather than newest-first.
    """
    service = AuditService(db)
    events, total = await service.list_for_case(
        case_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return AuditEventListResponse(
        events=[AuditEventResponse.from_event(e) for e in events],
        total=total,
    )


@router.get("/event/{event_id}", response_model=AuditEventResponse)
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
) -> AuditEventResponse:
    """Retrieve a single audit event, including its snapshots.

    Not every event is shown in the timeline with its full payload - AI events
    in particular carry metadata that belongs behind a click rather than in
    the row.
    """
    event = await db.get(AuditEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return AuditEventResponse.from_event(event)
