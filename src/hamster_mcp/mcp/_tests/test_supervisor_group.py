"""Tests for _core/supervisor_group.py."""

from __future__ import annotations

from hamster_mcp.mcp._core.events import Done, FormatSupervisorResponse, SupervisorCall
from hamster_mcp.mcp._core.groups import SourceGroup
from hamster_mcp.mcp._core.supervisor_group import (
    SUPERVISOR_ENDPOINTS,
    EndpointInfo,
    SupervisorGroup,
)


class TestSupervisorGroupProtocol:
    """Test that SupervisorGroup implements the SourceGroup protocol."""

    def test_implements_protocol(self) -> None:
        """SupervisorGroup satisfies the SourceGroup protocol."""
        group = SupervisorGroup(available=True)
        assert isinstance(group, SourceGroup)

    def test_name_property(self) -> None:
        """Group name is 'supervisor'."""
        group = SupervisorGroup(available=True)
        assert group.name == "supervisor"

    def test_available_property_true(self) -> None:
        """Availability reflects constructor parameter (True)."""
        group = SupervisorGroup(available=True)
        assert group.available is True

    def test_available_property_false(self) -> None:
        """Availability reflects constructor parameter (False)."""
        group = SupervisorGroup(available=False)
        assert group.available is False


class TestSupervisorGroupAvailability:
    """Tests for availability-related behavior."""

    def test_search_when_unavailable(self) -> None:
        """Search returns unavailability message when not available."""
        group = SupervisorGroup(available=False)
        result = group.search("logs")
        assert "not available" in result.lower()

    def test_explain_when_unavailable(self) -> None:
        """Explain returns None when not available."""
        group = SupervisorGroup(available=False)
        result = group.explain("core/logs")
        assert result is None

    def test_schema_when_unavailable(self) -> None:
        """Schema returns None when not available."""
        group = SupervisorGroup(available=False)
        result = group.schema("core/logs")
        assert result is None

    def test_has_command_when_unavailable(self) -> None:
        """has_command returns False when not available."""
        group = SupervisorGroup(available=False)
        assert group.has_command("core/logs") is False

    def test_parse_call_args_when_unavailable(self) -> None:
        """parse_call_args returns error when not available."""
        group = SupervisorGroup(available=False)
        result = group.parse_call_args("core/logs", {}, user_id=None)
        assert isinstance(result, Done)
        assert result.result.is_error
        assert "not available" in result.result.content[0].text.lower()  # type: ignore[union-attr]


class TestSupervisorGroupSearch:
    """Tests for SupervisorGroup.search()."""

    def test_search_finds_logs_endpoints(self) -> None:
        """Search 'logs' finds all log endpoints."""
        group = SupervisorGroup(available=True)
        result = group.search("logs")
        assert "core/logs" in result
        assert "supervisor/logs" in result
        assert "host/logs" in result
        assert "addons/{slug}/logs" in result

    def test_search_finds_info_endpoints(self) -> None:
        """Search 'info' finds info endpoints."""
        group = SupervisorGroup(available=True)
        result = group.search("info")
        assert "core/info" in result
        assert "supervisor/info" in result
        assert "host/info" in result

    def test_search_finds_addons(self) -> None:
        """Search 'addon' finds addon-related endpoints."""
        group = SupervisorGroup(available=True)
        result = group.search("addon")
        assert "addons" in result
        assert "addons/{slug}/info" in result

    def test_search_case_insensitive(self) -> None:
        """Search is case-insensitive."""
        group = SupervisorGroup(available=True)
        result = group.search("LOGS")
        assert "logs" in result.lower()

    def test_search_no_match(self) -> None:
        """Search with no matches returns appropriate message."""
        group = SupervisorGroup(available=True)
        result = group.search("nonexistent")
        assert 'No endpoints found matching "nonexistent"' in result

    def test_search_with_path_filter(self) -> None:
        """Search with path filter restricts results."""
        group = SupervisorGroup(available=True)
        result = group.search("info", path_filter="core")
        assert "core/info" in result
        # Should not include supervisor/info or host/info
        assert "supervisor/info" not in result
        assert "host/info" not in result

    def test_search_no_match_with_filter(self) -> None:
        """Search with no matches and filter returns appropriate message."""
        group = SupervisorGroup(available=True)
        result = group.search("nonexistent", path_filter="core")
        assert 'No endpoints found matching "nonexistent"' in result
        assert "core" in result


