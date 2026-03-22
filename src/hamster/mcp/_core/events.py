"""Protocol events and tool effect/continuation types.

These discriminated unions drive the entire system.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import (  # noqa: TC001 - used as dataclass field types
    CallToolResult,
    JsonRpcId,
)

# --- Group 1: Tool effect/continuation types ---
# Used by tools.py: call_tool() produces a ToolEffect, resume() takes
# a Continuation and I/O result and produces the next ToolEffect.


@dataclass(frozen=True, slots=True)
class FormatServiceResponse:
    """Format the raw HA service response into MCP content.

    Continuation type for service call results.
    """


@dataclass(frozen=True, slots=True)
class FormatHassResponse:
    """Format the raw WebSocket command response into MCP content.

    Continuation type for hass command results.
    """


@dataclass(frozen=True, slots=True)
class FormatSupervisorResponse:
    """Format the raw Supervisor API response into MCP content.

    Continuation type for supervisor call results.
    """


# Continuation union - grows as new continuation types are added
Continuation = FormatServiceResponse | FormatHassResponse | FormatSupervisorResponse


@dataclass(frozen=True, slots=True)
class Done:
    """Tool execution completed with a result."""

    result: CallToolResult


@dataclass(frozen=True, slots=True)
class ServiceCall:
    """Request to execute a Home Assistant service call."""

    domain: str
    service: str
    target: dict[str, object] | None
    data: dict[str, object]
    user_id: str | None
    continuation: Continuation


@dataclass(frozen=True, slots=True)
class HassCommand:
    """Request to execute a WebSocket command."""

    command_type: str
    params: dict[str, object]
    user_id: str | None
    continuation: Continuation


@dataclass(frozen=True, slots=True)
class SupervisorCall:
    """Request to execute a Supervisor API call."""

    method: str  # HTTP method: "GET", "POST", etc.
    path: str  # API path, e.g., "/core/logs"
    params: dict[str, object]  # Query params (GET) or body (POST)
    user_id: str | None
    continuation: Continuation


# ToolEffect union - what call_tool() and resume() return
ToolEffect = Done | ServiceCall | HassCommand | SupervisorCall


# --- Group 2: Request result types ---
# Returned by SessionManager.receive_request(). The transport does
# match/case on these. These tell the transport **what to do**, not
# what happened.


@dataclass(frozen=True, slots=True)
class SendResponse:
    """Send an HTTP response to the client.

    Covers all non-effect responses: initialization (200 + Mcp-Session-Id header),
    notification acknowledgment (202, no body), tool list (200), HTTP-level errors
    (405, 406, 415, 503), and JSON-RPC/protocol errors (400/404).
    """

    status: int
    headers: dict[str, str]
    body: dict[str, object] | None  # None for no-body responses (e.g. 202)


@dataclass(frozen=True, slots=True)
class RunEffects:
    """Run the effect dispatch loop for a tools/call request.

    The transport runs the effect dispatch loop, then calls
    manager.build_effect_response(request_id, result) to get a SendResponse.
    """

    request_id: JsonRpcId
    effect: ToolEffect


# ReceiveResult union - what SessionManager.receive_request() returns
ReceiveResult = SendResponse | RunEffects


# --- Group 3: Session lifecycle events ---


@dataclass(frozen=True, slots=True)
class SessionExpired:
    """A session has expired due to idle timeout."""

    session_id: str
