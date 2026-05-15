"""MedgemmaPredictionModule — concrete PredictionModule using a vLLM endpoint.

Talks to a self-hosted `vLLM <https://docs.vllm.ai>`_ server running
``google/medgemma-27b-text-it`` (or compatible).  Unlike ``OpenAIPredictionModule``
this connector:

  - reads its endpoint config from ``VLLM_PREDICTOR_URL`` / ``VLLM_PREDICTOR_MODEL``
    / ``VLLM_APIKEY`` (see :func:`resolve_vllm_config`);
  - renders the ``medgemma-prescreen`` prompt templates (a structured patient
    profile) via :class:`MedgemmaPromptManager`;
  - POSTs to the endpoint with raw ``httpx`` — the request mirrors the documented
    curl example exactly (``stream=False``, ``skip_special_tokens=False``), and
    the ``Authorization`` header is attached only when an API key is present;
  - parses the model's **XML** answer (``<disease>/<department>/<severity>``),
    stripping the silent reasoning block delimited by the ``<unused94> …
    <unused95>`` special tokens, then maps the human-readable names back to the
    disease / department / severity **IDs** that ``PredictionResult`` expects.

Transient errors (timeout, connection failure, ``5xx`` / ``429``) degrade
gracefully by returning an empty ``PredictionResult``.  Permanent errors (other
``4xx`` — auth, bad model) are re-raised so callers can fix their configuration.
"""

from __future__ import annotations

import logging
import re

import httpx

from prescreen_rulesets.constants import SEVERITY_ORDER
from prescreen_rulesets.interfaces import PredictionModule
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.prediction.prompt_manager import MedgemmaPromptManager
from prescreen_rulesets.ruleset import RulesetStore

logger = logging.getLogger(__name__)


