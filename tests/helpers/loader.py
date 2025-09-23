from typing import Any, Dict, Literal

from huggingface_hub import hf_hub_download

from .utils import load_yaml, find_repo_root

PRESCREEN_REPO = "ThaiLLM/prescreen-profiles"


def load_rules(version: str = "v1") -> Dict[Literal["oldcarts", "opd"], Any]:
    """
    Load constants from v*/const/*.yaml into a dict:
      {
        'oldcarts': [...],
        'opd': [...]
      }
    """
    base = find_repo_root() / version
    rules_dir = base / "rules"
    return {
        "oldcarts": load_yaml(rules_dir / "oldcarts.yaml"),
        "opd": load_yaml(rules_dir / "opd.yaml"),
    }


def load_constants() -> Dict[Literal["diseases", "departments", "severity", "nhso_symptoms"], Any]:
    """
    Load constants for prescreening:
      {
        'diseases': [...],
        'departments': [...],
        'severity_levels': [...]
        'nhso_symptoms': [...]
      }
    """
    diseases_path = hf_hub_download(repo_id=PRESCREEN_REPO, filename="diseases.yaml", repo_type="dataset")
    departments_path = hf_hub_download(repo_id=PRESCREEN_REPO, filename="departments.yaml", repo_type="dataset")
    severity_path = hf_hub_download(repo_id=PRESCREEN_REPO, filename="severity.yaml", repo_type="dataset")
    nhso_path = hf_hub_download(repo_id=PRESCREEN_REPO, filename="nhso_symptoms.yaml", repo_type="dataset")

    return {
        "diseases": load_yaml(diseases_path),
        "departments": load_yaml(departments_path),
        "severity_levels": load_yaml(severity_path),
        "nhso_symptoms": load_yaml(nhso_path),
    }
