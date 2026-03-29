"""Tests for _core/tools.py."""

from __future__ import annotations

import re

from hamster_mcp.mcp._core.events import (
    Done,
    FormatHassResponse,
    FormatServiceResponse,
    FormatSupervisorResponse,
    ServiceCall,
)
from hamster_mcp.mcp._core.groups import GroupRegistry, ServicesGroup
from hamster_mcp.mcp._core.tools import (
    TOOLS,
    call_tool,
    resume,
)
from hamster_mcp.mcp._core.types import (
    HassCommandResult,
    ServiceCallResult,
    SupervisorCallResult,
)


class TestToolDefinitions:
    """Tests for TOOLS constant."""

    def test_exactly_six_tools(self) -> None:
        assert len(TOOLS) == 6

    def test_all_tools_have_required_fields(self) -> None:
        for tool in TOOLS:
            assert tool.name, "Tool must have a name"
            assert tool.description, "Tool must have a description"
            assert isinstance(tool.input_schema, dict), (
                "Tool must have input_schema dict"
            )

    def test_tool_names_match_pattern(self) -> None:
        pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
        for tool in TOOLS:
            assert pattern.match(tool.name), (
                f"Tool name '{tool.name}' doesn't match pattern"
            )

    def test_expected_tool_names(self) -> None:
        names = {t.name for t in TOOLS}
        assert names == {
            "search",
            "explain",
            "call",
            "schema",
            "list_resources",
            "read_resource",
        }


