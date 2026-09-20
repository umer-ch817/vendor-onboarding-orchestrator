"""Inbound webhook callbacks from n8n.

Why this module exists
----------------------
The integration schemas ``WorkflowTrigger`` and ``WebhookPayload`` were
defined in ``app/schemas/__init__.py`` and then never used by any route. A
schema with no route is a contract with no counterparty: the n8n side of the
system had no way to report what it did, so every notification, retry and
workflow failure happened off the record.

This module closes that loop without moving any decision into n8n. n8n may
*report* an action here; it may not *take* one. The endpoint is deliberately
narrow:

  * It appends exactly one audit event.
  * It cannot change a case's status, risk score, or approval state.
  * It cannot touch a vendor, document, exception or approval row.
  * Its event types are checked against a closed allowlist, so a compromised
    or misconfigured workflow cannot write arbitrary strings into the trail
    that the audit filter menu is built from.

That constraint is the point. Section 3 of the project brief puts
orchestration in n8n and business logic in the backend; an inbound webhook
that could mutate state would be a hole straight through that boundary.

Authentication
--------------
A shared secret header (``X-N8N-Secret``) compared with ``hmac.compare_digest``.

This is prototype-grade and is labelled as such: one static secret, no
rotation, no per-workflow identity, no replay protection. It establishes that
the caller knows the secret -- nothing more. Production would use mTLS or a
signed request with a timestamp and a nonce. See ``docs/decisions.md``.
"""
from __future__ import annotations

import hmac
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import OnboardingCase
from app.schemas import WebhookPayload, WorkflowIncident
from app.services import AuditService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Closed allowlist of event types n8n is permitted to write.
#
# Each entry carries the description template, so the wording of the audit
# trail is owned here rather than being supplied by the caller. n8n sends a
# type and a small data dict; it never sends prose that lands in the trail.
# ---------------------------------------------------------------------------

ALLOWED_EVENT_TYPES: dict[str, str] = {
    "WORKFLOW_TRIGGERED": "Orchestration workflow started for this case.",
    "WORKFLOW_COMPLETED": "Orchestration workflow finished successfully.",
    "WORKFLOW_FAILED": "Orchestration workflow failed after exhausting its retries.",
    "NOTIFICATION_SENT": "Reviewer notification dispatched.",
    "NOTIFICATION_FAILED": "Reviewer notification could not be delivered.",
    "NOTIFICATION_SKIPPED": "Notification suppressed because the case was already actioned.",
    "REVIEWER_ASSIGNED": "Case handed to a reviewer queue.",
    "APPROVAL_OPENED": "Approval request raised for human decision.",
    "SLA_WARNING": "Case is approaching its review deadline.",
    "SLA_ESCALATED": "Case exceeded its review deadline and was escalated.",
    "DOCUMENT_PROCESSING_DISPATCHED": "Document sent for extraction.",
    "RETRY_EXHAUSTED": "A downstream call failed and no retries remain.",
}


# ---------------------------------------------------------------------------
# Platform incidents
#
# A separate vocabulary because an incident is a different kind of fact. It may
# belong to no case at all -- a malformed webhook, an unreachable container --
# and forcing it onto a case id would mean either inventing one or dropping the
# failure. Platform rows appear in the recent-events view and in no case
# timeline, which is the correct shape: nobody reviewing vendor 47 should have
# to scroll past a container restart.
# ---------------------------------------------------------------------------

INCIDENT_EVENT_TYPES: dict[str, str] = {
    "WORKFLOW_FAILED": "An orchestration workflow terminated with an error.",
    "INTEGRATION_UNREACHABLE": "A downstream service did not answer.",
    "RETRY_EXHAUSTED": "A downstream call failed and no retries remain.",
    "WEBHOOK_REJECTED": "An inbound trigger failed validation and was not processed.",
}


