"""Tests for supervisor unavailable scenarios.

Tests behavior when Supervisor is not available (e.g., core installation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamster.component.const import DOMAIN
from hamster.mcp._core.events import Done

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
        MockConfigEntry,
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for testing."""


@pytest.fixture(autouse=True)
def mock_http(hass: HomeAssistant) -> MagicMock:
    """Mock the hass.http component."""
    mock = MagicMock()
    mock.register_view = MagicMock()
    hass.http = mock
    return mock


class TestSupervisorUnavailable:
    """Tests for when Supervisor is unavailable."""

    async def test_supervisor_unavailable_search_returns_message(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that searching supervisor when unavailable returns clear message."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None
        assert supervisor_group.available is False

        result = supervisor_group.search("logs")
        assert "not available" in result.lower()

    async def test_supervisor_unavailable_explain_returns_none(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that explaining supervisor endpoint when unavailable returns None."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None

        result = supervisor_group.explain("core/logs")
        assert result is None

    async def test_supervisor_unavailable_has_command_returns_false(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that has_command returns False when supervisor unavailable."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None

        # Even known endpoints return False
        assert supervisor_group.has_command("core/logs") is False
        assert supervisor_group.has_command("supervisor/info") is False

    async def test_supervisor_unavailable_call_returns_error(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that calling supervisor endpoint when unavailable returns error."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None

        from hamster.mcp._core.types import TextContent

        effect = supervisor_group.parse_call_args("core/logs", {}, user_id="test_user")

        assert isinstance(effect, Done)
        assert effect.result.is_error is True
        assert len(effect.result.content) > 0
        # Check error message mentions unavailability
        first_content = effect.result.content[0]
        assert isinstance(first_content, TextContent)
        assert "not available" in first_content.text.lower()

    async def test_supervisor_not_in_search_all_when_unavailable(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that supervisor results don't appear in search_all when unavailable."""
        # Setup some services
        mock_descriptions = {
            "light": {
                "turn_on": {"description": "Turn on a light", "fields": {}},
            }
        }

        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value=mock_descriptions,
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Search for something that would match supervisor endpoints
        result = manager._registry.search_all("info")

        # Supervisor section should show unavailability message or be empty
        # The exact format depends on implementation, but it shouldn't
        # show actual supervisor endpoints
        # Note: search_all still includes the group, but shows unavailable message
        if "## supervisor" in result:
            # Should show unavailable message, not actual endpoints
            assert "not available" in result.lower() or "core/info" not in result


class TestOtherGroupsWorkWhenSupervisorUnavailable:
    """Tests that other groups work normally when supervisor is unavailable."""

    async def test_services_group_works(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that services group works when supervisor unavailable."""
        mock_descriptions = {
            "light": {
                "turn_on": {"description": "Turn on a light", "fields": {}},
            }
        }

        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value=mock_descriptions,
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        services_group = manager._registry.get("services")
        assert services_group is not None

        result = services_group.search("light")
        assert "light.turn_on" in result

    async def test_hass_group_works(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that hass group works when supervisor unavailable."""
        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
        }

        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=False),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        hass_group = manager._registry.get("hass")
        assert hass_group is not None

        result = hass_group.search("states")
        assert "get_states" in result
