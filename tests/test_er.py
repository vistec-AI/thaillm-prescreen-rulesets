"""Validation tests for ER rules:

- ``v1/rules/er/er_symptom.yaml``            (phase 1 — critical yes/no checks)
- ``v1/rules/er/er_adult_checklist.yaml``     (phase 3 — adult ER checklist)
- ``v1/rules/er/er_pediatric_checklist.yaml`` (phase 3 — pediatric ER checklist)

These tests validate schema correctness, QID naming conventions, and referential
integrity (severity/department IDs) against the local constant YAML files.
"""

from typing import Any

from helpers.utils import find_repo_root, load_yaml


# ---------------------------------------------------------------------------
# Paths — resolve once at module level so every test reuses them.
# find_repo_root() walks up until it hits pyproject.toml or .git.
# ---------------------------------------------------------------------------
_REPO_ROOT = find_repo_root()
_ER_DIR = _REPO_ROOT / "v1" / "rules" / "er"
_CONST_DIR = _REPO_ROOT / "v1" / "const"

# ---------------------------------------------------------------------------
# Load reference data from local v1/const/ (NOT from HuggingFace).
# We use local files because they are the authoritative source of truth,
# and we want tests to catch issues *before* anything is pushed.
# ---------------------------------------------------------------------------
_severity_levels: list[dict[str, Any]] = load_yaml(_CONST_DIR / "severity_levels.yaml")
_departments: list[dict[str, Any]] = load_yaml(_CONST_DIR / "departments.yaml")
_nhso_symptoms: list[dict[str, Any]] = load_yaml(_CONST_DIR / "nhso_symptoms.yaml")

# Build lookup sets for fast membership checks in tests.
_VALID_SEVERITY_IDS: set[str] = {s["id"] for s in _severity_levels}
_VALID_DEPARTMENT_IDS: set[str] = {d["id"] for d in _departments}
_VALID_SYMPTOM_NAMES: set[str] = {s["name"] for s in _nhso_symptoms}


# ===================================================================
# er_symptom.yaml  (phase 1 — critical yes/no checks)
#
# This file is a flat list of yes/no questions. If ANY answer is "yes",
# the patient is routed directly to Emergency (sev003 / dept002).
# Schema per item: { qid: str, text: str }  — no other fields allowed.
# ===================================================================

def _load_er_symptom() -> list[dict[str, Any]]:
    """Load er_symptom.yaml and verify the root is a list."""
    data = load_yaml(_ER_DIR / "er_symptom.yaml")
    assert isinstance(data, list), "er_symptom.yaml root must be a list"
    return data


def test_er_symptom_schema():
    """Each item must be a dict with exactly {qid, text} — no extra fields."""
    items = _load_er_symptom()
    assert len(items) > 0, "er_symptom.yaml must contain at least one entry"

    for idx, item in enumerate(items):
        # Build a human-readable label so assertion messages pinpoint the problem.
        label = f"er_symptom[{idx}]"
        assert isinstance(item, dict), f"{label} must be a dict"

        # --- Required keys ---
        assert "qid" in item, f"{label} missing 'qid'"
        assert "text" in item, f"{label} missing 'text'"

        # --- No extra keys (critical symptoms are simple yes/no, no overrides) ---
        allowed = {"qid", "text"}
        extra = set(item.keys()) - allowed
        assert not extra, f"{label} has unexpected keys: {extra}"

        # --- Type checks ---
        assert isinstance(item["qid"], str) and item["qid"].strip(), \
            f"{label} qid must be a non-empty string"
        assert isinstance(item["text"], str) and item["text"].strip(), \
            f"{label} text must be a non-empty string"


def test_er_symptom_qid_format_and_uniqueness():
    """QIDs must follow ``emer_critical_{number}`` and be unique."""
    items = _load_er_symptom()
    qids = [item["qid"] for item in items]

    # No duplicate QIDs
    assert len(set(qids)) == len(qids), \
        f"Duplicate qids in er_symptom.yaml: {[q for q in qids if qids.count(q) > 1]}"

    for qid in qids:
        # Convention: emer_critical_001, emer_critical_002, ...
        # Split into exactly 3 parts: ["emer", "critical", "001"]
        parts = qid.split("_")
        assert len(parts) == 3, \
            f"qid '{qid}' must have 3 parts separated by '_'"
        assert parts[0] == "emer", \
            f"qid '{qid}' must start with 'emer'"
        assert parts[1] == "critical", \
            f"qid '{qid}' second part must be 'critical'"
        assert parts[2].isdigit(), \
            f"qid '{qid}' third part must be numeric"


