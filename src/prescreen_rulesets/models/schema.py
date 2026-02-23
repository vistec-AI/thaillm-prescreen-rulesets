"""Pydantic models for prescreening constants and reference data.

These models mirror the YAML files in ``v1/const/`` and ``v1/rules/``:

  Constants (from v1/const/):
    - DepartmentConst: hospital department with bilingual name, gender filter
    - SeverityConst: triage severity level with bilingual name
    - NHSOSymptom: NHSO symptom category with bilingual name
    - UnderlyingDisease: chronic condition with bilingual name
    - Disease: disease entry with severity/department references

  Rules (from v1/rules/):
    - DemographicField: phase 0 demographic question definition
    - ERCriticalItem: phase 1 yes/no critical check
    - ERChecklistItem: phase 3 checklist item with optional severity/department

  Legacy aliases:
    - SeverityLevel, NHSOSymptoms, Department — kept for backwards compatibility
      with existing test code.
"""

from typing import List, Optional

from pydantic import BaseModel


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


class UnderlyingDisease(BaseModel):
    """Chronic / underlying condition from underlying_diseases.yaml."""

    name: str
    name_th: str


class Disease(BaseModel):
    """Disease definition from diseases.yaml.

    ``available_severity`` lists which severity levels this disease can trigger.
    """

    id: str
    original_value: str
    disease_name: str
    name_th: str
    description: str
    available_severity: List[str]


# ---------------------------------------------------------------------------
# Rules — v1/rules/demographic.yaml
# ---------------------------------------------------------------------------

class DemographicField(BaseModel):
    """Phase 0 demographic question definition.

    ``type`` is one of: datetime, enum, float, from_yaml, str.
    ``values`` provides the option list for enum types or a YAML path for from_yaml.
    """

    qid: str
    key: str
    field_name: str
    field_name_th: str
    type: str
    values: Optional[List[str] | str] = None
    optional: bool = False


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


# ---------------------------------------------------------------------------
# Legacy aliases — kept so existing test imports continue working
# ---------------------------------------------------------------------------

# tests/helpers/data_model/schema.py originally exported these names
SeverityLevel = SeverityConst
NHSOSymptoms = NHSOSymptom
Department = DepartmentConst
