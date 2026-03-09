"""Validation tests for `v1/rules/demographic.yaml`.

These checks enforce both baseline YAML schema and project-specific conventions
for demographic questions, including conditional field logic, new field types
(int, date, yes_no_detail), and detail_fields sub-structure.
"""

from pathlib import Path
from typing import Any

from helpers.utils import find_repo_root, load_yaml


_DEMO_RULES_PATH = Path("v1") / "rules" / "demographic.yaml"
_V1_DIR_NAME = "v1"
_QID_PREFIX = "demo_"
_ALLOWED_TYPES = {"datetime", "date", "enum", "float", "int", "from_yaml", "str", "yes_no_detail"}
_REQUIRED_KEYS = {"qid", "key", "field_name", "field_name_th", "type"}
# Allowed operators for condition blocks
_ALLOWED_CONDITION_OPS = {"eq", "ne", "lt", "le", "gt", "ge"}


def _load_demographic_rules() -> list[dict[str, Any]]:
    """Load demographic rules and validate root type early."""
    repo_root = find_repo_root()
    demographic_path = repo_root / _DEMO_RULES_PATH
    data = load_yaml(demographic_path)
    assert isinstance(data, list), "demographic.yaml root must be a list"
    return data


def _get_rules_by_type(rules: list[dict[str, Any]], rule_type: str) -> list[dict[str, Any]]:
    return [item for item in rules if item["type"] == rule_type]


def _assert_non_empty_string(value: object, label: str) -> None:
    assert isinstance(value, str) and value.strip(), f"{label} must be a non-empty string"


def _assert_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    assert not duplicates, f"Duplicate {label} found: {sorted(duplicates)}"


def test_demographic_schema_and_types():
    """Validate required keys, value types, optional flag, and new field semantics."""
    rules = _load_demographic_rules()
    assert len(rules) > 0, "demographic.yaml must contain at least one entry"

    for idx, item in enumerate(rules):
        entry_label = f"Entry {idx}"
        assert isinstance(item, dict), f"{entry_label} must be a dict"
        assert _REQUIRED_KEYS <= item.keys(), f"{entry_label} missing required keys"

        _assert_non_empty_string(item["qid"], f"{entry_label} qid")
        _assert_non_empty_string(item["key"], f"{entry_label} key")
        _assert_non_empty_string(item["field_name"], f"{entry_label} field_name")
        _assert_non_empty_string(item["field_name_th"], f"{entry_label} field_name_th")
        assert item["type"] in _ALLOWED_TYPES, f"{entry_label} has unsupported type {item['type']}"

        if "optional" in item:
            assert isinstance(item["optional"], bool), f"{entry_label} optional must be boolean"

        if "max_value" in item:
            assert isinstance(item["max_value"], int), f"{entry_label} max_value must be int"
            assert item["max_value"] > 0, f"{entry_label} max_value must be positive"


def test_demographic_qid_format_and_uniqueness():
    """Enforce qid naming convention: `demo_<name>` and no duplicates."""
    rules = _load_demographic_rules()
    qids = [item["qid"] for item in rules]

    _assert_unique(qids, "qid")

    for qid in qids:
        assert qid.startswith(_QID_PREFIX), f"qid {qid} must start with {_QID_PREFIX}"
        # Allow hyphens in the suffix (e.g. demo_age-months, demo_current-med)
        suffix = qid.removeprefix(_QID_PREFIX)
        assert suffix, f"qid {qid} must have a non-empty suffix after {_QID_PREFIX}"


def test_demographic_keys_are_unique():
    """Ensure each demographic entry maps to a unique key."""
    rules = _load_demographic_rules()
    keys = [item["key"] for item in rules]
    _assert_unique(keys, "key")


