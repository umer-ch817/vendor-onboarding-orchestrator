"""Raw text extraction from uploaded documents.

This module does the *mechanical* part of document handling: turn bytes into
text. It makes no judgements. Classification and field extraction happen in
the AI layer, and validation happens in the rules engine.

Supported in the prototype: PDF, plain text, and CSV. Anything else is
recorded as unsupported rather than silently treated as empty, because
"we could not read this" and "this document is blank" lead to very different
follow-up actions for a reviewer.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional


class UnsupportedDocumentError(Exception):
    """Raised when a file type cannot be processed by the prototype."""


class CorruptDocumentError(Exception):
    """Raised when a file claims a type but cannot actually be parsed."""


@dataclass
class ExtractionOutcome:
    """Result of turning a document's bytes into text."""

    text: str
    page_count: Optional[int] = None
    char_count: int = 0
    warnings: list[str] = field(default_factory=list)


# MIME types and extensions the prototype can read.
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/csv",
}

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".csv"}

# A PDF under this many characters of extracted text is almost certainly a
# scan. We do not do OCR in the prototype; we flag it for human transcription
# instead, which is the honest behaviour.
SCANNED_PDF_CHAR_THRESHOLD = 40


def extract_text(
    content: bytes,
    filename: str,
    mime_type: Optional[str] = None,
) -> ExtractionOutcome:
    """Extract text from a document's raw bytes.

    Raises ``UnsupportedDocumentError`` for types we cannot handle and
    ``CorruptDocumentError`` when a file cannot be parsed as its claimed type.
    """
    if not content:
        raise CorruptDocumentError("Document content is empty")

    extension = _extension_of(filename)

    if extension not in SUPPORTED_EXTENSIONS and mime_type not in SUPPORTED_MIME_TYPES:
        raise UnsupportedDocumentError(
            f"Unsupported document type: {extension or mime_type or 'unknown'}"
        )

    if extension == ".pdf" or mime_type == "application/pdf":
        return _extract_pdf(content)

    return _extract_plain_text(content, extension)


def _extension_of(filename: str) -> str:
    lowered = (filename or "").lower()
    dot = lowered.rfind(".")
    return lowered[dot:] if dot != -1 else ""


def _extract_plain_text(content: bytes, extension: str) -> ExtractionOutcome:
    """Decode a text-based document, tolerating imperfect encodings."""
    warnings: list[str] = []

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        # Real-world uploads are rarely clean UTF-8. Decode with replacement
        # rather than failing the whole document over one bad byte.
        text = content.decode("utf-8", errors="replace")
        warnings.append("Document was not valid UTF-8; some characters were replaced")

    stripped = text.strip()
    if extension == ".csv" and not stripped:
        warnings.append("CSV file contains no rows")

    return ExtractionOutcome(
        text=stripped,
        page_count=None,
        char_count=len(stripped),
        warnings=warnings,
    )


def _extract_pdf(content: bytes) -> ExtractionOutcome:
    """Extract text from a PDF, detecting scans we cannot read."""
    warnings: list[str] = []

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise UnsupportedDocumentError(
            "PDF support requires the 'pypdf' package"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            # An encrypted PDF that opens with an empty password is common.
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise CorruptDocumentError(
                    "PDF is password-protected and cannot be read"
                ) from exc

        pages: list[str] = []
        for index, page in enumerate(reader.pages):
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Page {index + 1} could not be read: {exc}")

        text = "\n".join(pages).strip()
        page_count = len(reader.pages)

    except CorruptDocumentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CorruptDocumentError(f"PDF could not be parsed: {exc}") from exc

    if len(text) < SCANNED_PDF_CHAR_THRESHOLD:
        warnings.append(
            "Little or no text layer found; this is likely a scanned document "
            "and will need human transcription"
        )

    return ExtractionOutcome(
        text=text,
        page_count=page_count,
        char_count=len(text),
        warnings=warnings,
    )
