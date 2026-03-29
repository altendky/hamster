"""Tests for docs_enrichment module.

All tests are pure --- no I/O, no mocks, no fixtures.
"""

from __future__ import annotations

from hamster_mcp.mcp._core.docs_enrichment import (
    _extract_command_types,
    _split_h2_sections,
    _split_h3_subsections,
    _type_from_json,
    _type_from_regex,
    enrich_commands,
    parse_websocket_docs,
)
from hamster_mcp.mcp._core.hass_group import CommandInfo

# ---------------------------------------------------------------------------
# _split_h2_sections
# ---------------------------------------------------------------------------


class TestSplitH2Sections:
    """Tests for _split_h2_sections."""

    def test_empty(self) -> None:
        assert _split_h2_sections("") == []

    def test_no_headings(self) -> None:
        assert _split_h2_sections("Just some text.\n\nMore text.") == []

    def test_single_section(self) -> None:
        md = "## Fetching states\n\nThis will get a dump of all states.\n"
        result = _split_h2_sections(md)
        assert len(result) == 1
        assert result[0][0] == "Fetching states"
        assert "dump of all states" in result[0][1]

    def test_multiple_sections(self) -> None:
        md = "## First\n\nBody 1\n\n## Second\n\nBody 2\n\n## Third\n\nBody 3\n"
        result = _split_h2_sections(md)
        assert len(result) == 3
        assert result[0][0] == "First"
        assert result[1][0] == "Second"
        assert result[2][0] == "Third"
        assert "Body 1" in result[0][1]
        assert "Body 2" in result[1][1]
        assert "Body 3" in result[2][1]

    def test_preserves_subsections_in_body(self) -> None:
        md = "## Parent\n\nIntro text\n\n### Child\n\nChild text\n"
        result = _split_h2_sections(md)
        assert len(result) == 1
        assert result[0][0] == "Parent"
        assert "### Child" in result[0][1]
        assert "Child text" in result[0][1]

    def test_preamble_before_first_heading_ignored(self) -> None:
        md = "---\ntitle: WebSocket API\n---\n\nIntro text.\n\n## First\n\nBody\n"
        result = _split_h2_sections(md)
        assert len(result) == 1
        assert result[0][0] == "First"


# ---------------------------------------------------------------------------
# _split_h3_subsections
# ---------------------------------------------------------------------------


class TestSplitH3Subsections:
    """Tests for _split_h3_subsections."""

    def test_empty(self) -> None:
        preamble, subs = _split_h3_subsections("")
        assert preamble == ""
        assert subs == []

    def test_no_subsections(self) -> None:
        body = "Just some text.\n\nMore text."
        preamble, subs = _split_h3_subsections(body)
        assert preamble == body
        assert subs == []

    def test_preamble_and_subsections(self) -> None:
        body = (
            "Intro text.\n\n"
            "### Sub One\n\nSub one body.\n\n"
            "### Sub Two\n\nSub two body.\n"
        )
        preamble, subs = _split_h3_subsections(body)
        assert preamble == "Intro text."
        assert len(subs) == 2
        assert subs[0][0] == "Sub One"
        assert "Sub one body" in subs[0][1]
        assert subs[1][0] == "Sub Two"
        assert "Sub two body" in subs[1][1]

    def test_no_preamble(self) -> None:
        body = "### First\n\nFirst body.\n\n### Second\n\nSecond body.\n"
        preamble, subs = _split_h3_subsections(body)
        assert preamble == ""
        assert len(subs) == 2
        assert subs[0][0] == "First"
        assert "First body" in subs[0][1]

    def test_single_subsection(self) -> None:
        body = "Preamble.\n\n### Only sub\n\nSub body.\n"
        preamble, subs = _split_h3_subsections(body)
        assert preamble == "Preamble."
        assert len(subs) == 1
        assert subs[0][0] == "Only sub"
        assert "Sub body" in subs[0][1]


# ---------------------------------------------------------------------------
# _type_from_json
# ---------------------------------------------------------------------------


class TestTypeFromJson:
    """Tests for _type_from_json."""

    def test_valid_json(self) -> None:
        block = '{\n  "id": 19,\n  "type": "get_states"\n}'
        assert _type_from_json(block) == "get_states"

    def test_strips_comments(self) -> None:
        block = '{\n  "id": 19,\n  "type": "get_states"\n  // Optional\n}'
        assert _type_from_json(block) == "get_states"

    def test_invalid_json_returns_none(self) -> None:
        block = '{\n  "id": 19,\n  "type": "call_service"\n  "extra": true\n}'
        assert _type_from_json(block) is None

    def test_non_dict_returns_none(self) -> None:
        block = "[1, 2, 3]"
        assert _type_from_json(block) is None

    def test_no_type_field_returns_none(self) -> None:
        block = '{\n  "id": 19,\n  "domain": "light"\n}'
        assert _type_from_json(block) is None

    def test_type_not_string_returns_none(self) -> None:
        block = '{\n  "id": 19,\n  "type": 42\n}'
        assert _type_from_json(block) is None


