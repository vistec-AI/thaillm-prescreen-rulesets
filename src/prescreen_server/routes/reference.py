"""Reference data endpoints — departments, severity levels, symptoms, diseases.

These are read-only endpoints that expose the constants loaded from
``v1/const/`` YAML files.  They don't require authentication since
the data is public reference information.
"""

from fastapi import APIRouter, Depends

from prescreen_rulesets.ruleset import RulesetStore

from prescreen_server.dependencies import get_store

router = APIRouter(prefix="/reference", tags=["reference"])


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/departments")
def list_departments(
    store: RulesetStore = Depends(get_store),
) -> list[dict]:
    """Return all hospital departments from the ruleset constants."""
    return [
        {
            "id": dept.id,
            "name": dept.name,
            "name_th": dept.name_th,
            "description": dept.description,
        }
        for dept in store.departments.values()
    ]


@router.get("/severity-levels")
def list_severity_levels(
    store: RulesetStore = Depends(get_store),
) -> list[dict]:
    """Return all severity/triage levels from the ruleset constants."""
    return [
        {
            "id": sev.id,
            "name": sev.name,
            "name_th": sev.name_th,
            "description": sev.description,
        }
        for sev in store.severity_levels.values()
    ]


@router.get("/symptoms")
def list_symptoms(
    store: RulesetStore = Depends(get_store),
) -> list[dict]:
    """Return all NHSO symptoms from the ruleset constants."""
    return [
        {
            "name": sym.name,
            "name_th": sym.name_th,
        }
        for sym in store.nhso_symptoms.values()
    ]


@router.get("/underlying-diseases")
def list_underlying_diseases(
    store: RulesetStore = Depends(get_store),
) -> list[dict]:
    """Return all underlying diseases from the ruleset constants."""
    return [
        {
            "name": d.name,
            "name_th": d.name_th,
        }
        for d in store.underlying_diseases
    ]
