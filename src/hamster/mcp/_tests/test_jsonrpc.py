"""Tests for _core/jsonrpc.py."""

from __future__ import annotations

from hamster.mcp._core.jsonrpc import (
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
    make_success_response,
    parse_batch,
    parse_message,
    serialize_call_tool_result,
    serialize_capabilities,
    serialize_content,
    serialize_server_info,
    serialize_tool,
)
from hamster.mcp._core.types import (
    CallToolResult,
    ImageContent,
    ServerCapabilities,
    ServerInfo,
    TextContent,
    Tool,
    ToolsCapability,
)


class TestConstants:
    """Tests for JSON-RPC constants."""

    def test_error_codes(self) -> None:
        assert PARSE_ERROR == -32700
        assert INVALID_REQUEST == -32600
        assert METHOD_NOT_FOUND == -32601
        assert INVALID_PARAMS == -32602

    def test_supported_versions(self) -> None:
        assert "2025-03-26" in SUPPORTED_VERSIONS
        assert SUPPORTED_VERSIONS[0] == MCP_PROTOCOL_VERSION


class TestMakeErrorResponse:
    """Tests for make_error_response."""

    def test_basic(self) -> None:
        resp = make_error_response(1, PARSE_ERROR, "Parse error")
        assert resp == {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": PARSE_ERROR, "message": "Parse error"},
        }

    def test_null_id(self) -> None:
        resp = make_error_response(None, INVALID_REQUEST, "Bad request")
        assert resp["id"] is None


class TestMakeSuccessResponse:
    """Tests for make_success_response."""

    def test_basic(self) -> None:
        resp = make_success_response(42, {"key": "value"})
        assert resp == {
            "jsonrpc": "2.0",
            "id": 42,
            "result": {"key": "value"},
        }


