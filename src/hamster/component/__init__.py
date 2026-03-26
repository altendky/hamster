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
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.const import EVENT_SERVICE_REGISTERED, EVENT_SERVICE_REMOVED
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.storage import Store
import voluptuous as vol

from hamster.mcp._core.docs_enrichment import enrich_commands, parse_websocket_docs
from hamster.mcp._core.groups import GroupRegistry, ServicesGroup
from hamster.mcp._core.hass_group import HassGroup, discover_commands
from hamster.mcp._core.session import SessionManager
from hamster.mcp._core.supervisor_group import SupervisorGroup
from hamster.mcp._core.types import ServerInfo
from hamster.mcp._io.aiohttp import AiohttpMCPTransport
from hamster.mcp._io.resources import load_all_resources

from .const import (
    DEFAULT_AUTO_FETCH_DOCS,
    DEFAULT_DOCS_GIT_REF,
    DEFAULT_DOCS_URL_TEMPLATE,
    DEFAULT_ENABLE_SERVICES_GROUP,
    DEFAULT_IDLE_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)
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

# Storage version and key for docs cache
_DOCS_STORE_VERSION = 1
_DOCS_STORE_KEY = "hamster_docs_cache"

# Service schema for refresh_docs
_REFRESH_DOCS_SCHEMA = vol.Schema(
    {
        vol.Optional("git_ref"): str,
    }
)


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


async def _refresh_websocket_docs(
    hass: HomeAssistant,
    manager: SessionManager,
    store: Store[dict[str, Any]],
    *,
    url_template: str,
    git_ref: str,
) -> dict[str, int]:
    """Fetch WebSocket docs, parse, enrich, and update registry.

    Args:
        hass: Home Assistant instance
        manager: Session manager holding the group registry
        store: Persistent store for caching parsed descriptions
        url_template: URL template with optional ``{ref}`` placeholder
        git_ref: Git ref (branch, tag, commit) substituted into the template

    Returns:
        Dict with ``commands_enriched`` and ``commands_total`` counts

    Raises:
        Exception: If the fetch or any step fails
    """
    # 1. Fetch raw markdown
    session = async_get_clientsession(hass)
    url = url_template.format(ref=git_ref)
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        resp.raise_for_status()
        markdown = await resp.text()

    # 2. Parse (core, pure)
    descriptions = parse_websocket_docs(markdown)

    # 3. Get current commands from existing HassGroup
    hass_group = manager.get_hass_group()
    if hass_group is None:
        msg = "Hass group not found in registry"
        raise RuntimeError(msg)

    current_commands = hass_group.commands

    # 4. Enrich (core, pure)
    enriched = enrich_commands(current_commands, descriptions)

    # 5. Update registry
    manager.update_hass_group(HassGroup(enriched))

    # 6. Persist parsed descriptions for next startup
    await store.async_save(
        {
            "descriptions": descriptions,
            "url_template": url_template,
            "git_ref": git_ref,
        }
    )

    commands_enriched = sum(1 for c in enriched.values() if c.description is not None)
    commands_total = len(enriched)

    return {
        "commands_enriched": commands_enriched,
        "commands_total": commands_total,
    }


