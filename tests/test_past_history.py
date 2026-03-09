"""Validation tests for `v1/rules/past_history.yaml` (Phase 5).

Validates field structure, QID conventions, condition blocks, and ensures
no key overlap with demographic fields.
"""

from pathlib import Path
from typing import Any

from helpers.utils import find_repo_root, load_yaml


_PAST_HISTORY_PATH = Path("v1") / "rules" / "past_history.yaml"
_DEMO_PATH = Path("v1") / "rules" / "demographic.yaml"
_QID_PREFIX = "past_"
_ALLOWED_TYPES = {"datetime", "date", "enum", "float", "int", "from_yaml", "str", "yes_no_detail"}
_REQUIRED_KEYS = {"qid", "key", "field_name", "field_name_th", "type"}
_ALLOWED_CONDITION_OPS = {"eq", "ne", "lt", "le", "gt", "ge"}


def _load_rules() -> list[dict[str, Any]]:
    """Load past history rules and validate root type."""
    repo_root = find_repo_root()
    data = load_yaml(repo_root / _PAST_HISTORY_PATH)
    assert isinstance(data, list), "past_history.yaml root must be a list"
    return data


def _load_demographic_keys() -> set[str]:
    """Load demographic field keys for overlap checking."""
    repo_root = find_repo_root()
    data = load_yaml(repo_root / _DEMO_PATH)
    return {item["key"] for item in data}


def test_past_history_schema_and_types():
    """Validate required keys and field types."""
    rules = _load_rules()
    assert len(rules) > 0, "past_history.yaml must contain at least one entry"

    for idx, item in enumerate(rules):
        label = f"Entry {idx} ({item.get('qid', '?')})"
        assert isinstance(item, dict), f"{label} must be a dict"
        assert _REQUIRED_KEYS <= item.keys(), f"{label} missing required keys"
        assert item["type"] in _ALLOWED_TYPES, f"{label} has unsupported type {item['type']}"

        if "optional" in item:
            assert isinstance(item["optional"], bool), f"{label} optional must be boolean"


def test_past_history_qid_format_and_uniqueness():
    """Enforce qid naming convention: `past_<name>` and no duplicates."""
    rules = _load_rules()
    qids = [item["qid"] for item in rules]

    # Check uniqueness
    seen: set[str] = set()
    for qid in qids:
        assert qid not in seen, f"Duplicate qid: {qid}"
        seen.add(qid)

    for qid in qids:
        assert qid.startswith(_QID_PREFIX), f"qid {qid} must start with {_QID_PREFIX}"
        suffix = qid.removeprefix(_QID_PREFIX)
        assert suffix, f"qid {qid} must have a non-empty suffix after {_QID_PREFIX}"


def test_past_history_keys_are_unique():
    """Ensure each entry maps to a unique key."""
    rules = _load_rules()
    keys = [item["key"] for item in rules]
    seen: set[str] = set()
    for key in keys:
        assert key not in seen, f"Duplicate key: {key}"
        seen.add(key)


def test_past_history_keys_no_overlap_with_demographics():
    """Past history keys must not overlap with demographic keys."""
    rules = _load_rules()
    past_keys = {item["key"] for item in rules}
    demo_keys = _load_demographic_keys()

    overlap = past_keys & demo_keys
    assert not overlap, f"Past history keys overlap with demographic keys: {sorted(overlap)}"


def test_past_history_condition_blocks():
    """Validate condition blocks reference valid fields and use valid operators."""
    rules = _load_rules()
    # Conditions can reference keys from demographics (e.g. age) or from
    # this file itself (e.g. vaccination_status).
    demo_keys = _load_demographic_keys()
    local_keys = {item["key"] for item in rules}
    all_valid_keys = demo_keys | local_keys

    for item in rules:
        if "condition" not in item:
            continue
        qid = item["qid"]
        cond = item["condition"]

        assert isinstance(cond, dict), f"{qid} condition must be a dict"
        assert "field" in cond, f"{qid} condition must have 'field'"
        assert "op" in cond, f"{qid} condition must have 'op'"
        assert "value" in cond, f"{qid} condition must have 'value'"
        assert cond["op"] in _ALLOWED_CONDITION_OPS, (
            f"{qid} condition.op '{cond['op']}' not in {_ALLOWED_CONDITION_OPS}"
        )
        assert cond["field"] in all_valid_keys, (
            f"{qid} condition references unknown field '{cond['field']}'"
        )


def test_past_history_enum_values():
    """For enum type, values must be a non-empty string list."""
    rules = _load_rules()
    enum_rules = [r for r in rules if r["type"] == "enum"]

    for item in enum_rules:
        qid = item["qid"]
        assert "values" in item, f"Enum entry {qid} must have values"
        assert isinstance(item["values"], list), f"Enum entry {qid} values must be a list"
        assert len(item["values"]) > 0, f"Enum entry {qid} values must not be empty"


def test_past_history_pediatric_fields_have_age_condition():
    """Pediatric-specific fields (vaccination, dev milestones) must have age < 15 condition."""
    rules = _load_rules()
    pediatric_qids = {"past_vaccination", "past_dev-milestones"}

    for item in rules:
        if item["qid"] in pediatric_qids:
            assert "condition" in item, (
                f"Pediatric field {item['qid']} must have a condition"
            )
            cond = item["condition"]
            assert cond["field"] == "age", (
                f"Pediatric field {item['qid']} condition must reference 'age'"
            )
            assert cond["op"] == "lt", (
                f"Pediatric field {item['qid']} condition must use 'lt' operator"
            )