class TestParseMessageSingleMessages:
    """Tests for parse_message with single messages."""

    def test_valid_request(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {"foo": "bar"}}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id == 1
        assert result.method == "test"
        assert result.params == {"foo": "bar"}

    def test_valid_notification(self) -> None:
        raw: dict[str, object] = {"jsonrpc": "2.0", "method": "notify", "params": {}}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcNotification)
        assert result.method == "notify"
        assert result.params == {}

    def test_response_object(self) -> None:
        raw: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"data": "value"},
        }
        result = parse_message(raw)
        assert isinstance(result, JsonRpcResponse)
        error = result.response["error"]
        assert isinstance(error, dict)
        assert error["code"] == INVALID_REQUEST

    def test_missing_jsonrpc(self) -> None:
        raw: dict[str, object] = {"id": 1, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)
        error = result.response["error"]
        assert isinstance(error, dict)
        assert error["code"] == INVALID_REQUEST

    def test_wrong_jsonrpc_version(self) -> None:
        raw: dict[str, object] = {"jsonrpc": "1.0", "id": 1, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)
        error = result.response["error"]
        assert isinstance(error, dict)
        assert error["code"] == INVALID_REQUEST

    def test_missing_method(self) -> None:
        raw: dict[str, object] = {"jsonrpc": "2.0", "id": 1}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)
        error = result.response["error"]
        assert isinstance(error, dict)
        assert error["code"] == INVALID_REQUEST

    def test_non_string_method(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": 123}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)

    def test_array_params(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": [1, 2, 3]}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)

    def test_string_params(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": "invalid"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)

    def test_bool_id(self) -> None:
        raw = {"jsonrpc": "2.0", "id": True, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)

    def test_object_id(self) -> None:
        raw: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": {"nested": "id"},
            "method": "test",
        }
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)

    def test_empty_dict(self) -> None:
        raw: dict[str, object] = {}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)

    def test_missing_params_defaults_to_empty(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.params == {}

    def test_null_params_treated_as_empty(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": "test", "params": None}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.params == {}

    def test_extra_fields_ignored(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1, "method": "test", "extra": "bar"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.method == "test"

    def test_error_response_id_null_when_cannot_extract(self) -> None:
        raw: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": {"complex": "id"},
            "method": "test",
        }
        result = parse_message(raw)
        assert isinstance(result, JsonRpcParseError)
        assert result.response["id"] is None


class TestParseMessageIdEdgeCases:
    """Tests for parse_message id edge cases."""

    def test_id_zero(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 0, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id == 0

    def test_id_empty_string(self) -> None:
        raw: dict[str, object] = {"jsonrpc": "2.0", "id": "", "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id == ""

    def test_id_null(self) -> None:
        raw: dict[str, object] = {"jsonrpc": "2.0", "id": None, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id is None

    def test_id_fractional(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 1.5, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id == 1.5

    def test_id_negative(self) -> None:
        raw = {"jsonrpc": "2.0", "id": -1, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id == -1

    def test_id_very_large(self) -> None:
        raw = {"jsonrpc": "2.0", "id": 10**20, "method": "test"}
        result = parse_message(raw)
        assert isinstance(result, JsonRpcRequest)
        assert result.id == 10**20


class TestParseBatch:
    """Tests for parse_batch."""

    def test_single_dict(self) -> None:
        body = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        result = parse_batch(body)
        assert isinstance(result, JsonRpcRequest)

    def test_array_of_valid_requests(self) -> None:
        body = [
            {"jsonrpc": "2.0", "id": 1, "method": "a"},
            {"jsonrpc": "2.0", "id": 2, "method": "b"},
        ]
        result = parse_batch(body)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(r, JsonRpcRequest) for r in result)

    def test_empty_array(self) -> None:
        body: list[object] = []
        result = parse_batch(body)
        assert isinstance(result, JsonRpcParseError)
        error = result.response["error"]
        assert isinstance(error, dict)
        assert error["code"] == INVALID_REQUEST

    def test_array_with_non_dict_element(self) -> None:
        body = [{"jsonrpc": "2.0", "id": 1, "method": "test"}, "invalid"]
        result = parse_batch(body)
        assert isinstance(result, list)
        assert len(result) == 2
        assert isinstance(result[0], JsonRpcRequest)
        assert isinstance(result[1], JsonRpcParseError)

    def test_mixed_requests_and_notifications(self) -> None:
        body = [
            {"jsonrpc": "2.0", "id": 1, "method": "request"},
            {"jsonrpc": "2.0", "method": "notify"},
        ]
        result = parse_batch(body)
        assert isinstance(result, list)
        assert isinstance(result[0], JsonRpcRequest)
        assert isinstance(result[1], JsonRpcNotification)

    def test_string_body(self) -> None:
        result = parse_batch("invalid")
        assert isinstance(result, JsonRpcParseError)

    def test_number_body(self) -> None:
        result = parse_batch(42)
        assert isinstance(result, JsonRpcParseError)

    def test_null_body(self) -> None:
        result = parse_batch(None)
        assert isinstance(result, JsonRpcParseError)

    def test_bool_body(self) -> None:
        result = parse_batch(True)
        assert isinstance(result, JsonRpcParseError)


class TestSerializeContent:
    """Tests for serialize_content."""

    def test_text_content(self) -> None:
        content = TextContent(text="hello")
        result = serialize_content(content)
        assert result == {"type": "text", "text": "hello"}

    def test_image_content(self) -> None:
        content = ImageContent(data="base64data", mime_type="image/png")
        result = serialize_content(content)
        assert result == {
            "type": "image",
            "data": "base64data",
            "mimeType": "image/png",
        }


class TestSerializeTool:
    """Tests for serialize_tool."""

    def test_basic(self) -> None:
        tool = Tool(
            name="my_tool",
            description="A tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        result = serialize_tool(tool)
        assert result == {
            "name": "my_tool",
            "description": "A tool",
            "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
        }


class TestSerializeCallToolResult:
    """Tests for serialize_call_tool_result."""

    def test_is_error_false_omitted(self) -> None:
        result = CallToolResult(content=(TextContent(text="ok"),), is_error=False)
        serialized = serialize_call_tool_result(result)
        assert "isError" not in serialized
        assert serialized["content"] == [{"type": "text", "text": "ok"}]

    def test_is_error_true_included(self) -> None:
        result = CallToolResult(content=(TextContent(text="fail"),), is_error=True)
        serialized = serialize_call_tool_result(result)
        assert serialized["isError"] is True


class TestSerializeCapabilities:
    """Tests for serialize_capabilities."""

    def test_tools_default(self) -> None:
        cap = ServerCapabilities(tools=ToolsCapability(), resources=None)
        result = serialize_capabilities(cap)
        assert result == {"tools": {}}

    def test_tools_list_changed_true(self) -> None:
        cap = ServerCapabilities(
            tools=ToolsCapability(list_changed=True), resources=None
        )
        result = serialize_capabilities(cap)
        assert result == {"tools": {"listChanged": True}}

    def test_tools_none(self) -> None:
        cap = ServerCapabilities(tools=None, resources=None)
        result = serialize_capabilities(cap)
        assert result == {}

    def test_resources_default(self) -> None:
        from hamster.mcp._core.types import ResourcesCapability

        cap = ServerCapabilities(
            tools=ToolsCapability(), resources=ResourcesCapability()
        )
        result = serialize_capabilities(cap)
        assert result == {"tools": {}, "resources": {}}

    def test_resources_none(self) -> None:
        cap = ServerCapabilities(tools=ToolsCapability(), resources=None)
        result = serialize_capabilities(cap)
        assert result == {"tools": {}}
        assert "resources" not in result


class TestSerializeServerInfo:
    """Tests for serialize_server_info."""

    def test_basic(self) -> None:
        info = ServerInfo(name="hamster", version="1.0.0")
        result = serialize_server_info(info)
        assert result == {"name": "hamster", "version": "1.0.0"}


class TestBuildInitializeResponse:
    """Tests for build_initialize_response."""

    def test_complete_response(self) -> None:
        info = ServerInfo(name="test", version="0.1")
        cap = ServerCapabilities(tools=ToolsCapability(), resources=None)
        result = build_initialize_response(1, info, cap, "2025-03-26")
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        inner = result["result"]
        assert isinstance(inner, dict)
        assert inner["protocolVersion"] == "2025-03-26"
        assert inner["capabilities"] == {"tools": {}}
        assert inner["serverInfo"] == {"name": "test", "version": "0.1"}
        assert "instructions" not in inner

    def test_with_instructions(self) -> None:
        info = ServerInfo(name="test", version="0.1")
        cap = ServerCapabilities(tools=ToolsCapability())
        result = build_initialize_response(
            1, info, cap, "2025-03-26", instructions="Use this server wisely."
        )
        inner = result["result"]
        assert isinstance(inner, dict)
        assert inner["instructions"] == "Use this server wisely."

    def test_instructions_none_omitted(self) -> None:
        info = ServerInfo(name="test", version="0.1")
        cap = ServerCapabilities(tools=ToolsCapability())
        result = build_initialize_response(
            1, info, cap, "2025-03-26", instructions=None
        )
        inner = result["result"]
        assert isinstance(inner, dict)
        assert "instructions" not in inner


class TestBuildToolListResponse:
    """Tests for build_tool_list_response."""

    def test_with_tools(self) -> None:
        tools = [
            Tool(name="t1", description="Tool 1", input_schema={}),
            Tool(name="t2", description="Tool 2", input_schema={}),
        ]
        result = build_tool_list_response(99, tools)
        assert result["id"] == 99
        inner = result["result"]
        assert isinstance(inner, dict)
        assert len(inner["tools"]) == 2


class TestBuildToolResultResponse:
    """Tests for build_tool_result_response."""

    def test_basic(self) -> None:
        tool_result = CallToolResult(content=(TextContent(text="done"),))
        result = build_tool_result_response(5, tool_result)
        assert result["id"] == 5
        inner = result["result"]
        assert isinstance(inner, dict)
        assert inner["content"] == [{"type": "text", "text": "done"}]
