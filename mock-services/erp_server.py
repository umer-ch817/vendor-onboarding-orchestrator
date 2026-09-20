#!/usr/bin/env python3
"""
Mock ERP Service — Vendor Onboarding & Risk Orchestrator

Provides deterministic vendor data lookups and ERP integration endpoints
for the demo. Runs keyless and returns synthetic data only.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Mock ERP Service", version="1.0.0")


class VendorERPResponse(BaseModel):
    """Response schema for ERP vendor lookup."""
    vendor_id: str
    legal_name: str
    trade_name: Optional[str] = None
    erp_status: str  # "active", "inactive", "on_hold"
    payment_terms: str  # "net_30", "net_45", "net_60", "cod"
    credit_limit: float
    currency: str = "USD"
    tax_exempt: bool = False
    tax_exempt_cert: Optional[str] = None
    preferred_payment_method: str = "ach"
    last_payment_date: Optional[date] = None
    outstanding_balance: float = 0.0
    total_spend_ytd: float = 0.0
    total_spend_ltm: float = 0.0
    on_time_payment_rate: float = 1.0
    dispute_count_ltm: int = 0


class VendorCreateERP(BaseModel):
    """Request schema for creating vendor in ERP."""
    legal_name: str
    trade_name: Optional[str] = None
    tax_id: Optional[str] = None
    address_line1: str
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str
    contact_email: str
    payment_terms: str = "net_30"
    credit_limit: float = 0.0
    currency: str = "USD"


# In-memory synthetic data store (demo only)
SYNTHETIC_VENDORS = {
    "V-001": VendorERPResponse(
        vendor_id="V-001",
        legal_name="Apex Industrial Solutions LLC",
        trade_name="Apex Industrial",
        erp_status="active",
        payment_terms="net_30",
        credit_limit=50000.0,
        currency="USD",
        tax_exempt=False,
        preferred_payment_method="ach",
        last_payment_date=date(2026, 8, 15),
        outstanding_balance=12500.0,
        total_spend_ytd=185000.0,
        total_spend_ltm=245000.0,
        on_time_payment_rate=0.98,
        dispute_count_ltm=1,
    ),
    "V-002": VendorERPResponse(
        vendor_id="V-002",
        legal_name="Blue Ridge Contracting Inc",
        trade_name="Blue Ridge",
        erp_status="active",
        payment_terms="net_45",
        credit_limit=100000.0,
        currency="USD",
        tax_exempt=False,
        preferred_payment_method="wire",
        last_payment_date=date(2026, 8, 20),
        outstanding_balance=45000.0,
        total_spend_ytd=420000.0,
        total_spend_ltm=580000.0,
        on_time_payment_rate=0.95,
        dispute_count_ltm=2,
    ),
    "V-003": VendorERPResponse(
        vendor_id="V-003",
        legal_name="Catalyst Consulting Group",
        trade_name="Catalyst",
        erp_status="active",
        payment_terms="net_30",
        credit_limit=25000.0,
        currency="USD",
        tax_exempt=True,
        tax_exempt_cert="EXEMPT-2026-001",
        preferred_payment_method="ach",
        last_payment_date=date(2026, 9, 1),
        outstanding_balance=0.0,
        total_spend_ytd=75000.0,
        total_spend_ltm=95000.0,
        on_time_payment_rate=1.0,
        dispute_count_ltm=0,
    ),
}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "mock-erp"}


@app.get("/api/v1/vendors/{vendor_id}", response_model=VendorERPResponse)
async def get_vendor(vendor_id: str) -> VendorERPResponse:
    """Look up vendor in ERP by internal ERP vendor ID."""
    if vendor_id not in SYNTHETIC_VENDORS:
        # Return a deterministic synthetic vendor for any unknown ID
        return VendorERPResponse(
            vendor_id=vendor_id,
            legal_name=f"Synthetic Vendor {vendor_id}",
            trade_name=f"SynVendor {vendor_id[-3:]}",
            erp_status="active",
            payment_terms="net_30",
            credit_limit=10000.0,
            currency="USD",
            tax_exempt=False,
            preferred_payment_method="ach",
            last_payment_date=None,
            outstanding_balance=0.0,
            total_spend_ytd=0.0,
            total_spend_ltm=0.0,
            on_time_payment_rate=1.0,
            dispute_count_ltm=0,
        )
    return SYNTHETIC_VENDORS[vendor_id]


@app.post("/api/v1/vendors", response_model=VendorERPResponse, status_code=201)
async def create_vendor(payload: VendorCreateERP) -> VendorERPResponse:
    """Create a new vendor in ERP (demo: returns synthetic response)."""
    # Generate deterministic vendor ID from hash of legal_name
    import hashlib
    vendor_id = f"V-{hashlib.md5(payload.legal_name.encode()).hexdigest()[:6].upper()}"

    return VendorERPResponse(
        vendor_id=vendor_id,
        legal_name=payload.legal_name,
        trade_name=payload.trade_name,
        erp_status="active",
        payment_terms=payload.payment_terms,
        credit_limit=payload.credit_limit,
        currency=payload.currency,
        tax_exempt=False,
        preferred_payment_method="ach",
        last_payment_date=None,
        outstanding_balance=0.0,
        total_spend_ytd=0.0,
        total_spend_ltm=0.0,
        on_time_payment_rate=1.0,
        dispute_count_ltm=0,
    )


@app.get("/api/v1/vendors/{vendor_id}/payment-history")
async def get_payment_history(vendor_id: str) -> dict:
    """Get payment history for a vendor (synthetic)."""
    return {
        "vendor_id": vendor_id,
        "payments": [
            {"date": "2026-08-15", "amount": 12500.0, "method": "ach", "status": "completed"},
            {"date": "2026-07-15", "amount": 12500.0, "method": "ach", "status": "completed"},
            {"date": "2026-06-15", "amount": 15000.0, "method": "ach", "status": "completed"},
        ],
        "summary": {
            "total_payments_ltm": 3,
            "on_time_rate": 1.0,
            "avg_days_to_pay": 28,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)