# ===================================================================
# er_adult_checklist.yaml  (phase 3 — adult ER checklist)
#
# Keyed by symptom name (e.g. "Headache", "Fever").  Each symptom maps
# to a list of checklist items.  Items without overrides default to
# Emergency (sev003 / dept002).
#
# Schema per item:
#   required: { qid: str, text: str }
#   optional: { min_severity: { id: str },        ← severity floor
#               department:   [{ id: str }, ...] }  ← department list
#
# "min_severity" means the patient's triage level is AT LEAST this
# severity — the downstream system may escalate but never downgrade.
# ===================================================================

def _load_er_adult_checklist() -> dict[str, list[dict[str, Any]]]:
    """Load er_adult_checklist.yaml and verify the root is a dict."""
    data = load_yaml(_ER_DIR / "er_adult_checklist.yaml")
    assert isinstance(data, dict), "er_adult_checklist.yaml root must be a dict"
    return data


def test_er_adult_checklist_symptom_keys():
    """Every symptom key must exist in nhso_symptoms.yaml."""
    checklist = _load_er_adult_checklist()
    for symptom in checklist:
        assert symptom in _VALID_SYMPTOM_NAMES, \
            f"Unknown symptom '{symptom}' in er_adult_checklist.yaml"


def test_er_adult_checklist_schema():
    """Validate item schema: {qid, text} required; optional min_severity and department."""
    checklist = _load_er_adult_checklist()
    _allowed_keys = {"qid", "text", "min_severity", "department"}

    for symptom, items in checklist.items():
        assert isinstance(items, list), \
            f"Adult checklist symptom '{symptom}' must be a list"

        for idx, item in enumerate(items):
            label = f"er_adult_checklist[{symptom}][{idx}]"
            assert isinstance(item, dict), f"{label} must be a dict"

            # --- Required keys ---
            assert "qid" in item, f"{label} missing 'qid'"
            assert "text" in item, f"{label} missing 'text'"

            # --- No unexpected keys (catches typos like "serverity") ---
            extra = set(item.keys()) - _allowed_keys
            assert not extra, f"{label} has unexpected keys: {extra}"

            # --- Type checks on required fields ---
            assert isinstance(item["qid"], str) and item["qid"].strip(), \
                f"{label} qid must be a non-empty string"
            assert isinstance(item["text"], str) and item["text"].strip(), \
                f"{label} text must be a non-empty string"


def test_er_adult_checklist_qid_format_and_uniqueness():
    """QIDs must follow ``emer_adult_{symptom_abbrev}{number}`` and be unique per symptom."""
    checklist = _load_er_adult_checklist()

    for symptom, items in checklist.items():
        qids = [item["qid"] for item in items]

        # Unique within this symptom
        assert len(set(qids)) == len(qids), \
            f"Duplicate qids in adult checklist '{symptom}'"

        for qid in qids:
            # Convention: emer_adult_hea001, emer_adult_diz002, ...
            # Split into exactly 3 parts: ["emer", "adult", "hea001"]
            parts = qid.split("_")
            assert len(parts) == 3, \
                f"qid '{qid}' must have 3 parts separated by '_' (got {len(parts)})"
            assert parts[0] == "emer", \
                f"qid '{qid}' must start with 'emer'"
            assert parts[1] == "adult", \
                f"qid '{qid}' second part must be 'adult'"
            # Third part is {symptom_abbrev}{number} (e.g. "hea001")
            assert len(parts[2]) > 0, \
                f"qid '{qid}' third part must be non-empty"

        # All QIDs under one symptom should share the same abbreviation prefix.
        # e.g. for Headache: all should start with "hea" (hea001, hea002, ...).
        # We strip trailing digits to extract the abbreviation.
        abbrevs = {item["qid"].split("_")[2].rstrip("0123456789") for item in items}
        assert len(abbrevs) <= 1, \
            f"Multiple abbreviation prefixes in adult checklist '{symptom}': {abbrevs}"


def test_er_adult_checklist_qid_globally_unique():
    """QIDs must be globally unique across all symptoms (not just within one)."""
    checklist = _load_er_adult_checklist()
    all_qids: list[str] = []
    for items in checklist.values():
        all_qids.extend(item["qid"] for item in items)
    assert len(set(all_qids)) == len(all_qids), \
        "Globally duplicate qids in er_adult_checklist.yaml"


