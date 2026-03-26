"""Button platform for Hamster MCP integration.

Provides a button entity to refresh WebSocket command documentation
from the Home Assistant developer docs repository.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity

from .const import DEFAULT_DOCS_GIT_REF, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for Hamster MCP."""
    async_add_entities([HamsterRefreshDocsButton(entry)])


class HamsterRefreshDocsButton(ButtonEntity):
    """Button to refresh WebSocket command documentation from GitHub."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_websocket_docs"
    _attr_icon = "mdi:file-document-refresh"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the button.

        Args:
            entry: Config entry for the integration
        """
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh_websocket_docs"

    async def async_press(self) -> None:
        """Handle button press --- refresh WebSocket docs."""
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data is None:
            _LOGGER.warning("Hamster integration data not found")
            return

        refresh_fn = data.get("refresh_docs")
        if refresh_fn is None:
            _LOGGER.warning("Docs refresh function not available")
            return

        git_ref = self._entry.options.get("docs_git_ref", DEFAULT_DOCS_GIT_REF)

        try:
            result = await refresh_fn(git_ref=git_ref)
            _LOGGER.info(
                "WebSocket docs refreshed: %d/%d commands enriched",
                result["commands_enriched"],
                result["commands_total"],
            )
        except Exception:
            _LOGGER.exception("Failed to refresh WebSocket docs")
