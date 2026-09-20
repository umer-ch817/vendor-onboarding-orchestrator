"""LLM provider abstraction.

The application never imports a vendor SDK directly. Every model call goes
through :class:`LLMProvider`. That gives three things:

1. **Provider neutrality** -- swapping OpenAI for Anthropic, a local model, or
   an internal gateway is a one-file change.
2. **Testability** -- the mock provider makes the entire pipeline runnable
   with no API key, which is what the demo depends on.
3. **Observability** -- token usage, latency, and prompt versions are captured
   uniformly rather than being re-implemented per call site.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class LLMResponse(BaseModel):
    """Normalised response from any provider."""

    content: str
    model: str
    prompt_version: str = "unknown"
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: int = 0
    attempts: int = 1
    provider: str = "unknown"


class LLMUnavailableError(RuntimeError):
    """Raised when the provider cannot be reached after all retries."""


class LLMInvalidResponseError(RuntimeError):
    """Raised when the provider returns content that cannot be parsed as JSON."""


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    name: str = "abstract"

    def __init__(self, max_retries: int | None = None):
        self.max_retries = (
            max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
        )

    @abstractmethod
    async def _call(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        json_mode: bool,
        prompt_version: str,
    ) -> LLMResponse:
        """Provider-specific single call. Implementations must not retry."""

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        json_mode: bool = True,
        prompt_version: str = "unknown",
    ) -> LLMResponse:
        """Call the provider with exponential backoff on transient failures.

        Retries transient errors only. A malformed response is *not* retried
        here -- the caller handles repair, because the caller knows the
        expected schema and can feed the validation error back to the model.
        """
        temperature = (
            temperature if temperature is not None else settings.LLM_TEMPERATURE
        )
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            started = time.monotonic()
            try:
                response = await self._call(
                    system,
                    user,
                    temperature=temperature,
                    json_mode=json_mode,
                    prompt_version=prompt_version,
                )
                response.prompt_version = prompt_version
                response.attempts = attempt
                response.latency_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "llm_call_succeeded",
                    extra={
                        "provider": self.name,
                        "model": response.model,
                        "prompt_version": prompt_version,
                        "attempt": attempt,
                        "latency_ms": response.latency_ms,
                    },
                )
                return response

            except Exception as exc:  # noqa: BLE001 - we re-raise below
                last_error = exc
                logger.warning(
                    "llm_call_failed",
                    extra={
                        "provider": self.name,
                        "attempt": attempt,
                        "max_retries": self.max_retries,
                        "error": str(exc),
                    },
                )
                if attempt < self.max_retries:
                    # 1s, 2s, 4s ... with jitter to avoid thundering herds.
                    backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(backoff)

        raise LLMUnavailableError(
            f"{self.name} unavailable after {self.max_retries} attempts: {last_error}"
        )

    @staticmethod
    def parse_json(content: str) -> dict[str, Any]:
        """Extract a JSON object from model output.

        Models wrap JSON in markdown fences, prefix it with prose, or trail a
        closing remark. Rather than trusting the model to obey "return only
        JSON", we defensively locate the outermost object.
        """
        if content is None:
            raise LLMInvalidResponseError("empty response")

        text = str(content).strip()

        # Strip markdown fences.
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fall back to locating the outermost balanced object.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMInvalidResponseError(
                f"no JSON object found in response: {text[:200]!r}"
            )

        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMInvalidResponseError(
                f"response was not valid JSON: {exc.msg} at position {exc.pos}"
            ) from exc


class OpenAIProvider(LLMProvider):
    """OpenAI-backed provider."""

    name = "openai"

    def __init__(self, api_key: str, model: str | None = None, **kwargs):
        super().__init__(**kwargs)
        if not api_key:
            raise ValueError("OpenAIProvider requires an API key")
        self.api_key = api_key
        self.model = model or settings.OPENAI_MODEL
        self._client = None

    @property
    def client(self):
        """Lazily construct the SDK client so import never fails."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        return self._client

    async def _call(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        json_mode: bool,
        prompt_version: str,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        completion = await self.client.chat.completions.create(**kwargs)
        choice = completion.choices[0]

        return LLMResponse(
            content=choice.message.content or "",
            model=completion.model,
            provider=self.name,
            prompt_tokens=getattr(completion.usage, "prompt_tokens", None),
            completion_tokens=getattr(completion.usage, "completion_tokens", None),
        )


class MockProvider(LLMProvider):
    """Deterministic offline provider.

    This is not a stub that returns canned strings. It implements enough
    document understanding to exercise the full pipeline -- extraction,
    classification, risk analysis, exception triage -- using regex parsing of
    the structured demo documents in ``documents/demo``.

    It exists so that ``docker compose up`` produces a working, demonstrable
    system with no API key and no network access, and so the test suite can
    assert on pipeline behaviour deterministically.
    """

    name = "mock"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # A fixed seed keeps the mock reproducible across runs, which matters
        # because the evaluation harness asserts on its output.
        self._rng = random.Random(1337)

    async def _call(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        json_mode: bool,
        prompt_version: str,
    ) -> LLMResponse:
        # Simulate realistic latency so timing code is exercised.
        await asyncio.sleep(self._rng.uniform(0.05, 0.15))

        if "document extraction engine" in system:
            payload = self._mock_extraction(user)
        elif "classify vendor onboarding documents" in system:
            payload = self._mock_classification(user)
        elif "vendor risk analyst" in system:
            payload = self._mock_risk_analysis(user)
        elif "triage vendor onboarding exceptions" in system:
            payload = self._mock_exception_triage(user)
        else:
            payload = {"error": "unrecognised prompt type"}

        return LLMResponse(
            content=json.dumps(payload, indent=2),
            model="mock-deterministic-v1",
            provider=self.name,
            prompt_tokens=len(user) // 4,
            completion_tokens=len(json.dumps(payload)) // 4,
        )

    # -- Mock implementations ------------------------------------------------

    @staticmethod
    def _extract_field(text: str, *labels: str) -> tuple[Optional[str], float]:
        """Find ``Label: value`` in the document text.

        Returns (value, confidence). Confidence is high when a label matched
        cleanly, lower when we fell back to a looser pattern, and 0.0 when
        nothing was found -- mirroring how a real model behaves.
        """
        for label in labels:
            pattern = rf"{re.escape(label)}\s*[:\-]\s*(.+)"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip().split("\n")[0].strip()
                value = value.strip("|").strip()
                if value and value.lower() not in {"", "n/a", "none", "[illegible]"}:
                    # An illegible marker means the model should be unsure.
                    if "illegible" in value.lower() or "obscured" in value.lower():
                        return None, 0.0
                    return value, 0.96
        return None, 0.0

    def _mock_extraction(self, user: str) -> dict[str, Any]:
        # Recover the document type and text from the prompt we built.
        type_match = re.search(r"DOCUMENT TYPE:\s*(\S+)", user)
        document_type = type_match.group(1) if type_match else "other"

        text_match = re.search(r"DOCUMENT TEXT\s*-+\s*(.+)", user, re.DOTALL)
        body = text_match.group(1) if text_match else user

        field_map = {
            "w9": [
                ("legal_name", ["Legal Name", "Name of entity"]),
                ("business_name", ["Business Name", "Disregarded Entity"]),
                ("tax_classification", ["Tax Classification", "Federal Tax Classification"]),
                ("address", ["Address", "Street Address"]),
                ("city_state_zip", ["City, State, ZIP", "City State Zip"]),
                ("tin", ["TIN", "Taxpayer Identification Number"]),
            ],
            "certificate_of_insurance": [
                ("insured_name", ["Named Insured", "Insured"]),
                ("policy_number", ["Policy Number", "Policy No"]),
                ("coverage_type", ["Coverage", "Type of Coverage"]),
                ("coverage_amount", ["Limit", "Coverage Amount", "Each Occurrence"]),
                ("effective_date", ["Effective Date", "Policy Effective"]),
                ("expiration_date", ["Expiration Date", "Policy Expiration", "Expires"]),
                ("insurer_name", ["Insurer", "Insurance Company", "Carrier"]),
            ],
            "business_registration": [
                ("legal_name", ["Registered Name", "Entity Name", "Legal Name"]),
                ("registration_number", ["File Number", "Registration Number", "Entity Number"]),
                ("jurisdiction", ["Jurisdiction", "State of Formation"]),
                ("registration_date", ["Formation Date", "Registration Date"]),
                ("active_status", ["Status", "Entity Status"]),
                ("entity_type", ["Entity Type", "Type"]),
            ],
            "banking_confirmation": [
                ("account_holder", ["Account Holder", "Account Name"]),
                ("bank_name", ["Bank Name", "Financial Institution"]),
                ("account_type", ["Account Type"]),
                ("account_identifier", ["Account Number", "Account No"]),
                ("routing_identifier", ["Routing Number", "ABA"]),
            ],
            "supplier_questionnaire": [
                ("company_name", ["Company Name"]),
                ("ownership_structure", ["Ownership Structure"]),
                ("beneficial_owners", ["Beneficial Owners", "Owners"]),
                ("years_in_business", ["Years in Business"]),
                ("payment_terms", ["Payment Terms"]),
                ("conflict_of_interest", ["Conflict of Interest"]),
            ],
            "master_services_agreement": [
                ("party_a", ["Party A", "Client"]),
                ("party_b", ["Party B", "Supplier", "Vendor"]),
                ("effective_date", ["Effective Date"]),
                ("term_months", ["Term", "Term Length"]),
                ("payment_terms", ["Payment Terms"]),
                ("termination_notice_days", ["Termination Notice", "Notice Period"]),
                ("governing_law", ["Governing Law"]),
            ],
        }

        specs = field_map.get(document_type, [("legal_name", ["Name"]), ("document_date", ["Date"])])

        fields: dict[str, Any] = {}
        for field_name, labels in specs:
            value, confidence = self._extract_field(body, *labels)
            fields[field_name] = {
                "value": value,
                "confidence": confidence,
                "source_location": f"label match: {labels[0]}" if value else "not found",
            }

        # Derive tin_present for W-9 when the TIN line existed at all.
        if document_type == "w9":
            tin_value = fields.get("tin", {}).get("value")
            fields["tin_present"] = {
                "value": bool(tin_value),
                "confidence": 0.95 if tin_value else 0.85,
                "source_location": "derived",
            }

        present = [f for f in fields.values() if f["value"] is not None]
        document_confidence = round(
            sum(f["confidence"] for f in present) / len(present), 2
        ) if present else 0.0

        warnings: list[str] = []
        if "document text truncated" in user:
            warnings.append("document text truncated")
        if document_confidence < 0.7:
            warnings.append("low overall extraction confidence")

        return {
            "document_type": document_type,
            "fields": fields,
            "document_confidence": document_confidence,
            "warnings": warnings,
        }

    def _mock_classification(self, user: str) -> dict[str, Any]:
        body = user.lower()
        signatures = [
            ("w9", ["form w-9", "request for taxpayer identification"]),
            ("certificate_of_insurance", ["certificate of insurance", "acord"]),
            ("business_registration", ["certificate of formation", "articles of incorporation", "business registration"]),
            ("banking_confirmation", ["bank confirmation", "ach", "voided check", "account holder"]),
            ("supplier_questionnaire", ["supplier questionnaire", "vendor questionnaire"]),
            ("master_services_agreement", ["master services agreement", "services agreement"]),
        ]
        for doc_type, markers in signatures:
            for marker in markers:
                if marker in body:
                    return {
                        "document_type": doc_type,
                        "confidence": 0.94,
                        "reasoning": f"Matched distinctive header text: {marker!r}.",
                        "detected_identifiers": [marker],
                    }
        return {
            "document_type": "other",
            "confidence": 0.30,
            "reasoning": "No recognised document header found in the text.",
            "detected_identifiers": [],
        }

    def _mock_risk_analysis(self, user: str) -> dict[str, Any]:
        """Derive signals from the evidence block we constructed.

        Only emits signals it can point at in the supplied text, matching the
        contract the real prompt enforces.
        """
        signals: list[dict[str, Any]] = []
        lowered = user.lower()

        if "not present" in lowered and "expiration_date" in lowered:
            signals.append({
                "type": "INSURANCE_EXPIRY_UNKNOWN",
                "severity": "medium",
                "description": "An insurance document is on file but its expiration date could not be determined.",
                "evidence": "certificate_of_insurance: expiration_date not present",
                "confidence": 0.88,
            })

        if "payment terms: 120" in lowered or "net 120" in lowered:
            signals.append({
                "type": "UNUSUAL_PAYMENT_TERMS",
                "severity": "medium",
                "description": "Requested payment terms of 120 days are materially longer than the standard 30-day terms.",
                "evidence": "Payment terms of net 120 stated in supplier documentation.",
                "confidence": 0.91,
            })

        if "beneficial owners: (not present)" in lowered or "ownership structure: (not present)" in lowered:
            signals.append({
                "type": "INCOMPLETE_OWNERSHIP_INFORMATION",
                "severity": "medium",
                "description": "No beneficial ownership information was disclosed for this entity.",
                "evidence": "supplier_questionnaire: beneficial_owners not present",
                "confidence": 0.85,
            })

        has_evidence = any(s["type"] for s in signals)
        if not signals:
            summary = (
                "The supplied documents are mutually consistent and no evidence-backed risk "
                "signal was identified. Outstanding items, if any, are handled by the "
                "deterministic requirement checks."
            )
            action = "AUTO_APPROVE"
            confidence = 0.90
        else:
            summary = (
                f"{len(signals)} evidence-backed concern(s) were identified in the vendor "
                "documentation. Each is listed with the document it derives from. A human "
                "reviewer should confirm the commercial context before approval."
            )
            action = "HUMAN_REVIEW"
            confidence = 0.86

        return {
            "risk_signals": signals,
            "summary": summary,
            "missing_context": [],
            "recommended_action": action,
            "confidence": confidence,
        }

    def _mock_exception_triage(self, user: str) -> dict[str, Any]:
        exc_type_match = re.search(r"type:\s*(\S+)", user)
        exc_type = exc_type_match.group(1) if exc_type_match else "UNKNOWN"

        catalogue = {
            "DOCUMENT_MISSING": (
                "A required document was never supplied, so the requirement cannot be evaluated.",
                [
                    ("REQUEST_INFORMATION", "Ask the vendor to supply the missing document.", True),
                    ("RESOLVE", "Resolve manually if the document exists outside the system.", False),
                    ("ESCALATE", "Escalate if the vendor is unresponsive.", False),
                ],
                "high",
            ),
            "DOCUMENT_EXPIRED": (
                "The document on file has passed its expiration date and no longer evidences current coverage.",
                [
                    ("REQUEST_INFORMATION", "Request an updated document from the vendor.", True),
                    ("OVERRIDE", "Override only with documented compliance sign-off.", False),
                    ("ESCALATE", "Escalate if coverage has actually lapsed.", False),
                ],
                "high",
            ),
            "ENTITY_NAME_MISMATCH": (
                "Two documents give materially different legal names, which can indicate a wrong "
                "entity, a trading name used as a legal name, or a documentation error.",
                [
                    ("REQUEST_INFORMATION", "Confirm the correct legal entity with the vendor.", True),
                    ("RESOLVE", "Resolve if one name is a documented trade name.", False),
                    ("ESCALATE", "Escalate if the discrepancy suggests a different legal entity.", False),
                ],
                "high",
            ),
            "BANKING_NAME_MISMATCH": (
                "The bank account holder does not match the vendor's legal name, which is a common "
                "vector for payment redirection fraud.",
                [
                    ("ESCALATE", "Escalate to finance before any payment is configured.", True),
                    ("REQUEST_INFORMATION", "Request bank documentation confirming account ownership.", False),
                    ("OVERRIDE", "Override only with dual authorisation.", False),
                ],
                "high",
            ),
            "LOW_CONFIDENCE_EXTRACTION": (
                "The system could not read one or more fields with sufficient confidence to act on them.",
                [
                    ("RESOLVE", "Verify and correct the field values manually, then re-run validation.", True),
                    ("REQUEST_INFORMATION", "Ask the vendor for a clearer copy of the document.", False),
                ],
                "medium",
            ),
            "INSURANCE_BELOW_MINIMUM": (
                "Stated coverage is below the minimum required for this vendor category.",
                [
                    ("REQUEST_INFORMATION", "Request a certificate evidencing compliant coverage limits.", True),
                    ("ESCALATE", "Escalate if the vendor cannot meet the requirement.", False),
                ],
                "high",
            ),
        }

        root_cause, options, urgency = catalogue.get(
            exc_type,
            (
                "The deterministic rule engine raised this exception; the underlying facts are "
                "as described in the exception record.",
                [
                    ("RESOLVE", "Resolve after confirming the facts.", True),
                    ("ESCALATE", "Escalate if resolution is outside your authority.", False),
                ],
                "medium",
            ),
        )

        vendor_message = None
        if any(opt[0] == "REQUEST_INFORMATION" and opt[2] for opt in options):
            vendor_message = (
                "Hello,\n\n"
                "As part of completing your vendor onboarding, we need one item clarified "
                "before we can proceed. Please review the outstanding point below and reply "
                "with the requested documentation at your earliest convenience.\n\n"
                "If anything is unclear, reply to this message and we will assist.\n\n"
                "Thank you,\nProcurement Operations"
            )

        return {
            "likely_root_cause": root_cause,
            "resolution_options": [
                {
                    "action": action,
                    "description": description,
                    "recommended": recommended,
                    "rationale": "Ranked by how directly it addresses the root cause.",
                }
                for action, description, recommended in options
            ],
            "vendor_message_draft": vendor_message,
            "reviewer_notes": (
                "Confirm the evidence below matches the vendor you intend to onboard before "
                "taking action."
            ),
            "urgency": urgency,
        }


def get_provider(provider_name: str | None = None) -> LLMProvider:
    """Construct the configured provider.

    Falls back to the mock provider whenever a networked provider is
    requested without credentials, so the application degrades to a working
    demo rather than crashing at startup.
    """
    name = (provider_name or settings.LLM_PROVIDER or "mock").lower()

    if name == "openai":
        if not settings.OPENAI_API_KEY:
            logger.warning(
                "llm_provider_fallback",
                extra={
                    "requested": "openai",
                    "using": "mock",
                    "reason": "OPENAI_API_KEY is not set",
                },
            )
            return MockProvider()
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
        )

    if name == "mock":
        return MockProvider()

    logger.warning(
        "llm_provider_unknown",
        extra={"requested": name, "using": "mock"},
    )
    return MockProvider()