def test_er_adult_checklist_min_severity_valid():
    """If min_severity is present, its id must exist in severity_levels.yaml."""
    checklist = _load_er_adult_checklist()

    for symptom, items in checklist.items():
        for idx, item in enumerate(items):
            if "min_severity" not in item:
                continue
            label = f"er_adult_checklist[{symptom}][{idx}] ({item['qid']})"

            # min_severity must be a dict like { id: "sev002_5" }
            sev = item["min_severity"]
            assert isinstance(sev, dict), f"{label} min_severity must be a dict"
            assert "id" in sev, f"{label} min_severity missing 'id'"
            assert isinstance(sev["id"], str), f"{label} min_severity.id must be a string"
            # Cross-reference against the constant file
            assert sev["id"] in _VALID_SEVERITY_IDS, \
                f"{label} min_severity.id '{sev['id']}' not in severity_levels"


def test_er_adult_checklist_department_valid():
    """If department is present, it must be a list of dicts with valid id."""
    checklist = _load_er_adult_checklist()

    for symptom, items in checklist.items():
        for idx, item in enumerate(items):
            if "department" not in item:
                continue
            label = f"er_adult_checklist[{symptom}][{idx}] ({item['qid']})"

            # department is a list like [{ id: "dept002" }, { id: "dept004" }]
            dept_list = item["department"]
            assert isinstance(dept_list, list), f"{label} department must be a list"
            assert len(dept_list) > 0, f"{label} department list must not be empty"

            for dept in dept_list:
                assert isinstance(dept, dict), \
                    f"{label} each department entry must be a dict"
                assert "id" in dept, \
                    f"{label} department entry missing 'id'"
                assert isinstance(dept["id"], str), \
                    f"{label} department.id must be a string"
                # Cross-reference against the constant file
                assert dept["id"] in _VALID_DEPARTMENT_IDS, \
                    f"{label} department.id '{dept['id']}' not in departments"


def test_er_adult_checklist_items_nonempty():
    """Every symptom must have at least one checklist item."""
    checklist = _load_er_adult_checklist()

    for symptom, items in checklist.items():
        assert len(items) > 0, f"Adult checklist symptom '{symptom}' has no items"


def test_er_adult_checklist_department_requires_min_severity():
    """If department override is present, min_severity must also be present.

    Rationale: a department override without a severity override would leave
    the severity at the default (Emergency), which may not be the intended
    behaviour for items that route to a non-ER department.
    """
    checklist = _load_er_adult_checklist()

    for symptom, items in checklist.items():
        for idx, item in enumerate(items):
            if "department" in item:
                label = f"er_adult_checklist[{symptom}][{idx}] ({item['qid']})"
                assert "min_severity" in item, \
                    f"{label} has department override but missing min_severity override"


# ===================================================================
# er_pediatric_checklist.yaml  (phase 3 — pediatric ER checklist)
#
# Same structure as the adult checklist but uses "severity" (exact
# override) instead of "min_severity" (floor).  An empty list ([])
# is allowed for symptoms with no pediatric-specific checks (e.g.
# "Muscle Pain: []").
#
# Schema per item:
#   required: { qid: str, text: str }
#   optional: { severity:   { id: str },           ← exact severity
#               department: [{ id: str }, ...] }    ← department list
# ===================================================================

def _load_er_pediatric_checklist() -> dict[str, list[dict[str, Any]]]:
    """Load er_pediatric_checklist.yaml and verify the root is a dict."""
    data = load_yaml(_ER_DIR / "er_pediatric_checklist.yaml")
    assert isinstance(data, dict), "er_pediatric_checklist.yaml root must be a dict"
    return data


def test_er_pediatric_checklist_symptom_keys():
    """Every symptom key must exist in nhso_symptoms.yaml."""
    checklist = _load_er_pediatric_checklist()
    for symptom in checklist:
        assert symptom in _VALID_SYMPTOM_NAMES, \
            f"Unknown symptom '{symptom}' in er_pediatric_checklist.yaml"


def test_er_pediatric_checklist_schema():
    """Validate item schema: {qid, text} required; optional severity and department."""
    checklist = _load_er_pediatric_checklist()
    _allowed_keys = {"qid", "text", "severity", "department"}

    for symptom, items in checklist.items():
        assert isinstance(items, list), \
            f"Pediatric checklist symptom '{symptom}' must be a list"

        for idx, item in enumerate(items):
            label = f"er_pediatric_checklist[{symptom}][{idx}]"
            assert isinstance(item, dict), f"{label} must be a dict"

            # --- Required keys ---
            assert "qid" in item, f"{label} missing 'qid'"
            assert "text" in item, f"{label} missing 'text'"

            # --- No unexpected keys ---
            extra = set(item.keys()) - _allowed_keys
            assert not extra, f"{label} has unexpected keys: {extra}"

            # --- Type checks on required fields ---
            assert isinstance(item["qid"], str) and item["qid"].strip(), \
                f"{label} qid must be a non-empty string"
            assert isinstance(item["text"], str) and item["text"].strip(), \
                f"{label} text must be a non-empty string"


