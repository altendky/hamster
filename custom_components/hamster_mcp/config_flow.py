"""Hamster MCP --- HACS deployment shim for config flow.

Re-exports the config flow from the hamster-mcp library package.
"""

from hamster_mcp.component.config_flow import HamsterConfigFlow as ConfigFlow

__all__ = ["ConfigFlow"]
