"""Hamster MCP --- HACS deployment shim.

This file re-exports the HA integration entry points from the hamster-mcp
library package.  The actual implementation lives in
src/hamster_mcp/component/.  This shim exists because HA discovers custom
components by looking for custom_components/<domain>/__init__.py.
"""

from hamster_mcp.component import async_setup_entry, async_unload_entry

__all__ = ["async_setup_entry", "async_unload_entry"]
