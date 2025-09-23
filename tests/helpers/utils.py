import yaml
from pathlib import Path
from typing import Any, Optional


def find_repo_root(start: Optional[Path] = None) -> Path:
    """
    Walk upwards to find the repo root (dir that has pyproject.toml or .git).
    Works both when running tests in this repo or when vendored as a submodule.
    """
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
