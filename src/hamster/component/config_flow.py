"""Config flow for Hamster MCP integration.

Minimal setup flow for single_config_entry with no user input fields.
Options flow exposes docs enrichment settings.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithConfigEntry,
)
import voluptuous as vol

from .const import (
    DEFAULT_AUTO_FETCH_DOCS,
    DEFAULT_DOCS_GIT_REF,
    DEFAULT_DOCS_URL_TEMPLATE,
    DOMAIN,
)


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

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return HamsterOptionsFlow(config_entry)


class HamsterOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options for Hamster MCP."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "auto_fetch_docs",
                        default=current.get("auto_fetch_docs", DEFAULT_AUTO_FETCH_DOCS),
                    ): bool,
                    vol.Optional(
                        "docs_url_template",
                        default=current.get(
                            "docs_url_template", DEFAULT_DOCS_URL_TEMPLATE
                        ),
                    ): vol.All(str, vol.Length(min=1)),
                    vol.Optional(
                        "docs_git_ref",
                        default=current.get("docs_git_ref", DEFAULT_DOCS_GIT_REF),
                    ): vol.All(str, vol.Length(min=1)),
                }
            ),
        )
