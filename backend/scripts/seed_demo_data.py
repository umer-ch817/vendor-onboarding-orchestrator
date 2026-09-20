#!/usr/bin/env python3
"""
Demo Data Seed Script — Vendor Onboarding & Risk Orchestrator

Generates 20 synthetic vendors across 6 distinct risk scenarios, each with:
- Onboarding cases (new_vendor, renewal, update)
- Documents with extracted fields (W-9, COI, Business Registration, Banking, Tax Cert, Questionnaire)
- Risk signals from deterministic rule engine
- Exceptions in the queue (some open, some resolved)
- Approval chains with role-based decisions
- Audit trail covering user, system, AI, and n8n events

All data is SYNTHETIC. No real PII, banking information, or real company data.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_maker, Base, engine
from app.models import (
    ActorType,
    Approval,
    ApprovalStatus,
    AuditEvent,
    Document,
    DocumentStatus,
    DocumentType,
    Exception as ExceptionModel,
    ExceptionSeverity,
    ExceptionStatus,
    ExtractedField,
    OnboardingCase,
    RiskAssessment,
    RiskLevel,
    RiskSignal,
    User,
    UserRole,
    Vendor,
    VendorStatus,
    WorkflowStatus,
)
from app.rules.engine import RuleEngine
from app.rules.risk_scoring import RiskScoringService
from app.rules.types import RequirementSpec
from app.schemas import VendorCreate, OnboardingCaseCreate
from app.services.audit_service import AuditService
from app.services.document_service import DocumentService
from app.services.onboarding_service import OnboardingService
from app.services.pipeline import OnboardingPipeline
from app.services.requirement_service import RequirementService
from app.services.vendor_service import VendorService
from app.utils.logging import get_logger

logger = get_logger(__name__)

# =============================================================================
# SYNTHETIC DATA CATALOGUES
# =============================================================================

# 6 Distinct Scenarios
SCENARIOS = [
    {
        "name": "clean_us_supplier",
        "label": "Clean US Supplier",
        "description": "Well-established US vendor, all docs current, low risk",
        "vendor_type": "supplier",
        "country": "US",
        "industry": "manufacturing",
        "risk_profile": "low",
        "doc_status": "current",
        "issues": [],
    },
    {
        "name": "expiring_insurance_contractor",
        "label": "Expiring Insurance Contractor",
        "description": "US contractor with COI expiring in 15 days",
        "vendor_type": "contractor",
        "country": "US",
        "industry": "construction",
        "risk_profile": "medium",
        "doc_status": "expiring_soon",
        "issues": ["EXPIRING_INSURANCE"],
    },
    {
        "name": "missing_docs_consultant",
        "label": "Missing Documents Consultant",
        "description": "US consultant missing W-9 and Business Registration",
        "vendor_type": "consultant",
        "country": "US",
        "industry": "professional_services",
        "risk_profile": "high",
        "doc_status": "missing_mandatory",
        "issues": ["MISSING_W9", "MISSING_BUSREG"],
    },
    {
        "name": "high_risk_geography_offshore",
        "label": "High-Risk Geography Offshore",
        "description": "Offshore service provider in high-risk country",
        "vendor_type": "service_provider",
        "country": "RU",
        "industry": "software_development",
        "risk_profile": "critical",
        "doc_status": "current",
        "issues": ["HIGH_RISK_GEOGRAPHY", "MISSING_TAX_CERT"],
    },
    {
        "name": "entity_mismatch_banking",
        "label": "Entity Name / Banking Mismatch",
        "description": "Vendor name on docs doesn't match legal entity; bank account holder differs",
        "vendor_type": "supplier",
        "country": "US",
        "industry": "wholesale",
        "risk_profile": "high",
        "doc_status": "mismatch",
        "issues": ["ENTITY_NAME_MISMATCH", "BANKING_MISMATCH"],
    },
    {
        "name": "renewal_expired_docs",
        "label": "Renewal with Expired Documents",
        "description": "Existing vendor renewal - COI and Tax Cert expired",
        "vendor_type": "supplier",
        "country": "CA",
        "industry": "logistics",
        "risk_profile": "medium",
        "doc_status": "expired",
        "issues": ["EXPIRED_COI", "EXPIRED_TAX_CERT"],
    },
]

# Synthetic vendor names (clearly fake)
VENDOR_NAMES = [
    "Apex Industrial Solutions LLC",
    "Blue Ridge Contracting Inc",
    "Catalyst Consulting Group",
    "Delta Manufacturing Co",
    "Echelon Software Services",
    "Frontier Logistics Partners",
    "Glacier Peak Wholesale",
    "Harbor View Supplies Ltd",
    "Ironclad Construction Co",
    "Jasper Ridge Analytics",
    "Keystone Professional Services",
    "Lighthouse Tech Solutions",
    "Meridian Global Trading",
    "Nexus Engineering Group",
    "Olympus Materials Inc",
    "Pinnacle Advisory LLC",
    "Quantum Systems Integrators",
    "Riverstone Distribution",
    "Summit Compliance Partners",
    "Terraforma Design Studio",
]

# Synthetic trade names
TRADE_NAMES = [
    "Apex Industrial",
    "Blue Ridge",
    "Catalyst",
    "Delta Mfg",
    "Echelon",
    "Frontier Logistics",
    "Glacier Peak",
    "Harbor View",
    "Ironclad",
    "Jasper Ridge",
    "Keystone",
    "Lighthouse",
    "Meridian",
    "Nexus",
    "Olympus",
    "Pinnacle",
    "Quantum",
    "Riverstone",
    "Summit",
    "Terraforma",
]

# Synthetic addresses (US)
US_ADDRESSES = [
    {"line1": "100 Innovation Drive", "city": "Austin", "state": "TX", "postal": "78701", "country": "US"},
    {"line1": "2500 Tech Parkway", "city": "San Jose", "state": "CA", "postal": "95134", "country": "US"},
    {"line1": "500 Commerce Blvd", "city": "Atlanta", "state": "GA", "postal": "30303", "country": "US"},
    {"line1": "7500 Research Way", "city": "Boston", "state": "MA", "postal": "02110", "country": "US"},
    {"line1": "1200 Market Street", "city": "Philadelphia", "state": "PA", "postal": "19107", "country": "US"},
    {"line1": "3000 Industrial Rd", "city": "Chicago", "state": "IL", "postal": "60601", "country": "US"},
    {"line1": "888 Corporate Center", "city": "Dallas", "state": "TX", "postal": "75201", "country": "US"},
    {"line1": "4500 Enterprise Ave", "city": "Seattle", "state": "WA", "postal": "98101", "country": "US"},
    {"line1": "2100 Business Loop", "city": "Denver", "state": "CO", "postal": "80202", "country": "US"},
    {"line1": "999 Venture Lane", "city": "Phoenix", "state": "AZ", "postal": "85001", "country": "US"},
]

# Synthetic non-US addresses
INTL_ADDRESSES = [
    {"line1": "100 Maple Street", "city": "Toronto", "state": "ON", "postal": "M5V 2L7", "country": "CA"},
    {"line1": "55 Queen's Road", "city": "London", "state": "", "postal": "EC2A 3RD", "country": "GB"},
    {"line1": "200 Friedrichstrasse", "city": "Berlin", "state": "BE", "postal": "10117", "country": "DE"},
    {"line1": "15 Rue de la Paix", "city": "Paris", "state": "IDF", "postal": "75002", "country": "FR"},
    {"line1": "7 Chome-3-1 Marunouchi", "city": "Tokyo", "state": "", "postal": "100-0005", "country": "JP"},
    {"line1": "42 Bolshaya Yakimanka", "city": "Moscow", "state": "", "postal": "119049", "country": "RU"},
    {"line1": "88 Raffles Place", "city": "Singapore", "state": "", "postal": "048618", "country": "SG"},
    {"line1": "25 Martin Place", "city": "Sydney", "state": "NSW", "postal": "2000", "country": "AU"},
]

# Industries
INDUSTRIES = [
    "manufacturing",
    "construction",
    "professional_services",
    "software_development",
    "wholesale",
    "logistics",
    "healthcare",
    "financial_services",
    "retail",
    "energy",
]

# Vendor types
VENDOR_TYPES = ["supplier", "contractor", "consultant", "service_provider"]

# Contact names (synthetic)
CONTACT_FIRST = ["James", "Maria", "Robert", "Jennifer", "Michael", "Lisa", "David", "Sarah", "Christopher", "Amanda"]
CONTACT_LAST = ["Anderson", "Thompson", "Martinez", "Garcia", "Robinson", "Clark", "Rodriguez", "Lewis", "Lee", "Walker"]

# Users for assignment (internal reviewers)
REVIEWER_USERS = [
    {"email": "alice.admin@company.example", "name": "Alice Admin", "role": UserRole.ADMIN, "dept": "IT"},
    {"email": "bob.procurement@company.example", "name": "Bob Procurement", "role": UserRole.PROCUREMENT_MANAGER, "dept": "Procurement"},
    {"email": "carol.analyst@company.example", "name": "Carol Analyst", "role": UserRole.PROCUREMENT_ANALYST, "dept": "Procurement"},
    {"email": "dave.compliance@company.example", "name": "Dave Compliance", "role": UserRole.COMPLIANCE_REVIEWER, "dept": "Compliance"},
    {"email": "eve.finance@company.example", "name": "Eve Finance", "role": UserRole.FINANCE_REVIEWER, "dept": "Finance"},
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def synthetic_tax_id(vendor_type: str, country: str) -> str:
    """Generate synthetic tax ID appropriate to country/type."""
    if country == "US":
        # EIN format: XX-XXXXXXX
        return f"{random.randint(10,99)}-{random.randint(1000000,9999999)}"
    elif country == "CA":
        # BN format: 9 digits
        return f"{random.randint(100000000,999999999)}"
    elif country == "GB":
        # VAT format: GB XXX XXXX XX
        return f"GB {random.randint(100,999)} {random.randint(1000,9999)} {random.randint(10,99)}"
    elif country == "DE":
        # DE VAT: DEXXXXXXXXX
        return f"DE{random.randint(100000000,999999999)}"
    else:
        return f"TAX{random.randint(100000,999999)}"


def synthetic_bank_account() -> str:
    """Generate synthetic last-4 of bank account."""
    return f"{random.randint(1000,9999)}"


def synthetic_bank_name() -> str:
    """Synthetic bank names."""
    banks = [
        "First National Bank",
        "Meridian Trust",
        "Capital One",
        "Chase Bank",
        "Wells Fargo",
        "Bank of America",
        "Citibank",
        "PNC Bank",
        "US Bank",
        "Truist",
    ]
    return random.choice(banks)


def synthetic_contact() -> tuple[str, str, str]:
    """Generate synthetic contact name, email, phone."""
    first = random.choice(CONTACT_FIRST)
    last = random.choice(CONTACT_LAST)
    name = f"{first} {last}"
    email = f"{first.lower()}.{last.lower()}@vendor{random.randint(100,999)}.example"
    phone = f"+1-{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}"
    return name, email, phone


def synthetic_document_content(doc_type: DocumentType, vendor_name: str, scenario: dict) -> bytes:
    """Generate synthetic document text content for extraction."""
    today = date.today()
    exp_soon = today + timedelta(days=15)
    exp_later = today + timedelta(days=180)
    expired = today - timedelta(days=30)

    if doc_type == DocumentType.W9:
        return f"""Form W-9
