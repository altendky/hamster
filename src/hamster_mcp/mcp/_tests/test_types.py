"""Tests for _core/types.py."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from hamster_mcp.mcp._core.types import (
    CallToolResult,
    Content,
    HassCommandResult,
    ImageContent,
    IncomingRequest,
    JsonRpcId,
    ServerCapabilities,
    ServerInfo,
    ServiceCallResult,
    TextContent,
    Tool,
    ToolsCapability,
)


class TestTextContent:
    """Tests for TextContent dataclass."""

    def test_construction(self) -> None:
        content = TextContent(text="hello world")
        assert content.text == "hello world"

    def test_frozen(self) -> None:
        content = TextContent(text="hello")
        with pytest.raises(FrozenInstanceError):
            content.text = "goodbye"  # type: ignore[misc]


class TestImageContent:
    """Tests for ImageContent dataclass."""

    def test_construction(self) -> None:
        content = ImageContent(data="base64data==", mime_type="image/png")
        assert content.data == "base64data=="
        assert content.mime_type == "image/png"

    def test_frozen(self) -> None:
        content = ImageContent(data="abc", mime_type="image/jpeg")
        with pytest.raises(FrozenInstanceError):
            content.data = "xyz"  # type: ignore[misc]


class TestContentUnion:
    """Tests for Content type alias."""

    def test_accepts_text_content(self) -> None:
        content: Content = TextContent(text="hello")
        assert isinstance(content, TextContent)

    def test_accepts_image_content(self) -> None:
        content: Content = ImageContent(data="abc", mime_type="image/png")
        assert isinstance(content, ImageContent)


class TestTool:
    """Tests for Tool dataclass."""

    def test_construction(self) -> None:
        tool = Tool(
            name="my_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
        )
        assert tool.name == "my_tool"
        assert tool.description == "A test tool"
        assert tool.input_schema == {"type": "object", "properties": {}}

    def test_frozen(self) -> None:
        tool = Tool(name="test", description="desc", input_schema={})
        with pytest.raises(FrozenInstanceError):
            tool.name = "changed"  # type: ignore[misc]


class TestCallToolResult:
    """Tests for CallToolResult dataclass."""

    def test_construction(self) -> None:
        content = (TextContent(text="result"),)
        result = CallToolResult(content=content)
        assert result.content == content
        assert result.is_error is False

    def test_is_error_default_false(self) -> None:
        result = CallToolResult(content=())
        assert result.is_error is False

    def test_is_error_explicit_true(self) -> None:
        result = CallToolResult(content=(), is_error=True)
        assert result.is_error is True

    def test_frozen(self) -> None:
        result = CallToolResult(content=())
        with pytest.raises(FrozenInstanceError):
            result.is_error = True  # type: ignore[misc]


class TestServerInfo:
    """Tests for ServerInfo dataclass."""

    def test_construction(self) -> None:
        info = ServerInfo(name="hamster-mcp", version="1.0.0")
        assert info.name == "hamster-mcp"
        assert info.version == "1.0.0"

    def test_frozen(self) -> None:
        info = ServerInfo(name="test", version="1.0")
        with pytest.raises(FrozenInstanceError):
            info.name = "changed"  # type: ignore[misc]


class TestToolsCapability:
    """Tests for ToolsCapability dataclass."""

    def test_default_list_changed_false(self) -> None:
        cap = ToolsCapability()
        assert cap.list_changed is False

    def test_list_changed_explicit_true(self) -> None:
        cap = ToolsCapability(list_changed=True)
        assert cap.list_changed is True

    def test_frozen(self) -> None:
        cap = ToolsCapability()
        with pytest.raises(FrozenInstanceError):
            cap.list_changed = True  # type: ignore[misc]


class TestServerCapabilities:
    """Tests for ServerCapabilities dataclass."""

    def test_default_tools_capability(self) -> None:
        cap = ServerCapabilities()
        assert cap.tools == ToolsCapability()
        assert cap.tools is not None
        assert cap.tools.list_changed is False

    def test_default_resources_capability(self) -> None:
        from hamster_mcp.mcp._core.types import ResourcesCapability

        cap = ServerCapabilities()
        assert cap.resources == ResourcesCapability()
        assert cap.resources is not None
        assert cap.resources.list_changed is False

    def test_tools_with_list_changed(self) -> None:
        cap = ServerCapabilities(tools=ToolsCapability(list_changed=True))
        assert cap.tools is not None
        assert cap.tools.list_changed is True

    def test_tools_none_not_supported(self) -> None:
        cap = ServerCapabilities(tools=None)
        assert cap.tools is None

    def test_resources_none_not_supported(self) -> None:
        cap = ServerCapabilities(resources=None)
        assert cap.resources is None

    def test_frozen(self) -> None:
        cap = ServerCapabilities()
        with pytest.raises(FrozenInstanceError):
            cap.tools = None  # type: ignore[misc]


class TestServiceCallResult:
    """Tests for ServiceCallResult dataclass."""

    def test_success_with_data(self) -> None:
        result = ServiceCallResult(success=True, data={"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_success_without_data(self) -> None:
        result = ServiceCallResult(success=True)
        assert result.success is True
        assert result.data is None
        assert result.error is None

    def test_error_case(self) -> None:
        result = ServiceCallResult(success=False, error="Service not found")
        assert result.success is False
        assert result.data is None
        assert result.error == "Service not found"

    def test_frozen(self) -> None:
        result = ServiceCallResult(success=True)
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]


class TestHassCommandResult:
    """Tests for HassCommandResult dataclass."""

    def test_success_with_dict_data(self) -> None:
        """Success with dict data."""
        result = HassCommandResult(success=True, data={"states": []})
        assert result.success is True
        assert result.data == {"states": []}
        assert result.error is None

    def test_success_with_list_data(self) -> None:
        """Success with list data (handler results can be any JSON type)."""
        result = HassCommandResult(success=True, data=[1, 2, 3])
        assert result.success is True
        assert result.data == [1, 2, 3]
        assert result.error is None

    def test_success_with_string_data(self) -> None:
        """Success with string data."""
        result = HassCommandResult(success=True, data="result string")
        assert result.success is True
        assert result.data == "result string"
        assert result.error is None

    def test_success_with_none_data(self) -> None:
        """Success with None data (default)."""
        result = HassCommandResult(success=True)
        assert result.success is True
        assert result.data is None
        assert result.error is None

    def test_error_case(self) -> None:
        """Error case with message."""
        result = HassCommandResult(success=False, error="Unknown command")
        assert result.success is False
        assert result.data is None
        assert result.error == "Unknown command"

    def test_frozen(self) -> None:
        """HassCommandResult is frozen."""
        result = HassCommandResult(success=True)
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]


class TestIncomingRequest:
    """Tests for IncomingRequest dataclass."""

    def test_construction_all_fields(self) -> None:
        request = IncomingRequest(
            http_method="POST",
            content_type="application/json",
            accept="application/json",
            origin="http://localhost:8123",
            host="localhost:8123",
            session_id="abc123",
            body=b'{"jsonrpc": "2.0"}',
        )
        assert request.http_method == "POST"
        assert request.content_type == "application/json"
        assert request.accept == "application/json"
        assert request.origin == "http://localhost:8123"
        assert request.host == "localhost:8123"
        assert request.session_id == "abc123"
        assert request.body == b'{"jsonrpc": "2.0"}'

    def test_optional_fields_none(self) -> None:
        request = IncomingRequest(
            http_method="POST",
            content_type=None,
            accept=None,
            origin=None,
            host="localhost",
            session_id=None,
            body=b"",
        )
        assert request.content_type is None
        assert request.accept is None
        assert request.origin is None
        assert request.session_id is None

    def test_frozen(self) -> None:
        request = IncomingRequest(
            http_method="POST",
            content_type=None,
            accept=None,
            origin=None,
            host="localhost",
            session_id=None,
            body=b"",
        )
        with pytest.raises(FrozenInstanceError):
            request.http_method = "GET"  # type: ignore[misc]


class TestJsonRpcId:
    """Tests for JsonRpcId type alias."""

    def test_int_valid(self) -> None:
        id_val: JsonRpcId = 42
        assert id_val == 42

    def test_float_valid(self) -> None:
        id_val: JsonRpcId = 1.5
        assert id_val == 1.5

    def test_str_valid(self) -> None:
        id_val: JsonRpcId = "request-1"
        assert id_val == "request-1"

    def test_none_valid(self) -> None:
        id_val: JsonRpcId = None
        assert id_val is None
