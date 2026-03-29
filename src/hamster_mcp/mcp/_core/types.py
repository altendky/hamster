"""MCP data types.

Frozen dataclasses with no behavior, no I/O, no serialization logic.
Wire format conversion lives in jsonrpc.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# JSON-RPC allows integer, number, string, or null request IDs.
# Fractional numbers are discouraged (SHOULD NOT) but valid.
# None represents a null ID (used in error responses when the original ID
# could not be determined).
JsonRpcId = int | float | str | None


@dataclass(frozen=True, slots=True)
class TextContent:
    """Text content in a tool result.

    No `type` field --- isinstance() discriminates.
    The "type": "text" wire-format key is added by jsonrpc.py.
    """

    text: str


@dataclass(frozen=True, slots=True)
class ImageContent:
    """Image content in a tool result (base64-encoded)."""

    data: str  # base64-encoded
    mime_type: str


# Content union for tool results.
# Intentionally incomplete --- MCP also defines AudioContent and
# EmbeddedResource content types, deferred until needed (see Q014).
Content = TextContent | ImageContent


@dataclass(frozen=True, slots=True)
class Tool:
    """MCP tool definition."""

    name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True, slots=True)
class CallToolResult:
    """Result of a tool invocation."""

    content: tuple[Content, ...]
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """MCP server identification."""

    name: str
    version: str


@dataclass(frozen=True, slots=True)
class ToolsCapability:
    """Tools capability declaration.

    list_changed=False means "we support tools, no listChanged".
    list_changed=True advertises listChanged notifications.
    """

    list_changed: bool = False


@dataclass(frozen=True, slots=True)
class ResourcesCapability:
    """Resources capability declaration.

    list_changed=False means "we support resources, no listChanged".
    list_changed=True advertises listChanged notifications.
    """

    list_changed: bool = False


@dataclass(frozen=True, slots=True)
class ServerCapabilities:
    """MCP server capabilities.

    tools=ToolsCapability() means "we support tools, no listChanged".
    tools=ToolsCapability(list_changed=True) advertises listChanged.
    tools=None means "tools not supported".
    resources=ResourcesCapability() means "we support resources".
    resources=None means "resources not supported".
    """

    tools: ToolsCapability | None = field(default_factory=ToolsCapability)
    resources: ResourcesCapability | None = field(default_factory=ResourcesCapability)


@dataclass(frozen=True, slots=True)
class Resource:
    """MCP resource metadata for resources/list responses."""

    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceContents:
    """MCP resource content for resources/read responses."""

    uri: str
    text: str
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceCallResult:
    """Result from executing a Home Assistant service call.

    Returned by EffectHandler.execute_service_call(), consumed by resume().
    """

    success: bool
    data: dict[str, object] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class HassCommandResult:
    """Result from executing a WebSocket command.

    Returned by EffectHandler.execute_hass_command(), consumed by resume().
    Handler results can be any JSON type, not just dict.
    """

    success: bool
    data: object = None  # Handler results can be any JSON type, not just dict
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SupervisorCallResult:
    """Result from executing a Supervisor API call.

    Returned by EffectHandler.execute_supervisor_call(), consumed by resume().
    Response data can be dict (JSON responses) or str (log content).
    """

    success: bool
    data: object = None  # Could be dict, str (logs), etc.
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingRequest:
    """Framework-agnostic representation of an HTTP request.

    The transport extracts these fields from the framework's request object
    and passes the struct to the sans-IO core, which handles all validation,
    parsing, and routing.
    """

    http_method: str  # "POST", "GET", or "DELETE"
    content_type: str | None  # From Content-Type header
    accept: str | None  # From Accept header
    origin: str | None  # From Origin header
    host: str  # From Host header
    session_id: str | None  # From Mcp-Session-Id header
    body: bytes  # Raw request body
    user_id: str | None = None  # Authenticated user ID for authorization
    user_name: str | None = None  # Authenticated user display name