Request for Taxpayer Identification Number and Certification

Name (as shown on your income tax return): {vendor_name}
Business name/disregarded entity name: {vendor_name}
Federal tax classification: Limited liability company
Exemptions (codes apply only to certain entities):
Address: 100 Innovation Drive, Austin, TX 78701
Requester's name and address: Internal Procurement Dept

Part I - Taxpayer Identification Number (TIN)
Employer identification number (EIN): {synthetic_tax_id('supplier', 'US')}

Part II - Certification
Under penalties of perjury, I certify that:
1. The number shown on this form is my correct taxpayer identification number
2. I am not subject to backup withholding

Sign Here: _________________________
Date: {today.strftime('%m/%d/%Y')}
""".encode()

    elif doc_type == DocumentType.CERTIFICATE_OF_INSURANCE:
        exp_date = expired if "EXPIRED_COI" in scenario["issues"] else (exp_soon if "EXPIRING_INSURANCE" in scenario["issues"] else exp_later)
        return f"""CERTIFICATE OF LIABILITY INSURANCE

PRODUCER: Meridian Insurance Brokers
INSURED: {vendor_name}

COVERAGES:
General Liability: $2,000,000 per occurrence / $4,000,000 aggregate
Automobile Liability: $1,000,000 combined single limit
Workers Compensation: Statutory limits
Umbrella Liability: $5,000,000

