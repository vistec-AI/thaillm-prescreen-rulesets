"""QuestionGeneratorPromptManager — Jinja2 renderer for question-generator prompts.

Renders system and user prompts from QA history for the OpenAI question
generator.  Follows the same Jinja2 pattern as
``prescreen_rulesets.prompt.manager.PromptManager``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

if TYPE_CHECKING:
    from prescreen_rulesets.models.pipeline import QAPair


class QuestionGeneratorPromptManager:
    """Jinja2-based prompt renderer for the question generator.

    Loads templates from the ``templates/llm_question_generator/`` directory
    and renders system/user prompts for the LLM call.

    Args:
        template_dir: optional override for the template directory.
            Defaults to ``templates/llm_question_generator/`` sibling of
            this module.
    """

    def __init__(self, template_dir: Path | None = None) -> None:
        if template_dir is None:
            template_dir = (
                Path(__file__).parent / "templates" / "llm_question_generator"
            )
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # Preserve Thai text in JSON serialization
        self._env.filters["tojson"] = lambda v: json.dumps(
            v, ensure_ascii=False,
        )

    def render_system(self) -> str:
        """Render the system prompt (role + guidelines + response format)."""
        template = self._env.get_template("system.md")
        return template.render()

    def render_prompt(self, qa_pairs: list[QAPair]) -> str:
        """Render the user prompt with QA history grouped by phase.

        Args:
            qa_pairs: ordered list of QA pairs from the rule-based flow.
                Pairs are grouped by ``phase`` for structured presentation.
        """
        grouped = self._group_by_phase(qa_pairs)
        template = self._env.get_template("prompt.md")
        return template.render(grouped_pairs=grouped)

    @staticmethod
    def _group_by_phase(qa_pairs: list[QAPair]) -> dict[int, list[QAPair]]:
        """Group QA pairs by their phase number.

        Pairs without a phase (e.g. LLM-generated) are placed under phase -1
        as a catch-all, though in practice only rule-based pairs (with a
        phase) should be passed to the question generator.
        """
        groups: dict[int, list[QAPair]] = defaultdict(list)
        for pair in qa_pairs:
            phase = pair.phase if pair.phase is not None else -1
            groups[phase].append(pair)
        # Return sorted by phase number for deterministic template rendering
        return dict(sorted(groups.items()))
