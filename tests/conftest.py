import pytest

from helpers.loader import load_yaml, load_rules, load_constants


@pytest.fixture
def yml():
    return load_yaml

@pytest.fixture(scope="session")
def rules():
    return load_rules()

@pytest.fixture(scope="session")
def consts():
    return load_constants()
