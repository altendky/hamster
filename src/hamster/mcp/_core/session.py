"""Session manager and per-session state machine.

The SessionManager is the single entry point for the sans-IO core: it receives
raw HTTP request data (IncomingRequest) and returns a complete response
instruction (ReceiveResult).
"""

from __future__ import annotations

from dataclasses import dataclass
import enum
import json
import secrets
from typing import TYPE_CHECKING

from .events import ReceiveResult, RunEffects, SendResponse, SessionExpired, ToolEffect
from .groups import GroupRegistry, ServicesGroup
from .jsonrpc import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    MCP_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_VERSIONS,
    JsonRpcNotification,
    JsonRpcParseError,
    JsonRpcRequest,
    JsonRpcResponse,
    build_initialize_response,
    build_tool_list_response,
    build_tool_result_response,
    make_error_response,
    parse_batch,
)
from .tools import TOOLS, call_tool
from .types import CallToolResult, JsonRpcId, ServerCapabilities, ServerInfo

if TYPE_CHECKING:
    from collections.abc import Callable


# --- Session internal result types ---


@dataclass(frozen=True, slots=True)
class SessionResponse:
    """A JSON-RPC response body to send to the client."""

    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class SessionAck:
    """A notification was processed. Manager wraps as SendResponse(202)."""


@dataclass(frozen=True, slots=True)
class SessionToolCall:
    """A tool call needs effect dispatch. Manager wraps as RunEffects."""

    request_id: JsonRpcId
    effect: ToolEffect


@dataclass(frozen=True, slots=True)
class SessionError:
    """A JSON-RPC error. Manager builds error response."""

    code: int
    message: str
    request_id: JsonRpcId | None = None


SessionResult = SessionResponse | SessionAck | SessionToolCall | SessionError


# --- Session state machine ---


