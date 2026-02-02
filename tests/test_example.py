"""Example test file to demonstrate testing structure."""

import pytest


@pytest.mark.unit
def test_example():
    """Example unit test."""
    assert True


@pytest.mark.unit
def test_with_fixture(sample_fixture):
    """Example test using a fixture."""
    assert sample_fixture["key"] == "value"
