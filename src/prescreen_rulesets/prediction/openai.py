"""OpenAIPredictionModule — concrete PredictionModule using OpenAI API.

Uses ``openai.AsyncOpenAI`` with structured output (``json_schema``
response format) to guarantee predictions stay within the valid
disease/department/severity domains.

Transient errors (rate limit, timeout, connection) degrade gracefully by
returning an empty ``PredictionResult``.  Permanent errors (auth, invalid
model) are re-raised so callers can fix their configuration.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import openai

from prescreen_rulesets.constants import SEVERITY_ORDER
from prescreen_rulesets.interfaces import PredictionModule
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.prediction.prompt_manager import PredictionPromptManager
from prescreen_rulesets.ruleset import RulesetStore

logger = logging.getLogger(__name__)


class OpenAIPredictionModule(PredictionModule):
    """LLM-backed prediction module using the OpenAI chat completions API
    with structured output for guaranteed-valid predictions.

    Args:
        store: ``RulesetStore`` — provides disease, department, and severity
            ID enumerations for the JSON schema and reference tables.
        api_key: API key.  When ``None``, resolved from environment variables:
            ``OPENAI_API_KEY`` first, then ``OPENROUTER_API_KEY`` as fallback.
        base_url: Base URL override for OpenAI-compatible endpoints.
            Auto-set when falling back to OpenRouter.
        model: Model identifier for chat completions.
        temperature: Sampling temperature.  ``None`` omits the parameter.
        max_tokens: Max tokens in the response.  ``None`` omits the parameter.
        max_diagnoses: Hard cap on the number of returned diagnoses (default 10).
    """

    def __init__(
        self,
        *,
        store: RulesetStore,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-5.4",
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_diagnoses: int = 10,
    ) -> None:
        # When no explicit api_key is provided, resolve the provider from
        # environment variables.  Priority: OPENAI_API_KEY > OPENROUTER_API_KEY.
        # OpenRouter requires a base_url override and a provider-prefixed model.
        if api_key is None and base_url is None:
            from prescreen_rulesets.constants import resolve_llm_config
            config = resolve_llm_config(model)
            api_key = config.api_key
            base_url = config.base_url
            model = config.model
            if config.provider != "none":
                logger.info("PredictionModule using %s provider", config.provider)

        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_diagnoses = max_diagnoses
        self._store = store
        self._prompt_manager = PredictionPromptManager(store)

        # Pre-build the structured output response format from the store's
        # disease/department/severity IDs.
        self._response_format = self._build_response_format()

        # Context set by the pipeline before calling predict()
        self._min_severity: str | None = None
        self._er_override: bool = False

    def set_context(
        self,
        *,
        min_severity: str | None = None,
        er_override: bool = False,
    ) -> None:
        """Set rule-based context for the next ``predict()`` call.

        Args:
            min_severity: rule-based severity ID — prediction must be at
                least this severe.
            er_override: if True, ER (sev003 + dept002) is forced regardless
                of the LLM's prediction.
        """
        self._min_severity = min_severity
        self._er_override = er_override

    _MIN_DIAGNOSES_REPROMPT = (
        "Your response contained fewer than 3 differential diagnoses. "
        "You MUST predict at least 3 diseases to ensure sufficient "
        "differential coverage for safe clinical triage. "
        "Please re-evaluate the patient history and provide your "
        "prediction again with at least 3 diagnoses."
    )

    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        """Run prediction on the combined Q&A history.

        Filters QA pairs, renders prompts, calls the OpenAI API with
        structured output, and parses/validates the response.

        If the LLM returns fewer than 3 diagnoses, it is re-prompted once
        with an additional message turn requesting at least 3.  If the
        retry still returns fewer than 3, the result is accepted as-is
        (the LLM genuinely could not produce more).

        Returns an empty ``PredictionResult`` on transient API errors
        so the pipeline can continue without predictions.
        """
        # Capture and reset context early so it's cleared regardless of
        # which code path returns (transient error, re-prompt, etc.).
        er_override = self._er_override
        min_severity = self._min_severity
        self._er_override = False
        self._min_severity = None

        filtered = self._filter_qa_pairs(qa_pairs)

        system_prompt = self._prompt_manager.render_system()
        user_prompt = self._prompt_manager.render_prompt(
            filtered, min_severity=min_severity,
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        content = await self._call_api(messages)
        if content is None:
            return PredictionResult()

        result = self._parse_response(content)

        # Re-prompt once if fewer than 3 diagnoses — the LLM may have
        # been overly conservative and can usually produce more when asked.
        if len(result.diagnoses) < 3:
            logger.info(
                "Prediction returned %d diagnoses (< 3), re-prompting",
                len(result.diagnoses),
            )
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {"role": "user", "content": self._MIN_DIAGNOSES_REPROMPT},
            )
            retry_content = await self._call_api(messages)
            if retry_content is not None:
                result = self._parse_response(retry_content)

        return self._apply_safety_constraints(
            result, er_override=er_override, min_severity=min_severity,
        )

    async def _call_api(
        self, messages: list[dict[str, str]],
    ) -> str | None:
        """Call the OpenAI chat completions API.

        Returns the response content string, or ``None`` on transient errors.
        Permanent errors are re-raised.
        """
        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "response_format": self._response_format,
            }
            if self._temperature is not None:
                kwargs["temperature"] = self._temperature
            if self._max_tokens is not None:
                kwargs["max_tokens"] = self._max_tokens

            response = await self._client.chat.completions.create(**kwargs)
        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
        ) as exc:
            logger.warning(
                "OpenAI transient error during prediction: %s", exc,
            )
            return None

        return response.choices[0].message.content or ""

    def _filter_qa_pairs(self, qa_pairs: list[QAPair]) -> list[QAPair]:
        """Filter QA pairs before sending to the LLM.

        Phase 3 (ER Checklist) entries where ``answer is False`` are removed
        because only positive findings are diagnostically relevant.
        """
        filtered: list[QAPair] = []
        for pair in qa_pairs:
            if pair.phase == 3 and pair.answer is False:
                continue
            filtered.append(pair)
        return filtered

    def _build_response_format(self) -> dict:
        """Build the structured output JSON schema with enums constraining
        disease IDs, department IDs, and severity IDs.

        Returns a dict suitable for the ``response_format`` parameter of the
        OpenAI chat completions API.
        """
        disease_ids = self._store.get_disease_ids()
        department_ids = self._store.get_department_ids()
        severity_ids = self._store.get_severity_ids()

        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "prediction_result",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "diagnoses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "disease_id": {
                                        "type": "string",
                                        "enum": disease_ids,
                                    },
                                },
                                "required": ["disease_id"],
                                "additionalProperties": False,
                            },
                        },
                        "departments": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": department_ids,
                            },
                        },
                        "severity": {
                            "type": "string",
                            "enum": severity_ids,
                        },
                        "reasoning": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "diagnoses",
                        "departments",
                        "severity",
                        "reasoning",
                    ],
                    "additionalProperties": False,
                },
            },
        }
        return schema

    def _parse_response(self, content: str) -> PredictionResult:
        """Parse the structured JSON response into a ``PredictionResult``.

        Extracts diagnoses (capped at ``max_diagnoses``), departments, and
        severity.  Does NOT apply safety constraints (ER override, min
        severity) — those are applied separately by ``_apply_safety_constraints``.
        """
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse prediction response as JSON")
            return PredictionResult()

        # Extract and cap diagnoses at max_diagnoses
        raw_diagnoses = data.get("diagnoses", [])
        diagnoses = [
            DiagnosisResult(disease_id=d["disease_id"])
            for d in raw_diagnoses
            if isinstance(d, dict) and "disease_id" in d
        ][: self._max_diagnoses]

        departments = data.get("departments", [])
        severity = data.get("severity")

        # Log reasoning for debugging but don't include in the result
        reasoning = data.get("reasoning", "")
        if reasoning:
            logger.debug("Prediction reasoning: %s", reasoning)

        return PredictionResult(
            diagnoses=diagnoses,
            departments=departments,
            severity=severity,
        )

    def _apply_safety_constraints(
        self,
        result: PredictionResult,
        *,
        er_override: bool,
        min_severity: str | None,
    ) -> PredictionResult:
        """Apply post-prediction safety constraints.

        Enforcements:
          1. ER override — if set, force sev003 + dept002.
          2. Min severity — if set, ensure the predicted severity is at
             least as severe as the rule-based floor.
        """
        departments = list(result.departments)
        severity = result.severity

        # --- Enforce ER override ---
        # When rule-based detects ER, always keep ER regardless of LLM output
        if er_override:
            from prescreen_rulesets.constants import (
                DEFAULT_ER_DEPARTMENT,
                DEFAULT_ER_SEVERITY,
            )
            severity = DEFAULT_ER_SEVERITY
            if DEFAULT_ER_DEPARTMENT not in departments:
                departments = [DEFAULT_ER_DEPARTMENT] + departments

        # --- Enforce minimum severity ---
        if min_severity and severity:
            min_idx = (
                SEVERITY_ORDER.index(min_severity)
                if min_severity in SEVERITY_ORDER
                else -1
            )
            pred_idx = (
                SEVERITY_ORDER.index(severity)
                if severity in SEVERITY_ORDER
                else -1
            )
            # If predicted severity is less severe than the minimum, bump it up
            if pred_idx < min_idx:
                severity = min_severity

        return PredictionResult(
            diagnoses=result.diagnoses,
            departments=departments,
            severity=severity,
        )