def test_demographic_enum_values_are_list():
    """For enum type, values must exist and be a non-empty string list."""
    rules = _load_demographic_rules()
    enum_rules = _get_rules_by_type(rules, "enum")
    assert len(enum_rules) > 0, "Expected at least one enum entry in demographic.yaml"

    for item in enum_rules:
        qid = item["qid"]
        assert "values" in item, f"Enum entry {qid} must have values"
        assert isinstance(item["values"], list), f"Enum entry {qid} values must be a list"
        assert len(item["values"]) > 0, f"Enum entry {qid} values must not be empty"
        assert all(isinstance(v, str) and v.strip() for v in item["values"]), \
            f"Enum entry {qid} values must be non-empty strings"


def test_demographic_from_yaml_values_path_exists_under_v1():
    """For from_yaml type, values must be a valid path string under v1/."""
    rules = _load_demographic_rules()
    from_yaml_rules = _get_rules_by_type(rules, "from_yaml")
    assert len(from_yaml_rules) > 0, "Expected at least one from_yaml entry in demographic.yaml"

    repo_root = find_repo_root()
    v1_dir = (repo_root / _V1_DIR_NAME).resolve()

    for item in from_yaml_rules:
        qid = item["qid"]
        values = item.get("values")
        _assert_non_empty_string(values, f"from_yaml entry {qid} values")

        value_path = Path(values)
        assert not value_path.is_absolute(), f"from_yaml entry {qid} values must be relative to v1/"

        # Resolve against v1/ and prevent escaping via `../` segments.
        resolved = (v1_dir / value_path).resolve()
        assert resolved.is_relative_to(v1_dir), f"from_yaml entry {qid} values must stay under v1/"
        assert resolved.exists(), f"from_yaml entry {qid} target file does not exist: {values}"
        assert resolved.is_file(), f"from_yaml entry {qid} target path must be a file: {values}"

        loaded = load_yaml(resolved)
        assert loaded is not None, f"from_yaml entry {qid} points to unreadable yaml: {values}"


def test_demographic_condition_blocks():
    """Validate condition blocks: required keys, valid operators, field references."""
    rules = _load_demographic_rules()
    all_keys = {item["key"] for item in rules}

    for item in rules:
        if "condition" not in item:
            continue
        qid = item["qid"]
        cond = item["condition"]

        assert isinstance(cond, dict), f"{qid} condition must be a dict"
        assert "field" in cond, f"{qid} condition must have 'field'"
        assert "op" in cond, f"{qid} condition must have 'op'"
        assert "value" in cond, f"{qid} condition must have 'value'"

        assert isinstance(cond["field"], str), f"{qid} condition.field must be a string"
        assert cond["op"] in _ALLOWED_CONDITION_OPS, (
            f"{qid} condition.op '{cond['op']}' not in {_ALLOWED_CONDITION_OPS}"
        )

        # The referenced field must exist in the same rule set
        assert cond["field"] in all_keys, (
            f"{qid} condition references unknown field '{cond['field']}'"
        )


def test_demographic_yes_no_detail_fields():
    """For yes_no_detail type, validate the field definition structure."""
    rules = _load_demographic_rules()
    ynd_rules = _get_rules_by_type(rules, "yes_no_detail")

    for item in ynd_rules:
        qid = item["qid"]
        # yes_no_detail fields may optionally have detail_fields
        if "detail_fields" in item:
            dfs = item["detail_fields"]
            assert isinstance(dfs, list), f"{qid} detail_fields must be a list"
            for df in dfs:
                assert isinstance(df, dict), f"{qid} detail_fields entry must be a dict"
                assert "key" in df, f"{qid} detail_fields entry missing 'key'"
                assert "type" in df, f"{qid} detail_fields entry missing 'type'"
                assert "field_name_th" in df, f"{qid} detail_fields entry missing 'field_name_th'"


def test_demographic_int_fields_valid():
    """For int type, validate optional max_value constraint."""
    rules = _load_demographic_rules()
    int_rules = _get_rules_by_type(rules, "int")
    assert len(int_rules) > 0, "Expected at least one int entry in demographic.yaml"

    for item in int_rules:
        qid = item["qid"]
        if "max_value" in item:
            assert isinstance(item["max_value"], int), f"{qid} max_value must be int"
            assert item["max_value"] > 0, f"{qid} max_value must be positive"
