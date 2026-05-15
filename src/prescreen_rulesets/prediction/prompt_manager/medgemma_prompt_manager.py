"""MedgemmaPromptManager — Jinja2 renderer for the medgemma-prescreen prompts.

Renders the ``system.md`` + ``instruction.md`` templates under
``templates/medgemma-prescreen/`` for the ``MedgemmaPredictionModule`` connector.

Unlike ``PredictionPromptManager`` (which renders a phase-grouped JSON prompt),
these templates expect a *structured patient profile* — demographics, presenting
problem, OLDCARTS components, past medical history — plus a flat conversation
transcript.  This manager reconstructs that profile purely from a
``list[QAPair]``, so it slots cleanly behind the ``PredictionModule.predict()``
contract (which only receives QA pairs, never the raw session row).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import jinja2

if TYPE_CHECKING:
    from prescreen_rulesets.models.pipeline import QAPair
    from prescreen_rulesets.ruleset import RulesetStore


# OLDCARTS (phase 4) qids follow ``{prefix}_{letter}_{number}``; the middle
# letter tags which OLDCARTS component the question covers.  This maps each
# letter to the matching instruction.md template variable.  The ``as``
# (associated symptoms) letter has no dedicated template field — those answers
# still appear in the conversation transcript.
_OLDCART_LETTER_FIELDS: dict[str, str] = {
    "o": "oldcart_onset",
    "l": "oldcart_location",
    "d": "oldcart_duration",
    "c": "oldcart_characteristic",
    "a": "oldcart_aggravating",
    "r": "oldcart_relieving",
    "t": "oldcart_timing",
    "s": "oldcart_severity",
}


class MedgemmaPromptManager:
    """Jinja2-based renderer for the medgemma-prescreen prompt templates.

    Args:
        store: ``RulesetStore`` — supplies the closed disease/department option
            lists for ``system.md`` and the OLDCARTS/OPD question metadata used
            to map answer ids back to human-readable labels.
        template_dir: optional override for the template directory.  Defaults to
            ``templates/medgemma-prescreen/`` sibling of this module.
    """

    def __init__(
        self, store: RulesetStore, template_dir: Path | None = None,
    ) -> None:
        self._store = store
        if template_dir is None:
            template_dir = (
                Path(__file__).parent / "templates" / "medgemma-prescreen"
            )
        # autoescape stays off — these are plain-text prompts, not HTML, and the
        # disease descriptions contain characters Jinja would otherwise escape.
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=False,
        )

    # ------------------------------------------------------------------
    # Public rendering API
    # ------------------------------------------------------------------

    def render_system(self) -> str:
        """Render ``system.md`` — the closed disease/department option lists.

        Independent of the patient case: the lists are the full domains the
        model must choose from.
        """
        template = self._env.get_template("system.md")
        return template.render(
            possible_diseases="\n".join(
                f"- {d.disease_name}" for d in self._store.diseases.values()
            ),
            possible_departments="\n".join(
                f"- {dept.name}" for dept in self._store.departments.values()
            ),
        )

    def render_instruction(self, qa_pairs: list[QAPair]) -> str:
        """Render ``instruction.md`` — the structured patient profile.

        Reconstructs demographics, presenting problem, OLDCARTS components, and
        past medical history from ``qa_pairs``, plus a flat conversation
        transcript of every pair.
        """
        template = self._env.get_template("instruction.md")
        return template.render(**self._build_context(qa_pairs))

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _build_context(self, qa_pairs: list[QAPair]) -> dict[str, str]:
        """Assemble the Jinja2 context for ``instruction.md`` from QA pairs.

        The medgemma templates were originally driven by the session row; here
        we rebuild the same fields from ``qa_pairs`` instead.  This round-trips
        correctly because ``pipeline._build_qa_pairs`` stores demographic /
        history answers with ``qid=field.qid`` and the presenting problem with
        the fixed qids ``primary_symptom`` / ``secondary_symptoms``.
        """
        # Index every QA pair by qid for O(1) field lookup.
        qid_to_answer: dict[str, Any] = {
            p.qid: p.answer for p in qa_pairs if p.qid
        }

        # --- Reconstruct the demographics-like dict (phases 0, 5, 6) ---
        # Demographics, past history, and personal history all land in the
        # session's demographics JSONB keyed by each field's `key`; rebuild that
        # mapping from the field definitions so the rest of this method reads
        # exactly like the original session-row-driven version.
        demographics: dict[str, Any] = {}
        for field in (
            *self._store.demographics,
            *self._store.past_history,
            *self._store.personal_history,
        ):
            if field.qid in qid_to_answer:
                demographics[field.key] = qid_to_answer[field.qid]

        # --- Presenting problem (phase 2) ---
        primary_symptom = qid_to_answer.get("primary_symptom")
        secondary_symptoms = qid_to_answer.get("secondary_symptoms")

        # --- OLDCARTS (phase 4): bucket answers by the qid's middle segment ---
        # Each entry keeps its question text alongside the answer ("question —
        # answer") so a component covering several questions stays legible.
        oldcart: dict[str, list[str]] = {
            field: [] for field in _OLDCART_LETTER_FIELDS.values()
        }
        for pair in qa_pairs:
            if pair.phase != 4 or not pair.qid:
                continue
            parts = pair.qid.split("_")
            field = (
                _OLDCART_LETTER_FIELDS.get(parts[1])
                if len(parts) == 3
                else None
            )
            if field:
                oldcart[field].append(
                    f"{pair.question} — "
                    f"{self._display_answer(pair, primary_symptom)}"
                )

        context: dict[str, str] = {
            # --- demographics — phases 0, 5 & 6 ---
            "age": self._format_answer(demographics.get("age")),
            "gender": self._format_answer(demographics.get("gender")),
            "height": self._format_answer(demographics.get("height")),
            "weight": self._format_answer(demographics.get("weight")),
            "occupation": self._format_answer(demographics.get("occupation")),
            # --- presenting problem (phase 2) ---
            # No free-text chief complaint is collected, so the primary symptom
            # — the patient's reason for the visit — stands in for it.
            "complaint": self._format_answer(primary_symptom),
            "primary_symptom": self._format_answer(primary_symptom),
            "secondary_symptoms": self._format_answer(secondary_symptoms),
            # --- past medical history (phases 0 & 5) ---
            "underlying_diseases": self._format_answer(
                demographics.get("underlying_diseases")
            ),
            "medical_history": self._format_answer(
                demographics.get("other_medical_conditions")
            ),
            "current_medication": self._format_answer(
                demographics.get("current_medication")
            ),
            "drug_food_allergies": self._format_answer(
                demographics.get("drug_food_allergies")
            ),
            "surgical_history": self._format_answer(
                demographics.get("surgical_history")
            ),
            # --- full conversation transcript (all phases + LLM follow-ups) ---
            "conversation": self._format_conversation(
                qa_pairs, primary_symptom,
            ),
        }

        # OLDCARTS template vars: join the component's question—answer pairs; a
        # component with no answered questions falls back to "N/A".
        for field, entries in oldcart.items():
            context[field] = "; ".join(entries) if entries else "N/A"

        return context

    # ------------------------------------------------------------------
    # Answer formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_answer(value: Any) -> str:
        """Render a raw answer value as readable text for the prompt templates.

        Normalises the answer shapes the engine stores — ``yes_no_detail`` dicts
        (``{"answer": bool, "detail": ...}``), lists (multi-select / underlying
        diseases), bools, and plain scalars — into a single display string.
        Empty or missing values become ``"N/A"`` so the rendered prompt never
        carries a bare blank.
        """
        if value is None or value == "":
            return "N/A"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, dict):
            # yes_no_detail: {"answer": bool, "detail": {...} | None}
            if "answer" in value:
                if not value["answer"]:
                    return "No"
                detail = value.get("detail")
                return (
                    f"Yes ({MedgemmaPromptManager._format_answer(detail)})"
                    if detail
                    else "Yes"
                )
            # Other dict shapes (e.g. free_text_with_fields) — flatten to "k: v".
            return "; ".join(f"{k}: {v}" for k, v in value.items()) or "N/A"
        if isinstance(value, list):
            formatted = [
                MedgemmaPromptManager._format_answer(v)
                for v in value
                if v not in (None, "")
            ]
            return ", ".join(formatted) if formatted else "N/A"
        return str(value)

    def _question_options(
        self, pair: QAPair, symptom: str | None,
    ) -> list | None:
        """Return the option list for a QAPair's source question, or None.

        Only OLDCARTS (phase 4) and OPD (phase 7) decision-tree questions carry
        id/label option lists worth resolving.  Other phases (demographics, ER,
        symptom selection) store their answer as the display value already, so
        they return None and the caller keeps the raw answer.
        """
        if not symptom or not pair.qid:
            return None
        source = {4: "oldcarts", 7: "opd"}.get(pair.phase)
        if source is None:
            return None
        try:
            question = self._store.get_question(source, symptom, pair.qid)
        except KeyError:
            return None
        # Only select-type questions have an `options` attribute; free_text /
        # number_range / etc. return None and fall through to _format_answer.
        return getattr(question, "options", None)

    def _display_answer(self, pair: QAPair, symptom: str | None) -> str:
        """Render a QAPair's answer as readable text, mapping option ids to labels.

        Select-type questions in the OLDCARTS (phase 4) and OPD (phase 7)
        decision trees store the answer as an option *id*; this swaps it for the
        option's human-readable *label*.  multi_select answers (a list of ids)
        are mapped element-wise.  Anything without a matching option list falls
        through to :meth:`_format_answer`.
        """
        options = self._question_options(pair, symptom)
        if options:
            id_to_label = {o.id: o.label for o in options}
            answer = pair.answer
            if isinstance(answer, list):
                labels = [str(id_to_label.get(a, a)) for a in answer]
                return ", ".join(labels) if labels else "N/A"
            if isinstance(answer, str) and answer in id_to_label:
                return id_to_label[answer]
        return self._format_answer(pair.answer)

    def _format_conversation(
        self, history: list[QAPair], symptom: str | None,
    ) -> str:
        """Render the full Q&A history as a flat transcript for the prompt.

        Each pair becomes a two-line ``- Q: ... / A: ...`` block, in
        chronological order across every phase (rule-based phases 0-7 plus LLM
        follow-ups).  Select-type answers are shown as option labels, not ids
        (see :meth:`_display_answer`).  Returns ``"N/A"`` for an empty history
        so the template never shows a blank.
        """
        if not history:
            return "N/A"
        return "\n".join(
            f"- Q: {pair.question or 'None'}\n"
            f"A: {self._display_answer(pair, symptom)}"
            for pair in history
        )
