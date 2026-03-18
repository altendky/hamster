"""I/O adapters for the MCP protocol.

This package bridges the sans-IO core to real transports.
It may import asyncio and aiohttp but must not import homeassistant.
The choice of asyncio over anyio is deliberate --- HA is built on
asyncio + aiohttp.  anyio is a possible future addition.
"""
