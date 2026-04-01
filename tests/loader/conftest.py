"""YAML loader tests use real ``load_config`` (no mock config patch)."""

import pytest


@pytest.fixture(autouse=True)
def _patch_config():
    """Shadow parent ``tests/conftest.py`` autouse patch so loader tests hit real YAML."""
    yield
