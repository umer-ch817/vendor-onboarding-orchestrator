"""Audit event recording.

Every state change in this system writes an audit row. The rule is simple:
if it changes what a reviewer will see, or explains why they see it, it is
audited.

WHAT IS DELIBERATELY NOT STORED
-------------------------------
No model chain-of-thought. Audit records store the model's *conclusion*, the
evidence it cited, its confidence, and which prompt version produced it. That
is sufficient to explain a decision six months later. Reconstructing the
model's internal reasoning is neither necessary nor appropriate, and would
not be reproducible in any case.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, ActorType
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AuditService:
    """Writes and reads the audit trail."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        *,
        event_type: str,
        description: str,
        actor_type: ActorType,
        case_id: Optional[int] = None,
        actor_id: Optional[int] = None,
        actor_name: Optional[str] = None,
        input_snapshot: Optional[dict[str, Any]] = None,
        output_snapshot: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Write one audit event.

        Audit writes never raise into the caller's transaction path: losing an
        audit row is bad, but failing a vendor's onboarding because the audit
        insert failed is worse. The failure is logged loudly instead.
        """
        event = AuditEvent(
            case_id=case_id,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name=actor_name,
            event_type=event_type,
            description=description,
            input_snapshot=_sanitise(input_snapshot),
            output_snapshot=_sanitise(output_snapshot),
            event_metadata=_sanitise(metadata),
            timestamp=datetime.utcnow(),
        )
        self.db.add(event)

        try:
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "audit_write_failed",
                extra={"event_type": event_type, "case_id": case_id, "error": str(exc)},
            )

        return event

    async def record_system(
        self,
        event_type: str,
        description: str,
        **kwargs: Any,
    ) -> AuditEvent:
        return await self.record(
            event_type=event_type,
            description=description,
            actor_type=ActorType.SYSTEM,
            **kwargs,
        )

    async def record_ai(
        self,
        event_type: str,
        description: str,
        analysis: Optional[Any] = None,
        **kwargs: Any,
    ) -> AuditEvent:
        """Record an AI action, attaching model metadata when available."""
        metadata = dict(kwargs.pop("metadata", None) or {})
        if analysis is not None:
            metadata["ai"] = {
                "provider": getattr(analysis, "provider", None),
                "model": getattr(analysis, "model", None),
                "prompt_version": getattr(analysis, "prompt_version", None),
                "latency_ms": getattr(analysis, "latency_ms", None),
                "attempts": getattr(analysis, "attempts", None),
                "repair_attempted": getattr(analysis, "repair_attempted", None),
                "prompt_tokens": getattr(analysis, "prompt_tokens", None),
                "completion_tokens": getattr(analysis, "completion_tokens", None),
            }
        return await self.record(
            event_type=event_type,
            description=description,
            actor_type=ActorType.AI,
            metadata=metadata,
            **kwargs,
        )
    async def record_user(
        self,
        event_type: str,
        description: str,
        user_id: int,
        user_name: Optional[str] = None,
        **kwargs: Any,
    ) -> AuditEvent:
        return await self.record(
            event_type=event_type,
            description=description,
            actor_type=ActorType.USER,
            actor_id=user_id,
            actor_name=user_name,
            **kwargs,
        )

    async def record_n8n(
        self,
        event_type: str,
        description: str,
        **kwargs: Any,
    ) -> AuditEvent:
        return await self.record(
            event_type=event_type,
            description=description,
            actor_type=ActorType.N8N,
            **kwargs,
        )

    async def list_for_case(
        self,
        case_id: int,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[Sequence[AuditEvent], int]:
        """Return a case's audit trail, oldest first.

        The timeline is read oldest-first because it is displayed as a
        narrative. Ordering is by timestamp then id, so that events written
        within the same millisecond still have a stable, meaningful order.
        """
        from sqlalchemy import func

        base = select(AuditEvent).where(AuditEvent.case_id == case_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        result = await self.db.execute(
            base.order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    async def list_recent(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> Sequence[AuditEvent]:
        """Most recent events across all cases, newest first."""
        query = select(AuditEvent)
        if event_type:
            query = query.where(AuditEvent.event_type == event_type)
        query = query.order_by(desc(AuditEvent.timestamp)).limit(limit)

        result = await self.db.execute(query)
        return result.scalars().all()


def _sanitise(payload: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Make an arbitrary dict JSON-safe for storage.

    Audit snapshots are assembled from ORM objects, dataclasses, dates and
    Decimals. Rather than making every call site responsible for
    serialisation, we normalise here.
    """
    if payload is None:
        return None

    import json
    from decimal import Decimal

    def default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "value"):
            return obj.value
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    try:
        return json.loads(json.dumps(payload, default=default))
    except (TypeError, ValueError) as exc:
        logger.warning("audit_snapshot_not_serialisable", extra={"error": str(exc)})
        return {"_unserialisable": str(payload)[:2000]}
