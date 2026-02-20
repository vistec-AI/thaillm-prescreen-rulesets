"""Prescreening constants shared across the SDK.

These values are referenced by the engine, evaluator, and ruleset store.
They mirror conventions encoded in the YAML rulesets under ``v1/``.
"""

# Severity IDs ordered from least to most severe.
# Used to compare severity levels when multiple ER checklist items match.
SEVERITY_ORDER: list[str] = ["sev001", "sev002", "sev002_5", "sev003"]

# Default severity/department for ER critical items (phase 1) and
# ER checklist items (phase 3) that lack explicit overrides.
DEFAULT_ER_SEVERITY = "sev003"
DEFAULT_ER_DEPARTMENT = "dept002"

# Patients younger than this age use the pediatric ER checklist (phase 3).
PEDIATRIC_AGE_THRESHOLD = 15

# Human-readable phase names for API responses and logging.
PHASE_NAMES: dict[int, str] = {
    0: "Demographics",
    1: "ER Critical Screen",
    2: "Symptom Selection",
    3: "ER Checklist",
    4: "OLDCARTS",
    5: "OPD",
}

# Auto-evaluated question types that the engine resolves without user input.
# These are never shown to the patient.
AUTO_EVAL_TYPES: set[str] = {"gender_filter", "age_filter", "conditional"}
