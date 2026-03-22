"""Tests for config_flow.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
import pytest

from hamster.component.config_flow import HamsterConfigFlow
from hamster.component.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for testing."""


async def test_form_shows_on_initial_step(hass: HomeAssistant) -> None:
    """Test that the form is shown on the initial step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result.get("errors") in (None, {})


async def test_entry_created_on_submit(hass: HomeAssistant) -> None:
    """Test that entry is created when form is submitted."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM

    # Submit the form (user_input is empty since we have no fields)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hamster MCP"
    assert result["data"] == {}


async def test_version_correct() -> None:
    """Test that the config flow has correct version."""
    # DOMAIN is set by the ConfigFlow decorator and stored differently
    assert HamsterConfigFlow.VERSION == 1


async def test_single_config_entry_abort(hass: HomeAssistant) -> None:
    """Test that a second config entry is aborted (single_config_entry).

    Note: We don't actually load/setup the entry since that requires HTTP
    infrastructure. The single_config_entry abort happens based on the
    entry existing in the config entries registry, not on it being loaded.
    """
    # First entry - complete the flow to create entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Second entry should be aborted - single_config_entry enforces this
    # at flow init time based on existing entries
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