class TestSupervisorGroupExplain:
    """Tests for SupervisorGroup.explain()."""

    def test_explain_known_endpoint(self) -> None:
        """Explain returns formatted info for known endpoint."""
        group = SupervisorGroup(available=True)
        result = group.explain("core/logs")
        assert result is not None
        assert "core/logs" in result
        assert "Home Assistant Core logs" in result
        assert "GET" in result

    def test_explain_shows_returns_text(self) -> None:
        """Explain shows return type for text endpoints."""
        group = SupervisorGroup(available=True)
        result = group.explain("core/logs")
        assert result is not None
        assert "Plain text" in result or "logs" in result.lower()

    def test_explain_shows_returns_json(self) -> None:
        """Explain shows return type for JSON endpoints."""
        group = SupervisorGroup(available=True)
        result = group.explain("core/info")
        assert result is not None
        assert "JSON" in result

    def test_explain_with_path_params(self) -> None:
        """Explain describes path parameters."""
        group = SupervisorGroup(available=True)
        result = group.explain("addons/{slug}/info")
        assert result is not None
        assert "slug" in result
        assert "required" in result.lower()

    def test_explain_unknown_endpoint(self) -> None:
        """Explain returns None for unknown endpoint."""
        group = SupervisorGroup(available=True)
        result = group.explain("unknown/endpoint")
        assert result is None


class TestSupervisorGroupSchema:
    """Tests for SupervisorGroup.schema()."""

    def test_schema_no_params(self) -> None:
        """Schema for endpoint with no params shows that."""
        group = SupervisorGroup(available=True)
        result = group.schema("core/logs")
        assert result is not None
        assert "No parameters required" in result

    def test_schema_with_path_params(self) -> None:
        """Schema includes path parameter info."""
        group = SupervisorGroup(available=True)
        result = group.schema("addons/{slug}/logs")
        assert result is not None
        assert "slug" in result
        assert "required" in result.lower()

    def test_schema_unknown_endpoint(self) -> None:
        """Schema returns None for unknown endpoint."""
        group = SupervisorGroup(available=True)
        result = group.schema("unknown")
        assert result is None


class TestSupervisorGroupHasCommand:
    """Tests for SupervisorGroup.has_command()."""

    def test_has_known_endpoint(self) -> None:
        """has_command returns True for known endpoint."""
        group = SupervisorGroup(available=True)
        assert group.has_command("core/logs") is True
        assert group.has_command("host/info") is True
        assert group.has_command("addons/{slug}/info") is True

    def test_has_unknown_endpoint(self) -> None:
        """has_command returns False for unknown endpoint."""
        group = SupervisorGroup(available=True)
        assert group.has_command("unknown") is False
        assert group.has_command("foo/bar") is False


class TestSupervisorGroupParseCallArgs:
    """Tests for SupervisorGroup.parse_call_args()."""

    def test_simple_endpoint_returns_effect(self) -> None:
        """Simple endpoint returns SupervisorCall effect."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args("core/logs", {}, user_id=None)
        assert isinstance(result, SupervisorCall)
        assert result.method == "GET"
        assert result.path == "/core/logs"
        assert result.params == {}
        assert result.user_id is None
        assert isinstance(result.continuation, FormatSupervisorResponse)

    def test_endpoint_with_user_id(self) -> None:
        """User ID is passed through."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args("core/logs", {}, user_id="user123")
        assert isinstance(result, SupervisorCall)
        assert result.user_id == "user123"

    def test_path_param_substitution(self) -> None:
        """Path parameters are substituted in the API path."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args(
            "addons/{slug}/logs", {"slug": "my_addon"}, user_id=None
        )
        assert isinstance(result, SupervisorCall)
        assert result.path == "/addons/my_addon/logs"
        # slug should be consumed, not in params
        assert "slug" not in result.params

    def test_missing_path_param_error(self) -> None:
        """Missing path parameter returns error."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args("addons/{slug}/logs", {}, user_id=None)
        assert isinstance(result, Done)
        assert result.result.is_error
        assert "slug" in result.result.content[0].text.lower()  # type: ignore[union-attr]

    def test_invalid_path_param_type_error(self) -> None:
        """Non-string path parameter returns error."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args(
            "addons/{slug}/logs",
            {"slug": 123},
            user_id=None,
        )
        assert isinstance(result, Done)
        assert result.result.is_error
        assert "must be a string" in result.result.content[0].text.lower()  # type: ignore[union-attr]

    def test_unknown_endpoint_error(self) -> None:
        """Unknown endpoint returns error."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args("unknown/endpoint", {}, user_id=None)
        assert isinstance(result, Done)
        assert result.result.is_error
        assert "not found" in result.result.content[0].text.lower()  # type: ignore[union-attr]

    def test_extra_params_passed_through(self) -> None:
        """Extra parameters (not path params) are passed through."""
        group = SupervisorGroup(available=True)
        result = group.parse_call_args(
            "addons/{slug}/logs", {"slug": "my_addon", "lines": 100}, user_id=None
        )
        assert isinstance(result, SupervisorCall)
        assert result.params == {"lines": 100}


