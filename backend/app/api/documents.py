"""Document upload and processing endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DocumentStatus, DocumentType
from app.schemas import (
    DocumentResponse,
    DocumentListResponse,
    DocumentWithExtraction,
)
from app.services import DocumentService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    vendor_id: int,
    case_id: int,
    file: UploadFile = File(...),
    document_type: Optional[DocumentType] = None,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Upload a document for a vendor's onboarding case.

    The document is stored and queued for extraction. If document_type is not
    provided, the classifier will determine it during processing.
    """
    service = DocumentService(db)

    # Read the file content
    content = await file.read()

    # Validate file size (configurable, default 25MB)
    max_size = 25 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {max_size // (1024 * 1024)}MB",
        )

    try:
        document = await service.register_document(
            vendor_id=vendor_id,
            case_id=case_id,
            filename=file.filename or "unnamed",
            content=content,
            mime_type=file.content_type,
            document_type=document_type,
        )
        logger.info(
            "document_uploaded",
            extra={
                "document_id": document.id,
                "case_id": case_id,
                "document_filename": file.filename,
                "size": len(content),
            },
        )
        return DocumentResponse.model_validate(document)
    except Exception as exc:
        logger.error("document_upload_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{document_id}/process")
async def process_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Process a single document: classify and extract fields.

    This runs synchronously so the caller can see extraction results
    immediately. For large batch processing, use the case-level assess endpoint.
    """
    from app.models import Document

    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="Document is already being processed")

    service = DocumentService(db)
    try:
        outcome = await service.process_document(document)
        await db.commit()

        logger.info(
            "document_processed",
            extra={
                "document_id": document_id,
                "success": outcome.success,
                "confidence": outcome.document_confidence,
            },
        )

        return {
            "document_id": document_id,
            "success": outcome.success,
            "document_type": document.document_type.value if document.document_type else None,
            "extraction_confidence": float(document.extraction_confidence or 0),
            "requires_verification": outcome.requires_human_verification,
            "failure_reason": outcome.failure_reason,
            "validation_errors": outcome.validation_errors,
            "warnings": getattr(outcome, "extraction_warnings", []),
            "extracted_fields": {
                name: {
                    "value": field.value,
                    "confidence": field.confidence,
                }
                for name, field in (outcome.result.fields.items() if outcome.result else [])
            },
        }
    except Exception as exc:
        await db.rollback()
        logger.error("document_processing_failed", extra={"document_id": document_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}")


@router.get("/{document_id}", response_model=DocumentWithExtraction)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
) -> DocumentWithExtraction:
    """Retrieve a document with its extracted fields."""
    from app.models import Document
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select

    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.extracted_fields))
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentWithExtraction.model_validate(document)


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    case_id: Optional[int] = Query(None),
    vendor_id: Optional[int] = Query(None),
    status: Optional[DocumentStatus] = Query(None),
    document_type: Optional[DocumentType] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List documents with optional filters."""
    from app.models import Document
    from sqlalchemy import select, func

    query = select(Document)

    if case_id:
        query = query.where(Document.case_id == case_id)
    if vendor_id:
        query = query.where(Document.vendor_id == vendor_id)
    if status:
        query = query.where(Document.status == status)
    if document_type:
        query = query.where(Document.document_type == document_type)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        query.order_by(Document.uploaded_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in documents],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{document_id}/verify")
async def verify_document(
    document_id: int,
    verified: bool,
    notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Mark a document as verified by a reviewer.

    Verification is a human action that confirms the extracted fields are
    correct. It does not change the extraction; it records that a person
    reviewed it.
    """
    from app.models import Document
    from datetime import datetime

    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    document.verification_status = "verified" if verified else "rejected"
    document.verification_notes = notes
    document.verified_at = datetime.utcnow()

    await db.flush()
    logger.info(
        "document_verified",
        extra={
            "document_id": document_id,
            "verified": verified,
        },
    )

    return {
        "document_id": document_id,
        "verification_status": document.verification_status,
        "verified_at": document.verified_at.isoformat(),
    }
