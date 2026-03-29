"""Tests for _core/hass_group.py."""

from __future__ import annotations

import pytest

from hamster_mcp.mcp._core.events import Done, FormatHassResponse, HassCommand
from hamster_mcp.mcp._core.groups import SourceGroup
from hamster_mcp.mcp._core.hass_group import (
    CommandInfo,
    HassGroup,
    discover_commands,
    voluptuous_to_description,
)


class TestHassGroupProtocol:
    """Test that HassGroup implements the SourceGroup protocol."""

    def test_implements_protocol(self) -> None:
        """HassGroup satisfies the SourceGroup protocol."""
        group = HassGroup({})
        assert isinstance(group, SourceGroup)

    def test_name_property(self) -> None:
        """Group name is 'hass'."""
        group = HassGroup({})
        assert group.name == "hass"

    def test_available_property(self) -> None:
        """Hass commands are always available."""
        group = HassGroup({})
        assert group.available is True


class TestHassGroupConstruction:
    """Tests for HassGroup construction."""

    def test_empty_commands(self) -> None:
        """Empty commands dict creates empty group."""
        group = HassGroup({})
        assert group.has_command("get_states") is False

    def test_commands_stored(self) -> None:
        """Commands are stored and retrievable."""
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            )
        }
        group = HassGroup(commands)
        assert group.has_command("get_states") is True


class TestHassGroupSearch:
    """Tests for HassGroup.search()."""

    def _make_group(self) -> HassGroup:
        """Create a test group with some commands."""
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
                description="Get all entity states",
            ),
            "config/entity_registry/list": CommandInfo(
                command_type="config/entity_registry/list",
                schema={"fields": {}},
                description="List all entities in the registry",
            ),
            "config/device_registry/list": CommandInfo(
                command_type="config/device_registry/list",
                schema={"fields": {}},
                description="List all devices",
            ),
            "call_service": CommandInfo(
                command_type="call_service",
                schema={"fields": {"domain": {"required": True, "type": "string"}}},
                description="Call a Home Assistant service",
            ),
        }
        return HassGroup(commands)

    def test_search_finds_by_command_type(self) -> None:
        """Search finds commands by type."""
        group = self._make_group()
        result = group.search("states")
        assert "get_states" in result

    def test_search_finds_by_description(self) -> None:
        """Search finds commands by description."""
        group = self._make_group()
        result = group.search("registry")
        assert "entity_registry" in result
        assert "device_registry" in result

    def test_search_case_insensitive(self) -> None:
        """Search is case-insensitive."""
        group = self._make_group()
        result = group.search("STATES")
        assert "get_states" in result

    def test_search_with_path_filter(self) -> None:
        """Search with path filter restricts results."""
        group = self._make_group()
        result = group.search("list", path_filter="config")
        assert "entity_registry" in result
        assert "device_registry" in result
        # get_states should not be included
        assert "get_states" not in result

    def test_search_no_match(self) -> None:
        """Search with no matches returns appropriate message."""
        group = self._make_group()
        result = group.search("nonexistent")
        assert 'No commands found matching "nonexistent"' in result

    def test_search_no_match_with_filter(self) -> None:
        """Search with no matches and filter returns appropriate message."""
        group = self._make_group()
        result = group.search("nonexistent", path_filter="config")
        assert 'No commands found matching "nonexistent"' in result
        assert "config" in result


class TestHassGroupExplain:
    """Tests for HassGroup.explain()."""

    def test_explain_known_command(self) -> None:
        """Explain returns formatted info for known command."""
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
                description="Get all entity states",
            )
        }
        group = HassGroup(commands)
        result = group.explain("get_states")
        assert result is not None
        assert "get_states" in result
        assert "Get all entity states" in result

    def test_explain_with_parameters(self) -> None:
        """Explain shows parameter information."""
        commands = {
            "call_service": CommandInfo(
                command_type="call_service",
                schema={
                    "fields": {
                        "domain": {
                            "required": True,
                            "type": "string",
                            "description": "Service domain",
                        },
                        "service": {
                            "required": True,
                            "type": "string",
                        },
                        "data": {
                            "required": False,
                            "type": "object",
                            "default": {},
                        },
                    }
                },
            )
        }
        group = HassGroup(commands)
        result = group.explain("call_service")
        assert result is not None
        assert "domain" in result
        assert "(required)" in result
        assert "Service domain" in result

    def test_explain_nested_path(self) -> None:
        """Explain handles nested paths."""
        commands = {
            "config/entity_registry/list": CommandInfo(
                command_type="config/entity_registry/list",
                schema={"fields": {}},
                description="List entities",
            )
        }
        group = HassGroup(commands)
        result = group.explain("config/entity_registry/list")
        assert result is not None
        assert "config/entity_registry/list" in result

    def test_explain_unknown_command(self) -> None:
        """Explain returns None for unknown command."""
        group = HassGroup({})
        result = group.explain("unknown")
        assert result is None