POLICY NUMBER: GL-{random.randint(100000,999999)}
EFFECTIVE DATE: {(today - timedelta(days=365)).strftime('%m/%d/%Y')}
EXPIRATION DATE: {exp_date.strftime('%m/%d/%Y')}

CERTIFICATE HOLDER: Internal Procurement Dept
CANCELLATION: 30 days written notice
""".encode()

    elif doc_type == DocumentType.BUSINESS_REGISTRATION:
        return f"""CERTIFICATE OF FORMATION / GOOD STANDING

Entity Name: {vendor_name}
Entity Type: Limited Liability Company
File Number: {random.randint(10000000,99999999)}
Formation Date: {(today - timedelta(days=random.randint(365,3650))).strftime('%m/%d/%Y')}
State of Formation: Delaware
Status: ACTIVE - In Good Standing
Registered Agent: Corporate Services Inc
Principal Office: 100 Innovation Drive, Austin, TX 78701

This certificate confirms the entity is authorized to transact business.
Issued: {today.strftime('%m/%d/%Y')}
""".encode()

    elif doc_type == DocumentType.BANKING_CONFIRMATION:
        # Entity mismatch scenario: different name on bank letter
        bank_name = synthetic_bank_name()
        account_holder = vendor_name if "BANKING_MISMATCH" not in scenario["issues"] else f"{vendor_name} Holdings LLC"
        return f"""BANK CONFIRMATION LETTER