def test_er_pediatric_checklist_qid_format_and_uniqueness():
    """QIDs must follow ``emer_ped_{symptom_abbrev}{number}`` and be unique per symptom."""
    checklist = _load_er_pediatric_checklist()

    for symptom, items in checklist.items():
        # Some symptoms may have an empty list (e.g. "Muscle Pain: []"),
        # which is valid — skip them.
        if len(items) == 0:
            continue

        qids = [item["qid"] for item in items]

        # Unique within this symptom
        assert len(set(qids)) == len(qids), \
            f"Duplicate qids in pediatric checklist '{symptom}'"

        for qid in qids:
            # Convention: emer_ped_hea001, emer_ped_fev002, ...
            # Split into exactly 3 parts: ["emer", "ped", "hea001"]
            parts = qid.split("_")
            assert len(parts) == 3, \
                f"qid '{qid}' must have 3 parts separated by '_' (got {len(parts)})"
            assert parts[0] == "emer", \
                f"qid '{qid}' must start with 'emer'"
            assert parts[1] == "ped", \
                f"qid '{qid}' second part must be 'ped'"
            assert len(parts[2]) > 0, \
                f"qid '{qid}' third part must be non-empty"

        # All QIDs under one symptom should share the same abbreviation prefix.
        abbrevs = {item["qid"].split("_")[2].rstrip("0123456789") for item in items}
        assert len(abbrevs) <= 1, \
            f"Multiple abbreviation prefixes in pediatric checklist '{symptom}': {abbrevs}"


def test_er_pediatric_checklist_qid_globally_unique():
    """QIDs must be globally unique across all symptoms."""
    checklist = _load_er_pediatric_checklist()
    all_qids: list[str] = []
    for items in checklist.values():
        all_qids.extend(item["qid"] for item in items)
    assert len(set(all_qids)) == len(all_qids), \
        "Globally duplicate qids in er_pediatric_checklist.yaml"


def test_er_pediatric_checklist_severity_valid():
    """If severity is present, its id must exist in severity_levels.yaml."""
    checklist = _load_er_pediatric_checklist()

    for symptom, items in checklist.items():
        for idx, item in enumerate(items):
            if "severity" not in item:
                continue
            label = f"er_pediatric_checklist[{symptom}][{idx}] ({item['qid']})"

            # severity must be a dict like { id: "sev002_5" }
            sev = item["severity"]
            assert isinstance(sev, dict), f"{label} severity must be a dict"
            assert "id" in sev, f"{label} severity missing 'id'"
            assert isinstance(sev["id"], str), f"{label} severity.id must be a string"
            # Cross-reference against the constant file
            assert sev["id"] in _VALID_SEVERITY_IDS, \
                f"{label} severity.id '{sev['id']}' not in severity_levels"


def test_er_pediatric_checklist_department_valid():
    """If department is present, it must be a list of dicts with valid id."""
    checklist = _load_er_pediatric_checklist()

    for symptom, items in checklist.items():
        for idx, item in enumerate(items):
            if "department" not in item:
                continue
            label = f"er_pediatric_checklist[{symptom}][{idx}] ({item['qid']})"

            # department is a list like [{ id: "dept002" }]
            dept_list = item["department"]
            assert isinstance(dept_list, list), f"{label} department must be a list"
            assert len(dept_list) > 0, f"{label} department list must not be empty"

            for dept in dept_list:
                assert isinstance(dept, dict), \
                    f"{label} each department entry must be a dict"
                assert "id" in dept, \
                    f"{label} department entry missing 'id'"
                assert isinstance(dept["id"], str), \
                    f"{label} department.id must be a string"
                # Cross-reference against the constant file
                assert dept["id"] in _VALID_DEPARTMENT_IDS, \
                    f"{label} department.id '{dept['id']}' not in departments"