class TestHassGroupSchema:
    """Tests for HassGroup.schema()."""

    def test_schema_known_command(self) -> None:
        """Schema returns parameter schema."""
        commands = {
            "call_service": CommandInfo(
                command_type="call_service",
                schema={
                    "fields": {
                        "domain": {"required": True, "type": "string"},
                    }
                },
            )
        }
        group = HassGroup(commands)
        result = group.schema("call_service")
        assert result is not None
        assert "domain" in result
        assert "string" in result

    def test_schema_no_params(self) -> None:
        """Schema for command with no params shows that."""
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            )
        }
        group = HassGroup(commands)
        result = group.schema("get_states")
        assert result is not None
        assert "No parameters required" in result

    def test_schema_unknown_command(self) -> None:
        """Schema returns None for unknown command."""
        group = HassGroup({})
        result = group.schema("unknown")
        assert result is None


class TestHassGroupHasCommand:
    """Tests for HassGroup.has_command()."""

    def _make_group_with_filtered(self) -> HassGroup:
        """Create a group that would have filtered commands if not filtered."""
        # Note: HassGroup constructor doesn't filter, but has_command does
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
            "subscribe_events": CommandInfo(
                command_type="subscribe_events",
                schema={"fields": {}},
            ),
            "auth": CommandInfo(
                command_type="auth",
                schema={"fields": {}},
            ),
        }
        return HassGroup(commands)

    def test_has_known_command(self) -> None:
        """has_command returns True for known command."""
        group = self._make_group_with_filtered()
        assert group.has_command("get_states") is True

    def test_subscribe_filtered(self) -> None:
        """has_command returns False for subscribe commands."""
        group = self._make_group_with_filtered()
        # Even though it's in the dict, it's filtered
        assert group.has_command("subscribe_events") is False

    def test_auth_filtered(self) -> None:
        """has_command returns False for auth commands."""
        group = self._make_group_with_filtered()
        assert group.has_command("auth") is False

    def test_unknown_command(self) -> None:
        """has_command returns False for unknown command."""
        group = HassGroup({})
        assert group.has_command("unknown") is False


class TestHassGroupParseCallArgs:
    """Tests for HassGroup.parse_call_args()."""

    def _make_group(self) -> HassGroup:
        """Create a test group."""
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
            "call_service": CommandInfo(
                command_type="call_service",
                schema={
                    "fields": {
                        "domain": {"required": True, "type": "string"},
                    }
                },
            ),
            "subscribe_events": CommandInfo(
                command_type="subscribe_events",
                schema={"fields": {}},
            ),
        }
        return HassGroup(commands)

    def test_valid_command_returns_effect(self) -> None:
        """Valid command returns HassCommand effect."""
        group = self._make_group()
        result = group.parse_call_args("get_states", {}, user_id=None)
        assert isinstance(result, HassCommand)
        assert result.command_type == "get_states"
        assert result.params == {}
        assert result.user_id is None
        assert isinstance(result.continuation, FormatHassResponse)

    def test_passes_params_through(self) -> None:
        """Arguments are passed as params."""
        group = self._make_group()
        args: dict[str, object] = {"domain": "light", "service": "turn_on"}
        result = group.parse_call_args("call_service", args, user_id="user123")
        assert isinstance(result, HassCommand)
        assert result.params == args
        assert result.user_id == "user123"

    def test_unknown_command_error(self) -> None:
        """Unknown command returns error."""
        group = self._make_group()
        result = group.parse_call_args("unknown", {}, user_id=None)
        assert isinstance(result, Done)
        assert result.result.is_error
        assert "not found" in result.result.content[0].text.lower()  # type: ignore[union-attr]

    def test_filtered_command_error(self) -> None:
        """Filtered command returns error."""
        group = self._make_group()
        result = group.parse_call_args("subscribe_events", {}, user_id=None)
        assert isinstance(result, Done)
        assert result.result.is_error
        assert "not available" in result.result.content[0].text.lower()  # type: ignore[union-attr]


class TestCommandFiltering:
    """Tests for command filtering logic."""

    def test_subscribe_prefix_filtered(self) -> None:
        """Commands starting with 'subscribe' are filtered."""
        from hamster_mcp.mcp._core.hass_group import _is_filtered_command

        assert _is_filtered_command("subscribe_events") is True
        assert _is_filtered_command("subscribe_trigger") is True

    def test_unsubscribe_prefix_filtered(self) -> None:
        """Commands starting with 'unsubscribe' are filtered."""
        from hamster_mcp.mcp._core.hass_group import _is_filtered_command

        assert _is_filtered_command("unsubscribe_events") is True

    def test_auth_filtered(self) -> None:
        """Auth commands are filtered."""
        from hamster_mcp.mcp._core.hass_group import _is_filtered_command

        assert _is_filtered_command("auth") is True
        assert _is_filtered_command("auth/sign_path") is True

    def test_normal_commands_not_filtered(self) -> None:
        """Normal commands are not filtered."""
        from hamster_mcp.mcp._core.hass_group import _is_filtered_command

        assert _is_filtered_command("get_states") is False
        assert _is_filtered_command("call_service") is False
        assert _is_filtered_command("config/entity_registry/list") is False


