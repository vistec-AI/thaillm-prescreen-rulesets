from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import yaml


def find_repo_root(start: Optional[Path] = None) -> Path:
    p = (start or Path(__file__).resolve()).parent
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


def load_yaml(path: Path | str) -> Any:
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Missing YAML file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rules_local(version: str = "v1") -> Dict[Literal["oldcarts", "opd"], Any]:
    base = find_repo_root() / version
    rules_dir = base / "rules"
    return {
        "oldcarts": load_yaml(rules_dir / "oldcarts.yaml"),
        "opd": load_yaml(rules_dir / "opd.yaml"),
    }


def load_er_rules_local(version: str = "v1") -> Dict[str, Any]:
    """Load the three ER rule YAML files from ``v1/rules/er/``.

    Returns a dict with three keys:
    - ``er_symptom``:    flat list of phase-1 critical yes/no checks
    - ``er_adult``:      dict keyed by symptom name → list of adult checklist items
    - ``er_pediatric``:  dict keyed by symptom name → list of pediatric checklist items
    """
    er_dir = find_repo_root() / version / "rules" / "er"
    return {
        "er_symptom": load_yaml(er_dir / "er_symptom.yaml"),
        "er_adult": load_yaml(er_dir / "er_adult_checklist.yaml"),
        "er_pediatric": load_yaml(er_dir / "er_pediatric_checklist.yaml"),
    }


def load_demographic_local(version: str = "v1") -> list[Dict[str, Any]]:
    """Load demographic field definitions from ``v1/rules/demographic.yaml``.

    Returns the flat list of field dicts.  For fields whose ``type`` is
    ``from_yaml``, the ``values`` string (a relative path like
    ``const/underlying_diseases.yaml``) is resolved to the actual list
    loaded from that YAML file, and the original path is preserved in
    ``values_path``.
    """
    root = find_repo_root()
    base = root / version
    items = load_yaml(base / "rules" / "demographic.yaml")
    if not isinstance(items, list):
        return []

    for item in items:
        if item.get("type") == "from_yaml" and isinstance(item.get("values"), str):
            ref_path = base / item["values"]
            # Keep the original relative path so the UI can display it
            item["values_path"] = item["values"]
            try:
                item["values"] = load_yaml(ref_path)
            except FileNotFoundError:
                item["values"] = []

    return items


def load_constants_local(version: str = "v1") -> Dict[str, Any]:
    base = find_repo_root() / version / "const"
    return {
        "diseases": load_yaml(base / "diseases.yaml"),
        "departments": load_yaml(base / "departments.yaml"),
        "severity_levels": load_yaml(base / "severity_levels.yaml"),
        "nhso_symptoms": load_yaml(base / "nhso_symptoms.yaml"),
    }


