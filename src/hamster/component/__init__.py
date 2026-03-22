"""Home Assistant custom component for Hamster MCP.

This module provides the HA integration entry points:
async_setup_entry, async_unload_entry, etc.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import logging
import os
import time
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_SERVICE_REGISTERED, EVENT_SERVICE_REMOVED
from homeassistant.helpers.service import async_get_all_descriptions

from hamster.mcp._core.groups import GroupRegistry, ServicesGroup
from hamster.mcp._core.hass_group import HassGroup, discover_commands
from hamster.mcp._core.session import SessionManager
from hamster.mcp._core.supervisor_group import SupervisorGroup
from hamster.mcp._core.types import ServerInfo
from hamster.mcp._io.aiohttp import AiohttpMCPTransport

from .const import DEFAULT_ENABLE_SERVICES_GROUP, DEFAULT_IDLE_TIMEOUT, DOMAIN
from .http import HamsterEffectHandler, HamsterMCPView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Get version from package metadata at module load time
# (avoids blocking I/O in async context)
try:
    _HAMSTER_VERSION = importlib.metadata.version("hamster")
except importlib.metadata.PackageNotFoundError:
    _HAMSTER_VERSION = "0.0.0-dev"

# Max retry attempts for initial index build
_MAX_RETRIES = 4
# Retry delays in seconds (exponential backoff capped at 15s)
_RETRY_DELAYS = [1.0, 2.0, 4.0, 8.0, 15.0]


def is_supervisor_available(hass: HomeAssistant) -> bool:
    """Check if Supervisor is available.

    Args:
        hass: Home Assistant instance

    Returns:
        True if Supervisor is available and accessible
    """
    # Import here to avoid issues when hassio is not installed
    try:
        from homeassistant.helpers.hassio import is_hassio
    except ImportError:
        return False

    # is_hassio() checks both SUPERVISOR env and hassio component
    if not is_hassio(hass):
        return False

    # Also need the auth token for API calls
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


async def _build_registry(
    hass: HomeAssistant,
    *,
    enable_services_group: bool,
) -> GroupRegistry:
    """Build a GroupRegistry with all available groups.

    Args:
        hass: Home Assistant instance
        enable_services_group: Whether to include the services group

    Returns:
        GroupRegistry with all groups registered
    """
    registry = GroupRegistry()

    # Services group
    if enable_services_group:
        descriptions = await async_get_all_descriptions(hass)
        registry.register(ServicesGroup(descriptions))

    # Hass group (WebSocket commands)
    ws_registry = hass.data.get("websocket_api", {})
    commands = discover_commands(ws_registry)
    registry.register(HassGroup(commands))

    # Supervisor group (availability-dependent)
    supervisor_available = is_supervisor_available(hass)
    registry.register(SupervisorGroup(available=supervisor_available))

    return registry


async def _build_registry_with_retry(
    hass: HomeAssistant,
    *,
    enable_services_group: bool,
) -> GroupRegistry:
    """Build a GroupRegistry with retry on failure.

    If building fails completely, returns an empty registry.
    Individual group failures are handled gracefully - other groups
    will still be registered.

    Args:
        hass: Home Assistant instance
        enable_services_group: Whether to include the services group

    Returns:
        GroupRegistry, possibly with some groups empty if they failed
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await _build_registry(
                hass, enable_services_group=enable_services_group
            )
        except Exception:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                _LOGGER.warning(
                    "Failed to build group registry (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                _LOGGER.warning(
                    "Failed to build registry after %d attempts, using partial",
                    _MAX_RETRIES + 1,
                )
                # Build partial registry - try each group separately
                return await _build_partial_registry(
                    hass, enable_services_group=enable_services_group
                )
    # Should not reach here
    return GroupRegistry()  # pragma: no cover


async def _build_partial_registry(
    hass: HomeAssistant,
    *,
    enable_services_group: bool,
) -> GroupRegistry:
    """Build a partial registry when full build fails.

    Tries to build each group independently, logging errors for failures.

    Args:
        hass: Home Assistant instance
        enable_services_group: Whether to include the services group

    Returns:
        GroupRegistry with whatever groups could be built
    """
    registry = GroupRegistry()

    # Try services group
    if enable_services_group:
        try:
            descriptions = await async_get_all_descriptions(hass)
            registry.register(ServicesGroup(descriptions))
        except Exception:
            _LOGGER.warning("Failed to build services group, starting empty")
            registry.register(ServicesGroup({}))

    # Try hass group
    try:
        ws_registry = hass.data.get("websocket_api", {})
        commands = discover_commands(ws_registry)
        registry.register(HassGroup(commands))
    except Exception:
        _LOGGER.warning("Failed to build hass group, starting empty")
        registry.register(HassGroup({}))

    # Supervisor group (can't fail - just availability check)
    supervisor_available = is_supervisor_available(hass)
    registry.register(SupervisorGroup(available=supervisor_available))

    return registry


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hamster MCP from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry being set up

    Returns:
        True if setup was successful
    """
    # Read config from entry options
    enable_services_group = entry.options.get(
        "enable_services_group", DEFAULT_ENABLE_SERVICES_GROUP
    )

    # Create components
    server_info = ServerInfo(name="hamster", version=_HAMSTER_VERSION)
    manager = SessionManager(
        server_info=server_info,
        idle_timeout=DEFAULT_IDLE_TIMEOUT,
    )

    effect_handler = HamsterEffectHandler(hass)

    # Build initial group registry
    registry = await _build_registry_with_retry(
        hass, enable_services_group=enable_services_group
    )
    manager.update_registry(registry)

    # Create services group rebuild callback for the transport
    # Only services group needs rebuilding on service events;
    # hass and supervisor groups don't change at runtime
    rebuild_services_callback: Callable[[], Awaitable[None]] | None = None
    if enable_services_group:

        async def _rebuild_services() -> None:
            """Rebuild the services group after service changes."""
            try:
                descriptions = await async_get_all_descriptions(hass)
                services_group = ServicesGroup(descriptions)
                manager.update_services_group(services_group)
            except Exception:
                _LOGGER.warning("Failed to rebuild services group, keeping existing")

        rebuild_services_callback = _rebuild_services

    # Create transport
    transport = AiohttpMCPTransport(
        manager, effect_handler, index_rebuild_callback=rebuild_services_callback
    )

    # Register HTTP view
    view = HamsterMCPView(transport)
    hass.http.register_view(view)

    # Listen for service events (only if services group is enabled)
    if enable_services_group:

        def on_service_event(event: Event) -> None:
            """Handle service registered/removed events."""
            manager.notify_services_changed(time.monotonic())
            transport.notify_activity()

        unsub_registered = hass.bus.async_listen(
            EVENT_SERVICE_REGISTERED, on_service_event
        )
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
