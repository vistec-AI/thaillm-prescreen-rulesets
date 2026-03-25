"""Prescreening constants shared across the SDK.

These values are referenced by the engine, evaluator, and ruleset store.
They mirror conventions encoded in the YAML rulesets under ``v1/``.

Several constants can be overridden via environment variables so that
deployments can adjust medical thresholds without code changes.
"""

from __future__ import annotations

import os
from typing import NamedTuple

# Severity IDs ordered from least to most severe.
# Used to compare severity levels when multiple ER checklist items match.
SEVERITY_ORDER: list[str] = ["sev001", "sev002", "sev002_5", "sev003"]

# Default severity/department for ER critical items (phase 1) and
# ER checklist items (phase 3) that lack explicit overrides.
# Overridable via DEFAULT_ER_SEVERITY / DEFAULT_ER_DEPARTMENT env vars.
DEFAULT_ER_SEVERITY = os.getenv("DEFAULT_ER_SEVERITY", "sev003")
DEFAULT_ER_DEPARTMENT = os.getenv("DEFAULT_ER_DEPARTMENT", "dept002")

# Patients younger than this age use the pediatric ER checklist (phase 3).
# Overridable via PEDIATRIC_AGE_THRESHOLD env var.
PEDIATRIC_AGE_THRESHOLD = int(os.getenv("PEDIATRIC_AGE_THRESHOLD", "15"))

# Human-readable phase names for API responses and logging.
PHASE_NAMES: dict[int, str] = {
    0: "Demographics",
    1: "ER Critical Screen",
    2: "Symptom Selection",
    3: "ER Checklist",
    4: "OLDCARTS",
    5: "Past History",
    6: "Personal History",
    7: "OPD",
}

# Fixed severity for urgency actions in OLDCARTS (always "Visit Urgently").
# Urgency terminates the session immediately with this severity level.
DEFAULT_URGENCY_SEVERITY = "sev002_5"

# Auto-evaluated question types that the engine resolves without user input.
# These are never shown to the patient.
AUTO_EVAL_TYPES: set[str] = {"gender_filter", "age_filter", "conditional"}


# ------------------------------------------------------------------
# LLM provider resolution
# ------------------------------------------------------------------

# OpenRouter base URL — the OpenAI-compatible endpoint that accepts
# provider-prefixed model names (e.g. "openai/gpt-5.4").
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Default model used when OpenRouter is the resolved provider.
# OpenRouter requires the provider prefix (e.g. "openai/") in front of
# the base model name.
OPENROUTER_DEFAULT_MODEL = "openai/gpt-5.4"


class LLMClientConfig(NamedTuple):
    """Resolved configuration for an OpenAI-compatible LLM client.

    Returned by :func:`resolve_llm_config`.  The ``api_key`` and
    ``base_url`` can be passed directly to ``openai.AsyncOpenAI()``.
    """
    api_key: str | None
    base_url: str | None
    model: str       # resolved model name (e.g. "gpt-5.4" or "openai/gpt-5.4")
    provider: str    # "openai" | "openrouter" | "none"


def resolve_llm_config(model: str = "gpt-5.4") -> LLMClientConfig:
    """Resolve which LLM provider to use based on environment variables.

    Priority: ``OPENAI_API_KEY`` > ``OPENROUTER_API_KEY``.

    When ``OPENAI_API_KEY`` is set (even if ``OPENROUTER_API_KEY`` is also
    set), the native OpenAI endpoint is used and the model name is kept
    as-is.  When only ``OPENROUTER_API_KEY`` is present, requests are routed
    through OpenRouter with a provider-prefixed model name
    (``openai/<model>``).

    If neither key is set, returns ``api_key=None`` — the OpenAI SDK will
    raise ``AuthenticationError`` on first call, matching existing behaviour.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return LLMClientConfig(
            api_key=openai_key,
            base_url=None,
            model=model,
            provider="openai",
        )

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        return LLMClientConfig(
            api_key=openrouter_key,
            base_url=OPENROUTER_BASE_URL,
            model=OPENROUTER_DEFAULT_MODEL,
            provider="openrouter",
        )

    return LLMClientConfig(
        api_key=None,
        base_url=None,
        model=model,
        provider="none",
    )