# ---------------------------------------------------------------------------
# _type_from_regex
# ---------------------------------------------------------------------------


class TestTypeFromRegex:
    """Tests for _type_from_regex."""

    def test_basic_match(self) -> None:
        block = '  "id": 19,\n  "type": "get_states"\n'
        assert _type_from_regex(block) == "get_states"

    def test_nested_type_ignored(self) -> None:
        block = (
            '  "id": 24,\n'
            '  "type": "fire_event",\n'
            '  "event_data": {\n'
            '    "type": "motion_detected"\n'
            "  }\n"
        )
        assert _type_from_regex(block) == "fire_event"

    def test_no_id_returns_none(self) -> None:
        block = '  "type": "auth_required",\n  "ha_version": "2021.5.3"\n'
        assert _type_from_regex(block) is None

    def test_slash_in_type(self) -> None:
        block = '  "id": 1,\n  "type": "config/entity_registry/list_for_display"\n'
        assert _type_from_regex(block) == "config/entity_registry/list_for_display"


# ---------------------------------------------------------------------------
# _extract_command_types
# ---------------------------------------------------------------------------


class TestExtractCommandTypes:
    """Tests for _extract_command_types."""

    def test_single_command(self) -> None:
        text = (
            'Description text.\n\n```json\n{\n  "id": 19,\n'
            '  "type": "get_states"\n}\n```\n'
        )
        assert _extract_command_types(text) == ["get_states"]

    def test_excludes_result_type(self) -> None:
        text = (
            '```json\n{\n  "id": 19,\n  "type": "result",\n  "success": true\n}\n```\n'
        )
        assert _extract_command_types(text) == []

    def test_excludes_event_type(self) -> None:
        text = '```json\n{\n  "id": 18,\n  "type": "event",\n  "event": {}\n}\n```\n'
        assert _extract_command_types(text) == []

    def test_excludes_auth_types(self) -> None:
        text = '```json\n{\n  "type": "auth",\n  "access_token": "ABC"\n}\n```\n'
        assert _extract_command_types(text) == []

    def test_multiple_blocks_with_command_and_response(self) -> None:
        text = (
            '```json\n{\n  "id": 19,\n  "type": "get_config"\n}\n```\n\n'
            '```json\n{\n  "id": 19,\n  "type": "result",\n'
            '  "success": true\n}\n```\n'
        )
        result = _extract_command_types(text)
        assert result == ["get_config"]

    def test_comment_in_json_block(self) -> None:
        text = (
            "```json\n{\n"
            '  "id": 24,\n'
            '  "type": "call_service",\n'
            '  "domain": "light",\n'
            '  "service": "turn_on",\n'
            "  // Optional\n"
            '  "service_data": {}\n'
            "  // Optional\n"
            '  "target": {}\n'
            "}\n```\n"
        )
        result = _extract_command_types(text)
        # JSON with comments stripped may still be invalid (missing commas
        # between elements where comments were), so regex fallback kicks in
        assert "call_service" in result

    def test_no_code_blocks(self) -> None:
        assert _extract_command_types("Just text, no code blocks.") == []


# ---------------------------------------------------------------------------
# parse_websocket_docs
# ---------------------------------------------------------------------------