class MedgemmaPredictionModule(PredictionModule):
    """LLM-backed prediction module using a self-hosted vLLM medgemma endpoint.

    Args:
        store: ``RulesetStore`` — supplies the disease/department/severity
            reference data and the name→ID reverse lookups.
        url: full chat-completions endpoint URL.  When ``None``, resolved from
            the ``VLLM_PREDICTOR_URL`` environment variable.
        model: model identifier sent in the request body.  When ``None``,
            resolved from ``VLLM_PREDICTOR_MODEL`` (default
            ``google/medgemma-27b-text-it``).
        api_key: bearer token for the endpoint.  When ``None`` (the resolved
            value when ``VLLM_APIKEY`` is empty/unset), no ``Authorization``
            header is sent — self-hosted vLLM typically runs without auth.
        temperature: sampling temperature (default ``0.0`` for deterministic
            triage).  ``None`` omits the parameter.
        max_tokens: max tokens in the response.  ``None`` omits the parameter.
        timeout: HTTP timeout in seconds for the prediction call.
    """

    def __init__(
        self,
        *,
        store: RulesetStore,
        url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        timeout: float = 60.0,
    ) -> None:
        # When no explicit URL is provided, resolve the endpoint from the
        # environment.  `url` is the discriminator: if the caller supplied it,
        # they own the full config and we skip env resolution entirely.
        if url is None:
            from prescreen_rulesets.constants import resolve_vllm_config
            config = resolve_vllm_config()
            url = config.url
            if model is None:
                model = config.model
            if api_key is None:
                api_key = config.api_key

        self._url = url
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._store = store
        self._prompt_manager = MedgemmaPromptManager(store)
        self._client = httpx.AsyncClient(timeout=timeout)

        # Build the request headers once.  The Authorization header is attached
        # only when an API key is present — an empty VLLM_APIKEY resolves to
        # None, in which case the request carries no auth at all.
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key is not None:
            self._headers["Authorization"] = f"Bearer {api_key}"

        # --- Disease name → ID reverse lookups ---
        # The medgemma templates feed the model a closed list of `disease_name`
        # strings; the model echoes one back, which we map to a `dNNN` ID.
        # `disease_name` is not guaranteed unique across disease rows — on
        # collision the first occurrence wins, which is fine because the model
        # only ever sees (and so can only return) that same name.  A lowercase
        # variant backs a case-insensitive fallback for minor capitalisation
        # drift.  Department and severity names use the store's own exact-match
        # reverse lookups (`dept_name_to_id` / `severity_name_to_id`).
        self._disease_name_to_id: dict[str, str] = {}
        self._disease_name_to_id_ci: dict[str, str] = {}
        for disease in store.diseases.values():
            self._disease_name_to_id.setdefault(disease.disease_name, disease.id)
            self._disease_name_to_id_ci.setdefault(
                disease.disease_name.lower(), disease.id,
            )

        # Context set by the pipeline before calling predict().
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

    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        """Run prediction on the combined Q&A history.

        Renders the medgemma-prescreen prompts, calls the vLLM endpoint, strips
        the model's silent reasoning block, parses the XML answer, and resolves
        the disease/department/severity names to IDs.

        Returns an empty ``PredictionResult`` on transient API errors so the
        pipeline can continue without predictions.
        """
        # Capture and reset context early so it's cleared regardless of which
        # code path returns (transient error, parse failure, etc.).
        er_override = self._er_override
        min_severity = self._min_severity
        self._er_override = False
        self._min_severity = None

        # No QA filtering — the medgemma template's "Conversation History" is
        # the full transcript, matching how the templates were designed/tested.
        system_prompt = self._prompt_manager.render_system()
        instruction = self._prompt_manager.render_instruction(qa_pairs)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction},
        ]

        content = await self._call_api(messages)
        if content is None:
            return PredictionResult()

        result = self._parse_response(content)

        return self._apply_safety_constraints(
            result, er_override=er_override, min_severity=min_severity,
        )

    async def _call_api(
        self, messages: list[dict[str, str]],
    ) -> str | None:
        """POST the chat-completion request to the vLLM endpoint.

        Returns the response content string, or ``None`` on transient errors.
        Permanent errors (auth, bad model — any non-5xx/429 4xx) are re-raised.

        The request body mirrors the documented curl example exactly:
        ``stream=False`` and ``skip_special_tokens=False`` — the latter is
        required so the ``<unused94>``/``<unused95>`` thinking-block delimiters
        appear verbatim in the response and can be stripped.
        """
        body: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            # Keep the model's special tokens in the output so the silent
            # reasoning block stays delimited and strippable.
            "skip_special_tokens": False,
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._max_tokens is not None:
            body["max_tokens"] = self._max_tokens

        try:
            response = await self._client.post(
                self._url, headers=self._headers, json=body,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Timeouts and connection-level failures are transient — degrade
            # gracefully so the pipeline can finish without a prediction.
            logger.warning(
                "vLLM transient error during prediction: %s", exc,
            )
            return None

        # 429 (rate limit) and 5xx (server overload / restart) are transient;
        # other 4xx (401 auth, 404 bad model, 422 bad request) are permanent
        # configuration errors and must surface to the caller.
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                "vLLM transient HTTP %d during prediction", response.status_code,
            )
            return None
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"] or ""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_thinking(content: str) -> str:
        """Remove the model's silent reasoning block.

        medgemma wraps its chain-of-thought between the special tokens
        ``<unused94> … <unused95>``; the final XML answer follows ``<unused95>``.
        With ``skip_special_tokens=False`` these tokens appear verbatim, so we
        take everything after the last ``<unused95>``.  When the token is absent
        (the model produced no thinking block) the content is returned
        unchanged.
        """
        if "<unused95>" in content:
            return content.rsplit("<unused95>", 1)[-1]
        return content

    @staticmethod
    def _extract_tag(text: str, tag: str) -> str | None:
        """Extract the inner text of a ``<tag>…</tag>`` element, or None."""
        match = re.search(
            rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    def _parse_response(self, content: str) -> PredictionResult:
        """Parse the model's XML answer into a ``PredictionResult``.

        Strips the thinking block, extracts the three answer tags, and resolves
        each human-readable name to its ID.  Unknown names are logged and
        omitted (empty diagnoses / departments, ``None`` severity) rather than
        raising — a malformed answer should degrade, not crash the pipeline.
        Does NOT apply safety constraints — those run in
        :meth:`_apply_safety_constraints`.
        """
        text = self._strip_thinking(content)

        # --- Disease → diagnoses list ---
        # medgemma returns a single primary diagnosis, so `diagnoses` has 0 or 1
        # entry (PredictionResult still types it as a list).
        diagnoses: list[DiagnosisResult] = []
        disease_name = self._extract_tag(text, "disease")
        if disease_name:
            disease_id = self._disease_name_to_id.get(disease_name)
            if disease_id is None:
                # Case-insensitive fallback for minor capitalisation drift.
                disease_id = self._disease_name_to_id_ci.get(
                    disease_name.lower(),
                )
            if disease_id:
                diagnoses = [DiagnosisResult(disease_id=disease_id)]
            else:
                logger.warning(
                    "Medgemma returned unknown disease name: %r", disease_name,
                )

        # --- Department → department IDs list ---
        departments: list[str] = []
        dept_name = self._extract_tag(text, "department")
        if dept_name:
            dept_id = self._store.dept_name_to_id(dept_name)
            if dept_id:
                departments = [dept_id]
            else:
                logger.warning(
                    "Medgemma returned unknown department name: %r", dept_name,
                )

        # --- Severity → severity ID ---
        severity: str | None = None
        severity_name = self._extract_tag(text, "severity")
        if severity_name:
            severity = self._store.severity_name_to_id(severity_name)
            if severity is None:
                logger.warning(
                    "Medgemma returned unknown severity name: %r",
                    severity_name,
                )

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
        # When rule-based detects ER, always keep ER regardless of LLM output.
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
            # If predicted severity is less severe than the minimum, bump it up.
            if pred_idx < min_idx:
                severity = min_severity

        return PredictionResult(
            diagnoses=result.diagnoses,
            departments=departments,
            severity=severity,
        )
