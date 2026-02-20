"""RulesetStore loading and lookup smoke tests.

Validates that RulesetStore loads all YAML rulesets from v1/ correctly
and that lookup methods return expected results.

Expected counts (from v1/const/ and v1/rules/):
    12 departments, 4 severity levels, 16 NHSO symptoms,
    8 demographic fields, 11 ER critical items
"""

import pytest

from prescreen_rulesets.ruleset import RulesetStore


@pytest.fixture(scope="session")
def store():
    """Load the full RulesetStore once for the entire test session."""
    s = RulesetStore()
    s.load()
    return s


# =====================================================================
# Loading tests — verify all reference data loads with correct counts
# =====================================================================


def test_store_loads_all_departments(store):
    """All 12 departments load and have required fields."""
    assert len(store.departments) == 12, (
        f"Expected 12 departments, got {len(store.departments)}"
    )
    for dept_id, dept in store.departments.items():
        assert dept.id == dept_id, f"Department key mismatch: {dept_id} vs {dept.id}"
        assert dept.name, f"Department {dept_id} missing name"
        assert dept.name_th, f"Department {dept_id} missing name_th"
        assert dept.description, f"Department {dept_id} missing description"


def test_store_loads_all_severity_levels(store):
    """All 4 severity levels load with correct IDs."""
    assert len(store.severity_levels) == 4, (
        f"Expected 4 severity levels, got {len(store.severity_levels)}"
    )
    expected_ids = {"sev001", "sev002", "sev002_5", "sev003"}
    assert set(store.severity_levels.keys()) == expected_ids, (
        f"Severity ID mismatch: {set(store.severity_levels.keys())} != {expected_ids}"
    )


def test_store_loads_all_nhso_symptoms(store):
    """All 16 NHSO symptoms load with bilingual names."""
    assert len(store.nhso_symptoms) == 16, (
        f"Expected 16 symptoms, got {len(store.nhso_symptoms)}"
    )
    for name, sym in store.nhso_symptoms.items():
        assert sym.name == name, f"Symptom key mismatch: {name} vs {sym.name}"
        assert sym.name_th, f"Symptom '{name}' missing name_th"


def test_store_loads_demographics(store):
    """8 demographic fields load with expected keys."""
    assert len(store.demographics) == 8, (
        f"Expected 8 demographic fields, got {len(store.demographics)}"
    )
    keys = {f.key for f in store.demographics}
    expected = {
        "date_of_birth", "gender", "height", "weight",
        "underlying_diseases", "medical_history", "occupation",
        "presenting_complaint",
    }
    assert keys == expected, f"Demographic key mismatch: {keys} != {expected}"


def test_store_loads_er_critical(store):
    """11 ER critical items load with correct qid prefix."""
    assert len(store.er_critical) == 11, (
        f"Expected 11 ER critical items, got {len(store.er_critical)}"
    )
    for item in store.er_critical:
        assert item.qid.startswith("emer_critical_"), (
            f"ER critical qid should start with 'emer_critical_': {item.qid}"
        )
        assert item.text, f"ER critical {item.qid} has empty text"


# =====================================================================
# Coverage tests — verify every symptom has trees and checklists
# =====================================================================


def test_store_oldcarts_covers_all_symptoms(store):
    """Every NHSO symptom has an OLDCARTS decision tree."""
    for name in store.nhso_symptoms:
        assert name in store.oldcarts, f"Symptom '{name}' missing from OLDCARTS"
        assert len(store.oldcarts[name]) > 0, (
            f"OLDCARTS tree for '{name}' has no questions"
        )


def test_store_opd_covers_all_symptoms(store):
    """Every NHSO symptom has an OPD decision tree."""
    for name in store.nhso_symptoms:
        assert name in store.opd, f"Symptom '{name}' missing from OPD"
        assert len(store.opd[name]) > 0, (
            f"OPD tree for '{name}' has no questions"
        )


def test_store_er_checklists_cover_all_symptoms(store):
    """Both adult and pediatric ER checklists cover all symptoms."""
    symptom_names = set(store.nhso_symptoms.keys())
    assert set(store.er_adult.keys()) == symptom_names, (
        "Adult ER checklist symptom set differs from NHSO symptoms"
    )
    assert set(store.er_pediatric.keys()) == symptom_names, (
        "Pediatric ER checklist symptom set differs from NHSO symptoms"
    )


# =====================================================================
# Lookup tests — verify get_* methods return valid data
# =====================================================================


def test_store_get_first_qid(store):
    """get_first_qid returns the first question for each symptom in both sources."""
    for name in store.nhso_symptoms:
        # OLDCARTS
        qid = store.get_first_qid("oldcarts", name)
        assert qid in store.oldcarts[name], (
            f"First OLDCARTS qid '{qid}' not found in tree for '{name}'"
        )
        # OPD
        qid = store.get_first_qid("opd", name)
        assert qid in store.opd[name], (
            f"First OPD qid '{qid}' not found in tree for '{name}'"
        )


def test_store_get_question_roundtrip(store):
    """get_question returns a valid typed Question model for every symptom."""
    for name in store.nhso_symptoms:
        first_qid = store.get_first_qid("oldcarts", name)
        q = store.get_question("oldcarts", name, first_qid)
        assert q.qid == first_qid, f"Question qid mismatch for {name}"
        assert q.question, f"Question text empty for {first_qid}"
        assert q.question_type, f"Question type empty for {first_qid}"


def test_store_resolve_department(store):
    """resolve_department returns dict with id, name, name_th, description."""
    result = store.resolve_department("dept001")
    assert result["id"] == "dept001", "Department id mismatch"
    assert "name" in result, "Missing 'name' in resolved department"
    assert "name_th" in result, "Missing 'name_th' in resolved department"
    assert "description" in result, "Missing 'description' in resolved department"


def test_store_resolve_severity(store):
    """resolve_severity returns dict with id, name, name_th, description."""
    result = store.resolve_severity("sev001")
    assert result["id"] == "sev001", "Severity id mismatch"
    assert "name" in result, "Missing 'name' in resolved severity"
    assert "name_th" in result, "Missing 'name_th' in resolved severity"
    assert "description" in result, "Missing 'description' in resolved severity"


def test_store_get_er_checklist_adult_vs_pediatric(store):
    """Adult and pediatric checklists return different items."""
    # Pick the first symptom for comparison
    symptom = next(iter(store.nhso_symptoms))

    adult_items = store.get_er_checklist(symptom, pediatric=False)
    pediatric_items = store.get_er_checklist(symptom, pediatric=True)

    assert isinstance(adult_items, list), "Adult checklist should be a list"
    assert isinstance(pediatric_items, list), "Pediatric checklist should be a list"

    # The two checklists should have different qid prefixes
    # (adult uses emer_adult_*, pediatric uses emer_ped_*)
    adult_qids = {item.qid for item in adult_items}
    pediatric_qids = {item.qid for item in pediatric_items}
    assert adult_qids != pediatric_qids, (
        f"Adult and pediatric checklists have identical qids for '{symptom}'"
    )