def _apply_cached_descriptions(
    manager: SessionManager,
    cached_descriptions: dict[str, str],
) -> None:
    """Apply cached descriptions to the current hass group.

    Called at startup to restore enrichment from the persistent store
    without requiring a network fetch.

    Args:
        manager: Session manager holding the group registry
        cached_descriptions: Previously parsed descriptions from the store
    """
    hass_group = manager.get_hass_group()
    if hass_group is None:
        return

    current_commands = hass_group.commands
    enriched = enrich_commands(current_commands, cached_descriptions)
    manager.update_hass_group(HassGroup(enriched))


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
    auto_fetch_docs = entry.options.get("auto_fetch_docs", DEFAULT_AUTO_FETCH_DOCS)
    docs_url_template = entry.options.get(
        "docs_url_template", DEFAULT_DOCS_URL_TEMPLATE
    )
    docs_git_ref = entry.options.get("docs_git_ref", DEFAULT_DOCS_GIT_REF)

    # Create components
    server_info = ServerInfo(name="hamster", version=_HAMSTER_VERSION)

    def build_instructions(user_id: str | None, user_name: str | None) -> str | None:
        """Build MCP instructions with current HA state.

        Called once per session at initialize time so the base URL
        reflects the current configuration without requiring a restart.
        Returns None when no URL is available (e.g. during early startup).
        """
        try:
            base_url = get_url(hass)
        except NoURLAvailableError:
            return None
        parts = [f"Home Assistant instance URL: {base_url}"]
        if user_name:
            parts.append(f"Authenticated user: {user_name}")
        return "\n".join(parts)

    # Load static resource documents (I/O happens here, not in _core)
    resources = load_all_resources()

    manager = SessionManager(
        server_info=server_info,
        resources=resources,
        idle_timeout=DEFAULT_IDLE_TIMEOUT,
        instructions_factory=build_instructions,
    )

    effect_handler = HamsterEffectHandler(hass)

    # Build initial group registry
    registry = await _build_registry_with_retry(
        hass, enable_services_group=enable_services_group
    )
    manager.update_registry(registry)

    # --- Docs enrichment ---
    docs_store: Store[dict[str, Any]] = Store(
        hass, _DOCS_STORE_VERSION, _DOCS_STORE_KEY
    )

    # Apply cached descriptions immediately (no network needed)
    cached = await docs_store.async_load()
    if cached is not None and isinstance(cached.get("descriptions"), dict):
        try:
            _apply_cached_descriptions(manager, cached["descriptions"])
            _LOGGER.debug(
                "Applied cached WebSocket docs (ref=%s)",
                cached.get("git_ref", "unknown"),
            )
        except Exception:
            _LOGGER.warning("Failed to apply cached WebSocket docs")

    # Create the refresh function closure used by both service and button
    async def _do_refresh_docs(
        *,
        git_ref: str = docs_git_ref,
    ) -> dict[str, int]:
        return await _refresh_websocket_docs(
            hass,
            manager,
            docs_store,
            url_template=docs_url_template,
            git_ref=git_ref,
        )

    # Register the hamster.refresh_docs service
    async def _handle_refresh_docs(call: Any) -> None:
        """Handle the refresh_docs service call."""
        ref = call.data.get("git_ref", docs_git_ref)
        try:
            result = await _do_refresh_docs(git_ref=ref)
            _LOGGER.info(
                "WebSocket docs refreshed via service: "
                "%d/%d commands enriched (ref=%s)",
                result["commands_enriched"],
                result["commands_total"],
                ref,
            )
        except Exception:
            _LOGGER.exception("Failed to refresh WebSocket docs via service")

    hass.services.async_register(
        DOMAIN,
        "refresh_docs",
        _handle_refresh_docs,
        schema=_REFRESH_DOCS_SCHEMA,
    )

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
        "refresh_docs": _do_refresh_docs,
    }

    # Set up entity platforms (button)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Auto-fetch docs in background if enabled
    if auto_fetch_docs:

        async def _auto_fetch_docs() -> None:
            """Fetch docs from GitHub in the background."""
            try:
                result = await _do_refresh_docs(git_ref=docs_git_ref)
                _LOGGER.info(
                    "Auto-fetched WebSocket docs: %d/%d commands enriched (ref=%s)",
                    result["commands_enriched"],
                    result["commands_total"],
                    docs_git_ref,
                )
            except Exception:
                _LOGGER.warning(
                    "Auto-fetch of WebSocket docs failed (will use cached if available)"
                )

        entry.async_create_background_task(
            hass,
            _auto_fetch_docs(),
            "hamster_auto_fetch_docs",
        )

    # Reload integration when options change so captured values are refreshed
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry being unloaded

    Returns:
        True if unload was successful
    """
    # Unload entity platforms
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    # Remove service
    hass.services.async_remove(DOMAIN, "refresh_docs")

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
