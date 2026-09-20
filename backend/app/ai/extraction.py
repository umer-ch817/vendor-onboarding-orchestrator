"""AI-backed document extraction service."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.ai.guardrails import AIValidationFailure, call_with_validation
from app.ai.provider import LLMProvider, LLMUnavailableError, get_provider
from app.ai.schemas import (
    AIAnalysisRecord,
    ClassificationResult,
    ExtractionResult,
)
from app.config import settings
from app.utils.logging import get_logger
from prompts import (
    CLASSIFICATION_PROMPT_VERSION,
    CLASSIFICATION_SYSTEM_PROMPT,
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_SYSTEM_PROMPT,
    build_classification_prompt,
    build_extraction_prompt,
)

logger = get_logger(__name__)


@dataclass
class ExtractionOutcome:
    """Result of an extraction attempt, including failure information.

    Failure is represented explicitly rather than by raising, because a
    failed extraction is a normal business event that must produce an
    exception record and route to a human -- not an error that aborts the
    onboarding case.
    """

    success: bool
    result: Optional[ExtractionResult] = None
    analysis: Optional[AIAnalysisRecord] = None
    failure_reason: Optional[str] = None
    validation_errors: list[str] = field(default_factory=list)
    raw_output: str = ""
    requires_human_verification: bool = False
    # Machine-level warnings from the text layer (e.g. "likely a scan") and
    # from the model itself. Kept separate from ``validation_errors``, which
    # means "the output did not conform to the schema".
    extraction_warnings: list[str] = field(default_factory=list)

    @property
    def document_confidence(self) -> float:
        return self.result.document_confidence if self.result else 0.0


class DocumentExtractionService:
    """Extracts structured fields from vendor documents."""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or get_provider()

    async def classify_document(
        self,
        document_text: str,
        filename: str = "",
    ) -> tuple[Optional[ClassificationResult], Optional[AIAnalysisRecord], Optional[str]]:
        """Determine the document type.

        Returns (result, analysis, failure_reason). A None result with a
        non-None failure_reason means the caller should route the document to
        manual classification.
        """
        user_prompt = build_classification_prompt(document_text, filename)

        try:
            result, response, repaired = await call_with_validation(
                self.provider,
                CLASSIFICATION_SYSTEM_PROMPT,
                user_prompt,
                ClassificationResult,
                prompt_version=CLASSIFICATION_PROMPT_VERSION,
                temperature=0.0,
            )
        except AIValidationFailure as exc:
            logger.warning(
                "document_classification_invalid",
                extra={"document_filename": filename, "errors": exc.validation_errors},
            )
            return None, None, "model returned unclassifiable output"
        except LLMUnavailableError as exc:
            logger.error("document_classification_unavailable", extra={"error": str(exc)})
            return None, None, "classification service unavailable"

        analysis = AIAnalysisRecord(
            provider=response.provider,
            model=response.model,
            prompt_version=response.prompt_version,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            repair_attempted=repaired,
        )
        return result, analysis, None

    async def extract_document(
        self,
        document_type: str,
        document_text: str,
        filename: str = "",
    ) -> ExtractionOutcome:
        """Extract structured fields from a document of a known type."""
        user_prompt = build_extraction_prompt(document_type, document_text, filename)

        try:
            result, response, repaired = await call_with_validation(
                self.provider,
                EXTRACTION_SYSTEM_PROMPT,
                user_prompt,
                ExtractionResult,
                prompt_version=EXTRACTION_PROMPT_VERSION,
                temperature=settings.LLM_TEMPERATURE,
            )
        except AIValidationFailure as exc:
            logger.warning(
                "document_extraction_invalid",
                extra={
                    "document_filename": filename,
                    "document_type": document_type,
                    "errors": exc.validation_errors,
                },
            )
            return ExtractionOutcome(
                success=False,
                failure_reason=(
                    "The extraction model returned output that did not conform to the "
                    "expected schema, even after a repair attempt."
                ),
                validation_errors=exc.validation_errors,
                raw_output=exc.raw_output,
                requires_human_verification=True,
            )
        except LLMUnavailableError as exc:
            logger.error(
                "document_extraction_unavailable",
                extra={"document_filename": filename, "error": str(exc)},
            )
            return ExtractionOutcome(
                success=False,
                failure_reason=(
                    "The extraction service was unavailable, so this document could not "
                    "be processed automatically."
                ),
                requires_human_verification=True,
            )

        analysis = AIAnalysisRecord(
            provider=response.provider,
            model=response.model,
            prompt_version=response.prompt_version,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
            attempts=response.attempts,
            repair_attempted=repaired,
        )

        # Confidence-aware routing. Low confidence does not fail the
        # extraction -- the values are still useful to a reviewer -- but it
        # does mark the document as requiring verification.
        low_confidence = result.low_confidence_fields(settings.CONFIDENCE_MEDIUM)
        requires_verification = (
            result.document_confidence < settings.CONFIDENCE_MEDIUM
            or len(low_confidence) > 0
        )

        if requires_verification:
            logger.info(
                "document_extraction_low_confidence",
                extra={
                    "document_filename": filename,
                    "document_confidence": result.document_confidence,
                    "low_confidence_fields": low_confidence,
                },
            )

        return ExtractionOutcome(
            success=True,
            result=result,
            analysis=analysis,
            requires_human_verification=requires_verification,
        )
