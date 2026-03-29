"""Pure functions for parsing HA developer docs and enriching WebSocket commands.

Parses the ``docs/api/websocket.md`` file from the
``home-assistant/developers.home-assistant`` repository and extracts
command descriptions that can be used to populate ``CommandInfo.description``
fields.

This module performs no I/O and holds no global state.
"""

from __future__ import annotations

import json
import re

from .hass_group import CommandInfo

# Types that appear in JSON code blocks but are not client-sent commands.
# Responses, server-sent messages, and protocol-level types.
_EXCLUDED_TYPES: frozenset[str] = frozenset(
    {
        "result",
        "event",
        "pong",
        "auth",
        "auth_required",
        "auth_ok",
        "auth_invalid",
        "supported_features",
    }
)

_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)
_COMMENT_RE = re.compile(r"//[^\n]*")
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_H3_RE = re.compile(r"^### (.+)$", re.MULTILINE)


def parse_websocket_docs(markdown: str) -> dict[str, str]:
    """Parse HA developer docs ``websocket.md`` into command descriptions.

    Splits the markdown by ``## `` headings.  For each section, finds JSON
    code blocks containing a ``"type"`` field and maps the type string to
    the section body text (prose + examples).

    Args:
        markdown: Raw markdown content of ``websocket.md``.

    Returns:
        Mapping of command type string to section description text.
        Commands already in :data:`_EXCLUDED_TYPES` are omitted.
    """
    result: dict[str, str] = {}

    sections = _split_h2_sections(markdown)
    for _heading, body in sections:
        preamble, subsections = _split_h3_subsections(body)

        if not subsections:
            # No ### subsections — whole body is the description.
            description = body.strip()
            if not description:
                continue
            for cmd_type in _extract_command_types(body):
                if cmd_type not in _EXCLUDED_TYPES and cmd_type not in result:
                    result[cmd_type] = description
        else:
            # Assign preamble commands the preamble text.
            if preamble:
                for cmd_type in _extract_command_types(preamble):
                    if cmd_type not in _EXCLUDED_TYPES and cmd_type not in result:
                        result[cmd_type] = preamble

            # Assign subsection commands their subsection text.
            for _sub_heading, sub_body in subsections:
                sub_desc = sub_body.strip()
                if not sub_desc:
                    continue
                for cmd_type in _extract_command_types(sub_body):
                    if cmd_type not in _EXCLUDED_TYPES and cmd_type not in result:
                        result[cmd_type] = sub_desc

    return result


def enrich_commands(
    commands: dict[str, CommandInfo],
    descriptions: dict[str, str],
) -> dict[str, CommandInfo]:
    """Create enriched ``CommandInfo`` objects with descriptions from docs.

    For each command whose type has a matching entry in *descriptions*,
    produces a new ``CommandInfo`` with the ``description`` field set.
    Commands without a matching description are returned unchanged.

    Args:
        commands: Current command dict (typically from ``HassGroup.commands``).
        descriptions: Parsed descriptions from :func:`parse_websocket_docs`.

    Returns:
        New dict with descriptions populated where matches exist.
        Does not mutate the input.
    """
    enriched: dict[str, CommandInfo] = {}
    for cmd_type, info in commands.items():
        desc = descriptions.get(cmd_type)
        if desc is not None:
            enriched[cmd_type] = CommandInfo(
                command_type=info.command_type,
                schema=info.schema,
                description=desc,
            )
        else:
            enriched[cmd_type] = info
    return enriched


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_h2_sections(markdown: str) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, body)`` pairs by ``## `` headings.

    The body includes everything between consecutive ``## `` headings,
    including any ``### `` subsections.
    """
    matches = list(_H2_RE.finditer(markdown))
    sections: list[tuple[str, str]] = []

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        sections.append((heading, body))

    return sections


def _split_h3_subsections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Split an H2 section body into preamble and ``### `` subsections.

    Args:
        body: The body text of a ``## `` section (as returned by
            :func:`_split_h2_sections`).

    Returns:
        A tuple of ``(preamble, subsections)`` where *preamble* is the text
        before the first ``### `` heading (may be empty) and *subsections*
        is a list of ``(heading, body)`` pairs for each ``### `` heading.
        If there are no ``### `` headings, *subsections* is empty and
        *preamble* contains the full body text.
    """
    matches = list(_H3_RE.finditer(body))
    if not matches:
        return body, []

    preamble = body[: matches[0].start()].strip()
    subsections: list[tuple[str, str]] = []

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sub_body = body[start:end].strip()
        subsections.append((heading, sub_body))

    return preamble, subsections


def _extract_command_types(text: str) -> list[str]:
    """Extract WebSocket command type strings from JSON code blocks.

    Tries full JSON parsing first.  If parsing fails (e.g. because the
    HA docs include ``//`` comments that make the JSON invalid), falls
    back to regex extraction matching the ``"type"`` field at the same
    indentation as the ``"id"`` field.

    Only returns types not in :data:`_EXCLUDED_TYPES`.
    """
    command_types: list[str] = []

    for match in _CODE_BLOCK_RE.finditer(text):
        block = match.group(1)
        cmd_type = _type_from_json(block) or _type_from_regex(block)
        if cmd_type is not None and cmd_type not in _EXCLUDED_TYPES:
            command_types.append(cmd_type)

    return command_types


def _type_from_json(block: str) -> str | None:
    """Try to extract ``"type"`` by parsing the block as JSON."""
    stripped = _COMMENT_RE.sub("", block)
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    cmd_type = data.get("type")
    return cmd_type if isinstance(cmd_type, str) else None


def _type_from_regex(block: str) -> str | None:
    """Fallback: extract ``"type"`` via regex with indentation matching.

    Matches the ``"type"`` field only when it appears at the same
    indentation level as the ``"id"`` field, avoiding nested
    ``"type"`` keys inside sub-objects.
    """
    id_match = re.search(r'^(\s*)"id"\s*:', block, re.MULTILINE)
    if id_match is None:
        return None

    indent = re.escape(id_match.group(1))
    type_match = re.search(
        rf'^{indent}"type"\s*:\s*"([^"]+)"',
        block,
        re.MULTILINE,
    )
    if type_match is None:
        return None

    return type_match.group(1)
