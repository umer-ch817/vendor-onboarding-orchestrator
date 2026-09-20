#!/usr/bin/env python3
"""
Mock Compliance Service — Vendor Onboarding & Risk Orchestrator

Provides deterministic sanctions screening, adverse media checks, and
regulatory compliance endpoints for the demo. Runs keyless and returns
synthetic data only.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Compliance Service", version="1.0.0")


class ScreeningResult(str, Enum):
    CLEAR = "clear"
    MATCH = "match"
    POTENTIAL_MATCH = "potential_match"
    ERROR = "error"


class SanctionsList(str, Enum):
    OFAC_SDN = "OFAC_SDN"
    OFAC_CONSOLIDATED = "OFAC_CONSOLIDATED"
    UN_CONSOLIDATED = "UN_CONSOLIDATED"
    EU_CONSOLIDATED = "EU_CONSOLIDATED"
    UK_HMT = "UK_HMT"
    CANADA_OSFI = "CANADA_OSFI"
    AUSTRALIA_DFAT = "AUSTRALIA_DFAT"


class AdverseMediaCategory(str, Enum):
    FINANCIAL_CRIME = "financial_crime"
    CORRUPTION_BRIBERY = "corruption_bribery"
    REGULATORY_ACTION = "regulatory_action"
    LITIGATION = "litigation"
    SANCTIONS = "sanctions"
    REPUTATIONAL = "reputational"
    CYBER = "cyber"
    ESG = "esg"


class SanctionsScreenRequest(BaseModel):
    legal_name: str
    country: str
    tax_id: Optional[str] = None
    date_of_birth: Optional[date] = None  # for individuals
    alternative_names: list[str] = []


class SanctionsMatch(BaseModel):
    list_name: SanctionsList
    match_name: str
    match_score: float = Field(..., ge=0, le=1)
    list_entry_id: Optional[str] = None
    program: Optional[str] = None
    remarks: Optional[str] = None


class SanctionsScreenResponse(BaseModel):
    request_id: str
    legal_name: str
    country: str
    overall_result: ScreeningResult
    matches: list[SanctionsMatch] = []
    lists_screened: list[SanctionsList]
    screened_at: date


class AdverseMediaArticle(BaseModel):
    title: str
    source: str
    url: str
    published_date: date
    category: AdverseMediaCategory
    relevance_score: float = Field(..., ge=0, le=1)
    snippet: str


class AdverseMediaResponse(BaseModel):
    request_id: str
    legal_name: str
    country: str
    overall_risk: str  # "low", "medium", "high"
    articles: list[AdverseMediaArticle] = []
    total_articles_found: int
    screened_at: date


class PEPStatus(str, Enum):
    NOT_PEP = "not_pep"
    PEP = "pep"
    RELATIVE_CLOSE_ASSOCIATE = "relative_close_associate"
    UNKNOWN = "unknown"


class PEPCheckResponse(BaseModel):
    request_id: str
    legal_name: str
    country: str
    pep_status: PEPStatus
    details: Optional[str] = None
    lists_checked: list[str]
    checked_at: date


# Deterministic synthetic responses based on input
def deterministic_screen(legal_name: str, country: str) -> tuple[ScreeningResult, list[SanctionsMatch]]:
    """Generate deterministic sanctions screening result."""
    import hashlib
    # Use hash of name + country for deterministic "randomness"
    seed = int(hashlib.md5(f"{legal_name}|{country}".encode()).hexdigest()[:8], 16)

    # High-risk countries get matches
    high_risk_countries = {"RU", "IR", "KP", "SY", "CU", "VE", "BY"}

    if country in high_risk_countries:
        # 80% chance of match for high-risk countries
        if seed % 10 < 8:
            return ScreeningResult.MATCH, [
                SanctionsMatch(
                    list_name=SanctionsList.OFAC_SDN,
                    match_name=f"Similar Entity to {legal_name}",
                    match_score=0.85 + (seed % 10) / 100,
                    list_entry_id=f"SDN-{seed % 10000}",
                    program="UKRAINE-EO14024",
                    remarks="Entity operating in sanctioned jurisdiction",
                ),
                SanctionsMatch(
                    list_name=SanctionsList.EU_CONSOLIDATED,
                    match_name=f"Associated Entity {legal_name}",
                    match_score=0.72 + (seed % 15) / 100,
                    list_entry_id=f"EU-{seed % 5000}",
                    program="RUSSIA_SANCTIONS",
                    remarks="Subsidiary of sanctioned parent",
                ),
            ]

    # 5% chance of potential match for any country
    if seed % 20 == 0:
        return ScreeningResult.POTENTIAL_MATCH, [
            SanctionsMatch(
                list_name=SanctionsList.UN_CONSOLIDATED,
                match_name=f"Name Similarity: {legal_name}",
                match_score=0.65 + (seed % 20) / 100,
                list_entry_id=f"UN-{seed % 8000}",
                remarks="Name similarity only - manual review recommended",
            ),
        ]

    return ScreeningResult.CLEAR, []


def deterministic_adverse_media(legal_name: str, country: str) -> tuple[str, list[AdverseMediaArticle]]:
    """Generate deterministic adverse media results."""
    import hashlib
    seed = int(hashlib.md5(f"{legal_name}|{country}|media".encode()).hexdigest()[:8], 16)

    # High-risk industries/geographies get more articles
    high_risk_countries = {"RU", "CN", "IR", "KP", "SY", "CU", "VE", "BY"}
    base_count = 3 if country in high_risk_countries else 1
    article_count = base_count + (seed % 3)

    categories = list(AdverseMediaCategory)
    articles = []

    for i in range(article_count):
        cat = categories[(seed + i) % len(categories)]
        articles.append(AdverseMediaArticle(
            title=f"{cat.value.replace('_', ' ').title()} Investigation Involving {legal_name}",
            source="Synthetic Compliance News",
            url=f"https://compliance-news.example/article/{seed + i}",
            published_date=date(2026, max(1, (seed + i) % 12), max(1, (seed + i) % 28)),
            category=cat,
            relevance_score=0.3 + ((seed + i) % 7) / 10,
            snippet=f"Regulatory authorities are examining {legal_name} for potential {cat.value.replace('_', ' ')} violations...",
        ))

    # Determine overall risk
    max_relevance = max((a.relevance_score for a in articles), default=0)
    if max_relevance > 0.7:
        overall = "high"
    elif max_relevance > 0.4:
        overall = "medium"
    else:
        overall = "low"

    return overall, articles


def deterministic_pep(legal_name: str, country: str) -> PEPStatus:
    """Generate deterministic PEP check result."""
    import hashlib
    seed = int(hashlib.md5(f"{legal_name}|{country}|pep".encode()).hexdigest()[:8], 16)

    # Very low probability for demo
    if seed % 100 == 0:
        return PEPStatus.PEP
    elif seed % 50 == 0:
        return PEPStatus.RELATIVE_CLOSE_ASSOCIATE
    return PEPStatus.NOT_PEP


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "mock-compliance"}


@app.post("/api/v1/screen/sanctions", response_model=SanctionsScreenResponse)
async def screen_sanctions(request: SanctionsScreenRequest) -> SanctionsScreenResponse:
    """Screen entity against global sanctions lists."""
    import uuid
    result, matches = deterministic_screen(request.legal_name, request.country)

    return SanctionsScreenResponse(
        request_id=f"SCR-{uuid.uuid4().hex[:8].upper()}",
        legal_name=request.legal_name,
        country=request.country,
        overall_result=result,
        matches=matches,
        lists_screened=list(SanctionsList),
        screened_at=date.today(),
    )


@app.post("/api/v1/screen/adverse-media", response_model=AdverseMediaResponse)
async def screen_adverse_media(
    legal_name: str = Query(..., min_length=1),
    country: str = Query(..., min_length=2, max_length=2),
) -> AdverseMediaResponse:
    """Screen entity for adverse media coverage."""
    import uuid
    overall_risk, articles = deterministic_adverse_media(legal_name, country)

    return AdverseMediaResponse(
        request_id=f"AMR-{uuid.uuid4().hex[:8].upper()}",
        legal_name=legal_name,
        country=country,
        overall_risk=overall_risk,
        articles=articles,
        total_articles_found=len(articles),
        screened_at=date.today(),
    )


@app.post("/api/v1/screen/pep", response_model=PEPCheckResponse)
async def check_pep(
    legal_name: str = Query(..., min_length=1),
    country: str = Query(..., min_length=2, max_length=2),
) -> PEPCheckResponse:
    """Check if entity or beneficial owners are Politically Exposed Persons."""
    import uuid
    pep_status = deterministic_pep(legal_name, country)

    return PEPCheckResponse(
        request_id=f"PEP-{uuid.uuid4().hex[:8].upper()}",
        legal_name=legal_name,
        country=country,
        pep_status=pep_status,
        details="No PEP match found in synthetic database" if pep_status == PEPStatus.NOT_PEP else "Potential PEP match - manual verification required",
        lists_checked=["World-Check PEP", "Internal PEP Database", "Government Records"],
        checked_at=date.today(),
    )


@app.post("/api/v1/screen/comprehensive")
async def comprehensive_screen(
    legal_name: str = Query(..., min_length=1),
    country: str = Query(..., min_length=2, max_length=2),
    tax_id: Optional[str] = Query(None),
) -> dict:
    """Run all compliance screens in one call."""
    import uuid
    request_id = f"COMP-{uuid.uuid4().hex[:8].upper()}"

    sanctions_result, sanctions_matches = deterministic_screen(legal_name, country)
    media_risk, media_articles = deterministic_adverse_media(legal_name, country)
    pep_status = deterministic_pep(legal_name, country)

    # Overall risk determination
    if sanctions_result == ScreeningResult.MATCH:
        overall = "high"
    elif sanctions_result == ScreeningResult.POTENTIAL_MATCH or media_risk == "high" or pep_status != PEPStatus.NOT_PEP:
        overall = "medium"
    else:
        overall = "low"

    return {
        "request_id": request_id,
        "legal_name": legal_name,
        "country": country,
        "overall_compliance_risk": overall,
        "sanctions": {
            "result": sanctions_result.value,
            "matches": [m.model_dump() for m in sanctions_matches],
        },
        "adverse_media": {
            "overall_risk": media_risk,
            "article_count": len(media_articles),
        },
        "pep": {
            "status": pep_status.value,
        },
        "screened_at": date.today().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)