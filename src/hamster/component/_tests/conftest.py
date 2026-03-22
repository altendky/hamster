"""Pytest configuration for component tests.

Imports custom_components.hamster before HA fixtures run. Without this early
import, HA's loader doesn't find the integration even though sys.path is set.
See also: conftest.py (root) for sys.path setup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

import custom_components.hamster  # noqa: F401
from hamster.component.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry with services group enabled for tests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hamster MCP",
        data={},
        options={"enable_services_group": True},
        entry_id="test_entry_id",
    )
    entry.add_to_hass(hass)
    return entry