class TestCallTool:
    """Tests for call_tool()."""

    def _make_registry(self) -> GroupRegistry:
        """Create a registry with a services group."""
        registry = GroupRegistry()
        group = ServicesGroup(
            {
                "light": {
                    "turn_on": {"description": "Turn on a light", "fields": {}},
                    "turn_off": {"description": "Turn off a light", "fields": {}},
                },
                "switch": {
                    "toggle": {"description": "Toggle a switch", "fields": {}},
                },
            }
        )
        registry.register(group)
        return registry

    def test_search_returns_done(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "search", {"query": "light"}, registry, user_id=None, resources=()
        )
        assert isinstance(result, Done)
        assert result.result.content[0].text  # type: ignore[union-attr]

    def test_search_with_path_filter(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "search",
            {"query": "turn", "path_filter": "services"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "turn_on" in text

    def test_search_with_domain_filter(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "search",
            {"query": "turn", "path_filter": "services/light"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "light.turn_on" in text
        # switch shouldn't be included with light domain filter
        assert "switch" not in text

    def test_explain_returns_done(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "explain",
            {"path": "services/light.turn_on"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert not result.result.is_error

    def test_explain_unknown_command_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "explain",
            {"path": "services/light.nonexistent"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_explain_unknown_group_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "explain",
            {"path": "unknown/foo"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_explain_invalid_path_format_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "explain",
            {"path": "nogroup"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "group/command" in text

    def test_explain_empty_path_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "explain",
            {"path": ""},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_valid_service_returns_service_call(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "call",
            {
                "path": "services/light.turn_on",
                "arguments": {
                    "target": {"entity_id": ["light.living_room"]},
                    "data": {"brightness": 255},
                },
            },
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, ServiceCall)
        assert result.domain == "light"
        assert result.service == "turn_on"
        assert result.target == {"entity_id": ["light.living_room"]}
        assert result.data == {"brightness": 255}
        assert result.user_id is None
        assert isinstance(result.continuation, FormatServiceResponse)

    def test_call_unknown_service_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "call",
            {"path": "services/light.nonexistent", "arguments": {}},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_unknown_group_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "call",
            {"path": "unknown/foo", "arguments": {}},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_invalid_path_format_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "call",
            {"path": "nogroup"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_missing_arguments_uses_empty(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "call",
            {"path": "services/light.turn_on"},
            registry,
            user_id="test-user",
            resources=(),
        )
        assert isinstance(result, ServiceCall)
        assert result.data == {}
        assert result.user_id == "test-user"

    def test_call_arguments_wrong_type_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "call",
            {"path": "services/light.turn_on", "arguments": "invalid"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_search_empty_registry(self) -> None:
        registry = GroupRegistry()
        result = call_tool(
            "search", {"query": "anything"}, registry, user_id=None, resources=()
        )
        assert isinstance(result, Done)
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "No commands found" in text

    def test_schema_returns_done(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "schema",
            {"path": "services/selector/boolean"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "boolean" in text

    def test_schema_service_fields(self) -> None:
        registry = GroupRegistry()
        group = ServicesGroup(
            {
                "light": {
                    "turn_on": {
                        "description": "Turn on",
                        "fields": {
                            "brightness": {
                                "description": "Brightness level",
                                "selector": {"number": {}},
                            }
                        },
                    },
                },
            }
        )
        registry.register(group)
        result = call_tool(
            "schema",
            {"path": "services/light.turn_on"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "brightness" in text

    def test_schema_unknown_path_error(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "schema",
            {"path": "services/unknown.service"},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_unknown_tool_error(self) -> None:
        registry = self._make_registry()
        result = call_tool("unknown_tool", {}, registry, user_id=None, resources=())
        assert isinstance(result, Done)
        assert result.result.is_error


class TestCallToolArgumentValidation:
    """Tests for argument validation in call_tool()."""

    def _make_registry(self) -> GroupRegistry:
        registry = GroupRegistry()
        group = ServicesGroup({"light": {"turn_on": {"description": "Turn on"}}})
        registry.register(group)
        return registry

    def test_search_missing_query(self) -> None:
        registry = self._make_registry()
        result = call_tool("search", {}, registry, user_id=None, resources=())
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_search_query_wrong_type(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "search", {"query": 123}, registry, user_id=None, resources=()
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_search_path_filter_wrong_type(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "search",
            {"query": "test", "path_filter": 123},
            registry,
            user_id=None,
            resources=(),
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_explain_missing_path(self) -> None:
        registry = self._make_registry()
        result = call_tool("explain", {}, registry, user_id=None, resources=())
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_explain_path_wrong_type(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "explain", {"path": 123}, registry, user_id=None, resources=()
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_missing_path(self) -> None:
        registry = self._make_registry()
        result = call_tool("call", {}, registry, user_id=None, resources=())
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_path_wrong_type(self) -> None:
        registry = self._make_registry()
        result = call_tool("call", {"path": 123}, registry, user_id=None, resources=())
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_schema_missing_path(self) -> None:
        registry = self._make_registry()
        result = call_tool("schema", {}, registry, user_id=None, resources=())
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_schema_path_wrong_type(self) -> None:
        registry = self._make_registry()
        result = call_tool(
            "schema", {"path": 123}, registry, user_id=None, resources=()
        )
        assert isinstance(result, Done)
        assert result.result.is_error


class TestResume:
    """Tests for resume()."""

    def test_success_with_data(self) -> None:
        io_result = ServiceCallResult(success=True, data={"state": "on"})
        result = resume(FormatServiceResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "state" in text
        assert "on" in text

    def test_success_without_data(self) -> None:
        io_result = ServiceCallResult(success=True)
        result = resume(FormatServiceResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "success" in text.lower()

    def test_error(self) -> None:
        io_result = ServiceCallResult(success=False, error="Service not found")
        result = resume(FormatServiceResponse(), io_result)
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "Service not found" in text


class TestResumeHassResponse:
    """Tests for resume() with FormatHassResponse continuation."""

    def test_success_with_dict_data(self) -> None:
        """Success result formats dict data as JSON text."""
        io_result = HassCommandResult(success=True, data={"states": ["on", "off"]})
        result = resume(FormatHassResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "states" in text
        assert "on" in text

    def test_success_with_list_data(self) -> None:
        """Success result formats list data as JSON text."""
        io_result = HassCommandResult(success=True, data=[1, 2, 3])
        result = resume(FormatHassResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "1" in text
        assert "2" in text
        assert "3" in text

    def test_success_with_string_data(self) -> None:
        """Success result formats string data as JSON text."""
        io_result = HassCommandResult(success=True, data="result value")
        result = resume(FormatHassResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "result value" in text

    def test_success_with_none_data(self) -> None:
        """Success result with None data returns success message."""
        io_result = HassCommandResult(success=True, data=None)
        result = resume(FormatHassResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "success" in text.lower() or "completed" in text.lower()

    def test_error_result(self) -> None:
        """Error result returns Done with is_error=True."""
        io_result = HassCommandResult(success=False, error="Unknown command")
        result = resume(FormatHassResponse(), io_result)
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "Unknown command" in text


class TestResumeSupervisorResponse:
    """Tests for resume() with FormatSupervisorResponse continuation."""

    def test_success_with_dict_data(self) -> None:
        """Success result formats dict data as JSON text."""
        io_result = SupervisorCallResult(
            success=True, data={"version": "2024.1", "hostname": "homeassistant"}
        )
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "version" in text
        assert "2024.1" in text
        assert "hostname" in text

    def test_success_with_string_data(self) -> None:
        """Success result with string data (logs) returns text directly."""
        io_result = SupervisorCallResult(
            success=True, data="Log line 1\nLog line 2\nLog line 3"
        )
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "Log line 1" in text
        assert "Log line 2" in text
        assert "Log line 3" in text

    def test_success_with_logs_dict(self) -> None:
        """Success result with logs wrapped in dict."""
        io_result = SupervisorCallResult(
            success=True, data={"logs": "2024-01-01 INFO Starting..."}
        )
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "logs" in text
        assert "Starting" in text

    def test_success_with_none_data(self) -> None:
        """Success result with None data returns success message."""
        io_result = SupervisorCallResult(success=True, data=None)
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "success" in text.lower() or "completed" in text.lower()

    def test_error_result(self) -> None:
        """Error result returns Done with is_error=True."""
        io_result = SupervisorCallResult(
            success=False, error="Supervisor not available"
        )
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "Supervisor not available" in text

    def test_error_with_api_error(self) -> None:
        """Error result includes API error message."""
        io_result = SupervisorCallResult(
            success=False, error="API Error: 401 Unauthorized"
        )
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "401" in text
        assert "Unauthorized" in text

    def test_error_requires_admin(self) -> None:
        """Error result for admin required."""
        io_result = SupervisorCallResult(
            success=False, error="Supervisor access requires admin privileges"
        )
        result = resume(FormatSupervisorResponse(), io_result)
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "admin" in text.lower()