def _require_secret(provided: Optional[str]) -> None:
    """Reject the call unless the shared secret matches.

    ``compare_digest`` is used rather than ``==`` so the comparison does not
    leak the secret's length or prefix through timing. It is a small thing,
    and it costs nothing.
    """
    expected = settings.N8N_API_KEY
    if not expected:
        # An unset secret must fail closed. Treating "no secret configured" as
        # "no auth required" is how a prototype becomes an incident.
        logger.error("n8n_webhook_secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook authentication is not configured.",
        )

    if not provided or not hmac.compare_digest(str(provided), str(expected)):
        logger.warning("n8n_webhook_rejected", extra={"reason": "bad_secret"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook secret.",
        )


@router.post("/n8n")
async def n8n_callback(
    payload: WebhookPayload,
    x_n8n_secret: Optional[str] = Header(default=None, alias="X-N8N-Secret"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record one n8n orchestration event against a case.

    Returns the audit event id so the caller can confirm the write landed. A
    404 for an unknown case is deliberate: an orchestration event attached to
    a case that does not exist would be an orphan row that the per-case
    timeline could never show and no one would ever read.
    """
    _require_secret(x_n8n_secret)

    event_type = payload.event_type.upper()
    if event_type not in ALLOWED_EVENT_TYPES:
        logger.warning(
            "n8n_webhook_unknown_event_type",
            extra={"event_type": event_type, "case_id": payload.case_id},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "unknown_event_type",
                "message": (
                    f"'{event_type}' is not a recognised orchestration event. "
                    f"Allowed: {', '.join(sorted(ALLOWED_EVENT_TYPES))}."
                ),
            },
        )

    case = await db.get(OnboardingCase, payload.case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Onboarding case {payload.case_id} not found.",
        )

    audit = AuditService(db)
    event = await audit.record_n8n(
        event_type,
        ALLOWED_EVENT_TYPES[event_type],
        case_id=payload.case_id,
        input_snapshot={"webhook_event_type": payload.event_type},
        output_snapshot=payload.data or {},
        metadata={
            "source": "n8n",
            "received_at": payload.timestamp.isoformat(),
            # Recorded so a workflow can be disabled without losing the trail
            # of what it had already done. n8n sends its own execution id.
            "workflow": (payload.data or {}).get("_workflow"),
            "execution_id": (payload.data or {}).get("_execution_id"),
        },
    )
    await db.commit()

    logger.info(
        "n8n_webhook_recorded",
        extra={"case_id": payload.case_id, "event_type": event_type},
    )
    return {
        "recorded": True,
        "event_id": event.id,
        "event_type": event_type,
        "case_id": payload.case_id,
    }


@router.get("/n8n/event-types")
async def list_allowed_event_types() -> dict[str, Any]:
    """The allowlist, for the workflow author and for documentation.

    Unauthenticated on purpose: it exposes the vocabulary of the audit trail,
    not any data from it. It lets someone building an n8n workflow discover
    the accepted event types without reading this file.
    """
    return {
        "event_types": [
            {"event_type": name, "description": text}
            for name, text in sorted(ALLOWED_EVENT_TYPES.items())
        ],
        "incident_event_types": [
            {"event_type": name, "description": text}
            for name, text in sorted(INCIDENT_EVENT_TYPES.items())
        ],
    }


# ---------------------------------------------------------------------------
# Platform incidents
#
# A separate endpoint because an incident is a different kind of fact. It may
# belong to no case at all -- a malformed webhook, an unreachable container --
# and forcing it onto a case id would mean either inventing one or dropping the
# failure. Platform rows appear in the recent-events view and in no case
# timeline, which is the correct shape: nobody reviewing vendor 47 should have
# to scroll past a container restart.
# ---------------------------------------------------------------------------

INCIDENT_EVENT_TYPES: dict[str, str] = {
    "WORKFLOW_FAILED": "An orchestration workflow terminated with an error.",
    "INTEGRATION_UNREACHABLE": "A downstream service did not answer.",
    "RETRY_EXHAUSTED": "A downstream call failed and no retries remain.",
    "WEBHOOK_REJECTED": "An inbound trigger failed validation and was not processed.",
}


# ---------------------------------------------------------------------------
# Platform incidents
#
# A separate endpoint because an incident is a different kind of fact. It may
# belong to no case at all -- a malformed webhook, an unreachable container --
# and forcing it onto a case id would mean either inventing one or dropping the
# failure. Platform rows appear in the recent-events view and in no case
# timeline, which is the correct shape: nobody reviewing vendor 47 should have
# to scroll past a container restart.
# ---------------------------------------------------------------------------

INCIDENT_EVENT_TYPES: dict[str, str] = {
    "WORKFLOW_FAILED": "An orchestration workflow terminated with an error.",
    "INTEGRATION_UNREACHABLE": "A downstream service did not answer.",
    "RETRY_EXHAUSTED": "A downstream call failed and no retries remain.",
    "WEBHOOK_REJECTED": "An inbound trigger failed validation and was not processed.",
}


@router.post("/n8n/incident")
async def n8n_incident(
    payload: WorkflowIncident,
    x_n8n_secret: Optional[str] = Header(default=None, alias="X-N8N-Secret"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record an orchestration failure that may not belong to any case."""
    _require_secret(x_n8n_secret)

    event_type = payload.event_type.upper()
    if event_type not in INCIDENT_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "unknown_event_type",
                "message": (
                    f"'{event_type}' is not a recognised incident type. "
                    f"Allowed: {', '.join(sorted(INCIDENT_EVENT_TYPES))}."
                ),
            },
        )

    # A case id is only used when it points at a case that exists. An incident
    # is still worth recording when the case reference is wrong, so this
    # degrades to a platform row instead of failing.
    case_id = payload.case_id
    if case_id is not None:
        if await db.get(OnboardingCase, case_id) is None:
            logger.warning(
                "n8n_incident_unknown_case",
                extra={"case_id": case_id, "event_type": event_type},
            )
            case_id = None

    description = payload.description or INCIDENT_EVENT_TYPES[event_type]
    audit = AuditService(db)
    event = await audit.record_n8n(
        event_type,
        description,
        case_id=case_id,
        output_snapshot={
            "workflow": payload.workflow,
            "execution_id": payload.execution_id,
            "node": payload.node,
            "message": payload.message,
            **(payload.data or {}),
        },
        metadata={"source": "n8n", "received_at": payload.timestamp.isoformat()},
    )
    await db.commit()

    logger.error(
        "n8n_incident_recorded",
        extra={
            "event_type": event_type,
            "workflow": payload.workflow,
            "node": payload.node,
            "message": payload.message,
        },
    )
    return {
        "recorded": True,
        "event_id": event.id,
        "event_type": event_type,
        "case_id": case_id,
    }
