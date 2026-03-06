"""PredictionPromptManager — Jinja2 renderer for prediction module prompts.

Renders system and user prompts for the OpenAI prediction module.
Takes a ``RulesetStore`` to build disease/department/severity reference tables
that are injected into the system prompt.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

if TYPE_CHECKING:
    from prescreen_rulesets.models.pipeline import QAPair
    from prescreen_rulesets.ruleset import RulesetStore


class PredictionPromptManager:
    """Jinja2-based prompt renderer for the prediction module.

    Args:
        store: ``RulesetStore`` instance — provides disease, department, and
            severity reference data for the system prompt.
        template_dir: optional override for the template directory.
            Defaults to ``templates/prediction/`` sibling of this module.
    """

    def __init__(self, store: RulesetStore, template_dir: Path | None = None) -> None:
        self._store = store
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates" / "prediction"
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
        """Render the system prompt with disease/department/severity reference tables."""
        template = self._env.get_template("system.md")

        # Build reference lists from the store
        diseases = [
            {"id": d.id, "disease_name": d.disease_name, "name_th": d.name_th}
            for d in sorted(self._store.diseases.values(), key=lambda d: d.id)
        ]
        departments = [
            {"id": d.id, "name": d.name, "name_th": d.name_th}
            for d in sorted(self._store.departments.values(), key=lambda d: d.id)
        ]
        severity_levels = [
            {"id": s.id, "name": s.name, "name_th": s.name_th}
            for s in self._store.get_severity_ids()
            for s in [self._store.severity_levels[s]]
        ]

        return template.render(
            diseases=diseases,
            departments=departments,
            severity_levels=severity_levels,
        )

    def render_prompt(
        self,
        qa_pairs: list[QAPair],
        min_severity: str | None = None,
    ) -> str:
        """Render the user prompt with QA history grouped by phase.

        Args:
            qa_pairs: ordered list of QA pairs from all stages.
            min_severity: optional minimum severity label to include
                as an instruction in the prompt.
        """
        grouped = self._group_by_phase(qa_pairs)
        template = self._env.get_template("prompt.md")
        return template.render(
            grouped_pairs=grouped,
            min_severity=min_severity,
        )

    @staticmethod
    def _group_by_phase(qa_pairs: list[QAPair]) -> dict[int, list[QAPair]]:
        """Group QA pairs by their phase number.

        Pairs without a phase (e.g. LLM-generated) are placed under phase 6.
        """
        groups: dict[int, list[QAPair]] = defaultdict(list)
        for pair in qa_pairs:
            phase = pair.phase if pair.phase is not None else 6
            groups[phase].append(pair)
        return dict(sorted(groups.items()))
