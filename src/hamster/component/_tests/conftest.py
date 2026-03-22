"""Pytest configuration for component tests.

Configures Home Assistant test infrastructure to find the hamster integration.
The pytest_plugins is loaded from the root conftest.py.
"""

from __future__ import annotations

# Verify the custom_components import works (path set in root conftest.py)
import custom_components.hamster  # noqa: F401