class SessionState(enum.Enum):
    """MCP session states."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    CLOSED = "closed"


class MCPServerSession:
    """Per-session state machine.

    Internal to the core - not called directly by the transport.
    Only SessionManager interacts with sessions.
    """

    def __init__(
        self,
        server_info: ServerInfo,
        capabilities: ServerCapabilities,
        instructions: str | None = None,
    ) -> None:
        """Initialize a new session."""
        self._state = SessionState.IDLE
        self._server_info = server_info
        self._capabilities = capabilities
        self._instructions = instructions
        self._negotiated_version: str | None = None

    @property
    def state(self) -> SessionState:
        """Current session state."""
        return self._state

    def handle(
        self,
        message: JsonRpcRequest | JsonRpcNotification,
        registry: GroupRegistry,
        user_id: str | None,
    ) -> SessionResult:
        """Handle a JSON-RPC message.

        Args:
            message: Parsed JSON-RPC request or notification
            registry: Group registry for tool calls
            user_id: Authenticated user ID for authorization

        Returns:
            SessionResult indicating what to do
        """
        if self._state == SessionState.CLOSED:
            return SessionError(
                code=INVALID_REQUEST,
                message="Session is closed",
                request_id=message.id if isinstance(message, JsonRpcRequest) else None,
            )

        method = message.method

        # ping is allowed in any non-closed state
        if method == "ping":
            if isinstance(message, JsonRpcRequest):
                return SessionResponse(
                    body=make_error_response(message.id, 0, "")["error"]
                    if False
                    else {"jsonrpc": "2.0", "id": message.id, "result": {}}
                )
            return SessionAck()

        if self._state == SessionState.IDLE:
            return self._handle_idle(message)
        if self._state == SessionState.INITIALIZING:
            return self._handle_initializing(message)
        if self._state == SessionState.ACTIVE:
            return self._handle_active(message, registry, user_id)

        # Should not reach here
        return SessionError(  # pragma: no cover
            code=INVALID_REQUEST,
            message="Invalid session state",
            request_id=message.id if isinstance(message, JsonRpcRequest) else None,
        )

    def _handle_idle(
        self, message: JsonRpcRequest | JsonRpcNotification
    ) -> SessionResult:
        """Handle messages in IDLE state."""
        if message.method != "initialize":
            return SessionError(
                code=INVALID_REQUEST,
                message="Session not initialized",
                request_id=message.id if isinstance(message, JsonRpcRequest) else None,
            )

        if isinstance(message, JsonRpcNotification):
            return SessionError(
                code=INVALID_REQUEST,
                message="initialize must be a request, not a notification",
            )

        # Extract and validate protocol version
        params = message.params
        requested_version = params.get("protocolVersion")
        if not isinstance(requested_version, str):
            return SessionError(
                code=INVALID_PARAMS,
                message="Missing protocolVersion",
                request_id=message.id,
            )

        # Version negotiation
        if requested_version in SUPPORTED_VERSIONS:
            self._negotiated_version = requested_version
        else:
            self._negotiated_version = MCP_PROTOCOL_VERSION

        self._state = SessionState.INITIALIZING
        return SessionResponse(
            body=build_initialize_response(
                message.id,
                self._server_info,
                self._capabilities,
                self._negotiated_version,
                instructions=self._instructions,
            )
        )

    def _handle_initializing(
        self, message: JsonRpcRequest | JsonRpcNotification
    ) -> SessionResult:
        """Handle messages in INITIALIZING state."""
        if message.method == "notifications/initialized":
            self._state = SessionState.ACTIVE
            return SessionAck()

        return SessionError(
            code=INVALID_REQUEST,
            message="Expected notifications/initialized",
            request_id=message.id if isinstance(message, JsonRpcRequest) else None,
        )

    def _handle_active(
        self,
        message: JsonRpcRequest | JsonRpcNotification,
        registry: GroupRegistry,
        user_id: str | None,
    ) -> SessionResult:
        """Handle messages in ACTIVE state."""
        method = message.method

        # Notifications in active state are acknowledged
        if isinstance(message, JsonRpcNotification):
            return SessionAck()

        # Request handling
        if method == "tools/list":
            return SessionResponse(body=build_tool_list_response(message.id, TOOLS))

        if method == "tools/call":
            return self._handle_tools_call(message, registry, user_id)

        # Unknown method
        return SessionError(
            code=METHOD_NOT_FOUND,
            message=f"Method not found: {method}",
            request_id=message.id,
        )

    def _handle_tools_call(
        self,
        message: JsonRpcRequest,
        registry: GroupRegistry,
        user_id: str | None,
    ) -> SessionResult:
        """Handle tools/call request."""
        params = message.params

        # Validate params.name
        name = params.get("name")
        if not isinstance(name, str):
            return SessionError(
                code=INVALID_PARAMS,
                message="Missing or invalid 'name' in tools/call params",
                request_id=message.id,
            )

        # Validate params.arguments
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return SessionError(
                code=INVALID_PARAMS,
                message="Invalid 'arguments' in tools/call params",
                request_id=message.id,
            )

        # Check if tool exists
        tool_names = {t.name for t in TOOLS}
        if name not in tool_names:
            return SessionError(
                code=INVALID_PARAMS,
                message=f"Unknown tool: {name}",
                request_id=message.id,
            )

        # Dispatch to tool
        effect = call_tool(name, arguments, registry, user_id)
        return SessionToolCall(request_id=message.id, effect=effect)

    def close(self) -> None:
        """Close the session."""
        self._state = SessionState.CLOSED


# --- Wakeup types ---

WakeupToken = object


@dataclass(frozen=True, slots=True)
class WakeupRequest:
    """Request for the I/O layer to wake the core at a specific time."""

    deadline: float
    token: WakeupToken


# --- Session Manager ---


class SessionManager:
    """Multi-session container and HTTP-to-protocol pipeline."""

    def __init__(
        self,
        server_info: ServerInfo,
        idle_timeout: float = 1800.0,
        session_id_factory: Callable[[], str] | None = None,
        debounce_delay: float = 0.5,
        instructions_factory: Callable[[str | None, str | None], str | None]
        | None = None,
    ) -> None:
        """Initialize the session manager.

        Args:
            server_info: Server identification
            idle_timeout: Session idle timeout in seconds (default 30 minutes)
            session_id_factory: Factory for generating session IDs
            debounce_delay: Delay for service index regeneration debouncing
            instructions_factory: Callable taking (user_id, user_name) that
                returns an MCP instructions string, or None.  Called once per
                session at initialize time.
        """
        self._server_info = server_info
        self._capabilities = ServerCapabilities()
        self._idle_timeout = idle_timeout
        self._session_id_factory = session_id_factory or (lambda: secrets.token_hex(16))
        self._debounce_delay = debounce_delay
        self._instructions_factory = instructions_factory

        self._sessions: dict[str, MCPServerSession] = {}
        self._last_activity: dict[str, float] = {}
        self._registry = GroupRegistry()

        # Debounce state for service index regeneration
        self._services_changed_at: float | None = None

    def update_registry(self, registry: GroupRegistry) -> None:
        """Replace the group registry."""
        self._registry = registry
        self._services_changed_at = None  # Clear pending regeneration

    def update_services_group(self, services_group: ServicesGroup) -> None:
        """Update just the services group within the existing registry.

        Used for service event handling where only the services group changes.
        """
        self._registry.update_group(services_group)
        self._services_changed_at = None  # Clear pending regeneration

    def notify_services_changed(self, now: float) -> None:
        """Record that services changed; starts debounce timer."""
        self._services_changed_at = now

    def receive_request(
        self,
        request: IncomingRequest,
        now: float,
    ) -> ReceiveResult | list[ReceiveResult]:
        """Process an incoming HTTP request.

        This is the main entry point for the sans-IO core.

        Args:
            request: Framework-agnostic HTTP request
            now: Current monotonic time

        Returns:
            ReceiveResult or list of ReceiveResults for batch
        """
        # 1. Check HTTP method
        if request.http_method == "GET":
            return SendResponse(
                status=405,
                headers={"Allow": "POST, DELETE"},
                body=None,
            )

        if request.http_method == "DELETE":
            return self._handle_delete(request)

        if request.http_method != "POST":
            return SendResponse(
                status=405,
                headers={"Allow": "POST, DELETE"},
                body=None,
            )

        # 2. Validate Content-Type
        if not self._validate_content_type(request.content_type):
            return SendResponse(
                status=415,
                headers={},
                body=None,
            )

        # 3. Validate Accept
        if not self._validate_accept(request.accept):
            return SendResponse(
                status=406,
                headers={},
                body=None,
            )

        # 4. Validate Origin
        if not self._validate_origin(request.origin, request.host):
            return SendResponse(
                status=403,
                headers={},
                body=None,
            )

        # 5. Parse JSON body
        try:
            body = json.loads(request.body) if request.body else None
        except (json.JSONDecodeError, ValueError):
            return SendResponse(
                status=400,
                headers={"Content-Type": "application/json"},
                body=make_error_response(None, PARSE_ERROR, "Parse error"),
            )

        if body is None:
            return SendResponse(
                status=400,
                headers={"Content-Type": "application/json"},
                body=make_error_response(None, PARSE_ERROR, "Parse error"),
            )

        # 6. Parse JSON-RPC
        parsed = parse_batch(body)

        if isinstance(parsed, list):
            return self._handle_batch(
                parsed, request.session_id, now, request.user_id, request.user_name
            )
        return self._handle_single(
            parsed, request.session_id, now, request.user_id, request.user_name
        )

    def _handle_delete(self, request: IncomingRequest) -> SendResponse:
        """Handle DELETE request (session termination)."""
        session_id = request.session_id
        if session_id is None:
            return SendResponse(
                status=400,
                headers={},
                body=None,
            )

        if self.close_session(session_id):
            return SendResponse(status=200, headers={}, body=None)
        return SendResponse(status=404, headers={}, body=None)

    def _validate_content_type(self, content_type: str | None) -> bool:
        """Validate Content-Type header."""
        if content_type is None:
            return False
        # Extract media type (ignore parameters like charset)
        media_type = content_type.split(";")[0].strip().lower()
        return media_type == "application/json"

    def _validate_accept(self, accept: str | None) -> bool:
        """Validate Accept header."""
        if accept is None:
            return True  # Absent is OK (treated as */*)
        if accept == "":
            return False  # Empty string is not valid

        # Check for compatible types
        accept_lower = accept.lower()
        compatible = ["application/json", "application/*", "*/*"]
        return any(compat in accept_lower for compat in compatible)

    def _validate_origin(self, origin: str | None, host: str) -> bool:
        """Validate Origin header against Host."""
        if origin is None:
            return True  # Non-browser clients don't send Origin

        # Extract host from origin URL
        try:
            # origin is like "http://localhost:8123" or "https://example.com"
            if "://" in origin:
                origin_host = origin.split("://", 1)[1]
                # Remove path if present
                origin_host = origin_host.split("/")[0]
            else:
                origin_host = origin
        except (IndexError, ValueError):
            return False

        return origin_host == host

    def _handle_single(
        self,
        parsed: JsonRpcRequest
        | JsonRpcNotification
        | JsonRpcResponse
        | JsonRpcParseError,
        session_id: str | None,
        now: float,
        user_id: str | None,
        user_name: str | None,
    ) -> ReceiveResult:
        """Handle a single JSON-RPC message."""
        # Handle parse errors
        if isinstance(parsed, JsonRpcParseError):
            return SendResponse(
                status=400,
                headers={"Content-Type": "application/json"},
                body=parsed.response,
            )

        # Handle unexpected response objects
        if isinstance(parsed, JsonRpcResponse):
            return SendResponse(
                status=400,
                headers={"Content-Type": "application/json"},
                body=parsed.response,
            )

        # Route message
        return self._route_message(parsed, session_id, now, user_id, user_name)

    def _handle_batch(
        self,
        parsed_list: list[
            JsonRpcRequest | JsonRpcNotification | JsonRpcResponse | JsonRpcParseError
        ],
        session_id: str | None,
        now: float,
        user_id: str | None,
        user_name: str | None,
    ) -> ReceiveResult | list[ReceiveResult]:
        """Handle a batch of JSON-RPC messages."""
        # Check for initialize in batch (not allowed)
        for parsed in parsed_list:
            if isinstance(parsed, JsonRpcRequest) and parsed.method == "initialize":
                return SendResponse(
                    status=400,
                    headers={"Content-Type": "application/json"},
                    body=make_error_response(
                        parsed.id, INVALID_REQUEST, "initialize not allowed in batch"
                    ),
                )

        results: list[ReceiveResult] = []
        for parsed in parsed_list:
            result = self._handle_single(parsed, session_id, now, user_id, user_name)
            # Notifications don't get responses in batch
            if (
                isinstance(parsed, JsonRpcNotification)
                and isinstance(result, SendResponse)
                and result.status == 202
            ):
                continue
            results.append(result)

        if not results:
            # All notifications
            return SendResponse(status=202, headers={}, body=None)

        return results

    def _route_message(
        self,
        message: JsonRpcRequest | JsonRpcNotification,
        session_id: str | None,
        now: float,
        user_id: str | None,
        user_name: str | None,
    ) -> ReceiveResult:
        """Route a message to the appropriate session."""
        if session_id is None:
            # No session - must be initialize
            if message.method == "initialize":
                return self._create_session_and_handle(message, now, user_id, user_name)
            return SendResponse(
                status=400,
                headers={"Content-Type": "application/json"},
                body=make_error_response(
                    message.id if isinstance(message, JsonRpcRequest) else None,
                    INVALID_REQUEST,
                    "Missing session ID",
                ),
            )

        # Look up existing session
        session = self._sessions.get(session_id)
        if session is None:
            return SendResponse(
                status=404,
                headers={"Content-Type": "application/json"},
                body=make_error_response(
                    message.id if isinstance(message, JsonRpcRequest) else None,
                    INVALID_REQUEST,
                    "Unknown session",
                ),
            )

        # Update activity timestamp
        self._last_activity[session_id] = now

        # Delegate to session
        result = session.handle(message, self._registry, user_id)
        return self._wrap_session_result(
            result, session_id=None
        )  # No header on non-init

    def _create_session_and_handle(
        self,
        message: JsonRpcRequest | JsonRpcNotification,
        now: float,
        user_id: str | None,
        user_name: str | None,
    ) -> ReceiveResult:
        """Create a new session and handle the initialize request."""
        # Generate session ID
        session_id = self._session_id_factory()

        # Validate session ID (must be visible ASCII 0x21-0x7E)
        if not self._is_valid_session_id(session_id):
            raise ValueError(f"Invalid session ID from factory: {session_id!r}")

        # Build per-session instructions via the factory
        # TODO: When a sans-IO tracing/logging tool is available, use it
        #       to report factory errors instead of letting them propagate
        #       unobserved through the I/O layer.
        instructions = (
            self._instructions_factory(user_id, user_name)
            if self._instructions_factory is not None
            else None
        )

        # Create session
        session = MCPServerSession(
            self._server_info, self._capabilities, instructions=instructions
        )
        self._sessions[session_id] = session
        self._last_activity[session_id] = now

        # Handle the initialize request
        result = session.handle(message, self._registry, user_id)
        return self._wrap_session_result(result, session_id=session_id)

    def _is_valid_session_id(self, session_id: str) -> bool:
        """Check if session ID contains only visible ASCII characters."""
        if not session_id:
            return False
        return all(0x21 <= ord(c) <= 0x7E for c in session_id)

    def _wrap_session_result(
        self,
        result: SessionResult,
        session_id: str | None,
    ) -> ReceiveResult:
        """Wrap a SessionResult into a ReceiveResult."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if session_id is not None:
            headers["Mcp-Session-Id"] = session_id

        if isinstance(result, SessionResponse):
            return SendResponse(status=200, headers=headers, body=result.body)

        if isinstance(result, SessionAck):
            # No Content-Type for 202
            return SendResponse(status=202, headers={}, body=None)

        if isinstance(result, SessionToolCall):
            return RunEffects(request_id=result.request_id, effect=result.effect)

        if isinstance(result, SessionError):
            return SendResponse(
                status=200,  # JSON-RPC errors are 200 with error body
                headers=headers,
                body=make_error_response(
                    result.request_id, result.code, result.message
                ),
            )

        # Should not reach here
        raise TypeError(
            f"Unknown session result type: {type(result)}"
        )  # pragma: no cover

    def build_effect_response(
        self,
        request_id: JsonRpcId,
        result: CallToolResult,
    ) -> SendResponse:
        """Build HTTP response after effect dispatch completes.

        This is session-independent and can be called even if the session
        has expired or been closed.
        """
        return SendResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=build_tool_result_response(request_id, result),
        )

    def check_wakeups(
        self,
        now: float,
    ) -> tuple[list[SessionExpired], bool, WakeupRequest | None]:
        """Check for expired sessions and pending debounce.

        Args:
            now: Current monotonic time

        Returns:
            Tuple of:
            - List of SessionExpired events for expired sessions
            - Whether index regeneration should happen
            - Next WakeupRequest, or None if nothing pending
        """
        expired_events: list[SessionExpired] = []
        next_expiry: float | None = None

        # Check for expired sessions
        expired_ids = []
        for session_id, last_activity in self._last_activity.items():
            expiry_time = last_activity + self._idle_timeout
            if now >= expiry_time:
                expired_ids.append(session_id)
            elif next_expiry is None or expiry_time < next_expiry:
                next_expiry = expiry_time

        # Remove expired sessions
        for session_id in expired_ids:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                session.close()
            self._last_activity.pop(session_id, None)
            expired_events.append(SessionExpired(session_id=session_id))

        # Check debounce
        should_regenerate = False
        debounce_deadline: float | None = None
        if self._services_changed_at is not None:
            debounce_deadline = self._services_changed_at + self._debounce_delay
            if now >= debounce_deadline:
                should_regenerate = True
                self._services_changed_at = None
                debounce_deadline = None

        # Compute next wakeup
        next_deadline: float | None = None
        if next_expiry is not None:
            next_deadline = next_expiry
        if debounce_deadline is not None and (
            next_deadline is None or debounce_deadline < next_deadline
        ):
            next_deadline = debounce_deadline

        wakeup: WakeupRequest | None = None
        if next_deadline is not None:
            wakeup = WakeupRequest(deadline=next_deadline, token=object())

        return expired_events, should_regenerate, wakeup

    def handle_wakeup(self, token: WakeupToken, now: float) -> None:
        """Handle a wakeup from the I/O layer.

        Reserved for future use. Currently a no-op.
        """

    def close_session(self, session_id: str) -> bool:
        """Explicitly close and remove a session.

        Returns True if session existed, False otherwise.
        """
        session = self._sessions.pop(session_id, None)
        self._last_activity.pop(session_id, None)
        if session is not None:
            session.close()
            return True
        return False


# Import for type checking
if TYPE_CHECKING:
    from .types import IncomingRequest