class TestParseWebsocketDocs:
    """Tests for parse_websocket_docs."""

    def test_simple_command(self) -> None:
        md = (
            "## Fetching states\n\n"
            "This will get a dump of all states.\n\n"
            '```json\n{\n  "id": 19,\n  "type": "get_states"\n}\n```\n\n'
            "The server will respond...\n\n"
            '```json\n{\n  "id": 19,\n  "type": "result"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        assert "get_states" in result
        assert "dump of all states" in result["get_states"]

    def test_excludes_non_command_sections(self) -> None:
        md = (
            "## Authentication phase\n\n"
            '```json\n{\n  "type": "auth_required"\n}\n```\n\n'
            '```json\n{\n  "type": "auth"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        assert result == {}

    def test_multiple_commands_in_one_section(self) -> None:
        md = (
            "## Manage exposed entities\n\n"
            "Intro text.\n\n"
            "### List exposed entities\n\n"
            "Returns the exposure status.\n\n"
            '```json\n{\n  "id": 18,\n'
            '  "type": "homeassistant/expose_entity/list"\n}\n```\n\n'
            "### Expose or unexpose entities\n\n"
            "Expose or unexpose.\n\n"
            '```json\n{\n  "id": 19,\n'
            '  "type": "homeassistant/expose_entity"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        # Each command gets its subsection-specific description
        assert "homeassistant/expose_entity/list" in result
        assert "homeassistant/expose_entity" in result

        list_desc = result["homeassistant/expose_entity/list"]
        expose_desc = result["homeassistant/expose_entity"]

        assert "Returns the exposure status" in list_desc
        assert "Expose or unexpose" not in list_desc

        assert "Expose or unexpose" in expose_desc
        assert "Returns the exposure status" not in expose_desc

    def test_first_type_wins_for_duplicate(self) -> None:
        md = (
            "## First occurrence\n\n"
            "First body text.\n\n"
            '```json\n{\n  "id": 1,\n  "type": "get_states"\n}\n```\n\n'
            "## Second occurrence\n\n"
            "Second body text.\n\n"
            '```json\n{\n  "id": 2,\n  "type": "get_states"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        assert "get_states" in result
        assert "First body text" in result["get_states"]
        assert "Second body text" not in result["get_states"]

    def test_section_with_no_json_blocks(self) -> None:
        md = "## Server states\n\nJust prose, no code blocks.\n"
        result = parse_websocket_docs(md)
        assert result == {}

    def test_empty_input(self) -> None:
        assert parse_websocket_docs("") == {}

    def test_preamble_command_in_multi_subsection_section(self) -> None:
        md = (
            "## Subscribe to trigger\n\n"
            "You can subscribe to triggers.\n\n"
            '```json\n{\n  "id": 2,\n  "type": "subscribe_trigger"\n}\n```\n\n'
            "### Unsubscribing from events\n\n"
            "To unsubscribe:\n\n"
            '```json\n{\n  "id": 3,\n  "type": "unsubscribe_events"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        assert "subscribe_trigger" in result
        assert "unsubscribe_events" in result

        sub_desc = result["subscribe_trigger"]
        unsub_desc = result["unsubscribe_events"]

        assert "subscribe to triggers" in sub_desc
        assert "unsubscribe" not in sub_desc.lower()

        assert "To unsubscribe" in unsub_desc
        assert "subscribe to triggers" not in unsub_desc

    def test_section_without_subsections_unchanged(self) -> None:
        md = (
            "## Fetching states\n\n"
            "This will get a dump of all states.\n\n"
            '```json\n{\n  "id": 19,\n  "type": "get_states"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        assert "get_states" in result
        assert "dump of all states" in result["get_states"]

    def test_subsection_with_no_commands_skipped(self) -> None:
        md = (
            "## Topic\n\n"
            "Intro.\n\n"
            "### Background\n\n"
            "Just prose, no code blocks.\n\n"
            "### The command\n\n"
            "Do the thing.\n\n"
            '```json\n{\n  "id": 1,\n  "type": "do_thing"\n}\n```\n'
        )
        result = parse_websocket_docs(md)
        assert "do_thing" in result
        assert "Do the thing" in result["do_thing"]
        assert "Just prose" not in result["do_thing"]


# ---------------------------------------------------------------------------
# enrich_commands
# ---------------------------------------------------------------------------


class TestEnrichCommands:
    """Tests for enrich_commands."""

    def test_matching_descriptions_applied(self) -> None:
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
        }
        descriptions = {"get_states": "Get all entity states."}
        result = enrich_commands(commands, descriptions)
        assert result["get_states"].description == "Get all entity states."

    def test_unmatched_commands_unchanged(self) -> None:
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
        }
        descriptions = {"get_config": "Get the config."}
        result = enrich_commands(commands, descriptions)
        assert result["get_states"].description is None

    def test_does_not_mutate_input(self) -> None:
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
        }
        descriptions = {"get_states": "Get all entity states."}
        result = enrich_commands(commands, descriptions)
        # Input unchanged
        assert commands["get_states"].description is None
        # Output has description
        assert result["get_states"].description == "Get all entity states."

    def test_preserves_schema(self) -> None:
        schema: dict[str, object] = {"fields": {"domain": {"required": True}}}
        commands = {
            "call_service": CommandInfo(
                command_type="call_service",
                schema=schema,
            ),
        }
        descriptions = {"call_service": "Call a service."}
        result = enrich_commands(commands, descriptions)
        assert result["call_service"].schema == schema
        assert result["call_service"].description == "Call a service."

    def test_overwrites_existing_description(self) -> None:
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
                description="Old description",
            ),
        }
        descriptions = {"get_states": "New description."}
        result = enrich_commands(commands, descriptions)
        assert result["get_states"].description == "New description."

    def test_empty_commands(self) -> None:
        result = enrich_commands({}, {"get_states": "desc"})
        assert result == {}

    def test_empty_descriptions(self) -> None:
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
        }
        result = enrich_commands(commands, {})
        assert result["get_states"].description is None

    def test_mixed_matching_and_unmatched(self) -> None:
        commands = {
            "get_states": CommandInfo(
                command_type="get_states",
                schema={"fields": {}},
            ),
            "get_config": CommandInfo(
                command_type="get_config",
                schema={"fields": {}},
            ),
            "fire_event": CommandInfo(
                command_type="fire_event",
                schema={"fields": {}},
            ),
        }
        descriptions = {
            "get_states": "All states.",
            "fire_event": "Fire an event.",
        }
        result = enrich_commands(commands, descriptions)
        assert result["get_states"].description == "All states."
        assert result["get_config"].description is None
        assert result["fire_event"].description == "Fire an event."
