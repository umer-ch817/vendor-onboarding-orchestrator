"""Versioned prompt templates.

Prompts live in dedicated modules rather than being buried inside workflow
nodes or service functions for three reasons:

1. **Reviewability** -- a prompt change is a behaviour change and should be
   reviewable on its own terms.
2. **Versioning** -- every prompt carries a version identifier that is
   persisted alongside the AI decision, so a six-month-old decision can be
   explained in terms of the prompt that produced it.
3. **Provider neutrality** -- the prompt text is a plain constant, so it can
   be sent to any provider implementing the LLMProvider interface.
"""
from prompts.document_extraction import (
    PROMPT_VERSION as EXTRACTION_PROMPT_VERSION,
    SYSTEM_PROMPT as EXTRACTION_SYSTEM_PROMPT,
    build_extraction_prompt,
)
from prompts.document_classification import (
    PROMPT_VERSION as CLASSIFICATION_PROMPT_VERSION,
    SYSTEM_PROMPT as CLASSIFICATION_SYSTEM_PROMPT,
    build_classification_prompt,
)
from prompts.risk_analysis import (
    PROMPT_VERSION as RISK_PROMPT_VERSION,
    SYSTEM_PROMPT as RISK_SYSTEM_PROMPT,
    build_risk_prompt,
)
from prompts.exception_analysis import (
    PROMPT_VERSION as EXCEPTION_PROMPT_VERSION,
    SYSTEM_PROMPT as EXCEPTION_SYSTEM_PROMPT,
    build_exception_prompt,
)

__all__ = [
    "EXTRACTION_PROMPT_VERSION",
    "EXTRACTION_SYSTEM_PROMPT",
    "build_extraction_prompt",
    "CLASSIFICATION_PROMPT_VERSION",
    "CLASSIFICATION_SYSTEM_PROMPT",
    "build_classification_prompt",
    "RISK_PROMPT_VERSION",
    "RISK_SYSTEM_PROMPT",
    "build_risk_prompt",
    "EXCEPTION_PROMPT_VERSION",
    "EXCEPTION_SYSTEM_PROMPT",
    "build_exception_prompt",
]
