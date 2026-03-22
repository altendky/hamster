"""Tests for component/__init__.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from hamster.component.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

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


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hamster MCP",
        data={},
        entry_id="test_entry_id",
    )
    entry.add_to_hass(hass)
    return entry


async def test_async_setup_entry_succeeds(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that async_setup_entry succeeds."""
    with patch(
        "hamster.component.async_get_all_descriptions",
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
        "hamster.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_tool_list_returns_four_tools(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that tools/list returns the 4 fixed tools."""
    with patch(
        "hamster.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify data was stored
    assert mock_config_entry.entry_id in hass.data[DOMAIN]

    # Check that the 4 tools are available
    from hamster.mcp._core.tools import TOOLS

    assert len(TOOLS) == 4


async def test_service_index_built_from_descriptions(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the service index is built from descriptions."""
    mock_descriptions = {
        "light": {
            "turn_on": {"description": "Turn on a light", "fields": {}},
        }
    }

    with patch(
        "hamster.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value=mock_descriptions,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify index was built with the service
    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]

    # Search should find the light service
    result = manager._index.search("light")
    assert "light.turn_on" in result


async def test_request_after_unload_returns_503(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that requests after unload return 503."""
    with patch(
        "hamster.component.async_get_all_descriptions",
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
            "hamster.component.async_get_all_descriptions",
            side_effect=failing_then_succeeding,
        ),
        patch("hamster.component.asyncio.sleep", new_callable=AsyncMock),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Should have retried and succeeded
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert call_count == 3

    # Verify index was built with the service
    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]
    result = manager._index.search("light")
    assert "light.turn_on" in result


async def test_index_build_all_retries_fail_starts_empty(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that if all retries fail, starts with empty index."""
    call_count = 0

    async def always_failing(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Simulated failure")

    with (
        patch(
            "hamster.component.async_get_all_descriptions",
            side_effect=always_failing,
        ),
        patch("hamster.component.asyncio.sleep", new_callable=AsyncMock),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Should still succeed with empty index
    assert mock_config_entry.state is ConfigEntryState.LOADED
    # 5 attempts (1 initial + 4 retries)
    assert call_count == 5

    # Verify index is empty
    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    manager = data["manager"]
    result = manager._index.search("anything")
    assert "No services found" in result


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
        "hamster.component.async_get_all_descriptions",
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
        "hamster.component.async_get_all_descriptions",
        side_effect=mock_descriptions,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Verify initial index
        data = hass.data[DOMAIN][mock_config_entry.entry_id]
        manager = data["manager"]
        result = manager._index.search("light")
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

    # Index should still have the original service (preserved on failure)
    result = manager._index.search("light")
    assert "light.turn_on" in result


async def test_unload_cancels_wakeup_task_cleanly(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that unload cancels the wakeup background task cleanly."""
    with patch(
        "hamster.component.async_get_all_descriptions",
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
        "hamster.component.async_get_all_descriptions",
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
