"""Shared test fixtures for ZettelForge test suite."""
import os
import pytest
from zettelforge.edition import reset_edition


@pytest.fixture
def enable_enterprise():
    """Temporarily enable Enterprise edition for tests that need it.

    Usage:
        def test_something(enable_enterprise):
            # Enterprise features are available here
            ...
    """
    os.environ["THREATENGRAM_LICENSE_KEY"] = "TG-1234-5678-9abc-def0"
    reset_edition()
    yield
    del os.environ["THREATENGRAM_LICENSE_KEY"]
    reset_edition()
