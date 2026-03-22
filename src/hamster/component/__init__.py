"""Home Assistant custom component for Hamster MCP.

This module provides the HA integration entry points:
async_setup_entry, async_unload_entry, etc.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_SERVICE_REGISTERED, EVENT_SERVICE_REMOVED
from homeassistant.helpers.service import async_get_all_descriptions

from hamster.mcp._core.session import SessionManager
from hamster.mcp._core.tools import ServiceIndex
from hamster.mcp._core.types import ServerInfo
from hamster.mcp._io.aiohttp import AiohttpMCPTransport

from .const import DEFAULT_IDLE_TIMEOUT, DOMAIN
from .http import HamsterEffectHandler, HamsterMCPView

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Max retry attempts for initial index build
_MAX_RETRIES = 4
# Retry delays in seconds (exponential backoff capped at 15s)
_RETRY_DELAYS = [1.0, 2.0, 4.0, 8.0, 15.0]


async def _build_service_index(hass: HomeAssistant) -> ServiceIndex:
    """Build a ServiceIndex from current service descriptions.

    Args:
        hass: Home Assistant instance

    Returns:
        ServiceIndex built from current descriptions
    """
    descriptions = await async_get_all_descriptions(hass)
    return ServiceIndex(descriptions)


async def _build_service_index_with_retry(hass: HomeAssistant) -> ServiceIndex:
    """Build a ServiceIndex with retry on failure.

    Args:
        hass: Home Assistant instance

    Returns:
        ServiceIndex, or empty index if all retries fail
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await _build_service_index(hass)
        except Exception:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                _LOGGER.warning(
                    "Failed to build service index (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                _LOGGER.warning(
                    "Failed to build service index after %d attempts, starting empty",
                    _MAX_RETRIES + 1,
                )
                return ServiceIndex({})
    # Should not reach here
    return ServiceIndex({})  # pragma: no cover


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hamster MCP from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry being set up

    Returns:
        True if setup was successful
    """
    # Get version from package metadata
    try:
        version = importlib.metadata.version("hamster")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0-dev"

    # Create components
    server_info = ServerInfo(name="hamster", version=version)
    manager = SessionManager(
        server_info=server_info,
        idle_timeout=DEFAULT_IDLE_TIMEOUT,
    )

    effect_handler = HamsterEffectHandler(hass)

    # Build initial service index
    index = await _build_service_index_with_retry(hass)
    manager.update_index(index)

    # Create index rebuild callback for the transport
    async def rebuild_index_callback() -> None:
        """Rebuild the service index."""
        try:
            new_index = await _build_service_index(hass)
            manager.update_index(new_index)
        except Exception:
            _LOGGER.warning("Failed to rebuild service index, keeping existing")

    # Create transport
    transport = AiohttpMCPTransport(
        manager, effect_handler, index_rebuild_callback=rebuild_index_callback
    )

    # Register HTTP view
    view = HamsterMCPView(transport)
    hass.http.register_view(view)

    # Listen for service events
    def on_service_event(event: Event) -> None:
        """Handle service registered/removed events."""
        manager.notify_services_changed(time.monotonic())
        transport.notify_activity()

    unsub_registered = hass.bus.async_listen(EVENT_SERVICE_REGISTERED, on_service_event)
    unsub_removed = hass.bus.async_listen(EVENT_SERVICE_REMOVED, on_service_event)

    # Register cleanup on unload
    entry.async_on_unload(unsub_registered)
    entry.async_on_unload(unsub_removed)

    # Start wakeup loop as background task
    wakeup_task = entry.async_create_background_task(
        hass,
        transport.start_wakeup_loop(),
        "hamster_wakeup_loop",
    )

    # Store references for unload
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "manager": manager,
        "transport": transport,
        "wakeup_task": wakeup_task,
    }

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry being unloaded

    Returns:
        True if unload was successful
    """
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data is None:
        return True

    transport: AiohttpMCPTransport = data["transport"]
    wakeup_task: asyncio.Task[None] = data["wakeup_task"]

    # Shutdown transport (new requests return 503)
    transport.shutdown()

    # Stop wakeup loop
    await transport.stop_wakeup_loop()

    # Cancel the background task if still running
    if not wakeup_task.done():
        wakeup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await wakeup_task

    return True
