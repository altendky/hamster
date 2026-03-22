"""Tests for _core/tools.py."""

from __future__ import annotations

import re

from hamster.mcp._core.events import Done, FormatServiceResponse, ServiceCall
from hamster.mcp._core.tools import (
    SELECTOR_DESCRIPTIONS,
    TOOLS,
    ServiceIndex,
    call_tool,
    describe_selector,
    resume,
)
from hamster.mcp._core.types import ServiceCallResult


class TestToolDefinitions:
    """Tests for TOOLS constant."""

    def test_exactly_four_tools(self) -> None:
        assert len(TOOLS) == 4

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
            "hamster_services_search",
            "hamster_services_explain",
            "hamster_services_call",
            "hamster_services_schema",
        }


class TestServiceIndexConstruction:
    """Tests for ServiceIndex construction."""

    def test_empty_descriptions(self) -> None:
        index = ServiceIndex({})
        assert index.search("anything") == 'No services found matching "anything".'

    def test_single_domain_service(self) -> None:
        descriptions = {
            "light": {
                "turn_on": {
                    "description": "Turn on a light",
                    "fields": {},
                },
            },
        }
        index = ServiceIndex(descriptions)
        result = index.search("light")
        assert "light.turn_on" in result

    def test_multiple_domains(self) -> None:
        descriptions = {
            "light": {"turn_on": {"description": "Turn on light"}},
            "switch": {"turn_on": {"description": "Turn on switch"}},
        }
        index = ServiceIndex(descriptions)
        result = index.search("turn_on")
        assert "light.turn_on" in result
        assert "switch.turn_on" in result


class TestServiceIndexSearch:
    """Tests for ServiceIndex.search()."""

    def test_match_service_name(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "desc"}}}
        index = ServiceIndex(descriptions)
        result = index.search("turn_on")
        assert "light.turn_on" in result

    def test_match_description(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "Illuminate the room"}}}
        index = ServiceIndex(descriptions)
        result = index.search("illuminate")
        assert "light.turn_on" in result

    def test_match_field_names(self) -> None:
        descriptions = {
            "light": {
                "turn_on": {
                    "description": "Turn on",
                    "fields": {"brightness": {"description": "Light level"}},
                }
            }
        }
        index = ServiceIndex(descriptions)
        result = index.search("brightness")
        assert "light.turn_on" in result

    def test_case_insensitive(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "TURN ON"}}}
        index = ServiceIndex(descriptions)
        result = index.search("turn on")
        assert "light.turn_on" in result

    def test_domain_filter(self) -> None:
        descriptions = {
            "light": {"turn_on": {"description": "Turn on light"}},
            "switch": {"turn_on": {"description": "Turn on switch"}},
        }
        index = ServiceIndex(descriptions)
        result = index.search("turn_on", domain="light")
        assert "light.turn_on" in result
        assert "switch.turn_on" not in result

    def test_no_match(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "Turn on"}}}
        index = ServiceIndex(descriptions)
        result = index.search("nonexistent")
        assert 'No services found matching "nonexistent"' in result

    def test_no_match_with_domain_filter(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "Turn on"}}}
        index = ServiceIndex(descriptions)
        result = index.search("toggle", domain="light")
        assert 'No services found in domain "light" matching "toggle"' in result

    def test_empty_index_any_query(self) -> None:
        index = ServiceIndex({})
        result = index.search("anything")
        assert "No services found" in result


class TestServiceIndexExplain:
    """Tests for ServiceIndex.explain()."""

    def test_known_service(self) -> None:
        descriptions = {
            "light": {
                "turn_on": {
                    "description": "Turn on a light",
                    "fields": {
                        "brightness": {
                            "description": "Brightness level",
                            "selector": {"number": {"min": 0, "max": 255}},
                        },
                    },
                    "target": {"entity": {"domain": "light"}},
                },
            },
        }
        index = ServiceIndex(descriptions)
        result = index.explain("light", "turn_on")
        assert result is not None
        assert "light.turn_on" in result
        assert "Turn on a light" in result
        assert "brightness" in result.lower()

    def test_unknown_service(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "Turn on"}}}
        index = ServiceIndex(descriptions)
        result = index.explain("light", "nonexistent")
        assert result is None

    def test_unknown_domain(self) -> None:
        descriptions = {"light": {"turn_on": {"description": "Turn on"}}}
        index = ServiceIndex(descriptions)
        result = index.explain("nonexistent", "turn_on")
        assert result is None

    def test_empty_index(self) -> None:
        index = ServiceIndex({})
        result = index.explain("light", "turn_on")
        assert result is None

    def test_service_with_sections(self) -> None:
        descriptions = {
            "light": {
                "turn_on": {
                    "description": "Turn on",
                    "fields": {
                        "advanced": {
                            "name": "Advanced Options",
                            "fields": {
                                "transition": {"description": "Transition time"},
                            },
                        },
                    },
                },
            },
        }
        index = ServiceIndex(descriptions)
        result = index.explain("light", "turn_on")
        assert result is not None
        assert "Advanced Options" in result
        assert "transition" in result