class TestEndpointInfo:
    """Tests for EndpointInfo dataclass."""

    def test_all_endpoints_have_valid_structure(self) -> None:
        """All defined endpoints have valid structure."""
        for info in SUPERVISOR_ENDPOINTS.values():
            assert isinstance(info.method, str)
            assert info.method in ("GET", "POST", "PUT", "DELETE", "PATCH")
            assert isinstance(info.path, str)
            assert info.path.startswith("/")
            assert isinstance(info.description, str)
            assert len(info.description) > 0
            assert isinstance(info.params_schema, dict)
            assert isinstance(info.path_params, tuple)
            assert isinstance(info.returns_text, bool)

    def test_path_params_match_path(self) -> None:
        """Endpoints with path_params have matching {param} in path."""
        for info in SUPERVISOR_ENDPOINTS.values():
            for param in info.path_params:
                assert f"{{{param}}}" in info.path, (
                    f"Path param '{param}' not found in path '{info.path}'"
                )

    def test_log_endpoints_return_text(self) -> None:
        """Log endpoints have returns_text=True."""
        for path, info in SUPERVISOR_ENDPOINTS.items():
            if "logs" in path:
                assert info.returns_text is True, (
                    f"Log endpoint '{path}' should have returns_text=True"
                )

    def test_info_endpoints_return_json(self) -> None:
        """Info endpoints have returns_text=False (JSON)."""
        for path, info in SUPERVISOR_ENDPOINTS.items():
            if "info" in path:
                assert info.returns_text is False, (
                    f"Info endpoint '{path}' should return JSON (returns_text=False)"
                )

    def test_endpoint_info_frozen(self) -> None:
        """EndpointInfo is frozen."""
        info = EndpointInfo(
            method="GET",
            path="/test",
            description="Test",
            params_schema={},
        )
        try:
            info.method = "POST"  # type: ignore[misc]
            raise AssertionError("EndpointInfo should be frozen")
        except AttributeError:
            pass  # Expected - dataclass is frozen


class TestEffectTypes:
    """Tests for SupervisorCall effect type."""

    def test_supervisor_call_construction(self) -> None:
        """SupervisorCall can be constructed with all fields."""
        effect = SupervisorCall(
            method="GET",
            path="/core/logs",
            params={"lines": 100},
            user_id="user123",
            continuation=FormatSupervisorResponse(),
        )
        assert effect.method == "GET"
        assert effect.path == "/core/logs"
        assert effect.params == {"lines": 100}
        assert effect.user_id == "user123"
        assert isinstance(effect.continuation, FormatSupervisorResponse)

    def test_supervisor_call_frozen(self) -> None:
        """SupervisorCall is frozen."""
        effect = SupervisorCall(
            method="GET",
            path="/core/logs",
            params={},
            user_id=None,
            continuation=FormatSupervisorResponse(),
        )
        try:
            effect.method = "POST"  # type: ignore[misc]
            raise AssertionError("SupervisorCall should be frozen")
        except AttributeError:
            pass  # Expected - dataclass is frozen

    def test_format_supervisor_response_construction(self) -> None:
        """FormatSupervisorResponse can be constructed (no fields)."""
        cont = FormatSupervisorResponse()
        assert cont is not None

    def test_format_supervisor_response_frozen(self) -> None:
        """FormatSupervisorResponse is frozen (trivially - no fields)."""
        cont = FormatSupervisorResponse()
        # No fields to modify, but verify it exists
        assert isinstance(cont, FormatSupervisorResponse)


class TestSupervisorCallResultType:
    """Tests for SupervisorCallResult type."""

    def test_success_result(self) -> None:
        """SupervisorCallResult can represent success."""
        from hamster_mcp.mcp._core.types import SupervisorCallResult

        result = SupervisorCallResult(success=True, data={"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_error_result(self) -> None:
        """SupervisorCallResult can represent error."""
        from hamster_mcp.mcp._core.types import SupervisorCallResult

        result = SupervisorCallResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.data is None
        assert result.error == "Something went wrong"

    def test_text_data_result(self) -> None:
        """SupervisorCallResult can hold text data (logs)."""
        from hamster_mcp.mcp._core.types import SupervisorCallResult

        result = SupervisorCallResult(success=True, data="Log line 1\nLog line 2")
        assert result.success is True
        assert result.data == "Log line 1\nLog line 2"

    def test_frozen(self) -> None:
        """SupervisorCallResult is frozen."""
        from hamster_mcp.mcp._core.types import SupervisorCallResult

        result = SupervisorCallResult(success=True)
        try:
            result.success = False  # type: ignore[misc]
            raise AssertionError("SupervisorCallResult should be frozen")
        except AttributeError:
            pass  # Expected


class TestToolEffectUnion:
    """Tests for ToolEffect union membership."""

    def test_supervisor_call_in_tool_effect(self) -> None:
        """SupervisorCall is part of ToolEffect union."""
        from hamster_mcp.mcp._core.events import ToolEffect

        effect = SupervisorCall(
            method="GET",
            path="/core/logs",
            params={},
            user_id=None,
            continuation=FormatSupervisorResponse(),
        )
        # This should type-check correctly
        _: ToolEffect = effect
        assert isinstance(effect, SupervisorCall)


class TestContinuationUnion:
    """Tests for Continuation union membership."""

    def test_format_supervisor_response_in_continuation(self) -> None:
        """FormatSupervisorResponse is part of Continuation union."""
        from hamster_mcp.mcp._core.events import Continuation

        cont = FormatSupervisorResponse()
        # This should type-check correctly
        _: Continuation = cont
        assert isinstance(cont, FormatSupervisorResponse)
