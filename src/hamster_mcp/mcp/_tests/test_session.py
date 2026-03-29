"""Tests for _core/session.py."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

from hamster_mcp.mcp._core.events import RunEffects, SendResponse
from hamster_mcp.mcp._core.groups import GroupRegistry, ServicesGroup
from hamster_mcp.mcp._core.jsonrpc import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
)
from hamster_mcp.mcp._core.session import (
    MCPServerSession,
    SessionAck,
    SessionError,
    SessionManager,
    SessionResponse,
    SessionState,
    SessionToolCall,
)
from hamster_mcp.mcp._core.types import (
    CallToolResult,
    IncomingRequest,
    ServerCapabilities,
    ServerInfo,
    TextContent,
)

# --- Helper functions ---


def make_request(
    body: dict[str, Any] | Sequence[Any] | str | None = None,
    *,
    method: str = "POST",
    content_type: str | None = "application/json",
    accept: str | None = "application/json",
    origin: str | None = None,
    host: str = "localhost:8123",
    session_id: str | None = None,
    user_id: str | None = None,
    user_name: str | None = None,
) -> IncomingRequest:
    """Create an IncomingRequest for testing."""
    if body is None:
        body_bytes = b""
    elif isinstance(body, str):
        body_bytes = body.encode()
    else:
        body_bytes = json.dumps(body).encode()

    return IncomingRequest(
        http_method=method,
        content_type=content_type,
        accept=accept,
        origin=origin,
        host=host,
        session_id=session_id,
        body=body_bytes,
        user_id=user_id,
        user_name=user_name,
    )


def make_jsonrpc_request(
    method: str,
    params: dict[str, object] | None = None,
    *,
    request_id: int | str = 1,
) -> dict[str, object]:
    """Create a JSON-RPC request dict."""
    req: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        req["params"] = params
    return req


def make_jsonrpc_notification(
    method: str, params: dict[str, object] | None = None
) -> dict[str, object]:
    """Create a JSON-RPC notification dict."""
    notif: dict[str, object] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        notif["params"] = params
    return notif


# --- MCPServerSession tests ---


class TestMCPServerSessionState:
    """Tests for MCPServerSession state machine."""

    def test_initial_state_idle(self) -> None:
        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        assert session.state == SessionState.IDLE

    def test_ping_in_idle(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(id=1, method="ping", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        assert result.body["result"] == {}

    def test_tools_list_before_init_error(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(id=1, method="tools/list", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_REQUEST

    def test_initialize_transitions_to_initializing(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        assert session.state == SessionState.INITIALIZING

    def test_initialized_notification_transitions_to_active(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcNotification, JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        # Initialize
        msg1 = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        session.handle(msg1, registry, user_id=None)

        # Send initialized notification
        msg2 = JsonRpcNotification(method="notifications/initialized", params={})
        result = session.handle(msg2, registry, user_id=None)
        assert isinstance(result, SessionAck)
        assert session.state == SessionState.ACTIVE

    def test_ping_in_initializing(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        # Initialize
        msg1 = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        session.handle(msg1, registry, user_id=None)
        assert session.state == SessionState.INITIALIZING

        # Ping should work
        msg2 = JsonRpcRequest(id=2, method="ping", params={})
        result = session.handle(msg2, registry, user_id=None)
        assert isinstance(result, SessionResponse)

    def test_ping_in_active(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcNotification, JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        # Full init sequence
        session.handle(
            JsonRpcRequest(
                id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
            ),
            registry,
            user_id=None,
        )
        session.handle(
            JsonRpcNotification(method="notifications/initialized", params={}),
            registry,
            user_id=None,
        )

        # Ping
        result = session.handle(
            JsonRpcRequest(id=2, method="ping", params={}), registry, user_id=None
        )
        assert isinstance(result, SessionResponse)

    def test_close_transitions_to_closed(self) -> None:
        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        session.close()
        assert session.state == SessionState.CLOSED

    def test_request_to_closed_session_error(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()
        session.close()

        msg = JsonRpcRequest(id=1, method="ping", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)


class TestMCPServerSessionVersionNegotiation:
    """Tests for version negotiation."""

    def test_matching_version(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert inner["protocolVersion"] == "2025-03-26"

    def test_unknown_version_returns_server_preferred(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "9999-01-01"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        # Should return server's preferred version
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert inner["protocolVersion"] == "2025-03-26"

    def test_missing_version_error(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(id=1, method="initialize", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_PARAMS


class TestMCPServerSessionInstructions:
    """Tests for instructions in initialize response."""

    def test_instructions_included_when_provided(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(
            info, ServerCapabilities(), (), instructions="HA at http://ha.local:8123"
        )
        registry = GroupRegistry()

        msg = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert inner["instructions"] == "HA at http://ha.local:8123"

    def test_instructions_omitted_when_none(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()

        msg = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert "instructions" not in inner


class TestMCPServerSessionToolsCall:
    """Tests for tools/call handling."""

    def _make_active_session(self) -> tuple[MCPServerSession, GroupRegistry]:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcNotification, JsonRpcRequest

        info = ServerInfo(name="test", version="1.0")
        session = MCPServerSession(info, ServerCapabilities(), ())
        registry = GroupRegistry()
        group = ServicesGroup({"light": {"turn_on": {"description": "Turn on"}}})
        registry.register(group)

        session.handle(
            JsonRpcRequest(
                id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
            ),
            registry,
            user_id=None,
        )
        session.handle(
            JsonRpcNotification(method="notifications/initialized", params={}),
            registry,
            user_id=None,
        )
        return session, registry

    def test_valid_tool_call(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        session, registry = self._make_active_session()
        msg = JsonRpcRequest(
            id=2,
            method="tools/call",
            params={"name": "search", "arguments": {"query": "light"}},
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionToolCall)
        assert result.request_id == 2

    def test_missing_name_error(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        session, registry = self._make_active_session()
        msg = JsonRpcRequest(id=2, method="tools/call", params={"arguments": {}})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_PARAMS

    def test_missing_arguments_uses_empty(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        session, registry = self._make_active_session()
        msg = JsonRpcRequest(id=2, method="tools/call", params={"name": "search"})
        result = session.handle(msg, registry, user_id=None)
        # Should still work - arguments defaults to {}
        assert isinstance(result, SessionToolCall)

    def test_unknown_tool_error(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        session, registry = self._make_active_session()
        msg = JsonRpcRequest(
            id=2, method="tools/call", params={"name": "unknown_tool", "arguments": {}}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_PARAMS

    def test_unknown_method_error(self) -> None:
        from hamster_mcp.mcp._core.jsonrpc import JsonRpcRequest

        session, registry = self._make_active_session()
        msg = JsonRpcRequest(id=2, method="unknown/method", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == METHOD_NOT_FOUND


# --- SessionManager tests ---


class TestSessionManagerHTTPValidation:
    """Tests for HTTP-level validation."""

    def test_wrong_content_type(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(body={}, content_type="text/plain")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 415

    def test_content_type_with_charset(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, content_type="application/json; charset=utf-8")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_accept_absent_ok(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, accept=None)
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_accept_empty_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, accept="")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 406

    def test_accept_text_html_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, accept="text/html")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 406

    def test_accept_application_json_ok(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, accept="application/json")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_accept_wildcard_ok(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, accept="*/*")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_accept_application_wildcard_ok(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, accept="application/*")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_origin_absent_ok(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, origin=None, host="localhost:8123")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_origin_matches_host_ok(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(
            body=body, origin="http://localhost:8123", host="localhost:8123"
        )
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_origin_mismatch_forbidden(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, origin="http://evil.com", host="localhost:8123")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 403

    def test_malformed_json_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(body="{invalid json")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400

    def test_empty_body_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(body=None)
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400

    def test_non_object_json_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(body='"just a string"')
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400

    def test_get_request_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(method="GET")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 405

    def test_delete_valid_session(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "test-session",
        )
        # Create session
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body)
        manager.receive_request(req, now=0.0)

        # Delete it
        req2 = make_request(method="DELETE", session_id="test-session")
        result = manager.receive_request(req2, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_delete_unknown_session(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(method="DELETE", session_id="unknown")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 404

    def test_delete_no_session_id(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(method="DELETE", session_id=None)
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400


class TestSessionManagerBatch:
    """Tests for batch request handling."""

    def test_batch_two_requests(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
        )
        # Init first
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)
        manager.receive_request(
            make_request(
                body=make_jsonrpc_notification("notifications/initialized"),
                session_id="sess",
            ),
            now=0.0,
        )

        # Batch request
        batch = [
            make_jsonrpc_request("tools/list", request_id=1),
            make_jsonrpc_request("tools/list", request_id=2),
        ]
        req = make_request(body=batch, session_id="sess")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_batch_only_notifications(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
        )
        # Init
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)
        manager.receive_request(
            make_request(
                body=make_jsonrpc_notification("notifications/initialized"),
                session_id="sess",
            ),
            now=0.0,
        )

        # Batch of notifications
        batch = [
            make_jsonrpc_notification("some/notification"),
            make_jsonrpc_notification("another/notification"),
        ]
        req = make_request(body=batch, session_id="sess")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 202

    def test_empty_batch_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        req = make_request(body=[])
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400

    def test_initialize_in_batch_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        batch = [make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})]
        req = make_request(body=batch)
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400


class TestSessionManagerRouting:
    """Tests for session routing."""

    def test_no_session_id_init_creates_session(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        req = make_request(body=body, session_id=None)
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200
        assert "Mcp-Session-Id" in result.headers

    def test_no_session_id_non_init_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("tools/list")
        req = make_request(body=body, session_id=None)
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 400

    def test_unknown_session_id_error(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        body = make_jsonrpc_request("tools/list")
        req = make_request(body=body, session_id="unknown")
        result = manager.receive_request(req, now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 404

    def test_session_id_header_only_on_init(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess123",
        )
        # Init - should have header
        body1 = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        result1 = manager.receive_request(make_request(body=body1), now=0.0)
        assert isinstance(result1, SendResponse)
        assert result1.headers.get("Mcp-Session-Id") == "sess123"

        # Initialized notification
        body2 = make_jsonrpc_notification("notifications/initialized")
        manager.receive_request(make_request(body=body2, session_id="sess123"), now=0.0)

        # tools/list - should NOT have session header
        body3 = make_jsonrpc_request("tools/list")
        result3 = manager.receive_request(
            make_request(body=body3, session_id="sess123"), now=0.0
        )
        assert isinstance(result3, SendResponse)
        assert "Mcp-Session-Id" not in result3.headers

    def test_multiple_sessions(self) -> None:
        counter = [0]

        def factory() -> str:
            counter[0] += 1
            return f"sess-{counter[0]}"

        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=factory,
        )

        # Create two sessions
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        r1 = manager.receive_request(make_request(body=body), now=0.0)
        r2 = manager.receive_request(make_request(body=body), now=0.0)

        assert isinstance(r1, SendResponse)
        assert isinstance(r2, SendResponse)
        assert r1.headers["Mcp-Session-Id"] == "sess-1"
        assert r2.headers["Mcp-Session-Id"] == "sess-2"


class TestSessionManagerRegistry:
    """Tests for group registry management."""

    def test_update_registry(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        registry = GroupRegistry()
        group = ServicesGroup({"light": {"turn_on": {"description": "Turn on"}}})
        registry.register(group)
        manager.update_registry(registry)
        # Registry is internal, just verify no error


class TestSessionManagerToolCallParams:
    """Tests for tools/call parameter validation."""

    def _make_active_manager(self) -> tuple[SessionManager, str]:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)
        manager.receive_request(
            make_request(
                body=make_jsonrpc_notification("notifications/initialized"),
                session_id="sess",
            ),
            now=0.0,
        )
        return manager, "sess"

    def test_missing_name(self) -> None:
        manager, sess = self._make_active_manager()
        body = make_jsonrpc_request("tools/call", {"arguments": {}})
        result = manager.receive_request(
            make_request(body=body, session_id=sess), now=0.0
        )
        assert isinstance(result, SendResponse)
        # Error is in JSON-RPC body
        assert result.body is not None
        error = result.body.get("error")
        assert isinstance(error, dict)
        assert error.get("code") == INVALID_PARAMS

    def test_name_wrong_type(self) -> None:
        manager, sess = self._make_active_manager()
        body: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": 123, "arguments": {}},
        }
        result = manager.receive_request(
            make_request(body=body, session_id=sess), now=0.0
        )
        assert isinstance(result, SendResponse)
        assert result.body is not None
        error = result.body.get("error")
        assert isinstance(error, dict)
        assert error.get("code") == INVALID_PARAMS

    def test_arguments_wrong_type(self) -> None:
        manager, sess = self._make_active_manager()
        body = make_jsonrpc_request(
            "tools/call", {"name": "search", "arguments": "string"}
        )
        result = manager.receive_request(
            make_request(body=body, session_id=sess), now=0.0
        )
        assert isinstance(result, SendResponse)
        assert result.body is not None
        error = result.body.get("error")
        assert isinstance(error, dict)
        assert error.get("code") == INVALID_PARAMS


class TestSessionManagerProgrammaticClose:
    """Tests for close_session()."""

    def test_close_valid(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)

        assert manager.close_session("sess") is True

        # Subsequent request should fail
        body2 = make_jsonrpc_request("tools/list")
        result = manager.receive_request(
            make_request(body=body2, session_id="sess"), now=0.0
        )
        assert isinstance(result, SendResponse)
        assert result.status == 404

    def test_close_unknown(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        assert manager.close_session("unknown") is False


class TestSessionManagerEffectResponse:
    """Tests for build_effect_response()."""

    def test_basic(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        result = CallToolResult(content=(TextContent(text="done"),))
        response = manager.build_effect_response(42, result)
        assert isinstance(response, SendResponse)
        assert response.status == 200
        assert response.body is not None
        assert response.body["id"] == 42

    def test_after_session_expired(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
            idle_timeout=0.0,  # Immediate expiry
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)

        # Expire the session
        manager.check_wakeups(now=1.0)

        # Should still work
        result = CallToolResult(content=(TextContent(text="done"),))
        response = manager.build_effect_response(1, result)
        assert isinstance(response, SendResponse)
        assert response.status == 200


class TestSessionManagerWakeups:
    """Tests for check_wakeups()."""

    def test_no_sessions_no_debounce(self) -> None:
        manager = SessionManager(ServerInfo(name="test", version="1.0"), resources=())
        expired, should_regen, wakeup = manager.check_wakeups(now=0.0)
        assert expired == []
        assert should_regen is False
        assert wakeup is None

    def test_within_timeout_not_expired(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
            idle_timeout=100.0,
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)

        expired, _should_regen, wakeup = manager.check_wakeups(now=50.0)
        assert expired == []
        assert wakeup is not None
        assert wakeup.deadline == 100.0

    def test_past_timeout_expired(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
            idle_timeout=100.0,
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)

        expired, _should_regen, _wakeup = manager.check_wakeups(now=100.0)
        assert len(expired) == 1
        assert expired[0].session_id == "sess"

    def test_activity_pushback(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
            idle_timeout=100.0,
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)
        manager.receive_request(
            make_request(
                body=make_jsonrpc_notification("notifications/initialized"),
                session_id="sess",
            ),
            now=0.0,
        )

        # Activity at t=50
        body2 = make_jsonrpc_request("tools/list")
        manager.receive_request(make_request(body=body2, session_id="sess"), now=50.0)

        # At t=100, should NOT be expired (last activity was t=50)
        expired, _, wakeup = manager.check_wakeups(now=100.0)
        assert expired == []
        assert wakeup is not None
        assert wakeup.deadline == 150.0

    def test_debounce_triggers(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            debounce_delay=1.0,
        )
        manager.notify_services_changed(now=0.0)

        # Before debounce
        _, should_regen, wakeup = manager.check_wakeups(now=0.5)
        assert should_regen is False
        assert wakeup is not None
        assert wakeup.deadline == 1.0

        # After debounce
        _, should_regen, _ = manager.check_wakeups(now=1.0)
        assert should_regen is True

    def test_debounce_reset(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            debounce_delay=1.0,
        )
        manager.notify_services_changed(now=0.0)
        manager.notify_services_changed(now=0.5)  # Reset

        # At t=1.0, should NOT trigger (reset to t=0.5 + 1.0 = t=1.5)
        _, should_regen, wakeup = manager.check_wakeups(now=1.0)
        assert should_regen is False
        assert wakeup is not None
        assert wakeup.deadline == 1.5


class TestSessionManagerConcurrency:
    """Tests for concurrent request handling."""

    def test_multiple_requests_before_response(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sess",
        )
        registry = GroupRegistry()
        group = ServicesGroup({"light": {"turn_on": {"description": "Turn on"}}})
        registry.register(group)
        manager.update_registry(registry)

        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        manager.receive_request(make_request(body=body), now=0.0)
        manager.receive_request(
            make_request(
                body=make_jsonrpc_notification("notifications/initialized"),
                session_id="sess",
            ),
            now=0.0,
        )

        # Two tools/call requests
        body1 = make_jsonrpc_request(
            "tools/call",
            {
                "name": "call",
                "arguments": {"path": "services/light.turn_on"},
            },
            request_id=1,
        )
        body2 = make_jsonrpc_request(
            "tools/call",
            {
                "name": "call",
                "arguments": {"path": "services/light.turn_on"},
            },
            request_id=2,
        )

        r1 = manager.receive_request(
            make_request(body=body1, session_id="sess"), now=0.0
        )
        r2 = manager.receive_request(
            make_request(body=body2, session_id="sess"), now=0.0
        )

        # Both should return RunEffects
        assert isinstance(r1, RunEffects)
        assert isinstance(r2, RunEffects)
        assert r1.request_id == 1
        assert r2.request_id == 2


class TestSessionManagerSessionIdValidation:
    """Tests for session ID validation."""

    def test_valid_ascii(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "abc123",
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        result = manager.receive_request(make_request(body=body), now=0.0)
        assert isinstance(result, SendResponse)
        assert result.status == 200

    def test_space_invalid(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "abc 123",
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        with pytest.raises(ValueError, match="Invalid session ID"):
            manager.receive_request(make_request(body=body), now=0.0)

    def test_control_char_invalid(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "abc\n123",
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        with pytest.raises(ValueError, match="Invalid session ID"):
            manager.receive_request(make_request(body=body), now=0.0)

    def test_non_ascii_invalid(self) -> None:
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "café",
        )
        body = make_jsonrpc_request("initialize", {"protocolVersion": "2025-03-26"})
        with pytest.raises(ValueError, match="Invalid session ID"):
            manager.receive_request(make_request(body=body), now=0.0)


class TestHappyPath:
    """Full happy path test."""

    def test_full_flow(self) -> None:
        manager = SessionManager(
            ServerInfo(name="hamster-mcp", version="1.0.0"),
            resources=(),
            session_id_factory=lambda: "test-session-id",
        )
        registry = GroupRegistry()
        group = ServicesGroup({"light": {"turn_on": {"description": "Turn on"}}})
        registry.register(group)
        manager.update_registry(registry)

        # 1. Initialize
        init_body = make_jsonrpc_request(
            "initialize", {"protocolVersion": "2025-03-26"}
        )
        init_result = manager.receive_request(make_request(body=init_body), now=0.0)
        assert isinstance(init_result, SendResponse)
        assert init_result.status == 200
        assert init_result.headers["Mcp-Session-Id"] == "test-session-id"

        # 2. Initialized notification
        ack_body = make_jsonrpc_notification("notifications/initialized")
        ack_result = manager.receive_request(
            make_request(body=ack_body, session_id="test-session-id"), now=0.0
        )
        assert isinstance(ack_result, SendResponse)
        assert ack_result.status == 202

        # 3. List tools
        list_body = make_jsonrpc_request("tools/list")
        list_result = manager.receive_request(
            make_request(body=list_body, session_id="test-session-id"), now=0.0
        )
        assert isinstance(list_result, SendResponse)
        assert list_result.status == 200
        assert list_result.body is not None
        inner = list_result.body["result"]
        assert isinstance(inner, dict)
        assert "tools" in inner

        # 4. Call tool
        call_body = make_jsonrpc_request(
            "tools/call",
            {"name": "search", "arguments": {"query": "light"}},
        )
        call_result = manager.receive_request(
            make_request(body=call_body, session_id="test-session-id"), now=0.0
        )
        assert isinstance(call_result, RunEffects)
        assert call_result.request_id == 1


class TestSessionManagerInstructionsFactory:
    """Tests for instructions_factory on SessionManager."""

    def test_factory_called_with_user_identity(self) -> None:
        """Factory receives user_id and user_name from the initialize request."""
        calls: list[tuple[str | None, str | None]] = []

        def factory(user_id: str | None, user_name: str | None) -> str:
            calls.append((user_id, user_name))
            return f"Hello {user_name}"

        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sid-1",
            instructions_factory=factory,
        )

        init_body = make_jsonrpc_request(
            "initialize", {"protocolVersion": "2025-03-26"}
        )
        result = manager.receive_request(
            make_request(body=init_body, user_id="uid-1", user_name="Kyle"),
            now=0.0,
        )
        assert isinstance(result, SendResponse)
        assert result.status == 200
        assert calls == [("uid-1", "Kyle")]

        # Verify instructions appear in the response
        assert result.body is not None
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert inner["instructions"] == "Hello Kyle"

    def test_no_factory_means_no_instructions(self) -> None:
        """Without a factory, initialize response has no instructions key."""
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sid-1",
        )

        init_body = make_jsonrpc_request(
            "initialize", {"protocolVersion": "2025-03-26"}
        )
        result = manager.receive_request(
            make_request(body=init_body, user_id="uid-1", user_name="Kyle"),
            now=0.0,
        )
        assert isinstance(result, SendResponse)
        assert result.body is not None
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert "instructions" not in inner

    def test_factory_returning_none_omits_instructions(self) -> None:
        """A factory that returns None produces no instructions key."""
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: "sid-1",
            instructions_factory=lambda uid, uname: None,
        )

        init_body = make_jsonrpc_request(
            "initialize", {"protocolVersion": "2025-03-26"}
        )
        result = manager.receive_request(
            make_request(body=init_body),
            now=0.0,
        )
        assert isinstance(result, SendResponse)
        assert result.body is not None
        inner = result.body["result"]
        assert isinstance(inner, dict)
        assert "instructions" not in inner

    def test_factory_called_per_session(self) -> None:
        """Each new session calls the factory independently."""
        counter = [0]

        def counting_factory(user_id: str | None, user_name: str | None) -> str:
            counter[0] += 1
            return f"Session {counter[0]}"

        sid = [0]
        manager = SessionManager(
            ServerInfo(name="test", version="1.0"),
            resources=(),
            session_id_factory=lambda: (
                f"sid-{(sid.__setitem__(0, sid[0] + 1), sid[0])[1]}"
            ),
            instructions_factory=counting_factory,
        )

        for i in range(1, 4):
            init_body = make_jsonrpc_request(
                "initialize", {"protocolVersion": "2025-03-26"}, request_id=i
            )
            result = manager.receive_request(make_request(body=init_body), now=float(i))
            assert isinstance(result, SendResponse)
            assert result.body is not None
            inner = result.body["result"]
            assert isinstance(inner, dict)
            assert inner["instructions"] == f"Session {i}"

        assert counter[0] == 3
