"""JSON-RPC 2.0 message parsing and response building.

Includes MCP type serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .types import (
    CallToolResult,
    Content,
    ImageContent,
    JsonRpcId,
    Resource,
    ResourceContents,
    ServerCapabilities,
    ServerInfo,
    TextContent,
    Tool,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# MCP protocol versions
SUPPORTED_VERSIONS: tuple[str, ...] = ("2025-03-26",)
MCP_PROTOCOL_VERSION = SUPPORTED_VERSIONS[0]


@dataclass(frozen=True, slots=True)
class JsonRpcRequest:
    """A parsed JSON-RPC request (has id and method)."""

    id: JsonRpcId
    method: str
    params: dict[str, object]


@dataclass(frozen=True, slots=True)
class JsonRpcNotification:
    """A parsed JSON-RPC notification (has method, no id)."""

    method: str
    params: dict[str, object]


@dataclass(frozen=True, slots=True)
class JsonRpcResponse:
    """Received when client sends a JSON-RPC response object.

    Since the server never sends requests to clients, these are unexpected.
    Treated as INVALID_REQUEST.
    """

    response: dict[str, object]


@dataclass(frozen=True, slots=True)
class JsonRpcParseError:
    """A JSON-RPC parse or validation error with pre-built response."""

    response: dict[str, object]


ParsedMessage = (
    JsonRpcRequest | JsonRpcNotification | JsonRpcResponse | JsonRpcParseError
)


def make_error_response(
    request_id: JsonRpcId,
    code: int,
    message: str,
) -> dict[str, object]:
    """Build a JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def make_success_response(
    request_id: JsonRpcId,
    result: object,
) -> dict[str, object]:
    """Build a JSON-RPC success response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _extract_id(raw: dict[str, object]) -> tuple[JsonRpcId, bool]:
    """Extract and validate the id field from a raw message.

    Returns (id, is_valid). If id is invalid type, returns (None, False).
    If id key is absent, returns (None, True) - this indicates a notification.
    """
    if "id" not in raw:
        return None, True  # No id = notification (valid)

    id_val = raw["id"]
    # Valid id types: int, float, str, None (null)
    # Invalid: bool (isinstance check - bool is subclass of int!), list, dict
    if isinstance(id_val, bool):
        return None, False
    if isinstance(id_val, int | float | str) or id_val is None:
        return id_val, True
    return None, False


def parse_message(raw: dict[str, object]) -> ParsedMessage:
    """Parse a single JSON-RPC message object.

    Validates JSON-RPC 2.0 structure and returns appropriate parsed type.
    """
    # Check if this is a response object (has result or error, no method)
    if ("result" in raw or "error" in raw) and "method" not in raw:
        raw_id = raw.get("id")
        response_id: JsonRpcId = (
            raw_id if isinstance(raw_id, int | float | str) else None
        )
        error_response = make_error_response(
            response_id,
            INVALID_REQUEST,
            "Unexpected response object",
        )
        return JsonRpcResponse(response=error_response)

    # Validate jsonrpc version
    if raw.get("jsonrpc") != "2.0":
        return JsonRpcParseError(
            response=make_error_response(
                None, INVALID_REQUEST, "Invalid JSON-RPC version"
            )
        )

    # Validate method
    method = raw.get("method")
    if not isinstance(method, str):
        return JsonRpcParseError(
            response=make_error_response(
                None, INVALID_REQUEST, "Missing or invalid method"
            )
        )

    # Validate and extract params (default to empty dict)
    params = raw.get("params")
    if params is None:
        params = {}
    elif not isinstance(params, dict):
        return JsonRpcParseError(
            response=make_error_response(None, INVALID_REQUEST, "Invalid params type")
        )

    # Extract and validate id
    id_val, id_valid = _extract_id(raw)
    if not id_valid:
        return JsonRpcParseError(
            response=make_error_response(None, INVALID_REQUEST, "Invalid id type")
        )

    # Determine if request or notification based on presence of id key
    if "id" in raw:
        return JsonRpcRequest(id=id_val, method=method, params=params)
    return JsonRpcNotification(method=method, params=params)


def parse_batch(body: object) -> list[ParsedMessage] | ParsedMessage:
    """Parse the top-level JSON value after json.loads.

    Handles single messages and batch arrays.
    """
    if isinstance(body, dict):
        return parse_message(body)

    if isinstance(body, list):
        if not body:  # Empty array
            return JsonRpcParseError(
                response=make_error_response(None, INVALID_REQUEST, "Empty batch")
            )
        results: list[ParsedMessage] = []
        for item in body:
            if isinstance(item, dict):
                results.append(parse_message(item))
            else:
                results.append(
                    JsonRpcParseError(
                        response=make_error_response(
                            None, INVALID_REQUEST, "Invalid batch element"
                        )
                    )
                )
        return results

    # Not a dict or list - invalid
    return JsonRpcParseError(
        response=make_error_response(None, INVALID_REQUEST, "Invalid JSON-RPC message")
    )


# --- MCP Type Serialization ---


def serialize_content(content: Content) -> dict[str, object]:
    """Serialize Content to wire format."""
    if isinstance(content, TextContent):
        return {"type": "text", "text": content.text}
    if isinstance(content, ImageContent):
        return {"type": "image", "data": content.data, "mimeType": content.mime_type}
    # Should not happen with proper typing
    raise TypeError(f"Unknown content type: {type(content)}")  # pragma: no cover


def serialize_tool(tool: Tool) -> dict[str, object]:
    """Serialize Tool to wire format with camelCase."""
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
    }


def serialize_call_tool_result(result: CallToolResult) -> dict[str, object]:
    """Serialize CallToolResult to wire format.

    isError key is omitted when false, included when true.
    """
    serialized: dict[str, object] = {
        "content": [serialize_content(c) for c in result.content],
    }
    if result.is_error:
        serialized["isError"] = True
    return serialized


def serialize_server_info(info: ServerInfo) -> dict[str, object]:
    """Serialize ServerInfo to wire format."""
    return {"name": info.name, "version": info.version}


def serialize_capabilities(capabilities: ServerCapabilities) -> dict[str, object]:
    """Serialize ServerCapabilities to wire format.

    tools=ToolsCapability() -> {"tools": {}}
    tools=ToolsCapability(list_changed=True) -> {"tools": {"listChanged": true}}
    tools=None -> (tools key omitted)
    resources=ResourcesCapability() -> {"resources": {}}
    resources=None -> (resources key omitted)
    """
    result: dict[str, object] = {}

    if capabilities.tools is not None:
        tools_obj: dict[str, object] = {}
        if capabilities.tools.list_changed:
            tools_obj["listChanged"] = True
        result["tools"] = tools_obj

    if capabilities.resources is not None:
        resources_obj: dict[str, object] = {}
        if capabilities.resources.list_changed:
            resources_obj["listChanged"] = True
        result["resources"] = resources_obj

    return result


# --- MCP Response Builders ---


def build_initialize_response(
    request_id: JsonRpcId,
    server_info: ServerInfo,
    capabilities: ServerCapabilities,
    protocol_version: str,
    instructions: str | None = None,
) -> dict[str, object]:
    """Build full initialization response."""
    result: dict[str, object] = {
        "protocolVersion": protocol_version,
        "capabilities": serialize_capabilities(capabilities),
        "serverInfo": serialize_server_info(server_info),
    }
    if instructions is not None:
        result["instructions"] = instructions
    return make_success_response(request_id, result)


def build_tool_list_response(
    request_id: JsonRpcId,
    tools: Sequence[Tool],
) -> dict[str, object]:
    """Build tool list response.

    No pagination - all tools in one response. Cursor support deferred.
    """
    return make_success_response(
        request_id,
        {"tools": [serialize_tool(t) for t in tools]},
    )


def build_tool_result_response(
    request_id: JsonRpcId,
    result: CallToolResult,
) -> dict[str, object]:
    """Build tool result response."""
    return make_success_response(request_id, serialize_call_tool_result(result))


# --- MCP Resource Serialization ---


def serialize_resource(resource: Resource) -> dict[str, object]:
    """Serialize Resource to wire format."""
    result: dict[str, object] = {
        "uri": resource.uri,
        "name": resource.name,
    }
    if resource.description is not None:
        result["description"] = resource.description
    if resource.mime_type is not None:
        result["mimeType"] = resource.mime_type
    return result


def serialize_resource_contents(contents: ResourceContents) -> dict[str, object]:
    """Serialize ResourceContents to wire format."""
    result: dict[str, object] = {
        "uri": contents.uri,
        "text": contents.text,
    }
    if contents.mime_type is not None:
        result["mimeType"] = contents.mime_type
    return result


def build_resource_list_response(
    request_id: JsonRpcId,
    resource_list: Sequence[Resource],
) -> dict[str, object]:
    """Build resources/list response.

    No pagination --- all resources in one response.
    """
    return make_success_response(
        request_id,
        {"resources": [serialize_resource(r) for r in resource_list]},
    )


def build_resource_read_response(
    request_id: JsonRpcId,
    contents: Sequence[ResourceContents],
) -> dict[str, object]:
    """Build resources/read response."""
    return make_success_response(
        request_id,
        {"contents": [serialize_resource_contents(c) for c in contents]},
    )
