"""RulesetStore — loads all YAML rulesets from ``v1/`` into typed models.

This is the single source of truth for rule data at runtime.  The store is
loaded once at startup and provides fast lookup by symptom, phase, and qid.

Usage::

    store = RulesetStore()          # defaults to v1/ relative to repo root
    store.load()                    # parse all YAML files

    q = store.get_question("oldcarts", "Headache", "hea_o_001")
    first = store.get_first_qid("opd", "Headache")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from prescreen_rulesets.models.question import Question, question_mapper
from prescreen_rulesets.models.schema import (
    DemographicField,
    DepartmentConst,
    ERChecklistItem,
    ERCriticalItem,
    NHSOSymptom,
    SeverityConst,
    UnderlyingDisease,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility helpers (originally in tests/helpers/utils.py)
# ---------------------------------------------------------------------------

def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk upwards from *start* to find the repo root (dir with pyproject.toml or .git).

    Falls back to cwd if no marker is found.
    """
    p = (start or Path(__file__).resolve()).parent
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


def load_yaml(path: Path | str) -> Any:
    """Load a single YAML file and return the parsed contents."""
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Missing YAML file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# RulesetStore
# ---------------------------------------------------------------------------

class RulesetStore:
    """Loads all YAML from ``v1/`` and provides typed lookup.

    Attributes populated after :meth:`load`:

        departments       — dict[id, DepartmentConst]
        severity_levels   — dict[id, SeverityConst]
        nhso_symptoms     — dict[name, NHSOSymptom]
        underlying_diseases — list[UnderlyingDisease]
        demographics      — list[DemographicField]
        er_critical       — list[ERCriticalItem]
        er_adult          — dict[symptom_name, list[ERChecklistItem]]
        er_pediatric      — dict[symptom_name, list[ERChecklistItem]]
        oldcarts          — dict[symptom_name, dict[qid, Question]]
        opd               — dict[symptom_name, dict[qid, Question]]
    """

    def __init__(self, ruleset_dir: str | Path | None = None) -> None:
        if ruleset_dir is None:
            ruleset_dir = find_repo_root() / "v1"
        self._base = Path(ruleset_dir)

        # Populated by load()
        self.departments: dict[str, DepartmentConst] = {}
        self.severity_levels: dict[str, SeverityConst] = {}
        self.nhso_symptoms: dict[str, NHSOSymptom] = {}
        self.underlying_diseases: list[UnderlyingDisease] = []
        self.demographics: list[DemographicField] = []
        self.er_critical: list[ERCriticalItem] = []
        self.er_adult: dict[str, list[ERChecklistItem]] = {}
        self.er_pediatric: dict[str, list[ERChecklistItem]] = {}
        self.oldcarts: dict[str, dict[str, Question]] = {}
        self.opd: dict[str, dict[str, Question]] = {}

        # Ordered qid lists per symptom (preserves YAML order for first-qid lookup)
        self._oldcarts_order: dict[str, list[str]] = {}
        self._opd_order: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Parse all YAML files under the ruleset directory into typed models.

        Call this once at startup.  Raises ``FileNotFoundError`` if expected
        YAML files are missing.
        """
        self._load_constants()
        self._load_demographics()
        self._load_er()
        self._load_decision_trees()
        logger.info(
            "RulesetStore loaded: %d departments, %d symptoms, %d oldcarts, %d opd",
            len(self.departments),
            len(self.nhso_symptoms),
            len(self.oldcarts),
            len(self.opd),
        )

    def _load_constants(self) -> None:
        """Load v1/const/*.yaml into typed model dicts."""
        const_dir = self._base / "const"

        # Departments — keyed by id
        for raw in load_yaml(const_dir / "departments.yaml"):
            dept = DepartmentConst(**raw)
            self.departments[dept.id] = dept

        # Severity levels — keyed by id
        for raw in load_yaml(const_dir / "severity_levels.yaml"):
            sev = SeverityConst(**raw)
            self.severity_levels[sev.id] = sev

        # NHSO symptoms — keyed by English name
        for raw in load_yaml(const_dir / "nhso_symptoms.yaml"):
            sym = NHSOSymptom(**raw)
            self.nhso_symptoms[sym.name] = sym

        # Underlying diseases
        for raw in load_yaml(const_dir / "underlying_diseases.yaml"):
            self.underlying_diseases.append(UnderlyingDisease(**raw))

    def _load_demographics(self) -> None:
        """Load v1/rules/demographic.yaml into DemographicField list."""
        raw_list = load_yaml(self._base / "rules" / "demographic.yaml")
        for raw in raw_list:
            self.demographics.append(DemographicField(**raw))

    def _load_er(self) -> None:
        """Load ER rule files: critical, adult checklist, pediatric checklist."""
        er_dir = self._base / "rules" / "er"

        # Phase 1 — critical yes/no items
        for raw in load_yaml(er_dir / "er_symptom.yaml"):
            self.er_critical.append(ERCriticalItem(**raw))

        # Phase 3 — adult checklist (keyed by symptom name)
        adult_raw = load_yaml(er_dir / "er_adult_checklist.yaml")
        for symptom_name, items in adult_raw.items():
            self.er_adult[symptom_name] = [ERChecklistItem(**item) for item in items]

        # Phase 3 — pediatric checklist (keyed by symptom name)
        ped_raw = load_yaml(er_dir / "er_pediatric_checklist.yaml")
        for symptom_name, items in ped_raw.items():
            self.er_pediatric[symptom_name] = [ERChecklistItem(**item) for item in items]

    def _load_decision_trees(self) -> None:
        """Load OLDCARTS and OPD decision trees, keyed by symptom.

        Each question is parsed through ``question_mapper`` to get the right
        Pydantic type based on ``question_type``.
        """
        # OLDCARTS — phase 4
        oldcarts_raw = load_yaml(self._base / "rules" / "oldcarts.yaml")
        for symptom_name, questions in oldcarts_raw.items():
            parsed: dict[str, Question] = {}
            order: list[str] = []
            for q_dict in questions:
                qtype = q_dict.get("question_type")
                cls = question_mapper.get(qtype)
                if cls is None:
                    raise ValueError(
                        f"Unknown question_type '{qtype}' in OLDCARTS/{symptom_name}"
                    )
                q = cls(**q_dict)
                parsed[q.qid] = q
                order.append(q.qid)
            self.oldcarts[symptom_name] = parsed
            self._oldcarts_order[symptom_name] = order

        # OPD — phase 5
        opd_raw = load_yaml(self._base / "rules" / "opd.yaml")
        for symptom_name, questions in opd_raw.items():
            parsed = {}
            order: list[str] = []
            for q_dict in questions:
                qtype = q_dict.get("question_type")
                cls = question_mapper.get(qtype)
                if cls is None:
                    raise ValueError(
                        f"Unknown question_type '{qtype}' in OPD/{symptom_name}"
                    )
                q = cls(**q_dict)
                parsed[q.qid] = q
                order.append(q.qid)
            self.opd[symptom_name] = parsed
            self._opd_order[symptom_name] = order

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_first_qid(self, source: str, symptom: str) -> str:
        """Return the first question ID for a symptom in the given source.

        Args:
            source: "oldcarts" or "opd"
            symptom: symptom name (e.g. "Headache")

        Returns:
            The qid of the first question in YAML order.

        Raises:
            KeyError: if the symptom is not found in the source.
        """
        order = self._oldcarts_order if source == "oldcarts" else self._opd_order
        return order[symptom][0]

    def get_question(self, source: str, symptom: str, qid: str) -> Question:
        """Look up a single question by source, symptom, and qid.

        Args:
            source: "oldcarts" or "opd"
            symptom: symptom name (e.g. "Headache")
            qid: question ID (e.g. "hea_o_001")

        Returns:
            The parsed Question model.

        Raises:
            KeyError: if the symptom or qid is not found.
        """
        tree = self.oldcarts if source == "oldcarts" else self.opd
        return tree[symptom][qid]

    def get_questions_for_symptom(self, source: str, symptom: str) -> dict[str, Question]:
        """Return all questions for a symptom in the given source.

        Args:
            source: "oldcarts" or "opd"
            symptom: symptom name (e.g. "Headache")

        Returns:
            Dict of {qid: Question} in YAML order.
        """
        tree = self.oldcarts if source == "oldcarts" else self.opd
        return tree[symptom]

    def get_er_checklist(self, symptom: str, *, pediatric: bool = False) -> list[ERChecklistItem]:
        """Return the ER checklist items for a symptom.

        Args:
            symptom: symptom name (e.g. "Headache")
            pediatric: if True, return the pediatric checklist; otherwise adult.

        Returns:
            List of ERChecklistItem, or empty list if the symptom has no items.
        """
        checklist = self.er_pediatric if pediatric else self.er_adult
        return checklist.get(symptom, [])

    def resolve_department(self, dept_id: str) -> dict:
        """Look up a department by ID and return a dict with name fields.

        Returns a dict suitable for API responses: {id, name, name_th, description}.
        """
        dept = self.departments[dept_id]
        return {"id": dept.id, "name": dept.name, "name_th": dept.name_th, "description": dept.description}

    def resolve_severity(self, sev_id: str) -> dict:
        """Look up a severity level by ID and return a dict with name fields.

        Returns a dict suitable for API responses: {id, name, name_th, description}.
        """
        sev = self.severity_levels[sev_id]
        return {"id": sev.id, "name": sev.name, "name_th": sev.name_th, "description": sev.description}