{bank_name}
100 Financial Plaza
Austin, TX 78701

Date: {today.strftime('%m/%d/%Y')}

TO WHOM IT MAY CONCERN:

This letter confirms that {account_holder} maintains an active checking account
with our institution.

Account Holder: {account_holder}
Account Type: Business Checking
Account Number (last 4): {synthetic_bank_account()}
Account Opened: {(today - timedelta(days=random.randint(365,1825))).strftime('%m/%d/%Y')}
Current Status: Active, in good standing

This information is provided at the request of the account holder.
Authorized Signature: _________________________
""".encode()

    elif doc_type == DocumentType.TAX_CERTIFICATE:
        exp_date = expired if "EXPIRED_TAX_CERT" in scenario["issues"] else exp_later
        return f"""TAX REGISTRATION CERTIFICATE

Jurisdiction: {scenario['country']}
Tax Authority: Revenue Department

Taxpayer: {vendor_name}
Registration Number: {synthetic_tax_id('supplier', scenario['country'])}
Registration Date: {(today - timedelta(days=random.randint(365,1825))).strftime('%m/%d/%Y')}
Expiration Date: {exp_date.strftime('%m/%d/%Y')}
Status: {'EXPIRED' if 'EXPIRED_TAX_CERT' in scenario['issues'] else 'ACTIVE'}

Tax Types Registered:
- Corporate Income Tax
- VAT/GST (where applicable)
- Payroll Tax

This certificate is valid until the expiration date shown above.
""".encode()

    elif doc_type == DocumentType.SUPPLIER_QUESTIONNAIRE:
        ownership = "Complete" if "INCOMPLETE_OWNERSHIP" not in scenario["issues"] else "Incomplete - beneficial owners not disclosed"
        return f"""SUPPLIER QUESTIONNAIRE - OWNERSHIP & CONFLICT OF INTEREST DISCLOSURE

Company: {vendor_name}

SECTION 1: OWNERSHIP STRUCTURE
Legal Structure: Limited Liability Company
State of Incorporation: Delaware
Parent Company: None
Ultimate Parent: None

