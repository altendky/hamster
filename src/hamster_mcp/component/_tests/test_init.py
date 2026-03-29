"""Tests for component/__init__.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hamster_mcp.component.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
        MockConfigEntry,
    )

from homeassistant.config_entries import ConfigEntryState


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


async def test_async_setup_entry_succeeds(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that async_setup_entry succeeds."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.data
    assert mock_config_entry.entry_id in hass.data[DOMAIN]


async def test_async_unload_entry_succeeds(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that async_unload_entry succeeds."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_tool_list_returns_six_tools(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that tools/list returns the 6 fixed tools."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify data was stored
    assert mock_config_entry.entry_id in hass.data[DOMAIN]

    # Check that the 6 tools are available
    from hamster_mcp.mcp._core.tools import TOOLS

    assert len(TOOLS) == 6


async def test_registry_built_from_descriptions(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the group registry is built from descriptions."""
    mock_descriptions = {
        "light": {
            "turn_on": {"description": "Turn on a light", "fields": {}},
        }
    }

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value=mock_descriptions,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify registry was built with the service
    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]

    # Search should find the light service
    result = manager._registry.search_all("light")
    assert "light.turn_on" in result


async def test_all_three_groups_registered(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that all three groups (services, hass, supervisor) are registered."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]

    # Check all groups are registered
    services_group = manager._registry.get("services")
    hass_group = manager._registry.get("hass")
    supervisor_group = manager._registry.get("supervisor")

    assert services_group is not None, "services group should be registered"
    assert hass_group is not None, "hass group should be registered"
    assert supervisor_group is not None, "supervisor group should be registered"

    assert services_group.name == "services"
    assert hass_group.name == "hass"
    assert supervisor_group.name == "supervisor"


async def test_hass_group_built_from_websocket_api(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that hass group is built from websocket_api registry."""
    # Mock a simple websocket command
    mock_handler = MagicMock()
    mock_schema = False  # No additional params
    hass.data["websocket_api"] = {
        "get_states": (mock_handler, mock_schema),
    }

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]

    hass_group = manager._registry.get("hass")
    assert hass_group is not None
    assert hass_group.has_command("get_states")


async def test_supervisor_group_availability_detected(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that supervisor group availability is correctly detected."""
    with (
        patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ),
        # Supervisor not available (no hassio)
        patch("hamster_mcp.component.is_supervisor_available", return_value=False),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]

    supervisor_group = manager._registry.get("supervisor")
    assert supervisor_group is not None
    assert supervisor_group.available is False


async def test_request_after_unload_returns_503(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that requests after unload return 503."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Get transport before unload
        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        transport = data["transport"]

        # Unload
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Transport should be shutdown
    assert transport._loaded is False


async def test_index_build_retries_on_failure(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that index build retries with backoff on failure."""
    call_count = 0

    async def failing_then_succeeding(
        *args: object, **kwargs: object
    ) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("Simulated failure")
        return {"light": {"turn_on": {"description": "Turn on", "fields": {}}}}

    with (
        patch(
            "hamster_mcp.component.async_get_all_descriptions",
            side_effect=failing_then_succeeding,
        ),
        patch("hamster_mcp.component.asyncio.sleep", new_callable=AsyncMock),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Should have retried and succeeded
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert call_count == 3

    # Verify registry was built with the service
    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]
    result = manager._registry.search_all("light")
    assert "light.turn_on" in result


async def test_index_build_all_retries_fail_starts_empty(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that if all retries fail, starts with partial registry."""
    call_count = 0

    async def always_failing(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Simulated failure")

    with (
        patch(
            "hamster_mcp.component.async_get_all_descriptions",
            side_effect=always_failing,
        ),
        patch("hamster_mcp.component.asyncio.sleep", new_callable=AsyncMock),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Should still succeed with partial registry
    assert mock_config_entry.state is ConfigEntryState.LOADED
    # 6 attempts: 5 for retry loop + 1 for partial build of services group
    assert call_count == 6

    # Verify registry has groups but services is empty
    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]

    # All three groups should still be registered
    assert manager._registry.get("services") is not None
    assert manager._registry.get("hass") is not None
    assert manager._registry.get("supervisor") is not None

    # Services group should be empty
    result = manager._registry.search_all("anything")
    # Should get "No commands found" since all groups are empty
    assert "No commands found" in result or "No" in result


async def test_service_events_trigger_index_rebuild(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that service events trigger index rebuild via debounce."""
    from homeassistant.const import EVENT_SERVICE_REGISTERED

    rebuild_count = 0
    original_descriptions: dict[str, object] = {}

    async def mock_descriptions(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal rebuild_count
        rebuild_count += 1
        if rebuild_count == 1:
            return original_descriptions
        return {"new_domain": {"new_service": {"description": "New", "fields": {}}}}

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        side_effect=mock_descriptions,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Fire a service registered event
        hass.bus.async_fire(
            EVENT_SERVICE_REGISTERED, {"domain": "new_domain", "service": "new_service"}
        )

        # Wait for debounce (manager default is 0.5s, but we can trigger manually)
        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        transport = data["transport"]

        # Notify activity to wake the loop
        transport.notify_activity()

        # Give time for the wakeup loop to process
        import asyncio

        await asyncio.sleep(0.6)
        await hass.async_block_till_done()

    # Should have rebuilt the index
    assert rebuild_count >= 2


async def test_index_refresh_failure_preserves_existing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that index refresh failure preserves existing index."""
    from homeassistant.const import EVENT_SERVICE_REGISTERED

    call_count = 0
    initial_descriptions: dict[str, object] = {
        "light": {"turn_on": {"description": "Turn on", "fields": {}}}
    }

    async def mock_descriptions(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return initial_descriptions
        raise RuntimeError("Refresh failed")

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        side_effect=mock_descriptions,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Verify initial registry
        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]
        result = manager._registry.search_all("light")
        assert "light.turn_on" in result

        # Fire a service event to trigger rebuild
        hass.bus.async_fire(
            EVENT_SERVICE_REGISTERED, {"domain": "new", "service": "service"}
        )

        transport = data["transport"]
        transport.notify_activity()

        import asyncio

        await asyncio.sleep(0.6)
        await hass.async_block_till_done()

    # Registry should still have the original service (preserved on failure)
    result = manager._registry.search_all("light")
    assert "light.turn_on" in result


async def test_unload_cancels_wakeup_task_cleanly(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that unload cancels the wakeup background task cleanly."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Get the wakeup task
        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        wakeup_task = data["wakeup_task"]

        # Task should be running
        assert not wakeup_task.done()

        # Unload
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Task should be done (cancelled)
    assert wakeup_task.done()


async def test_event_listeners_cleaned_up_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that event listeners are cleaned up on unload."""
    from homeassistant.const import EVENT_SERVICE_REGISTERED, EVENT_SERVICE_REMOVED

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        # Count listeners before setup (async_listeners returns dict[str, int])
        listeners = hass.bus.async_listeners()
        initial_registered_count = listeners.get(EVENT_SERVICE_REGISTERED, 0)
        initial_removed_count = listeners.get(EVENT_SERVICE_REMOVED, 0)

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Should have added listeners
        listeners = hass.bus.async_listeners()
        after_setup_registered = listeners.get(EVENT_SERVICE_REGISTERED, 0)
        after_setup_removed = listeners.get(EVENT_SERVICE_REMOVED, 0)
        assert after_setup_registered > initial_registered_count
        assert after_setup_removed > initial_removed_count

        # Unload
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Listeners should be removed
    listeners = hass.bus.async_listeners()
    final_registered = listeners.get(EVENT_SERVICE_REGISTERED, 0)
    final_removed = listeners.get(EVENT_SERVICE_REMOVED, 0)
    assert final_registered == initial_registered_count
    assert final_removed == initial_removed_count


async def test_instructions_factory_wired_up(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that SessionManager gets an instructions_factory from setup."""
    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]
    assert manager._instructions_factory is not None


async def test_instructions_factory_includes_base_url(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that instructions factory produces text with the HA base URL."""
    with (
        patch(
            "hamster_mcp.component.async_get_all_descriptions",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "hamster_mcp.component.get_url",
            return_value="http://ha.local:8123",
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]
    factory = manager._instructions_factory

    # Mock get_url for factory calls (factory captures hass, calls get_url)
    with patch(
        "hamster_mcp.component.get_url",
        return_value="http://ha.local:8123",
    ):
        # Call with user info
        result = factory("uid-1", "Kyle")
        assert result is not None
        assert "Kyle" in result
        assert "Home Assistant instance URL: http://ha.local:8123" in result

        # Call without user info
        result_anon = factory(None, None)
        assert result_anon is not None
        assert "Kyle" not in result_anon
        assert "Home Assistant instance URL: http://ha.local:8123" in result_anon


async def test_instructions_factory_returns_none_when_no_url(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that instructions factory returns None when no URL is available."""
    from homeassistant.helpers.network import NoURLAvailableError

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]
    factory = manager._instructions_factory

    with patch(
        "hamster_mcp.component.get_url",
        side_effect=NoURLAvailableError,
    ):
        result = factory("uid-1", "Kyle")
        assert result is None
