from helpers.data_model.schema import (
    Disease,
    NHSOSymptoms,
    Department
)
from helpers.loader import load_constants

constants = load_constants()


def test_load_constants():
    assert isinstance(constants, dict)
    assert all(k in constants for k in ["diseases", "nhso_symptoms", "severity_levels", "departments"])


def test_parse_disease():
    diseases = constants["diseases"]

    for d in diseases:
        Disease(**d)


def test_parse_nhso_symptoms():
    nhso_symptoms = constants["nhso_symptoms"]

    for s in nhso_symptoms:
        NHSOSymptoms(**s)


def test_parse_departments():
    departments = constants["departments"]

    for s in departments:
        Department(**s)
