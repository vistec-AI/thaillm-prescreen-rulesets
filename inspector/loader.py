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


def load_constants_local(version: str = "v1") -> Dict[str, Any]:
    base = find_repo_root() / version / "const"
    return {
        "diseases": load_yaml(base / "diseases.yaml"),
        "departments": load_yaml(base / "departments.yaml"),
        "severity_levels": load_yaml(base / "severity_levels.yaml"),
        "nhso_symptoms": load_yaml(base / "nhso_symptoms.yaml"),
    }


