"""Tests for multi-source integration.

Tests the full flow: search -> explain -> call for all three groups
(services, hass, supervisor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamster.component.const import DOMAIN

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


@pytest.fixture
def mock_descriptions() -> dict[str, dict[str, object]]:
    """Mock service descriptions."""
    return {
        "light": {
            "turn_on": {
                "description": "Turn on a light",
                "fields": {
                    "brightness": {
                        "description": "Brightness value",
                        "selector": {"number": {}},
                    }
                },
            },
            "turn_off": {"description": "Turn off a light", "fields": {}},
        },
        "switch": {
            "toggle": {"description": "Toggle a switch", "fields": {}},
        },
    }


class TestServicesGroupFlow:
    """Tests for services group full flow."""

    async def test_search_services(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test searching services group."""
        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=mock_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Search in services group
        services_group = manager._registry.get("services")
        assert services_group is not None

        result = services_group.search("light")
        assert "light.turn_on" in result
        assert "light.turn_off" in result

    async def test_explain_service(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test explaining a service."""
        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=mock_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        services_group = manager._registry.get("services")
        assert services_group is not None

        result = services_group.explain("light.turn_on")
        assert result is not None
        assert "Turn on a light" in result

    async def test_call_service_produces_effect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test calling a service produces ServiceCall effect."""
        from hamster.mcp._core.events import ServiceCall

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=mock_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        services_group = manager._registry.get("services")
        assert services_group is not None

        effect = services_group.parse_call_args(
            "light.turn_on",
            {
                "target": {"entity_id": ["light.living_room"]},
                "data": {"brightness": 255},
            },
            user_id="test_user",
        )

        assert isinstance(effect, ServiceCall)
        assert effect.domain == "light"
        assert effect.service == "turn_on"
        assert effect.user_id == "test_user"


class TestHassGroupFlow:
    """Tests for hass group full flow."""

    async def test_search_hass_commands(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test searching hass group."""
        # Mock websocket_api registry
        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
            "config/entity_registry/list": (mock_handler, False),
            "lovelace/resources": (mock_handler, False),
        }

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        hass_group = manager._registry.get("hass")
        assert hass_group is not None

        result = hass_group.search("registry")
        assert "config/entity_registry/list" in result

    async def test_explain_hass_command(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test explaining a hass command."""
        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
        }

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        hass_group = manager._registry.get("hass")
        assert hass_group is not None

        result = hass_group.explain("get_states")
        assert result is not None
        assert "get_states" in result

    async def test_call_hass_command_produces_effect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test calling a hass command produces HassCommand effect."""
        from hamster.mcp._core.events import HassCommand

        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
        }

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        hass_group = manager._registry.get("hass")
        assert hass_group is not None

        effect = hass_group.parse_call_args("get_states", {}, user_id="test_user")

        assert isinstance(effect, HassCommand)
        assert effect.command_type == "get_states"
        assert effect.user_id == "test_user"


class TestSupervisorGroupFlow:
    """Tests for supervisor group full flow."""

    async def test_search_supervisor_endpoints(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test searching supervisor group."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None
        assert supervisor_group.available is True

        result = supervisor_group.search("logs")
        assert "core/logs" in result
        assert "supervisor/logs" in result

    async def test_explain_supervisor_endpoint(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test explaining a supervisor endpoint."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None

        result = supervisor_group.explain("core/logs")
        assert result is not None
        assert "Home Assistant Core logs" in result

    async def test_call_supervisor_endpoint_produces_effect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test calling a supervisor endpoint produces SupervisorCall effect."""
        from hamster.mcp._core.events import SupervisorCall

        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        supervisor_group = manager._registry.get("supervisor")
        assert supervisor_group is not None

        effect = supervisor_group.parse_call_args("core/logs", {}, user_id="test_user")

        assert isinstance(effect, SupervisorCall)
        assert effect.path == "/core/logs"
        assert effect.method == "GET"
        assert effect.user_id == "test_user"


class TestCrossGroupSearch:
    """Tests for cross-group search."""

    async def test_search_all_returns_results_from_all_groups(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test that search_all returns results from all groups."""
        # Setup websocket commands
        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
            "lovelace/info": (mock_handler, False),
        }

        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value=mock_descriptions,
            ),
            patch("hamster.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Search for "info" should find results in multiple groups
        result = manager._registry.search_all("info")

        # Should have supervisor results (host/info, core/info, supervisor/info)
        assert "## supervisor" in result
        assert "core/info" in result or "host/info" in result

        # Should have hass results (lovelace/info)
        assert "## hass" in result
        assert "lovelace/info" in result

    async def test_search_all_with_group_filter(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test search_all with group filter."""
        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
        }

        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value=mock_descriptions,
            ),
            patch("hamster.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        # Search only in services group
        result = manager._registry.search_all("light", path_filter="services")
        assert "light.turn_on" in result
        # Should not have other group headers
        assert "## supervisor" not in result
        assert "## hass" not in result


class TestPathResolution:
    """Tests for path resolution across groups."""

    async def test_resolve_services_path(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test resolving a services path."""
        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=mock_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("services/light.turn_on")
        assert result is not None
        group, path = result
        assert group.name == "services"
        assert path == "light.turn_on"

    async def test_resolve_hass_path(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test resolving a hass path."""
        mock_handler = MagicMock()
        hass.data["websocket_api"] = {
            "get_states": (mock_handler, False),
        }

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("hass/get_states")
        assert result is not None
        group, path = result
        assert group.name == "hass"
        assert path == "get_states"

    async def test_resolve_supervisor_path(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test resolving a supervisor path."""
        with (
            patch(
                "hamster.component.async_get_all_descriptions",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("hamster.component.is_supervisor_available", return_value=True),
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("supervisor/core/logs")
        assert result is not None
        group, path = result
        assert group.name == "supervisor"
        assert path == "core/logs"

    async def test_resolve_unknown_group_returns_none(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that resolving unknown group returns None."""
        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        result = manager._registry.resolve_path("unknown/some/path")
        assert result is None


class TestErrorConditions:
    """Tests for error conditions in multi-source integration."""

    async def test_unknown_command_returns_error(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that unknown command returns error."""
        from hamster.mcp._core.events import Done

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        services_group = manager._registry.get("services")
        assert services_group is not None

        effect = services_group.parse_call_args(
            "unknown.service", {}, user_id="test_user"
        )

        assert isinstance(effect, Done)
        assert effect.result.is_error is True

    async def test_invalid_arguments_returns_error(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        mock_descriptions: dict[str, dict[str, object]],
    ) -> None:
        """Test that invalid arguments return error."""
        from hamster.mcp._core.events import Done

        with patch(
            "hamster.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value=mock_descriptions,
        ):
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]

        services_group = manager._registry.get("services")
        assert services_group is not None

        # Invalid target type (should be dict, not string)
        effect = services_group.parse_call_args(
            "light.turn_on",
            {"target": "invalid"},  # Should be dict
            user_id="test_user",
        )

        assert isinstance(effect, Done)
        assert effect.result.is_error is True
