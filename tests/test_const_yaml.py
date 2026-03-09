"""Validation tests for constant YAML files in v1/const/.

Validates that each constant YAML file parses correctly and checks
new fields like sub_types and specify on underlying diseases.
"""

from helpers.data_model.schema import (
    Disease,
    NHSOSymptoms,
    Department
)
from helpers.loader import load_constants
from helpers.utils import find_repo_root, load_yaml

constants = load_constants()


def test_load_constants():
    """All expected constant keys exist in the loaded data."""
    assert isinstance(constants, dict)
    assert all(k in constants for k in ["diseases", "nhso_symptoms", "severity_levels", "departments"])


def test_parse_disease():
    """Every entry in diseases.yaml parses as a Disease model."""
    diseases = constants["diseases"]

    for d in diseases:
        Disease(**d)


def test_parse_nhso_symptoms():
    """Every entry in nhso_symptoms.yaml parses as an NHSOSymptoms model."""
    nhso_symptoms = constants["nhso_symptoms"]

    for s in nhso_symptoms:
        NHSOSymptoms(**s)


def test_parse_departments():
    """Every entry in departments.yaml parses as a Department model."""
    departments = constants["departments"]

    for s in departments:
        Department(**s)


def test_underlying_diseases_structure():
    """Validate underlying_diseases.yaml: required fields, sub_types, specify."""
    repo_root = find_repo_root()
    diseases = load_yaml(repo_root / "v1" / "const" / "underlying_diseases.yaml")
    assert isinstance(diseases, list), "underlying_diseases.yaml root must be a list"
    assert len(diseases) > 0, "underlying_diseases.yaml must have at least one entry"

    names = []
    for idx, item in enumerate(diseases):
        label = f"Entry {idx}"
        assert isinstance(item, dict), f"{label} must be a dict"
        assert "name" in item, f"{label} missing 'name'"
        assert "name_th" in item, f"{label} missing 'name_th'"
        assert isinstance(item["name"], str), f"{label} name must be a string"
        assert isinstance(item["name_th"], str), f"{label} name_th must be a string"
        names.append(item["name"])

        # Optional specify flag
        if "specify" in item:
            assert isinstance(item["specify"], bool), f"{label} specify must be boolean"

        # Optional sub_types
        if "sub_types" in item:
            subs = item["sub_types"]
            assert isinstance(subs, list), f"{label} sub_types must be a list"
            assert len(subs) > 0, f"{label} sub_types must not be empty"
            for sub_idx, sub in enumerate(subs):
                sub_label = f"{label}.sub_types[{sub_idx}]"
                assert isinstance(sub, dict), f"{sub_label} must be a dict"
                assert "name" in sub, f"{sub_label} missing 'name'"
                assert "name_th" in sub, f"{sub_label} missing 'name_th'"
                if "specify" in sub:
                    assert isinstance(sub["specify"], bool), f"{sub_label} specify must be boolean"

    # Check uniqueness
    seen: set[str] = set()
    for name in names:
        assert name not in seen, f"Duplicate underlying disease name: {name}"
        seen.add(name)


def test_underlying_diseases_alzheimer_removed():
    """Alzheimer disease should no longer be in the underlying diseases list."""
    repo_root = find_repo_root()
    diseases = load_yaml(repo_root / "v1" / "const" / "underlying_diseases.yaml")
    names = [d["name"] for d in diseases]
    assert "Alzheimer disease" not in names, "Alzheimer disease should be removed"


def test_underlying_diseases_new_entries():
    """Verify new diseases are present: Gout, Autoimmune, G6PD, Genetic, Congenital, Other."""
    repo_root = find_repo_root()
    diseases = load_yaml(repo_root / "v1" / "const" / "underlying_diseases.yaml")
    names = {d["name"] for d in diseases}

    expected_new = {
        "Gout",
        "Autoimmune disease",
        "G6PD deficiency",
        "Genetic disorder",
        "Congenital anomalies",
        "Other",
    }
    missing = expected_new - names
    assert not missing, f"Missing expected new diseases: {sorted(missing)}"


def test_underlying_diseases_heart_has_subtypes():
    """Heart disease must have sub_types defined."""
    repo_root = find_repo_root()
    diseases = load_yaml(repo_root / "v1" / "const" / "underlying_diseases.yaml")
    heart = next((d for d in diseases if d["name"] == "Heart disease"), None)
    assert heart is not None, "Heart disease not found"
    assert "sub_types" in heart, "Heart disease must have sub_types"
    assert len(heart["sub_types"]) >= 4, "Heart disease must have at least 4 sub_types"
