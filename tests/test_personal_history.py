"""Validation tests for `v1/rules/personal_history.yaml` (Phase 6).

Validates field structure, QID conventions, occupation enum values,
detail_fields for smoking/alcohol, and no key overlap with other phases.
"""

from pathlib import Path
from typing import Any

from helpers.utils import find_repo_root, load_yaml


_PERSONAL_HISTORY_PATH = Path("v1") / "rules" / "personal_history.yaml"
_DEMO_PATH = Path("v1") / "rules" / "demographic.yaml"
_PAST_HISTORY_PATH = Path("v1") / "rules" / "past_history.yaml"
_QID_PREFIX = "pers_"
_ALLOWED_TYPES = {"datetime", "date", "enum", "float", "int", "from_yaml", "str", "yes_no_detail"}
_REQUIRED_KEYS = {"qid", "key", "field_name", "field_name_th", "type"}


def _load_rules() -> list[dict[str, Any]]:
    """Load personal history rules and validate root type."""
    repo_root = find_repo_root()
    data = load_yaml(repo_root / _PERSONAL_HISTORY_PATH)
    assert isinstance(data, list), "personal_history.yaml root must be a list"
    return data


def test_personal_history_schema_and_types():
    """Validate required keys and field types."""
    rules = _load_rules()
    assert len(rules) > 0, "personal_history.yaml must contain at least one entry"

    for idx, item in enumerate(rules):
        label = f"Entry {idx} ({item.get('qid', '?')})"
        assert isinstance(item, dict), f"{label} must be a dict"
        assert _REQUIRED_KEYS <= item.keys(), f"{label} missing required keys"
        assert item["type"] in _ALLOWED_TYPES, f"{label} has unsupported type {item['type']}"


def test_personal_history_qid_format_and_uniqueness():
    """Enforce qid naming convention: `pers_<name>` and no duplicates."""
    rules = _load_rules()
    qids = [item["qid"] for item in rules]

    seen: set[str] = set()
    for qid in qids:
        assert qid not in seen, f"Duplicate qid: {qid}"
        seen.add(qid)

    for qid in qids:
        assert qid.startswith(_QID_PREFIX), f"qid {qid} must start with {_QID_PREFIX}"
        suffix = qid.removeprefix(_QID_PREFIX)
        assert suffix, f"qid {qid} must have a non-empty suffix after {_QID_PREFIX}"


def test_personal_history_keys_are_unique():
    """Ensure each entry maps to a unique key."""
    rules = _load_rules()
    keys = [item["key"] for item in rules]
    seen: set[str] = set()
    for key in keys:
        assert key not in seen, f"Duplicate key: {key}"
        seen.add(key)


def test_personal_history_keys_no_overlap_with_other_phases():
    """Personal history keys must not overlap with demographic or past history keys."""
    repo_root = find_repo_root()
    rules = _load_rules()
    personal_keys = {item["key"] for item in rules}

    demo_data = load_yaml(repo_root / _DEMO_PATH)
    demo_keys = {item["key"] for item in demo_data}

    past_data = load_yaml(repo_root / _PAST_HISTORY_PATH)
    past_keys = {item["key"] for item in past_data}

    overlap_demo = personal_keys & demo_keys
    assert not overlap_demo, (
        f"Personal history keys overlap with demographic keys: {sorted(overlap_demo)}"
    )

    overlap_past = personal_keys & past_keys
    assert not overlap_past, (
        f"Personal history keys overlap with past history keys: {sorted(overlap_past)}"
    )


def test_personal_history_occupation_enum():
    """Occupation field must be an enum with the expected values."""
    rules = _load_rules()
    occupation = next((r for r in rules if r["key"] == "occupation"), None)
    assert occupation is not None, "Missing occupation field"
    assert occupation["type"] == "enum", "Occupation must be enum type"
    assert isinstance(occupation["values"], list), "Occupation values must be a list"
    assert len(occupation["values"]) > 0, "Occupation must have at least one value"
    assert "other" in occupation["values"], "Occupation must include 'other' option"


def test_personal_history_detail_fields():
    """Smoking and alcohol fields must have detail_fields with valid structure."""
    rules = _load_rules()
    ynd_rules = [r for r in rules if r["type"] == "yes_no_detail"]
    assert len(ynd_rules) >= 2, "Expected at least 2 yes_no_detail fields (smoking, alcohol)"

    for item in ynd_rules:
        qid = item["qid"]
        if "detail_fields" in item:
            dfs = item["detail_fields"]
            assert isinstance(dfs, list), f"{qid} detail_fields must be a list"
            assert len(dfs) > 0, f"{qid} detail_fields must not be empty"

            for df in dfs:
                assert isinstance(df, dict), f"{qid} detail_fields entry must be a dict"
                assert "key" in df, f"{qid} detail_fields entry missing 'key'"
                assert "type" in df, f"{qid} detail_fields entry missing 'type'"
                assert "field_name_th" in df, f"{qid} detail_fields entry missing 'field_name_th'"

                # Enum detail fields must have values
                if df["type"] == "enum":
                    assert "values" in df, (
                        f"{qid} detail_field {df['key']} with type 'enum' must have 'values'"
                    )
                    assert isinstance(df["values"], list), (
                        f"{qid} detail_field {df['key']} values must be a list"
                    )


def test_personal_history_smoking_has_detail_fields():
    """Smoking field must have cigarettes_per_day and smoking_years detail fields."""
    rules = _load_rules()
    smoking = next((r for r in rules if r["key"] == "smoking_history"), None)
    assert smoking is not None, "Missing smoking_history field"
    assert "detail_fields" in smoking, "smoking_history must have detail_fields"

    detail_keys = {df["key"] for df in smoking["detail_fields"]}
    assert "cigarettes_per_day" in detail_keys, "Missing cigarettes_per_day detail field"
    assert "smoking_years" in detail_keys, "Missing smoking_years detail field"


def test_personal_history_alcohol_has_detail_fields():
    """Alcohol field must have drinking_frequency and drinking_years detail fields."""
    rules = _load_rules()
    alcohol = next((r for r in rules if r["key"] == "alcohol_history"), None)
    assert alcohol is not None, "Missing alcohol_history field"
    assert "detail_fields" in alcohol, "alcohol_history must have detail_fields"

    detail_keys = {df["key"] for df in alcohol["detail_fields"]}
    assert "drinking_frequency" in detail_keys, "Missing drinking_frequency detail field"
    assert "drinking_years" in detail_keys, "Missing drinking_years detail field"
