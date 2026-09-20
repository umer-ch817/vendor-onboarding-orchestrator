"""API router configuration"""
from fastapi import APIRouter

from app.api.vendors import router as vendors_router
from app.api.onboarding import router as onboarding_router
from app.api.documents import router as documents_router
from app.api.risk import router as risk_router
from app.api.exceptions import router as exceptions_router
from app.api.approvals import router as approvals_router
from app.api.audit import router as audit_router
from app.api.dashboard import router as dashboard_router
from app.api.webhooks import router as webhooks_router

router = APIRouter()

# Include all API routers
router.include_router(vendors_router, prefix="/vendors", tags=["Vendors"])
router.include_router(onboarding_router, prefix="/onboarding", tags=["Onboarding"])
router.include_router(documents_router, prefix="/documents", tags=["Documents"])
router.include_router(risk_router, prefix="/risk", tags=["Risk Analysis"])
router.include_router(exceptions_router, prefix="/exceptions", tags=["Exceptions"])
router.include_router(approvals_router, prefix="/approvals", tags=["Approvals"])
router.include_router(audit_router, prefix="/audit", tags=["Audit"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])

# Inbound callbacks from n8n. Kept on its own prefix so the whole surface n8n
# is allowed to touch can be found with a single grep for "/webhooks".
router.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])