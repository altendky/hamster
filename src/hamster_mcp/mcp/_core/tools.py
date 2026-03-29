"""Meta-tool definitions, GroupRegistry-based call_tool(), and resume().

Uses the "meta-tool" pattern: instead of generating one MCP tool per HA service,
4 fixed tools let the LLM discover and invoke any command dynamically across
multiple source groups (services, hass, supervisor).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .events import (
    Continuation,
    Done,
    FormatHassResponse,
    FormatServiceResponse,
    FormatSupervisorResponse,
    ToolEffect,
)
from .resources import ResourceEntry
from .resources import read_resource as _read_resource
from .types import (
    CallToolResult,
    HassCommandResult,
    ServiceCallResult,
    SupervisorCallResult,
    TextContent,
    Tool,
)

if TYPE_CHECKING:
    from .groups import GroupRegistry

# --- Fixed tool definitions ---

TOOLS: tuple[Tool, ...] = (
    Tool(
        name="search",
        description=(
            "Search for commands across all groups. Use path_filter to narrow "
            "scope (e.g., 'services', 'services/light', 'hass/config')."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to find matching commands",
                },
                "path_filter": {
                    "type": "string",
                    "description": (
                        "Optional path prefix filter "
                        "(e.g., 'services', 'services/light', 'hass')"
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="explain",
        description=(
            "Get detailed description of a command. Path format: "
            "group/command (e.g., 'services/light.turn_on', 'hass/get_states')."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Command path in group/command format "
                        "(e.g., 'services/light.turn_on')"
                    ),
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="call",
        description=(
            "Execute a command. Path format: group/command. "
            "Arguments are command-specific."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Command path in group/command format "
                        "(e.g., 'services/light.turn_on', 'hass/get_states')"
                    ),
                },
                "arguments": {
                    "type": "object",
                    "description": "Command-specific arguments",
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="schema",
        description=(
            "Get schema/type information for a command or type. "
            "For services, use 'services/selector/TYPE' "
            "(e.g., 'services/selector/duration'). "
            "For commands, use the command path."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to command or type "
                        "(e.g., 'services/light.turn_on', 'services/selector/duration')"
                    ),
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="list_resources",
        description=(
            "List available resource documents with practical guidance "
            "for working with Home Assistant entities, services, and "
            "configurations. Returns URIs that can be read with "
            "read_resource."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="read_resource",
        description=(
            "Read a specific resource document by URI. Use "
            "list_resources to discover available URIs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": (
                        "The URI of the resource to read "
                        "(e.g., 'insights:service-targeting'). "
                        "Use list_resources to discover available URIs."
                    ),
                },
            },
            "required": ["uri"],
        },
    ),
)


# --- Tool dispatch ---


def _make_error(message: str) -> Done:
    """Create a Done result with an error."""
    return Done(
        result=CallToolResult(
            content=(TextContent(text=message),),
            is_error=True,
        )
    )


def _make_text(text: str) -> Done:
    """Create a Done result with text content."""
    return Done(result=CallToolResult(content=(TextContent(text=text),)))


def call_tool(
    name: str,
    arguments: dict[str, object],
    registry: GroupRegistry,
    user_id: str | None,
    resources: tuple[ResourceEntry, ...],
) -> ToolEffect:
    """Dispatch a tool call by name.

    Args:
        name: Tool name (search, explain, call, schema)
        arguments: Tool arguments
        registry: Group registry with registered source groups
        user_id: Authenticated user ID for authorization
        resources: Pre-loaded static resource entries

    Returns:
        ToolEffect (Done for immediate results, effect for I/O)
    """
    if name == "search":
        return _call_search(arguments, registry)
    if name == "explain":
        return _call_explain(arguments, registry)
    if name == "call":
        return _call_call(arguments, registry, user_id)
    if name == "schema":
        return _call_schema(arguments, registry)
    if name == "list_resources":
        return _call_list_resources(resources)
    if name == "read_resource":
        return _call_read_resource(arguments, resources)
    return _make_error(f"Unknown tool: {name}")


def _call_search(arguments: dict[str, object], registry: GroupRegistry) -> ToolEffect:
    """Handle search tool."""
    query = arguments.get("query")
    if not isinstance(query, str):
        return _make_error("Missing or invalid 'query' parameter (must be a string)")

    path_filter = arguments.get("path_filter")
    if path_filter is not None and not isinstance(path_filter, str):
        return _make_error("Invalid 'path_filter' parameter (must be a string)")

    result = registry.search_all(query, path_filter=path_filter)
    return _make_text(result)


def _call_explain(arguments: dict[str, object], registry: GroupRegistry) -> ToolEffect:
    """Handle explain tool."""
    path = arguments.get("path")
    if not isinstance(path, str):
        return _make_error("Missing or invalid 'path' parameter (must be a string)")

    if not path:
        return _make_error("Invalid path: empty string")

    resolved = registry.resolve_path(path)
    if resolved is None:
        if "/" not in path:
            return _make_error(f"Invalid path format (must be group/command): {path}")
        return _make_error(f"Unknown group in path: {path}")

    group, in_group_path = resolved
    result = group.explain(in_group_path)
    if result is None:
        return _make_error(f"Command not found: {path}")
    return _make_text(result)


def _call_call(
    arguments: dict[str, object], registry: GroupRegistry, user_id: str | None
) -> ToolEffect:
    """Handle call tool."""
    path = arguments.get("path")
    if not isinstance(path, str):
        return _make_error("Missing or invalid 'path' parameter (must be a string)")

    if not path:
        return _make_error("Invalid path: empty string")

    resolved = registry.resolve_path(path)
    if resolved is None:
        if "/" not in path:
            return _make_error(f"Invalid path format (must be group/command): {path}")
        return _make_error(f"Unknown group in path: {path}")

    call_arguments = arguments.get("arguments")
    if call_arguments is None:
        call_arguments = {}
    if not isinstance(call_arguments, dict):
        return _make_error("Invalid 'arguments' parameter (must be an object)")

    group, in_group_path = resolved
    return group.parse_call_args(in_group_path, call_arguments, user_id)


def _call_list_resources(resources: tuple[ResourceEntry, ...]) -> ToolEffect:
    """Handle list_resources tool."""
    entries = resources
    if not entries:
        return _make_text("No resources available.")

    lines = [f"Available resources ({len(entries)}):"]
    for entry in entries:
        lines.append(f"\n{entry.uri} -- {entry.title}")
        lines.append(f"  {entry.description}")
    return _make_text("\n".join(lines))


def _call_read_resource(
    arguments: dict[str, object], resources: tuple[ResourceEntry, ...]
) -> ToolEffect:
    """Handle read_resource tool."""
    uri = arguments.get("uri")
    if not isinstance(uri, str):
        return _make_error("Missing or invalid 'uri' parameter (must be a string)")

    entry = _read_resource(resources, uri)
    if entry is not None:
        return _make_text(entry.content)

    available = ", ".join(e.uri for e in resources)
    return _make_error(f"Resource not found: {uri}. Available URIs: {available}")


def _call_schema(arguments: dict[str, object], registry: GroupRegistry) -> ToolEffect:
    """Handle schema tool."""
    path = arguments.get("path")
    if not isinstance(path, str):
        return _make_error("Missing or invalid 'path' parameter (must be a string)")

    if not path:
        return _make_error("Invalid path: empty string")

    resolved = registry.resolve_path(path)
    if resolved is None:
        if "/" not in path:
            return _make_error(f"Invalid path format (must be group/command): {path}")
        return _make_error(f"Unknown group in path: {path}")

    group, in_group_path = resolved
    result = group.schema(in_group_path)
    if result is None:
        return _make_error(f"Schema not found: {path}")
    return _make_text(result)


# --- Continuation ---


def resume(
    continuation: Continuation,
    io_result: ServiceCallResult | HassCommandResult | SupervisorCallResult,
) -> ToolEffect:
    """Resume tool execution after I/O completes.

    Args:
        continuation: The continuation from ServiceCall, HassCommand, or SupervisorCall
        io_result: Result of the I/O operation

    Returns:
        Next ToolEffect (usually Done)
    """
    if isinstance(continuation, FormatServiceResponse):
        if not isinstance(io_result, ServiceCallResult):
            return _make_error(
                "Invalid IO result type for FormatServiceResponse"
            )  # pragma: no cover
        return _format_service_response(io_result)

    if isinstance(continuation, FormatHassResponse):
        if not isinstance(io_result, HassCommandResult):
            return _make_error(
                "Invalid IO result type for FormatHassResponse"
            )  # pragma: no cover
        return _format_hass_response(io_result)

    if isinstance(continuation, FormatSupervisorResponse):
        if not isinstance(io_result, SupervisorCallResult):
            return _make_error(
                "Invalid IO result type for FormatSupervisorResponse"
            )  # pragma: no cover
        return _format_supervisor_response(io_result)

    # Should not happen with proper typing, but handle gracefully
    return _make_error(
        f"Unknown continuation type: {type(continuation)}"
    )  # pragma: no cover


def _format_service_response(io_result: ServiceCallResult) -> Done:
    """Format a service call result into MCP content."""
    if not io_result.success:
        return Done(
            result=CallToolResult(
                content=(TextContent(text=f"Error: {io_result.error}"),),
                is_error=True,
            )
        )

    if io_result.data:
        text = json.dumps(io_result.data, indent=2, default=str)
    else:
        text = "Service call completed successfully."

    return Done(result=CallToolResult(content=(TextContent(text=text),)))


def _format_hass_response(io_result: HassCommandResult) -> Done:
    """Format a WebSocket command result into MCP content."""
    if not io_result.success:
        return Done(
            result=CallToolResult(
                content=(TextContent(text=f"Error: {io_result.error}"),),
                is_error=True,
            )
        )

    if io_result.data is not None:
        text = json.dumps(io_result.data, indent=2, default=str)
    else:
        text = "Command completed successfully."

    return Done(result=CallToolResult(content=(TextContent(text=text),)))


def _format_supervisor_response(io_result: SupervisorCallResult) -> Done:
    """Format a Supervisor API result into MCP content."""
    if not io_result.success:
        return Done(
            result=CallToolResult(
                content=(TextContent(text=f"Error: {io_result.error}"),),
                is_error=True,
            )
        )

    if io_result.data is not None:
        # Handle both dict (JSON) and str (logs) responses
        if isinstance(io_result.data, str):
            text = io_result.data
        else:
            text = json.dumps(io_result.data, indent=2, default=str)
    else:
        text = "Supervisor call completed successfully."

    return Done(result=CallToolResult(content=(TextContent(text=text),)))
