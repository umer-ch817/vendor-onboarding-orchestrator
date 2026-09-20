"""Guardrail helpers shared by every AI-backed service.

The contract for all AI calls in this system:

    call -> parse JSON -> validate against schema
      -> on validation failure: repair once, feeding the error back
      -> on second failure: raise, so the caller can route to human review

The important property is that *failure is a first-class outcome*. A model
that cannot produce a schema-valid response does not get to half-succeed.
"""
from __future__ import annotations

import json
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.provider import (
    LLMInvalidResponseError,
    LLMProvider,
    LLMResponse,
    LLMUnavailableError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIValidationFailure(RuntimeError):
    """Raised when model output cannot be coerced into the expected schema.

    Carries the raw model output and the validation errors so the caller can
    persist them as evidence for the reviewer.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_output: str = "",
        validation_errors: list[str] | None = None,
        prompt_version: str = "unknown",
    ):
        super().__init__(message)
        self.raw_output = raw_output
        self.validation_errors = validation_errors or []
        self.prompt_version = prompt_version


def _format_errors(exc: ValidationError) -> list[str]:
    """Render Pydantic errors as short, prompt-friendly strings."""
    formatted = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "(root)"
        formatted.append(f"{location}: {err['msg']}")
    return formatted


def _build_repair_prompt(original_user: str, raw_output: str, errors: list[str]) -> str:
    """Construct a repair instruction.

    The failing output and the specific schema violations are fed back. This
    is far more effective than simply retrying, because it converts a blind
    retry into a targeted correction.
    """
    error_block = "\n".join(f"  - {e}" for e in errors)
    return f"""{original_user}

----------------------------------------------------------------------
YOUR PREVIOUS RESPONSE WAS REJECTED BY SCHEMA VALIDATION

Previous response:
{raw_output}

Validation errors:
{error_block}

Return a corrected JSON object that satisfies the schema exactly. Do not
include any text outside the JSON object.
"""


async def call_with_validation(
    provider: LLMProvider,
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    *,
    prompt_version: str = "unknown",
    temperature: float | None = None,
    allow_repair: bool = True,
) -> tuple[T, LLMResponse, bool]:
    """Call the model and return a schema-validated result.

    Returns:
        (validated_model, llm_response, repair_was_used)

    Raises:
        AIValidationFailure: the model could not produce valid output, even
            after one repair attempt.
        LLMUnavailableError: the provider could not be reached.
    """
    response = await provider.complete(
        system_prompt,
        user_prompt,
        temperature=temperature,
        json_mode=True,
        prompt_version=prompt_version,
    )

    payload, raw_error = _try_parse(provider, response.content)
    if raw_error is None:
        validated, errors = _try_validate(schema, payload)
        if validated is not None:
            return validated, response, False
    else:
        errors = [raw_error]

    logger.warning(
        "ai_schema_validation_failed",
        extra={
            "schema": schema.__name__,
            "prompt_version": prompt_version,
            "attempt": 1,
            "errors": errors,
        },
    )

    if not allow_repair:
        raise AIValidationFailure(
            f"Model output failed {schema.__name__} validation",
            raw_output=response.content,
            validation_errors=errors,
            prompt_version=prompt_version,
        )

    # ---- Repair attempt -------------------------------------------------
    repair_prompt = _build_repair_prompt(user_prompt, response.content, errors)
    repair_response = await provider.complete(
        system_prompt,
        repair_prompt,
        temperature=0.0,  # a corrected answer needs no creativity
        json_mode=True,
        prompt_version=prompt_version,
    )

    payload, raw_error = _try_parse(provider, repair_response.content)
    if raw_error is not None:
        raise AIValidationFailure(
            f"Repair attempt did not return parseable JSON for {schema.__name__}",
            raw_output=repair_response.content,
            validation_errors=[raw_error],
            prompt_version=prompt_version,
        )

    validated, errors = _try_validate(schema, payload)
    if validated is None:
        logger.error(
            "ai_schema_validation_failed_after_repair",
            extra={
                "schema": schema.__name__,
                "prompt_version": prompt_version,
                "errors": errors,
            },
        )
        raise AIValidationFailure(
            f"Model output failed {schema.__name__} validation after repair",
            raw_output=repair_response.content,
            validation_errors=errors,
            prompt_version=prompt_version,
        )

    logger.info(
        "ai_schema_repaired",
        extra={"schema": schema.__name__, "prompt_version": prompt_version},
    )
    return validated, repair_response, True


def _try_parse(provider: LLMProvider, content: str) -> tuple[dict[str, Any], str | None]:
    """Parse model output, returning (payload, error_message)."""
    try:
        payload = provider.parse_json(content)
    except LLMInvalidResponseError as exc:
        return {}, str(exc)

    if not isinstance(payload, dict):
        return {}, f"expected a JSON object, received {type(payload).__name__}"
    return payload, None


def _try_validate(
    schema: Type[T], payload: dict[str, Any]
) -> tuple[T | None, list[str]]:
    """Validate payload against schema, returning (model, errors)."""
    try:
        return schema.model_validate(payload), []
    except ValidationError as exc:
        return None, _format_errors(exc)


__all__ = [
    "AIValidationFailure",
    "LLMUnavailableError",
    "call_with_validation",
]