def test_er_pediatric_checklist_department_requires_severity():
    """If department override is present, severity must also be present.

    Rationale: same as the adult checklist — overriding the department
    without also overriding severity would leave severity at the default
    (Emergency), which is likely unintended for non-ER departments.
    """
    checklist = _load_er_pediatric_checklist()

    for symptom, items in checklist.items():
        for idx, item in enumerate(items):
            if "department" in item:
                label = f"er_pediatric_checklist[{symptom}][{idx}] ({item['qid']})"
                assert "severity" in item, \
                    f"{label} has department override but missing severity override"


# ===================================================================
# ER early-exit sanity check
#
# When an ER checklist item effectively routes to Emergency severity
# (sev003), the department must include Emergency Medicine (dept002).
# An emergency patient being routed to a non-ER department (e.g.
# Dermatology) would be a data error.
# ===================================================================

def test_er_emergency_severity_requires_er_department():
    """If an ER item has Emergency severity (sev003), its department must include dept002.

    This applies to both explicit overrides and the implicit default:
    - Items WITHOUT overrides default to sev003 + dept002 (always valid,
      no check needed since the schema forbids extra keys).
    - Items WITH a severity override of sev003 must also route to dept002.
      They may include additional departments, but dept002 must be present.
    """
    # --- Adult checklist: uses "min_severity" key ---
    adult = _load_er_adult_checklist()
    for symptom, items in adult.items():
        for idx, item in enumerate(items):
            # Skip items without severity override — they default to sev003/dept002
            if "min_severity" not in item:
                continue
            label = f"er_adult_checklist[{symptom}][{idx}] ({item['qid']})"

            effective_sev = item["min_severity"].get("id", "sev003")
            if effective_sev == "sev003" and "department" in item:
                dept_ids = [d["id"] for d in item["department"]]
                assert "dept002" in dept_ids, (
                    f"{label} has Emergency severity (sev003) but department "
                    f"override {dept_ids} does not include Emergency Medicine (dept002)"
                )

    # --- Pediatric checklist: uses "severity" key ---
    pediatric = _load_er_pediatric_checklist()
    for symptom, items in pediatric.items():
        for idx, item in enumerate(items):
            if "severity" not in item:
                continue
            label = f"er_pediatric_checklist[{symptom}][{idx}] ({item['qid']})"

            effective_sev = item["severity"].get("id", "sev003")
            if effective_sev == "sev003" and "department" in item:
                dept_ids = [d["id"] for d in item["department"]]
                assert "dept002" in dept_ids, (
                    f"{label} has Emergency severity (sev003) but department "
                    f"override {dept_ids} does not include Emergency Medicine (dept002)"
                )


# ===================================================================
# Cross-file consistency
#
# These tests check invariants that span multiple ER files to catch
# issues like a symptom being present in one checklist but not the
# other, or QID collisions between files.
# ===================================================================

def test_er_checklists_cover_same_symptoms():
    """Adult and pediatric checklists should cover the same set of symptom keys."""
    adult = _load_er_adult_checklist()
    pediatric = _load_er_pediatric_checklist()

    adult_symptoms = set(adult.keys())
    pediatric_symptoms = set(pediatric.keys())

    assert adult_symptoms == pediatric_symptoms, (
        f"Symptom key mismatch between adult and pediatric checklists. "
        f"Only in adult: {adult_symptoms - pediatric_symptoms}. "
        f"Only in pediatric: {pediatric_symptoms - adult_symptoms}."
    )


def test_er_no_qid_collision_across_files():
    """QIDs must not collide between er_symptom, adult checklist, and pediatric checklist.

    Each file uses a different prefix (emer_critical_, emer_adult_, emer_ped_)
    so collisions should be impossible — but this test catches copy-paste
    mistakes or accidental prefix reuse.
    """
    symptom_qids = {item["qid"] for item in _load_er_symptom()}

    adult_qids: set[str] = set()
    for items in _load_er_adult_checklist().values():
        adult_qids.update(item["qid"] for item in items)

    pediatric_qids: set[str] = set()
    for items in _load_er_pediatric_checklist().values():
        pediatric_qids.update(item["qid"] for item in items)

    overlap_sa = symptom_qids & adult_qids
    overlap_sp = symptom_qids & pediatric_qids
    overlap_ap = adult_qids & pediatric_qids

    assert not overlap_sa, \
        f"QID collision between er_symptom and adult checklist: {overlap_sa}"
    assert not overlap_sp, \
        f"QID collision between er_symptom and pediatric checklist: {overlap_sp}"
    assert not overlap_ap, \
        f"QID collision between adult and pediatric checklist: {overlap_ap}"