class TestSelectorDescriptions:
    """Tests for selector descriptions."""

    def test_known_selector_has_description(self) -> None:
        for selector_type in SELECTOR_DESCRIPTIONS:
            desc = describe_selector(selector_type)
            assert desc, f"Empty description for {selector_type}"
            assert selector_type in desc

    def test_unknown_selector_fallback(self) -> None:
        result = describe_selector("unknown_selector_type")
        assert "unknown_selector_type" in result
        assert "Unknown" in result

    def test_common_selectors_present(self) -> None:
        expected = ["boolean", "text", "number", "entity", "target", "duration"]
        for sel in expected:
            assert sel in SELECTOR_DESCRIPTIONS


class TestCallTool:
    """Tests for call_tool()."""

    def _make_index(self) -> ServiceIndex:
        return ServiceIndex(
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

    def test_search_returns_done(self) -> None:
        index = self._make_index()
        result = call_tool("hamster_services_search", {"query": "light"}, index)
        assert isinstance(result, Done)
        assert result.result.content[0].text  # type: ignore[union-attr]

    def test_explain_returns_done(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_explain", {"domain": "light", "service": "turn_on"}, index
        )
        assert isinstance(result, Done)
        assert not result.result.is_error

    def test_explain_unknown_service_error(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_explain",
            {"domain": "light", "service": "nonexistent"},
            index,
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_valid_service_returns_service_call(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_call",
            {
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": ["light.living_room"]},
                "data": {"brightness": 255},
            },
            index,
        )
        assert isinstance(result, ServiceCall)
        assert result.domain == "light"
        assert result.service == "turn_on"
        assert result.target == {"entity_id": ["light.living_room"]}
        assert result.data == {"brightness": 255}
        assert isinstance(result.continuation, FormatServiceResponse)

    def test_call_unknown_service_error(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_call",
            {"domain": "light", "service": "nonexistent", "data": {}},
            index,
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_search_empty_index(self) -> None:
        index = ServiceIndex({})
        result = call_tool("hamster_services_search", {"query": "anything"}, index)
        assert isinstance(result, Done)
        assert "No services found" in result.result.content[0].text  # type: ignore[union-attr]

    def test_call_empty_index_error(self) -> None:
        index = ServiceIndex({})
        result = call_tool(
            "hamster_services_call",
            {"domain": "light", "service": "turn_on", "data": {}},
            index,
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_schema_returns_done(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_schema", {"selector_type": "boolean"}, index
        )
        assert isinstance(result, Done)
        assert "boolean" in result.result.content[0].text  # type: ignore[union-attr]

    def test_unknown_tool_error(self) -> None:
        index = self._make_index()
        result = call_tool("unknown_tool", {}, index)
        assert isinstance(result, Done)
        assert result.result.is_error


class TestCallToolArgumentValidation:
    """Tests for argument validation in call_tool()."""

    def _make_index(self) -> ServiceIndex:
        return ServiceIndex({"light": {"turn_on": {"description": "Turn on"}}})

    def test_search_missing_query(self) -> None:
        index = self._make_index()
        result = call_tool("hamster_services_search", {}, index)
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_search_query_wrong_type(self) -> None:
        index = self._make_index()
        result = call_tool("hamster_services_search", {"query": 123}, index)
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_explain_missing_domain(self) -> None:
        index = self._make_index()
        result = call_tool("hamster_services_explain", {"service": "turn_on"}, index)
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_explain_missing_service(self) -> None:
        index = self._make_index()
        result = call_tool("hamster_services_explain", {"domain": "light"}, index)
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_missing_domain(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_call", {"service": "turn_on", "data": {}}, index
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_missing_service(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_call", {"domain": "light", "data": {}}, index
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_call_missing_data_uses_empty(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_call", {"domain": "light", "service": "turn_on"}, index
        )
        # Should succeed and use empty data
        assert isinstance(result, ServiceCall)
        assert result.data == {}

    def test_call_target_wrong_type(self) -> None:
        index = self._make_index()
        result = call_tool(
            "hamster_services_call",
            {"domain": "light", "service": "turn_on", "target": "invalid"},
            index,
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_schema_missing_selector_type(self) -> None:
        index = self._make_index()
        result = call_tool("hamster_services_schema", {}, index)
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
