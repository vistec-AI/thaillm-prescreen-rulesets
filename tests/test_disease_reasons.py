"""Validation tests for v1/const/disease_reasons.yaml.

``disease_reasons.yaml`` maps disease IDs to custom termination reasons that the
pipeline surfaces in the final result (``PipelineResult.reason`` ->
``tool_content.note``).  The file uses a two-section structure:

  reasons          - named, reusable reason strings.
  disease_reasons  - disease ID (from diseases.yaml) -> reason key above.

These tests read the local ``v1/`` files directly (via ``find_repo_root()``) so
local edits are caught before they are pushed.
"""

from helpers.utils import find_repo_root, load_yaml

# --- Load reference data (local files, not HuggingFace) ---
repo_root = find_repo_root()
disease_reasons = load_yaml(repo_root / "v1" / "const" / "disease_reasons.yaml")
diseases = load_yaml(repo_root / "v1" / "const" / "diseases.yaml")

# Set of all valid disease IDs for cross-referencing the mapping.
DISEASE_IDS = {d["id"] for d in diseases}

# Curated telemedicine-eligible disease set — these mild/manageable conditions
# must all map to the shared "telemedicine" reason.
TELEMEDICINE_DISEASE_IDS = {
    "d089", "d114", "d119", "d142", "d151", "d167", "d176", "d181",
    "d199", "d276", "d277", "d310", "d326", "d374", "d392", "d410",
    "d437", "d440", "d446",
}


def test_disease_reasons_structure():
    """The file has the two expected sections, both mappings."""
    assert isinstance(disease_reasons, dict), "disease_reasons.yaml root must be a mapping"
    assert "reasons" in disease_reasons, "missing 'reasons' section"
    assert "disease_reasons" in disease_reasons, "missing 'disease_reasons' section"
    assert isinstance(disease_reasons["reasons"], dict), "'reasons' must be a mapping"
    assert isinstance(disease_reasons["disease_reasons"], dict), (
        "'disease_reasons' must be a mapping"
    )


def test_reason_strings_nonempty():
    """Every named reason is a non-empty string."""
    for key, text in disease_reasons["reasons"].items():
        assert isinstance(text, str) and text.strip(), (
            f"reason '{key}' must be a non-empty string"
        )


def test_disease_ids_exist():
    """Every disease ID in the mapping exists in diseases.yaml."""
    for disease_id in disease_reasons["disease_reasons"]:
        assert disease_id in DISEASE_IDS, (
            f"disease_reasons.yaml references unknown disease ID '{disease_id}'"
        )


def test_reason_keys_resolve():
    """Every disease maps to a reason key defined in the 'reasons' section.

    Mirrors the ValueError guard in RulesetStore._load_constants() — a dangling
    reference would break loading at runtime.
    """
    named = disease_reasons["reasons"]
    for disease_id, reason_key in disease_reasons["disease_reasons"].items():
        assert reason_key in named, (
            f"disease '{disease_id}' references unknown reason key '{reason_key}'"
        )


def test_telemedicine_diseases_present():
    """The curated telemedicine-eligible disease set is mapped to 'telemedicine'."""
    mapping = disease_reasons["disease_reasons"]
    missing = TELEMEDICINE_DISEASE_IDS - mapping.keys()
    assert not missing, f"Missing telemedicine-eligible diseases: {sorted(missing)}"
    for disease_id in TELEMEDICINE_DISEASE_IDS:
        assert mapping[disease_id] == "telemedicine", (
            f"disease '{disease_id}' should map to the 'telemedicine' reason"
        )