Beneficial Owners (>=25%):
{'- John Smith - 40%' if ownership == 'Complete' else '- [NOT DISCLOSED]'}
{'- Jane Doe - 35%' if ownership == 'Complete' else '- [NOT DISCLOSED]'}
{'- Employee Trust - 25%' if ownership == 'Complete' else '- [NOT DISCLOSED]'}

SECTION 2: CONFLICT OF INTEREST
Any current/former government employees? No
Any relationships with our employees? No
Any pending litigation? No

SECTION 3: COMPLIANCE
Anti-corruption policy: Yes
Data privacy compliance: Yes
Export controls compliance: Yes

Completed by: {synthetic_contact()[0]}
Date: {today.strftime('%m/%d/%Y')}
Signature: _________________________
""".encode()

    else:
        return f"""GENERIC DOCUMENT: {doc_type.value}
Vendor: {vendor_name}
Date: {today.strftime('%m/%d/%Y')}
Content: This is a synthetic document for demo purposes.
""".encode()


def scenario_document_types(scenario: dict) -> list[DocumentType]:
    """Determine which document types exist for a scenario."""
    base = [
        DocumentType.W9,
        DocumentType.CERTIFICATE_OF_INSURANCE,
        DocumentType.BUSINESS_REGISTRATION,
        DocumentType.BANKING_CONFIRMATION,
    ]

    if scenario["country"] != "US":
        base.append(DocumentType.TAX_CERTIFICATE)

    if scenario["vendor_type"] in ["supplier", "service_provider"] or scenario["risk_profile"] in ["high", "critical"]:
        base.append(DocumentType.SUPPLIER_QUESTIONNAIRE)

    # Remove missing docs
    if "MISSING_W9" in scenario["issues"]:
        base = [d for d in base if d != DocumentType.W9]
    if "MISSING_BUSREG" in scenario["issues"]:
        base = [d for d in base if d != DocumentType.BUSINESS_REGISTRATION]
    if "MISSING_TAX_CERT" in scenario["issues"]:
        base = [d for d in base if d != DocumentType.TAX_CERTIFICATE]

    return base


# =============================================================================
# MAIN SEED FUNCTION
# =============================================================================

async def seed_all() -> None:
    """Main entry point: creates all demo data."""
    logger.info("Starting demo data seed")

    async with async_session_maker() as db:
        # Create tables if not exist
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 1. Create internal reviewer users
        users = await create_users(db)

        # 2. Seed requirement catalogue
        req_service = RequirementService(db)
        await req_service.seed_defaults()

        # 3. Create vendors + cases + documents per scenario
        await create_scenario_data(db, users)

        # 4. Run assessment pipeline on submitted cases
        await run_assessments(db)

        # 5. Create approval chains for cases ready for decision
        await create_approvals(db, users)

        # 6. Create some resolved exceptions
        await create_resolved_exceptions(db, users)

        await db.commit()
        logger.info("Demo data seed completed successfully")


async def create_users(db: AsyncSession) -> list[User]:
    """Create internal reviewer users."""
    users = []
    for u in REVIEWER_USERS:
        existing = await db.execute(select(User).where(User.email == u["email"]))
        if existing.scalar_one_or_none():
            users.append(existing.scalar_one())
            continue
        user = User(
            email=u["email"],
            name=u["name"],
            role=u["role"],
            department=u["dept"],
            is_active=True,
        )
        db.add(user)
        users.append(user)
    await db.flush()
    logger.info("Created %d reviewer users", len(users))
    return users


async def create_scenario_data(db: AsyncSession, users: list[User]) -> None:
    """Create vendors, cases, documents for each scenario."""
    vendor_service = VendorService(db)
    onboarding_service = OnboardingService(db)
    doc_service = DocumentService(db)

    # Distribute 20 vendors across 6 scenarios
    vendors_per_scenario = [4, 4, 3, 3, 3, 3]  # = 20
    vendor_idx = 0

    for scenario, count in zip(SCENARIOS, vendors_per_scenario):
        for i in range(count):
            vendor_idx += 1
            await create_vendor_case_docs(db, vendor_service, onboarding_service, doc_service, users, scenario, vendor_idx)

    logger.info("Created all scenario data")


async def create_vendor_case_docs(
    db: AsyncSession,
    vendor_service: VendorService,
    onboarding_service: OnboardingService,
    doc_service: DocumentService,
    users: list[User],
    scenario: dict,
    vendor_idx: int,
) -> None:
    """Create one vendor with case and documents."""
    # Pick name
    name = VENDOR_NAMES[vendor_idx - 1]
    trade = TRADE_NAMES[vendor_idx - 1]

    # Address
    if scenario["country"] == "US":
        addr = random.choice(US_ADDRESSES)
    else:
        addr = random.choice(INTL_ADDRESSES)
        # Force country match
        addr = {**addr, "country": scenario["country"]}

    contact_name, contact_email, contact_phone = synthetic_contact()

    # Create vendor
    vendor_create = VendorCreate(
        legal_name=name,
        trade_name=trade,
        vendor_type=scenario["vendor_type"],
        industry=scenario["industry"],
        tax_id=synthetic_tax_id(scenario["vendor_type"], scenario["country"]),
        website=f"https://{trade.lower().replace(' ', '')}.example",
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        address_line1=addr["line1"],
        address_line2="",
        city=addr["city"],
        state=addr["state"],
        postal_code=addr["postal"],
        country=addr["country"],
        bank_name=synthetic_bank_name(),
        bank_account_last4=synthetic_bank_account(),
    )
    vendor = await vendor_service.create(vendor_data=vendor_create)

    # Create onboarding case
    requester = random.choice(users)
    case_create = OnboardingCaseCreate(
        vendor_id=vendor.id,
        onboarding_type=random.choice(["new_vendor", "renewal", "update"]),
        priority=random.choice(["low", "normal", "high"]),
        requester_name=requester.name,
        requester_email=requester.email,
        requester_department=requester.department,
    )
    case = await onboarding_service.create(case_data=case_create)

    # Submit case (moves to DOCUMENT_COLLECTION)
    await onboarding_service.update_status(case.id, WorkflowStatus.DOCUMENT_COLLECTION)

    # Create documents
    doc_types = scenario_document_types(scenario)
    for doc_type in doc_types:
        content = synthetic_document_content(doc_type, name, scenario)
        # synthetic_document_content() returns plain text, so the file must be
        # declared as text. Naming it .pdf would route it through the PDF
        # parser, which cannot parse it, and every document would fail.
        filename = f"{doc_type.value}_{name.replace(' ', '_')[:30]}.txt"

        document = await doc_service.register_document(
            vendor_id=vendor.id,
            case_id=case.id,
            filename=filename,
            content=content,
            mime_type="text/plain",
        )

        # Process document (classify + extract)
        await doc_service.process_document(document, declared_type=doc_type)

        # Update case document counts
        case.documents_required = len(doc_types)
        case.documents_received += 1
        await onboarding_service.update_progress(case.id)

    # Also add 1-2 extra "OTHER" documents randomly
    if random.random() < 0.3:
        for _ in range(random.randint(1, 2)):
            content = b"Supplemental document content for demo"
            document = await doc_service.register_document(
                vendor_id=vendor.id,
                case_id=case.id,
                filename=f"supplemental_{random.randint(1000,9999)}.txt",
                content=content,
                mime_type="text/plain",
            )
            await doc_service.process_document(document)
            case.documents_received += 1
            await onboarding_service.update_progress(case.id)

    logger.info("Created vendor %s (%s) with case %s and %d documents",
                vendor.legal_name, scenario["name"], case.case_number, len(doc_types))


async def run_assessments(db: AsyncSession) -> None:
    """Run the assessment pipeline on all submitted cases."""
    result = await db.execute(
        select(OnboardingCase).where(
            OnboardingCase.workflow_status.in_([
                WorkflowStatus.DOCUMENT_COLLECTION,
                WorkflowStatus.EXTRACTION,
                WorkflowStatus.VALIDATION,
                WorkflowStatus.RISK_ANALYSIS,
                WorkflowStatus.REVIEW_REQUIRED,
            ])
        )
    )
    cases = result.scalars().all()

    pipeline = OnboardingPipeline(db)

    for case in cases:
        try:
            logger.info("Running assessment for case %s", case.case_number)
            assessment_result = await pipeline.run(case.id)
            await db.commit()
            logger.info("Case %s assessed: route=%s score=%d",
                        case.case_number, assessment_result.route, assessment_result.score_total)
        except Exception as e:
            await db.rollback()
            logger.error("Assessment failed for case %s: %s", case.case_number, e)


async def create_approvals(db: AsyncSession, users: list[User]) -> None:
    """Create approval chains for cases in APPROVAL_PENDING or REVIEW_REQUIRED."""
    from app.services.approval_service import ApprovalService

    result = await db.execute(
        select(OnboardingCase).where(
            OnboardingCase.workflow_status.in_([
                WorkflowStatus.APPROVAL_PENDING,
                WorkflowStatus.REVIEW_REQUIRED,
            ])
        ).options(selectinload(OnboardingCase.vendor))
    )
    cases = result.scalars().all()

    approval_service = ApprovalService(db)

    # Role mapping for approval types
    role_map = {
        "manager": [u for u in users if u.role == UserRole.PROCUREMENT_MANAGER],
        "compliance": [u for u in users if u.role in (UserRole.COMPLIANCE_REVIEWER, UserRole.PROCUREMENT_MANAGER)],
        "finance": [u for u in users if u.role == UserRole.FINANCE_REVIEWER],
        "legal": [u for u in users if u.role == UserRole.ADMIN],
    }

    for case in cases:
        # Determine which approvals needed based on risk
        approval_types = []
        if case.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM]:
            approval_types = ["manager", "compliance", "finance"]
        else:
            approval_types = ["manager", "compliance", "finance", "legal"]

        for atype in approval_types:
            reviewers = role_map.get(atype, [])
            if not reviewers:
                continue
            reviewer = random.choice(reviewers)

            try:
                await approval_service.request(
                    case_id=case.id,
                    approval_type=atype,
                    reviewer_id=reviewer.id,
                    actor_user_id=reviewer.id,
                    actor_user_name=reviewer.name,
                )
            except Exception as e:
                logger.warning("Could not create %s approval for case %s: %s", atype, case.case_number, e)

        # Update case status to APPROVAL_PENDING
        if case.workflow_status == WorkflowStatus.REVIEW_REQUIRED:
            await db.execute(
                select(OnboardingCase).where(OnboardingCase.id == case.id)
            )
            case.workflow_status = WorkflowStatus.APPROVAL_PENDING
            await db.flush()

    logger.info("Created approval chains for %d cases", len(cases))


async def create_resolved_exceptions(db: AsyncSession, users: list[User]) -> None:
    """Create some resolved exceptions to show history."""
    from app.services.exception_service import ExceptionService

    result = await db.execute(
        select(ExceptionModel).where(ExceptionModel.status == ExceptionStatus.OPEN)
    )
    open_exceptions = result.scalars().all()

    exception_service = ExceptionService(db)
    admin_user = next(u for u in users if u.role == UserRole.ADMIN)

    # Resolve ~30% of open exceptions
    to_resolve = random.sample(open_exceptions, k=max(1, len(open_exceptions) // 3))

    for exc in to_resolve:
        resolution_type = random.choice(["resolved", "dismissed", "override"])
        if resolution_type == "override":
            resolution = "Risk accepted based on compensating controls and vendor track record. Business need outweighs residual risk."
        elif resolution_type == "dismissed":
            resolution = "Exception raised in error - document was present but misclassified. Re-verified and confirmed valid."
        else:
            resolution = "Vendor provided updated document. Verified and confirmed compliant. Exception no longer applies."

        try:
            await exception_service.resolve(
                exception_id=exc.id,
                resolution=resolution,
                resolution_type=resolution_type,
                actor_user_id=admin_user.id,
                actor_user_name=admin_user.name,
            )
            logger.info("Resolved exception %d (%s) as %s", exc.id, exc.type, resolution_type)
        except Exception as e:
            logger.warning("Could not resolve exception %d: %s", exc.id, e)

    await db.commit()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql://vendoruser:vendorpass@localhost:5432/vendordb")
    os.environ.setdefault("LLM_PROVIDER", "mock")

    asyncio.run(seed_all())
    print("✅ Demo data seeded successfully!")
    print("Not idempotent: truncate before re-running (see RUNBOOK.md).")