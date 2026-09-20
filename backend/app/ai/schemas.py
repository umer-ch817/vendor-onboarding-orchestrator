"""Pydantic schemas for validating model output.

Every AI response is parsed into one of these models before it is allowed to
affect system state. This is the single most important guardrail in the
system: a model that returns prose, hallucinates an extra field, or emits a
confidence of 7.3 is stopped here rather than corrupting a downstream
decision.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Severity = Literal["low", "medium", "high", "critical"]
RecommendedAction = Literal[
    "AUTO_APPROVE", "HUMAN_REVIEW", "REQUEST_INFORMATION", "ESCALATE"
]


class StrictModel(BaseModel):
    """Base model that rejects unknown fields.

    Rejecting extra keys is deliberate. If a model invents a field, we want
    to know about it rather than silently discarding it, because it usually
    means the prompt and the schema have drifted apart.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Document classification
# ---------------------------------------------------------------------------

class ClassificationResult(StrictModel):
    document_type: Literal[
        "w9",
        "certificate_of_insurance",
        "business_registration",
        "banking_confirmation",
        "supplier_questionnaire",
        "master_services_agreement",
        "voided_check",
        "tax_certificate",
        "other",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=1000)
    detected_identifiers: list[str] = Field(default_factory=list, max_length=20)


# ---------------------------------------------------------------------------
# Document extraction
# ---------------------------------------------------------------------------

class ExtractedFieldValue(StrictModel):
    """A single extracted field.

    ``value`` is intentionally permissive (str | bool | None) because some
    fields are naturally boolean -- ``tin_present`` -- while most are strings.
    Numbers and dates stay as strings so that normalization, not the model,
    owns canonicalisation.
    """

    value: Optional[str | bool | float | int] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_location: str = Field(default="", max_length=255)

    @field_validator("value", mode="before")
    @classmethod
    def coerce_blank_to_none(cls, v: Any) -> Any:
        """Treat empty strings and common null-ish tokens as absent."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped == "" or stripped.lower() in {
                "n/a", "na", "none", "null", "unknown", "-", "--"
            }:
                return None
        return v


class ExtractionResult(StrictModel):
    document_type: str
    fields: dict[str, ExtractedFieldValue] = Field(default_factory=dict)
    document_confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def check_confidence_consistency(self) -> "ExtractionResult":
        """Reconcile the headline confidence with the per-field evidence.

        A model sometimes reports 0.99 overall while every individual field
        is null. That is incoherent, and rather than rejecting the whole
        extraction we clamp the headline figure down to what the fields
        actually support. Silent inflation of confidence is exactly the
        failure mode that would defeat the confidence thresholds downstream.
        """
        if not self.fields:
            return self

        present = [f for f in self.fields.values() if f.value is not None]
        if not present:
            # Nothing was extracted; the headline cannot exceed the
            # per-field confidence we did report.
            ceiling = max((f.confidence for f in self.fields.values()), default=0.0)
            if self.document_confidence > ceiling:
                self.document_confidence = round(min(self.document_confidence, ceiling), 4)
            if not self.warnings:
                self.warnings.append("no fields could be extracted from this document")
            return self

        mean_present = sum(f.confidence for f in present) / len(present)
        if self.document_confidence > mean_present + 0.05:
            self.document_confidence = round(mean_present, 4)

        return self

    def field_values(self) -> dict[str, Any]:
        """Flatten to ``{field_name: raw_value}``."""
        return {name: f.value for name, f in self.fields.items()}

    def field_confidences(self) -> dict[str, float]:
        return {name: f.confidence for name, f in self.fields.items()}

    def low_confidence_fields(self, threshold: float) -> list[str]:
        """Names of fields whose confidence falls below ``threshold``.

        Fields that are legitimately absent (value is None with 0.0
        confidence) are excluded -- an absent field is a requirement problem,
        not an extraction-confidence problem, and conflating the two would
        generate noisy exceptions.
        """
        return [
            name
            for name, field in self.fields.items()
            if field.value is not None and field.confidence < threshold
        ]


# ---------------------------------------------------------------------------
# Risk analysis
# ---------------------------------------------------------------------------

class RiskSignalCandidate(StrictModel):
    """A risk signal proposed by the model.

    These are *candidates*. The rules layer decides whether a candidate is
    promoted to a persisted risk signal.
    """

    type: str = Field(min_length=3, max_length=60)
    severity: Severity
    description: str = Field(min_length=10, max_length=2000)
    evidence: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("type")
    @classmethod
    def normalise_type(cls, v: str) -> str:
        """Force signal types into a stable SCREAMING_SNAKE_CASE form."""
        cleaned = v.strip().upper().replace(" ", "_").replace("-", "_")
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
        return cleaned


class RiskAnalysisResult(StrictModel):
    risk_signals: list[RiskSignalCandidate] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=4000)
    missing_context: list[str] = Field(default_factory=list, max_length=20)
    recommended_action: RecommendedAction
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_evidence_for_signals(self) -> "RiskAnalysisResult":
        """Drop signals that carry no usable evidence.

        The prompt already forbids unsupported claims, but prompts are
        advisory. This enforces it: a signal with a trivial evidence string
        is discarded rather than shown to a reviewer as if it were grounded.
        """
        self.risk_signals = [
            s for s in self.risk_signals if len(s.evidence.strip()) >= 8
        ]
        return self


# ---------------------------------------------------------------------------
# Exception triage
# ---------------------------------------------------------------------------

class ResolutionOption(StrictModel):
    action: Literal["RESOLVE", "REQUEST_INFORMATION", "ESCALATE", "OVERRIDE"]
    description: str = Field(min_length=5, max_length=1000)
    recommended: bool = False
    rationale: str = Field(default="", max_length=1000)


class ExceptionTriageResult(StrictModel):
    likely_root_cause: str = Field(min_length=5, max_length=2000)
    resolution_options: list[ResolutionOption] = Field(default_factory=list, max_length=6)
    vendor_message_draft: Optional[str] = Field(default=None, max_length=4000)
    reviewer_notes: str = Field(default="", max_length=2000)
    urgency: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def ensure_at_least_one_option(self) -> "ExceptionTriageResult":
        """Guarantee the reviewer always has a path forward.

        If the model returned no usable options we synthesise the safest
        default rather than presenting an empty action list.
        """
        if not self.resolution_options:
            self.resolution_options = [
                ResolutionOption(
                    action="ESCALATE",
                    description="Escalate to a reviewer for manual determination.",
                    recommended=True,
                    rationale="The triage model did not propose a specific resolution.",
                )
            ]
        return self


# ---------------------------------------------------------------------------
# Analysis envelope
# ---------------------------------------------------------------------------

class AIAnalysisRecord(BaseModel):
    """Metadata captured for every AI interaction, for audit purposes.

    Deliberately records *what the model concluded and how confident it was*,
    not hidden chain-of-thought. Audit needs to explain a decision; it does
    not need to reconstruct the model's internal reasoning.
    """

    provider: str
    model: str
    prompt_version: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: int = 0
    attempts: int = 1
    repair_attempted: bool = False
    validation_errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
