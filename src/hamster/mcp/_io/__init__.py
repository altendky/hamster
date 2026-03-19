"""I/O adapters for the MCP protocol.

This package bridges the sans-IO core to real transports.
It may import asyncio and aiohttp.  It does not import homeassistant
so the transport layer remains HA-independent and testable without HA
infrastructure.  The choice of asyncio over anyio is deliberate --- HA
is built on asyncio + aiohttp.  anyio is a possible future addition.
"""
