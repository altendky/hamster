"""Tests for the aiohttp transport adapter.

Tests use aiohttp.test_utils.TestClient - full HTTP round-trips, no HA dependency.
Most protocol behavior (header validation, JSON parsing, session routing, error
responses) is already covered by Stage 5's pure tests. These tests focus on what
the transport adds: I/O integration and effect dispatch.

These tests require socket access (disabled by pytest-socket when
pytest-homeassistant-custom-component is installed). Mark module with
enable_socket to allow socket usage.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from hamster.mcp._core.session import SessionManager
from hamster.mcp._core.tools import ServiceIndex
from hamster.mcp._core.types import ServerInfo, ServiceCallResult
from hamster.mcp._io.aiohttp import AiohttpMCPTransport, EffectHandler

# Re-enable sockets for this module (disabled by pytest-homeassistant-custom-component)
pytestmark = pytest.mark.enable_socket

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from hamster.mcp._core.events import SessionExpired
    from hamster.mcp._core.session import WakeupRequest


class MockEffectHandler:
    """Mock effect handler for testing."""

    def __init__(self) -> None:
        """Initialize mock handler."""
        self.calls: list[
            tuple[str, str, dict[str, object] | None, dict[str, object]]
        ] = []
        self.result = ServiceCallResult(success=True, data={"result": "ok"})
        self.should_raise: Exception | None = None

    async def execute_service_call(
        self,
        domain: str,
        service: str,
        target: dict[str, object] | None,
        data: dict[str, object],
    ) -> ServiceCallResult:
        """Execute mock service call."""
        self.calls.append((domain, service, target, data))
        if self.should_raise is not None:
            raise self.should_raise
        return self.result


# Verify MockEffectHandler satisfies EffectHandler protocol
_: type[EffectHandler] = MockEffectHandler


@pytest.fixture
def session_counter() -> list[int]:
    """Counter for deterministic session IDs."""
    return [0]


@pytest.fixture
def session_manager(session_counter: list[int]) -> SessionManager:
    """Create a SessionManager with deterministic session IDs."""

    def factory() -> str:
        session_counter[0] += 1
        return f"session-{session_counter[0]}"

    server_info = ServerInfo(name="test-server", version="1.0.0")
    manager = SessionManager(
        server_info=server_info,
        idle_timeout=1800.0,
        session_id_factory=factory,
    )
    # Add some services to the index for tool testing
    manager.update_index(
        ServiceIndex(
            {
                "light": {
                    "turn_on": {
                        "description": "Turn on a light",
                        "fields": {"brightness": {"description": "Brightness level"}},
                    },
                    "turn_off": {
                        "description": "Turn off a light",
                        "fields": {},
                    },
                },
            }
        )
    )
    return manager


@pytest.fixture
def effect_handler() -> MockEffectHandler:
    """Create a mock effect handler."""
    return MockEffectHandler()


@pytest.fixture
def transport(
    session_manager: SessionManager, effect_handler: MockEffectHandler
) -> AiohttpMCPTransport:
    """Create an aiohttp transport."""
    return AiohttpMCPTransport(session_manager, effect_handler)


@pytest.fixture
async def client(
    transport: AiohttpMCPTransport,
) -> AsyncIterator[TestClient[web.Request, web.Application]]:
    """Create an aiohttp test client."""
    app = web.Application()
    app.router.add_route("*", "/mcp", transport.handle)
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


async def _init_session(client: TestClient[web.Request, web.Application]) -> str:
    """Initialize a session and return the session ID."""
    # Send initialize
    resp = await client.post(
        "/mcp",
        json=_make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 200
    session_id = resp.headers.get("Mcp-Session-Id")
    assert session_id is not None

    # Send initialized notification
    resp = await client.post(
        "/mcp",
        json=_make_jsonrpc("notifications/initialized", request_id=None),
        headers={
            "Content-Type": "application/json",
            "Mcp-Session-Id": session_id,
        },
    )
    assert resp.status == 202

    return session_id


class TestCompleteFlow:
    """Test complete MCP flow through HTTP."""

    async def test_init_ack_list_call(
        self,
        client: TestClient[web.Request, web.Application],
        effect_handler: MockEffectHandler,
    ) -> None:
        """Test init -> ack -> tools/list -> tools/call -> response."""
        # Initialize session
        session_id = await _init_session(client)

        # tools/list
        resp = await client.post(
            "/mcp",
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
        assert len(tools) == 4
        tool_names = {t["name"] for t in tools}
        assert "hamster_services_call" in tool_names

        # tools/call - hamster_services_search (no I/O)
        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_search",
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
        assert "light" in content[0]["text"].lower()

        # tools/call - hamster_services_call (with I/O)
        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_call",
                    "arguments": {
                        "domain": "light",
                        "service": "turn_on",
                        "target": {"entity_id": ["light.living_room"]},
                        "data": {"brightness": 255},
                    },
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
        # Should have the JSON response from effect handler
        text = content[0]["text"]
        assert "result" in text or "ok" in text

        # Verify effect handler was called
        assert len(effect_handler.calls) == 1
        call = effect_handler.calls[0]
        assert call[0] == "light"
        assert call[1] == "turn_on"
        assert call[2] == {"entity_id": ["light.living_room"]}
        assert call[3] == {"brightness": 255}


class TestIncomingRequestConstruction:
    """Test that transport correctly extracts headers and body."""

    async def test_headers_extracted_correctly(
        self, client: TestClient[web.Request, web.Application]
    ) -> None:
        """Verify transport extracts all headers for IncomingRequest."""
        # Just test that init works - headers are being extracted correctly
        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"}),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        assert resp.status == 200
        assert "Mcp-Session-Id" in resp.headers

    async def test_content_type_with_charset(
        self, client: TestClient[web.Request, web.Application]
    ) -> None:
        """Test that content-type with charset is accepted."""
        # aiohttp's request.content_type strips parameters
        resp = await client.post(
            "/mcp",
            data=json.dumps(
                _make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"})
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        # The sans-IO core handles the content-type validation
        # aiohttp strips charset, so we test that it doesn't break
        assert resp.status == 200


class TestEffectDispatch:
    """Test effect dispatch behavior."""

    async def test_done_returns_immediately(
        self, client: TestClient[web.Request, web.Application]
    ) -> None:
        """Done effect returns result immediately without I/O."""
        session_id = await _init_session(client)

        # hamster_services_search returns Done immediately
        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_search",
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

    async def test_service_call_invokes_handler(
        self,
        client: TestClient[web.Request, web.Application],
        effect_handler: MockEffectHandler,
    ) -> None:
        """ServiceCall effect invokes the effect handler."""
        session_id = await _init_session(client)

        effect_handler.result = ServiceCallResult(success=True, data={"state": "on"})

        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_call",
                    "arguments": {
                        "domain": "light",
                        "service": "turn_on",
                        "data": {},
                    },
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
        assert "state" in content[0]["text"]
        assert len(effect_handler.calls) == 1

    async def test_effect_handler_exception_produces_error_response(
        self,
        client: TestClient[web.Request, web.Application],
        effect_handler: MockEffectHandler,
    ) -> None:
        """Effect handler exception produces proper error response."""
        session_id = await _init_session(client)

        effect_handler.should_raise = ValueError("Something went wrong")

        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_call",
                    "arguments": {
                        "domain": "light",
                        "service": "turn_on",
                        "data": {},
                    },
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
        assert content[0]["type"] == "text"
        assert "ValueError" in content[0]["text"]
        assert "Something went wrong" in content[0]["text"]
        assert data["result"].get("isError") is True


class TestLoadedFlag:
    """Test the loaded flag behavior."""

    async def test_requests_after_shutdown_return_503(
        self,
        transport: AiohttpMCPTransport,
        client: TestClient[web.Request, web.Application],
    ) -> None:
        """Requests after shutdown() return 503."""
        # First, verify normal operation
        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 200

        # Shutdown
        transport.shutdown()

        # Now requests should return 503
        resp = await client.post(
            "/mcp",
            json=_make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 503


class TestBatchRequests:
    """Test batch request handling."""

    async def test_batch_with_multiple_tools_call(
        self,
        client: TestClient[web.Request, web.Application],
        effect_handler: MockEffectHandler,
    ) -> None:
        """Batch with multiple tools/call requests processed sequentially."""
        session_id = await _init_session(client)

        effect_handler.result = ServiceCallResult(success=True, data={"count": 1})

        batch = [
            _make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_call",
                    "arguments": {"domain": "light", "service": "turn_on", "data": {}},
                },
                request_id=1,
            ),
            _make_jsonrpc(
                "tools/call",
                {
                    "name": "hamster_services_call",
                    "arguments": {"domain": "light", "service": "turn_off", "data": {}},
                },
                request_id=2,
            ),
        ]

        resp = await client.post(
            "/mcp",
            json=batch,
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert len(effect_handler.calls) == 2


class TestWakeupLoop:
    """Test wakeup loop behavior."""

    async def test_wakeup_loop_starts_and_stops(
        self, session_manager: SessionManager, effect_handler: MockEffectHandler
    ) -> None:
        """Wakeup loop can be started and stopped cleanly."""
        transport = AiohttpMCPTransport(session_manager, effect_handler)

        # Start the loop in a task
        loop_task = asyncio.create_task(transport.start_wakeup_loop())

        # Give it a moment to start
        await asyncio.sleep(0.01)

        # Notify activity to wake it
        transport.notify_activity()

        # Stop it
        transport.shutdown()
        await transport.stop_wakeup_loop()

        # Verify the task is done
        assert loop_task.done() or loop_task.cancelled()

    async def test_wakeup_loop_calls_rebuild_callback(
        self, effect_handler: MockEffectHandler
    ) -> None:
        """Wakeup loop triggers index rebuild callback after debounce."""
        rebuild_called = asyncio.Event()

        async def rebuild_callback() -> None:
            rebuild_called.set()

        server_info = ServerInfo(name="test-server", version="1.0.0")
        manager = SessionManager(
            server_info=server_info,
            idle_timeout=1800.0,
            debounce_delay=0.05,  # Short debounce for testing
        )
        manager.update_index(ServiceIndex({}))

        transport = AiohttpMCPTransport(
            manager, effect_handler, index_rebuild_callback=rebuild_callback
        )

        # Start loop
        loop_task = asyncio.create_task(transport.start_wakeup_loop())

        # Notify services changed
        import time

        manager.notify_services_changed(time.monotonic())
        transport.notify_activity()

        # Wait for rebuild callback
        try:
            await asyncio.wait_for(rebuild_called.wait(), timeout=1.0)
        except TimeoutError:
            pytest.fail("Rebuild callback was not called within timeout")

        # Clean up
        transport.shutdown()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    async def test_wakeup_loop_expires_sessions(
        self, effect_handler: MockEffectHandler
    ) -> None:
        """Wakeup loop expires idle sessions."""
        server_info = ServerInfo(name="test-server", version="1.0.0")
        counter = [0]

        def factory() -> str:
            counter[0] += 1
            return f"session-{counter[0]}"

        manager = SessionManager(
            server_info=server_info,
            idle_timeout=0.05,  # Very short timeout for testing
            session_id_factory=factory,
        )
        manager.update_index(ServiceIndex({}))

        transport = AiohttpMCPTransport(manager, effect_handler)

        # Create an app and client
        app = web.Application()
        app.router.add_route("*", "/mcp", transport.handle)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # Initialize a session
            resp = await client.post(
                "/mcp",
                json=_make_jsonrpc("initialize", {"protocolVersion": "2025-03-26"}),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 200
            session_id = resp.headers.get("Mcp-Session-Id")
            assert session_id is not None

            # Start wakeup loop
            loop_task = asyncio.create_task(transport.start_wakeup_loop())

            # Wake it to process
            transport.notify_activity()

            # Wait for session to expire
            await asyncio.sleep(0.15)

            # Wake again to process expiration
            transport.notify_activity()
            await asyncio.sleep(0.05)

            # Try to use the expired session - should get 404
            resp = await client.post(
                "/mcp",
                json=_make_jsonrpc("ping"),
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": session_id,
                },
            )
            assert resp.status == 404

            # Clean up
            transport.shutdown()
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
        finally:
            await client.close()

    async def test_notify_activity_wakes_sleeping_loop(
        self, session_manager: SessionManager, effect_handler: MockEffectHandler
    ) -> None:
        """notify_activity() wakes the loop immediately."""
        transport = AiohttpMCPTransport(session_manager, effect_handler)

        # Start loop
        loop_task = asyncio.create_task(transport.start_wakeup_loop())
        await asyncio.sleep(0.01)

        # The loop should be waiting on the event
        # notify_activity should wake it
        transport.notify_activity()

        # Give it time to process
        await asyncio.sleep(0.01)

        # Clean up
        transport.shutdown()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task


class TestWakeupLoopErrorResilience:
    """Test wakeup loop error handling."""

    async def test_exception_during_check_wakeups_continues(
        self, effect_handler: MockEffectHandler
    ) -> None:
        """Exception during check_wakeups() is caught and loop continues."""
        server_info = ServerInfo(name="test-server", version="1.0.0")
        manager = SessionManager(
            server_info=server_info,
            idle_timeout=1800.0,
            debounce_delay=0.5,
        )
        manager.update_index(ServiceIndex({}))

        transport = AiohttpMCPTransport(manager, effect_handler)

        # Patch check_wakeups to raise an exception on first call
        call_count = 0
        original_check = manager.check_wakeups

        def patched_check(
            now: float,
        ) -> tuple[list[SessionExpired], bool, WakeupRequest | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Test error")
            return original_check(now)

        manager.check_wakeups = patched_check  # type: ignore[method-assign]

        # Start loop
        loop_task = asyncio.create_task(transport.start_wakeup_loop())

        # Give it time to fail and retry
        await asyncio.sleep(0.2)

        # Loop should still be running
        assert not loop_task.done()
        assert call_count >= 2

        # Clean up
        transport.shutdown()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    async def test_rebuild_callback_exception_continues(
        self, effect_handler: MockEffectHandler
    ) -> None:
        """Exception in rebuild callback is caught and loop continues."""

        async def failing_callback() -> None:
            raise RuntimeError("Rebuild failed")

        server_info = ServerInfo(name="test-server", version="1.0.0")
        manager = SessionManager(
            server_info=server_info,
            idle_timeout=1800.0,
            debounce_delay=0.02,
        )
        manager.update_index(ServiceIndex({}))

        transport = AiohttpMCPTransport(
            manager, effect_handler, index_rebuild_callback=failing_callback
        )

        # Start loop
        loop_task = asyncio.create_task(transport.start_wakeup_loop())

        # Trigger rebuild
        import time

        manager.notify_services_changed(time.monotonic())
        transport.notify_activity()

        # Wait for it to process
        await asyncio.sleep(0.1)

        # Loop should still be running despite callback failure
        assert not loop_task.done()

        # Clean up
        transport.shutdown()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
