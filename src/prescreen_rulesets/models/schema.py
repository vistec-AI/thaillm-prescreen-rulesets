"""Pydantic models for prescreening constants and reference data.

These models mirror the YAML files in ``v1/const/`` and ``v1/rules/``:

  Constants (from v1/const/):
    - DepartmentConst: hospital department with bilingual name, gender filter
    - SeverityConst: triage severity level with bilingual name
    - NHSOSymptom: NHSO symptom category with bilingual name
    - UnderlyingDisease: chronic condition with bilingual name (+ sub_types, specify)
    - Disease: disease entry with severity/department references

  Rules (from v1/rules/):
    - DemographicField: demographic/past-history/personal-history question definition
    - ERCriticalItem: phase 1 yes/no critical check
    - ERChecklistItem: phase 3 checklist item with optional severity/department

  Supporting models:
    - FieldCondition: conditional visibility for demographic fields
    - UnderlyingDiseaseSubType: sub-type under a disease (e.g. CAD under Heart disease)
    - DetailField: follow-up field for yes_no_detail type

  Legacy aliases:
    - SeverityLevel, NHSOSymptoms, Department — kept for backwards compatibility
      with existing test code.
"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants — v1/const/*.yaml
# ---------------------------------------------------------------------------

class DepartmentConst(BaseModel):
    """Hospital department from departments.yaml.

    ``genders`` controls which patients see this department (e.g. "any", "female").
    """

    id: str
    name: str
    name_th: str
    description: str
    genders: str = "any"


class SeverityConst(BaseModel):
    """Triage severity level from severity_levels.yaml.

    The 4 levels are: sev001 (Observe at Home), sev002 (Visit Hospital),
    sev002_5 (Visit Urgently), sev003 (Emergency).
    """

    id: str
    name: str
    name_th: str
    description: str


class NHSOSymptom(BaseModel):
    """NHSO symptom category from nhso_symptoms.yaml."""

    name: str
    name_th: str


class UnderlyingDiseaseSubType(BaseModel):
    """Sub-type under an underlying disease (e.g. CAD under Heart disease)."""

    name: str
    name_th: str
    specify: bool = False


class UnderlyingDisease(BaseModel):
    """Chronic / underlying condition from underlying_diseases.yaml."""

    name: str
    name_th: str
    sub_types: Optional[List[UnderlyingDiseaseSubType]] = None
    specify: bool = False


class Disease(BaseModel):
    """Disease definition from diseases.yaml.

    ``available_severity`` lists which severity levels this disease can trigger.
    ``departments`` lists which hospital departments handle this disease.
    """

    id: str
    original_value: str
    disease_name: str
    name_th: str
    description: str
    available_severity: List[str]
    departments: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Supporting models for demographic/bulk-collection fields
# ---------------------------------------------------------------------------

class FieldCondition(BaseModel):
    """Condition controlling whether a demographic field is shown/required.

    Evaluated against already-collected demographics. For example,
    ``{"field": "gender", "op": "eq", "value": "Female"}`` means the field
    is only relevant when the patient's gender is Female.
    """

    field: str      # key of the field to check (e.g. "age", "gender")
    op: str         # operator: eq, ne, lt, le, gt, ge
    value: Any      # expected value


class DetailField(BaseModel):
    """Follow-up field for yes_no_detail type.

    When the parent field's answer is True/yes, these sub-fields are
    collected as part of the detail.
    """

    key: str
    type: str
    field_name_th: str
    values: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Rules — v1/rules/demographic.yaml, past_history.yaml, personal_history.yaml
# ---------------------------------------------------------------------------

class DemographicField(BaseModel):
    """Demographic / bulk-collection question definition.

    Used for phase 0 (Demographics), phase 5 (Past History), and
    phase 6 (Personal History).

    ``type`` is one of: datetime, date, enum, float, int, from_yaml,
    str, yes_no_detail.
    ``values`` provides the option list for enum types or a YAML path
    for from_yaml.
    ``condition`` controls conditional visibility based on other fields.
    ``detail_fields`` provides follow-up fields for yes_no_detail type.
    ``max_value`` sets an upper bound (e.g. gestational age max 42).
    """

    qid: str
    key: str
    field_name: str
    field_name_th: str
    type: str
    values: Optional[List[str] | str] = None
    optional: bool = False
    condition: Optional[FieldCondition] = None
    detail_fields: Optional[List[DetailField]] = None
    max_value: Optional[int] = None


# ---------------------------------------------------------------------------
# Rules — v1/rules/er/
# ---------------------------------------------------------------------------

class ERCriticalItem(BaseModel):
    """Phase 1 ER critical yes/no check from er_symptom.yaml.

    If ANY critical item is positive, the session terminates immediately
    with severity=sev003 and department=dept002 (Emergency Medicine).
    """

    qid: str
    text: str
    # Optional custom reason shown when this item triggers early termination.
    # If omitted, the engine auto-generates a technical reason string.
    reason: Optional[str] = None
    # Optional condition controlling visibility based on demographics.
    # Uses the same FieldCondition model as demographic/past-history fields.
    # When present, the item is only shown if the condition is satisfied.
    condition: Optional[FieldCondition] = None


class ERChecklistItem(BaseModel):
    """Phase 3 ER checklist item from er_adult_checklist.yaml or er_pediatric_checklist.yaml.

    Adult items use ``min_severity`` (severity floor); pediatric items use
    ``severity`` (exact match).  Both are treated the same way by the engine:
    first positive item wins.

    Items without explicit severity default to sev003 (Emergency).
    Items without explicit department default to dept002 (Emergency Medicine).
    """

    qid: str
    text: str
    # Adult checklist uses min_severity, pediatric uses severity — both optional
    min_severity: Optional[dict] = None
    severity: Optional[dict] = None
    department: Optional[List[dict]] = None
    # Optional custom reason shown when this item triggers early termination.
    # If omitted, the engine auto-generates a technical reason string.
    reason: Optional[str] = None
    # Optional condition controlling visibility based on demographics.
    # When present, the item is only shown if the condition is satisfied.
    # Example: emer_ped_vag004 shown only for females.
    condition: Optional[FieldCondition] = None
    # Optional auto-complete condition — when met, the item is automatically
    # answered as positive (true) and triggers termination.  When not met,
    # the item is hidden (the answer is definitively false).
    # Example: emer_ped_cou006 auto-completes when age < 1 year.
    auto_complete: Optional[FieldCondition] = None


# ---------------------------------------------------------------------------
# Legacy aliases — kept so existing test imports continue working
# ---------------------------------------------------------------------------

# tests/helpers/data_model/schema.py originally exported these names
SeverityLevel = SeverityConst
NHSOSymptoms = NHSOSymptom
Department = DepartmentConst
