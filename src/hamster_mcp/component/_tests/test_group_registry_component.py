"""Tests for group registry component integration.

Tests GroupRegistry behavior within the component context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamster_mcp.component.const import DOMAIN
from hamster_mcp.mcp._core.groups import ServicesGroup

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


class TestGroupRegistryStartup:
    """Tests for registry startup behavior."""

    async def test_registry_starts_empty_before_setup(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that registry starts empty before groups are registered."""
        from hamster_mcp.mcp._core.groups import GroupRegistry

        registry = GroupRegistry()
        assert registry.get("services") is None
        assert registry.get("hass") is None
        assert registry.get("supervisor") is None

    async def test_groups_registered_after_setup(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that groups are registered after setup."""
        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        all_groups = manager._registry.all_groups()
        assert len(all_groups) == 3

        group_names = {g.name for g in all_groups}
        assert group_names == {"services", "hass", "supervisor"}


class TestGroupRegistryUpdateServices:
    """Tests for updating services group."""

    async def test_update_group_replaces_services(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that update_group replaces the existing services group."""
        initial_descriptions: dict[str, dict[str, object]] = {
            "light": {"turn_on": {"description": "Turn on", "fields": {}}}
        }

        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=initial_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Initial state
        result = manager._registry.search_all("light")
        assert "light.turn_on" in result

        # Update with new descriptions
        new_descriptions: dict[str, dict[str, object]] = {
            "switch": {"toggle": {"description": "Toggle", "fields": {}}}
        }
        new_services_group = ServicesGroup(new_descriptions)
        manager._registry.update_group(new_services_group)

        # Old service gone, new service present
        result = manager._registry.search_all("light")
        assert "light.turn_on" not in result

        result = manager._registry.search_all("switch")
        assert "switch.toggle" in result


class TestGroupRegistrySearchAll:
    """Tests for search_all aggregation."""

    async def test_search_all_aggregates_results(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that search_all aggregates results from all groups."""
        mock_descriptions = {
            "light": {"turn_on": {"description": "Turn on light", "fields": {}}}
        }

        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "config/light_registry/list": (mock_handler, False),
        }

        with (
            patch(
                "hamster_mcp.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value=mock_descriptions,
            ),
            patch("hamster_mcp.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Search for "light" should find results in multiple groups
        result = manager._registry.search_all("light")

        # Should have group headers
        assert "## services" in result
        assert "## hass" in result

    async def test_search_all_with_path_filter(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test search_all with path_filter restricts to group."""
        mock_descriptions = {
            "light": {"turn_on": {"description": "Turn on", "fields": {}}}
        }

        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
        }

        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=mock_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Filter to services only
        result = manager._registry.search_all("turn", path_filter="services")
        assert "light.turn_on" in result
        assert "## hass" not in result
        assert "## supervisor" not in result

    async def test_search_all_empty_results(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test search_all with no matches."""
        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.search_all("nonexistent_query_xyz")
        assert "No commands found" in result


class TestGroupRegistryResolvePath:
    """Tests for resolve_path."""

    async def test_resolve_path_parses_correctly(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that resolve_path correctly parses group/path."""
        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Services path
        result = manager._registry.resolve_path("services/light.turn_on")
        assert result is not None
        group, path = result
        assert group.name == "services"
        assert path == "light.turn_on"

        # Hass path with nested command
        result = manager._registry.resolve_path("hass/config/entity_registry/list")
        assert result is not None
        group, path = result
        assert group.name == "hass"
        assert path == "config/entity_registry/list"

    async def test_resolve_path_empty_string(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test resolve_path with empty string."""
        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("")
        assert result is None

    async def test_resolve_path_no_slash(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test resolve_path with no slash."""
        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("nogroup")
        assert result is None

    async def test_resolve_path_trailing_slash(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test resolve_path with group/ (trailing slash)."""
        with patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("services/")
        assert result is not None
        group, path = result
        assert group.name == "services"
        assert path == ""
