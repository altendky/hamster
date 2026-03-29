"""Tests for HTTP view integration.

Tests the full MCP flow through Home Assistant's HTTP infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from hamster_mcp.component.const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
        MockConfigEntry,
    )

# Enable sockets for HTTP tests.  Use the fixture (not the bare marker) to
# avoid non-deterministic hook-ordering between pytest-socket and
# pytest-homeassistant-custom-component.  See test_aiohttp.py docstring.
pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for testing."""


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> AsyncIterator[dict[str, object]]:
    """Set up the integration and return the stored data."""
    # Mock hass.http since we're testing the view directly
    mock_http = MagicMock()
    mock_http.register_view = MagicMock()
    hass.http = mock_http

    with patch(
        "hamster_mcp.component.async_get_all_descriptions",
        new_callable=AsyncMock,
        return_value={
            "light": {
                "turn_on": {"description": "Turn on a light", "fields": {}},
                "turn_off": {"description": "Turn off a light", "fields": {}},
            }
        },
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][mock_config_entry.entry_id]
    yield data

    # Cleanup
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def http_client(
    setup_integration: dict[str, object],
) -> AsyncIterator[TestClient[web.Request, web.Application]]:
    """Create an HTTP test client for the MCP view."""
    from hamster_mcp.mcp._io.aiohttp import AiohttpMCPTransport

    transport = setup_integration["transport"]
    assert isinstance(transport, AiohttpMCPTransport)

    # Create a test app with the transport handler
    app = web.Application()
    app.router.add_route("*", "/api/hamster_mcp", transport.handle)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        yield client
    finally:
        await client.close()


def _make_jsonrpc(
    method: str,
    params: dict[str, object] | None = None,
    request_id: int | str | None = 1,
) -> dict[str, object]:
    """Build a JSON-RPC request."""
    msg: dict[str, object] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    if request_id is not None:
        msg["id"] = request_id
    return msg


async def _init_session(
    client: TestClient[web.Request, web.Application],
) -> str:
    """Initialize a session and return the session ID."""
    resp = await client.post(
        "/api/hamster_mcp",
        json=_make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 200
    session_id = resp.headers.get("Mcp-Session-Id")
    assert session_id is not None

    # Send initialized notification
    resp = await client.post(
        "/api/hamster_mcp",
        json=_make_jsonrpc("notifications/initialized", request_id=None),
        headers={
            "Content-Type": "application/json",
            "Mcp-Session-Id": session_id,
        },
    )
    assert resp.status == 202

    return session_id


class TestFullMCPFlow:
    """Test complete MCP protocol flow through HA HTTP."""

    async def test_init_ack_list_call_flow(
        self,
        http_client: TestClient[web.Request, web.Application],
        setup_integration: dict[str, object],
    ) -> None:
        """Test full flow: init -> ack -> tools/list -> tools/call."""
        # Initialize session
        session_id = await _init_session(http_client)

        # tools/list
        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc("tools/list"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert "result" in data
        tools = data["result"]["tools"]
        assert len(tools) == 6

        # tools/call - search for services
        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "search",
                    "arguments": {"query": "light"},
                },
            ),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert "result" in data
        content = data["result"]["content"]
        assert len(content) == 1
        assert "light.turn_on" in content[0]["text"]

    async def test_tools_call_with_service_execution(
        self,
        hass: HomeAssistant,
        http_client: TestClient[web.Request, web.Application],
        setup_integration: dict[str, object],
    ) -> None:
        """Test tools/call that executes a service via effect handler.

        We mock the effect handler's execute_service_call since hass.services
        is read-only in tests.
        """
        from hamster_mcp.mcp._core.types import ServiceCallResult

        session_id = await _init_session(http_client)

        # Get the effect handler from the stored data and mock its method
        data = setup_integration
        transport = data["transport"]
        # Access the effect handler
        from hamster_mcp.mcp._io.aiohttp import AiohttpMCPTransport

        assert isinstance(transport, AiohttpMCPTransport)

        # Mock at the effect handler level
        with patch.object(
            transport._effect_handler,
            "execute_service_call",
            new_callable=AsyncMock,
        ) as mock_call:
            mock_call.return_value = ServiceCallResult(
                success=True, data={"state": "on"}
            )

            resp = await http_client.post(
                "/api/hamster_mcp",
                json=_make_jsonrpc(
                    "tools/call",
                    {
                        "name": "call",
                        "arguments": {
                            "path": "services/light.turn_on",
                            "arguments": {
                                "target": {"entity_id": ["light.living_room"]},
                                "data": {"brightness": 255},
                            },
                        },
                    },
                ),
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": session_id,
                },
            )

            assert resp.status == 200
            result_data = await resp.json()
            assert "result" in result_data
            content = result_data["result"]["content"]
            assert "state" in content[0]["text"]

            # Verify effect handler was called
            mock_call.assert_called_once()
            call_args = mock_call.call_args
            # execute_service_call is called with positional args
            assert call_args.args[0] == "light"  # domain
            assert call_args.args[1] == "turn_on"  # service

    async def test_explain_service(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test explain tool."""
        session_id = await _init_session(http_client)

        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "explain",
                    "arguments": {"path": "services/light.turn_on"},
                },
            ),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )

        assert resp.status == 200
        data = await resp.json()
        assert "result" in data
        content = data["result"]["content"]
        assert "light.turn_on" in content[0]["text"]

    async def test_schema_tool(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test schema tool."""
        session_id = await _init_session(http_client)

        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "schema",
                    "arguments": {"path": "services/selector/boolean"},
                },
            ),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )

        assert resp.status == 200
        data = await resp.json()
        assert "result" in data
        content = data["result"]["content"]
        assert "boolean" in content[0]["text"].lower()


class TestHTTPErrors:
    """Test HTTP error handling."""

    async def test_missing_session_id_returns_400(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test that missing session ID for non-init request returns 400."""
        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc("tools/list"),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    async def test_invalid_session_id_returns_404(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test that invalid session ID returns 404."""
        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc("tools/list"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": "nonexistent-session",
            },
        )
        assert resp.status == 404

    async def test_get_request_returns_405(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test that GET request returns 405 (SSE not supported yet)."""
        resp = await http_client.get(
            "/api/hamster_mcp",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 405

    async def test_wrong_content_type_returns_415(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test that wrong Content-Type returns 415."""
        resp = await http_client.post(
            "/api/hamster_mcp",
            data="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status == 415

    async def test_invalid_json_returns_400(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test that invalid JSON returns 400 with parse error."""
        resp = await http_client.post(
            "/api/hamster_mcp",
            data="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"]["code"] == -32700  # Parse error


class TestSessionManagement:
    """Test session lifecycle."""

    async def test_delete_session(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test DELETE request terminates session."""
        session_id = await _init_session(http_client)

        # Delete the session
        resp = await http_client.delete(
            "/api/hamster_mcp",
            headers={"Mcp-Session-Id": session_id},
        )
        assert resp.status == 200

        # Subsequent request should return 404
        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc("tools/list"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 404

    async def test_ping_request(
        self,
        http_client: TestClient[web.Request, web.Application],
    ) -> None:
        """Test ping request returns success."""
        session_id = await _init_session(http_client)

        resp = await http_client.post(
            "/api/hamster_mcp",
            json=_make_jsonrpc("ping"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert "result" in data
        assert data["result"] == {}