class TestVoluptuousConversion:
    """Tests for voluptuous schema conversion."""

    def test_schema_false(self) -> None:
        """schema=False produces empty fields."""
        result = voluptuous_to_description(False)
        assert result == {"fields": {}}

    def test_schema_none(self) -> None:
        """schema=None produces empty fields."""
        result = voluptuous_to_description(None)
        assert result == {"fields": {}}

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_required_field(self) -> None:
        """vol.Required produces required=True."""
        import voluptuous as vol

        schema = vol.Schema({vol.Required("entity_id"): str})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        assert "entity_id" in fields
        field = fields["entity_id"]
        assert isinstance(field, dict)
        assert field["required"] is True
        assert field["type"] == "string"

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_optional_field(self) -> None:
        """vol.Optional produces required=False."""
        import voluptuous as vol

        schema = vol.Schema({vol.Optional("brightness"): int})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        assert "brightness" in fields
        field = fields["brightness"]
        assert isinstance(field, dict)
        assert field["required"] is False

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_optional_with_default(self) -> None:
        """vol.Optional with default includes the default."""
        import voluptuous as vol

        schema = vol.Schema({vol.Optional("count", default=10): int})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        assert "count" in fields
        field = fields["count"]
        assert isinstance(field, dict)
        assert field["required"] is False
        assert field["default"] == 10

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_coerce_int(self) -> None:
        """vol.Coerce(int) produces type='integer'."""
        import voluptuous as vol

        schema = vol.Schema({vol.Required("count"): vol.Coerce(int)})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        field = fields["count"]
        assert isinstance(field, dict)
        assert field["type"] == "integer"

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_coerce_float(self) -> None:
        """vol.Coerce(float) produces type='number'."""
        import voluptuous as vol

        schema = vol.Schema({vol.Required("value"): vol.Coerce(float)})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        field = fields["value"]
        assert isinstance(field, dict)
        assert field["type"] == "number"

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_coerce_str(self) -> None:
        """vol.Coerce(str) produces type='string'."""
        import voluptuous as vol

        schema = vol.Schema({vol.Required("name"): vol.Coerce(str)})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        field = fields["name"]
        assert isinstance(field, dict)
        assert field["type"] == "string"

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_any_validator(self) -> None:
        """vol.Any produces type='any'."""
        import voluptuous as vol

        schema = vol.Schema({vol.Required("value"): vol.Any(str, int)})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        field = fields["value"]
        assert isinstance(field, dict)
        assert field["type"] == "any"

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_all_validator_extracts_base_type(self) -> None:
        """vol.All extracts type from first validator."""
        import voluptuous as vol

        schema = vol.Schema({vol.Required("name"): vol.All(str, vol.Length(min=1))})
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        field = fields["name"]
        assert isinstance(field, dict)
        assert field["type"] == "string"

    @pytest.mark.skipif(
        not pytest.importorskip("voluptuous", reason="voluptuous not installed"),
        reason="voluptuous not installed",
    )
    def test_basic_types(self) -> None:
        """Basic Python types are converted correctly."""
        import voluptuous as vol

        schema = vol.Schema(
            {
                vol.Required("s"): str,
                vol.Required("i"): int,
                vol.Required("f"): float,
                vol.Required("b"): bool,
                vol.Required("d"): dict,
                vol.Required("l"): list,
            }
        )
        result = voluptuous_to_description(schema)
        fields = result["fields"]
        assert isinstance(fields, dict)
        s_field = fields["s"]
        i_field = fields["i"]
        f_field = fields["f"]
        b_field = fields["b"]
        d_field = fields["d"]
        l_field = fields["l"]
        assert isinstance(s_field, dict)
        assert s_field["type"] == "string"
        assert isinstance(i_field, dict)
        assert i_field["type"] == "integer"
        assert isinstance(f_field, dict)
        assert f_field["type"] == "number"
        assert isinstance(b_field, dict)
        assert b_field["type"] == "boolean"
        assert isinstance(d_field, dict)
        assert d_field["type"] == "object"
        assert isinstance(l_field, dict)
        assert l_field["type"] == "array"


class TestDiscoverCommands:
    """Tests for discover_commands()."""

    def test_empty_registry(self) -> None:
        """Empty registry produces empty commands."""
        result = discover_commands({})
        assert result == {}

    def test_filters_subscribe(self) -> None:
        """Subscribe commands are filtered out."""
        registry = {
            "get_states": (lambda: None, False),
            "subscribe_events": (lambda: None, False),
        }
        result = discover_commands(registry)
        assert "get_states" in result
        assert "subscribe_events" not in result

    def test_filters_auth(self) -> None:
        """Auth commands are filtered out."""
        registry = {
            "get_states": (lambda: None, False),
            "auth": (lambda: None, False),
            "auth/sign_path": (lambda: None, False),
        }
        result = discover_commands(registry)
        assert "get_states" in result
        assert "auth" not in result
        assert "auth/sign_path" not in result

    def test_schema_false_handled(self) -> None:
        """Commands with schema=False have empty fields."""
        registry = {
            "get_states": (lambda: None, False),
        }
        result = discover_commands(registry)
        info = result["get_states"]
        assert info.schema == {"fields": {}}
