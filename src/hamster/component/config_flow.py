"""Config flow for Hamster MCP integration.

Minimal setup flow for single_config_entry with no user input fields.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class HamsterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hamster MCP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Since this is a single_config_entry integration with no configuration
        options, we show a simple confirmation form and create the entry.
        """
        if user_input is not None:
            return self.async_create_entry(title="Hamster MCP", data={})
        return self.async_show_form(step_id="user")
