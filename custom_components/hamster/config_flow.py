"""Hamster MCP --- HACS deployment shim for config flow.

Re-exports the config flow from the hamster library package.
"""

from hamster.component.config_flow import HamsterConfigFlow as ConfigFlow

__all__ = ["ConfigFlow"]
