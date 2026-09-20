"""Document lifecycle: upload, classify, extract, persist.

Responsibilities, in order:

1. Record an uploaded document and its bytes on disk.
2. Determine its type (from the upload, or by asking the classifier).
3. Extract structured fields via the AI layer, which already validates the
   model's output against a schema.
4. Persist each extracted field *with both its raw and normalized value*, so
   a reviewer can always see what the system actually compared.
5. Surface anything that needs a human -- failed extraction, low confidence,
   a scan with no text layer -- as data rather than as an exception.

What this module deliberately does not do: decide whether anything is wrong.
That is the rule engine's job, and keeping the two apart is what makes the
findings explainable.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Sequence

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.extraction import DocumentExtractionService, ExtractionOutcome
from app.config import settings
from app.models import (
    Document,
    DocumentStatus,
    DocumentType,
    ExtractedField,
)
from app.rules.types import DocumentEvidence, FieldEvidence
from app.services.document_processing import (
    CorruptDocumentError,
    UnsupportedDocumentError,
    extract_text,
)
from app.services.normalization import normalize_value
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Fields carrying document-level dates, lifted onto the Document row so the
# rule engine can compare expiry dates without digging into fields.
EXPIRATION_FIELDS = {"expiration_date", "expiry_date", "valid_until"}


class DocumentService:
    """Owns document records and their extracted content."""

    def __init__(
        self,
        db: AsyncSession,
        extraction_service: Optional[DocumentExtractionService] = None,
        storage_root: Optional[str] = None,
    ):
        self.db = db
        self.extractor = extraction_service or DocumentExtractionService()
        self.storage_root = Path(storage_root or settings.DOCUMENT_STORAGE_PATH)

    # -- creation ----------------------------------------------------------

    async def register_document(
        self,
        *,
        vendor_id: int,
        case_id: int,
        filename: str,
        content: bytes,
        mime_type: Optional[str] = None,
        document_type: Optional[DocumentType] = None,
    ) -> Document:
        """Store a document and its bytes.

        ``document_type`` is optional: when the uploader does not declare one,
        the classifier fills it in during processing. Until then the document
        is stored as OTHER so the row is never in an invalid state.
        """
        document = Document(
            vendor_id=vendor_id,
            case_id=case_id,
            document_type=document_type or DocumentType.OTHER,
            filename=filename,
            file_size=len(content),
            mime_type=mime_type,
            status=DocumentStatus.PENDING,
        )
        self.db.add(document)
        await self.db.flush()

        try:
            path = self._write_bytes(document, content)
            document.file_path = str(path)
        except OSError as exc:  # noqa: BLE001
            logger.error(
                "document_write_failed",
                extra={"document_id": document.id, "error": str(exc)},
            )
            document.status = DocumentStatus.FAILED

        await self.db.flush()
        return document

    def _write_bytes(self, document: Document, content: bytes) -> Path:
        """Persist raw bytes under a per-case directory."""
        directory = self.storage_root / f"case_{document.case_id}"
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = f"{document.id}_{Path(document.filename).name}"
        path = directory / safe_name
        path.write_bytes(content)
        return path

    # -- processing --------------------------------------------------------

    async def process_document(
        self,
        document: Document,
        declared_type: Optional[DocumentType] = None,
    ) -> ExtractionOutcome:
        """Classify (if needed) and extract a document's fields."""
        document.status = DocumentStatus.PROCESSING
        await self.db.flush()

        try:
            content = Path(document.file_path).read_bytes() if document.file_path else b""
            raw = extract_text(content, document.filename, document.mime_type)
        except (UnsupportedDocumentError, CorruptDocumentError) as exc:
            return await self._fail(document, str(exc))
        except OSError as exc:
            return await self._fail(document, f"Stored file could not be read: {exc}")

        if not raw.text.strip():
            return await self._fail(
                document,
                "No readable text could be extracted. This is likely a scanned "
                "image and requires manual transcription.",
            )

        document_type = declared_type or document.document_type

        # Resolve the type when it was not declared (or was declared as OTHER).
        if document_type in (None, DocumentType.OTHER):
            classification, _analysis, failure = await self.extractor.classify_document(
                raw.text, document.filename
            )
            if classification is None:
                return await self._fail(
                    document, failure or "Document could not be classified"
                )
            document_type = _to_document_type(classification.document_type)
            if classification.confidence < settings.CONFIDENCE_MEDIUM:
                raw.warnings.append(
                    f"document classified as {document_type.value} with low "
                    f"confidence ({classification.confidence:.2f})"
                )

        document.document_type = document_type

        outcome = await self.extractor.extract_document(
            document_type.value, raw.text, document.filename
        )

        if not outcome.success or outcome.result is None:
            return await self._fail(
                document,
                outcome.failure_reason or "Extraction failed",
                outcome=outcome,
            )

        await self._persist_fields(document, outcome)

        document.status = DocumentStatus.EXTRACTED
        document.extraction_confidence = Decimal(
            str(round(outcome.result.document_confidence, 2))
        )
        document.processed_at = datetime.utcnow()
        document.verification_status = (
            "pending" if outcome.requires_human_verification else "not_required"
        )
        await self.db.flush()

        # Attach the extraction warnings to the returned outcome so the caller
        # can raise exceptions from them without re-reading the model output.
        outcome.extraction_warnings = list(raw.warnings) + list(outcome.result.warnings or [])
        return outcome

    async def _persist_fields(self, document: Document, outcome: ExtractionOutcome) -> None:
        """Replace a document's extracted fields with the latest extraction."""
        result = outcome.result
        assert result is not None

        # Re-processing must not accumulate stale fields.
        await self.db.execute(
            delete(ExtractedField).where(ExtractedField.document_id == document.id)
        )

        for name, field in result.fields.items():
            if field.value is None:
                continue

            raw_value = field.value
            self.db.add(
                ExtractedField(
                    document_id=document.id,
                    field_name=name,
                    field_value=str(raw_value) if not isinstance(raw_value, bool) else str(raw_value).lower(),
                    normalized_value=normalize_value(name, raw_value),
                    confidence=Decimal(str(round(field.confidence, 2))),
                    source_location=field.source_location or None,
                    is_valid=True,
                )
            )

            if name.lower() in EXPIRATION_FIELDS:
                parsed = _parse_date(raw_value)
                if parsed:
                    document.expiration_date = datetime.combine(parsed, datetime.min.time())
                else:
                    outcome.validation_errors.append(
                        f"expiration date {raw_value!r} could not be parsed"
                    )

        await self.db.flush()

    async def _fail(
        self,
        document: Document,
        reason: str,
        outcome: Optional[ExtractionOutcome] = None,
    ) -> ExtractionOutcome:
        """Mark a document failed and return an outcome describing why."""
        document.status = DocumentStatus.FAILED
        document.verification_status = "pending"
        document.processed_at = datetime.utcnow()
        await self.db.flush()

        logger.warning(
            "document_processing_failed",
            extra={"document_id": document.id, "reason": reason},
        )

        if outcome is not None:
            outcome.success = False
            outcome.failure_reason = reason
            outcome.requires_human_verification = True
            return outcome

        return ExtractionOutcome(
            success=False,
            failure_reason=reason,
            requires_human_verification=True,
        )

    # -- reads -------------------------------------------------------------

    async def list_for_case(self, case_id: int) -> Sequence[Document]:
        result = await self.db.execute(
            select(Document)
            .where(Document.case_id == case_id)
            .options(selectinload(Document.extracted_fields))
            .order_by(Document.uploaded_at.asc())
        )
        return result.scalars().all()

    # -- evidence assembly -------------------------------------------------

    async def build_evidence(self, case_id: int) -> list[DocumentEvidence]:
        """Convert a case's documents into rule-engine evidence.

        This is the seam between the ORM and the pure rule engine. Doing the
        conversion in one place means the rule engine stays free of database
        imports and remains testable on plain dataclasses.
        """
        documents = await self.list_for_case(case_id)
        return [self._to_evidence(doc) for doc in documents]

    @staticmethod
    def _to_evidence(document: Document) -> DocumentEvidence:
        fields: dict[str, FieldEvidence] = {}

        for field in document.extracted_fields or []:
            fields[field.field_name] = FieldEvidence(
                name=field.field_name,
                raw_value=field.field_value,
                normalized_value=field.normalized_value or "",
                confidence=float(field.confidence or 0),
                document_id=document.id,
                document_type=_enum_value(document.document_type),
                manually_corrected=bool(field.manually_corrected),
            )

        return DocumentEvidence(
            document_id=document.id,
            document_type=_enum_value(document.document_type),
            filename=document.filename,
            status=_enum_value(document.status),
            extraction_confidence=float(document.extraction_confidence or 0),
            expiration_date=_as_date(document.expiration_date),
            document_date=_as_date(document.document_date),
            fields=fields,
            warnings=[],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else (str(value) if value else "")


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return _parse_date(value)


def _parse_date(value: Any) -> Optional[date]:
    from app.utils.normalization import normalize_date

    iso = normalize_date(str(value))
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


def _to_document_type(value: str) -> DocumentType:
    """Map a classifier label onto the DocumentType enum, safely."""
    try:
        return DocumentType(value)
    except ValueError:
        return DocumentType.OTHER
