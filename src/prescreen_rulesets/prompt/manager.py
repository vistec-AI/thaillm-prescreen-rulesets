"""PromptManager — Jinja2-based prompt renderer for LLM players.

Loads templates from the ``template/`` directory and renders ``QuestionsStep``
objects into LLM-ready prompt strings with JSON response instructions.

Templates are dispatched by phase for bulk steps (0-3) and by question_type
for sequential steps (4-5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

from prescreen_rulesets.models.session import QuestionsStep

if TYPE_CHECKING:
    from prescreen_rulesets.models.pipeline import QAPair


# --- Phase-to-template mapping for bulk phases ---
_PHASE_TEMPLATES: dict[int, str] = {
    0: "demographics.jinja2",
    1: "er_critical.jinja2",
    2: "symptom_selection.jinja2",
    3: "er_checklist.jinja2",
}

# --- question_type-to-template mapping for sequential phases ---
_QTYPE_TEMPLATES: dict[str, str] = {
    "single_select": "single_select.jinja2",
    "multi_select": "multi_select.jinja2",
    "number_range": "number_range.jinja2",
    "free_text": "free_text.jinja2",
    "free_text_with_fields": "free_text_with_fields.jinja2",
    "image_single_select": "image_single_select.jinja2",
    "image_multi_select": "image_multi_select.jinja2",
}


class PromptManager:
    """Jinja2-based prompt renderer for LLM players.

    Loads templates from the ``template/`` directory and renders
    ``QuestionsStep`` objects into LLM-ready prompt strings with
    JSON response instructions.

    Args:
        template_dir: optional override for the template directory.
            Defaults to ``template/`` sibling of this module.
    """

    def __init__(self, template_dir: Path | None = None) -> None:
        if template_dir is None:
            template_dir = Path(__file__).parent / "template"
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            # Keep whitespace control simple — templates use explicit trim
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # Register the json filter for use in templates
        self._env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)

    def render_step(
        self,
        step: QuestionsStep,
        history: list[QAPair] | None = None,
    ) -> str:
        """Render a full QuestionsStep as an LLM prompt.

        Dispatches by phase for bulk (0-3) and by question_type for
        sequential (4-5).  Includes JSON response format instructions.

        Args:
            history: optional list of prior Q&A pairs.  When provided,
                the template prepends a "Previous answers" section so the
                LLM has conversational context.
        """
        phase = step.phase

        # Bulk phases 0-3 each have their own template
        if phase in _PHASE_TEMPLATES:
            template_name = _PHASE_TEMPLATES[phase]
            return self._render_bulk(template_name, step, history=history)

        # Sequential phases 4-5: dispatch by question_type
        if step.questions:
            question = step.questions[0]
            qtype = question.question_type
            template_name = _QTYPE_TEMPLATES.get(qtype)
            if template_name is not None:
                return self._render_sequential(
                    template_name, step, question, history=history,
                )

        # Fallback: render a generic prompt listing questions
        return self._render_fallback(step, history=history)

    def render(self, template_name: str, **context) -> str:
        """Render a named template with arbitrary context."""
        template = self._env.get_template(template_name)
        return template.render(**context)

    # --- Internal rendering helpers ---

    def _render_bulk(
        self,
        template_name: str,
        step: QuestionsStep,
        *,
        history: list[QAPair] | None = None,
    ) -> str:
        """Render a bulk-phase template with the full step as context."""
        # Build a submission example for demographics
        submission_example = None
        if step.phase == 0 and step.questions:
            example = {}
            for q in step.questions:
                key = q.metadata.get("key", q.qid) if q.metadata else q.qid
                schema = q.answer_schema or {}
                if schema.get("format") == "date":
                    example[key] = "YYYY-MM-DD"
                elif "enum" in schema:
                    example[key] = schema["enum"][0] if schema["enum"] else ""
                elif schema.get("type") == "number":
                    example[key] = 0
                else:
                    example[key] = "..."
            submission_example = json.dumps(example, ensure_ascii=False, indent=2)

        template = self._env.get_template(template_name)
        return template.render(
            step=step,
            submission_example=submission_example,
            history=history,
        )

    def _render_sequential(
        self,
        template_name: str,
        step: QuestionsStep,
        question,
        *,
        history: list[QAPair] | None = None,
    ) -> str:
        """Render a sequential-phase template with the question as context."""
        template = self._env.get_template(template_name)
        return template.render(step=step, question=question, history=history)

    def render_llm_questions(
        self,
        questions: list[str],
        *,
        history: list[QAPair] | None = None,
    ) -> str:
        """Render LLM-generated follow-up questions as a free-text prompt.

        Used during the ``llm_questioning`` pipeline stage to let an LLM
        player answer the generated follow-up questions.

        Args:
            history: optional list of prior Q&A pairs to prepend as context.
        """
        template = self._env.get_template("llm_questions.jinja2")
        return template.render(questions=questions, history=history)

    def _render_fallback(
        self,
        step: QuestionsStep,
        history: list[QAPair] | None = None,
    ) -> str:
        """Generic fallback prompt when no specific template matches."""
        lines = []

        # Prepend history when available
        if history:
            lines.append("Previous answers:")
            for pair in history:
                lines.append(f"- Q: {pair.question} → A: {pair.answer}")
            lines.append("")

        lines.append(f"Phase {step.phase} — {step.phase_name}")
        lines.append("")
        for q in step.questions:
            lines.append(f"Question ({q.qid}): {q.question}")
            if q.options:
                for opt in q.options:
                    lines.append(f"  - \"{opt['id']}\": {opt['label']}")
        lines.append("")
        lines.append("Respond with a JSON value matching the expected format.")
        return "\n".join(lines)
