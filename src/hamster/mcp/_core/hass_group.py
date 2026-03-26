"""HassGroup: WebSocket command discovery and invocation.

Discovers WebSocket commands from hass.data["websocket_api"] and
implements the SourceGroup protocol for search, explain, schema,
and command invocation.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from .events import Done, FormatHassResponse, HassCommand, ToolEffect
from .types import CallToolResult, TextContent

_LOGGER = logging.getLogger(__name__)


# --- Types ---


@dataclass(frozen=True, slots=True)
class CommandInfo:
    """Metadata for a WebSocket command.

    Attributes:
        command_type: The command type string (e.g., "get_states")
        schema: JSON-representable schema description
        description: Human-readable description (None until docs enrichment)
    """

    command_type: str
    schema: dict[str, object]
    description: str | None = None


# --- Voluptuous schema conversion ---


def _get_voluptuous_type(validator: object) -> str:
    """Extract type string from a voluptuous validator.

    Returns one of: "string", "integer", "number", "boolean", "object",
    "array", "any"
    """
    # Import voluptuous lazily to avoid issues in sans-IO tests
    try:
        import voluptuous as vol
    except ImportError:
        return "any"

    # Handle Coerce
    if isinstance(validator, vol.Coerce):
        coerce_type = validator.type
        if coerce_type is int:
            return "integer"
        if coerce_type is float:
            return "number"
        if coerce_type is str:
            return "string"
        if coerce_type is bool:
            return "boolean"
        return "any"

    # Handle All (chain of validators) - extract base type from first
    if isinstance(validator, vol.All):
        if validator.validators:
            return _get_voluptuous_type(validator.validators[0])
        return "any"

    # Handle Any (union type)
    if isinstance(validator, vol.Any):
        return "any"

    # Handle In (enum-like)
    if isinstance(validator, vol.In):
        return "string"

    # Handle boolean
    if validator is bool or (
        isinstance(validator, type) and issubclass(validator, bool)
    ):
        return "boolean"

    # Handle basic types
    if validator is str or (isinstance(validator, type) and issubclass(validator, str)):
        return "string"
    if validator is int or (isinstance(validator, type) and issubclass(validator, int)):
        return "integer"
    if validator is float or (
        isinstance(validator, type) and issubclass(validator, float)
    ):
        return "number"
    if validator is dict or (
        isinstance(validator, type) and issubclass(validator, dict)
    ):
        return "object"
    if validator is list or (
        isinstance(validator, type) and issubclass(validator, list)
    ):
        return "array"

    # Handle Schema (nested)
    if isinstance(validator, vol.Schema):
        return "object"

    # Unknown - return any
    _LOGGER.debug("Unknown voluptuous validator type: %s", type(validator))
    return "any"


def _extract_field_info(
    key: object, validator: object
) -> tuple[str, dict[str, object]] | None:
    """Extract field info from a voluptuous key-validator pair.

    Returns (field_name, field_info) or None if not extractable.
    """
    try:
        import voluptuous as vol
    except ImportError:
        return None

    field_name: str
    required: bool = True
    default: object = None
    has_default: bool = False
    description: str | None = None

    # Extract field name and optionality
    if isinstance(key, vol.Required):
        field_name = str(key.schema)
        required = True
        if hasattr(key, "description") and key.description:
            description = str(key.description)
    elif isinstance(key, vol.Optional):
        field_name = str(key.schema)
        required = False
        if key.default is not vol.UNDEFINED:
            has_default = True
            # voluptuous wraps defaults in a lambda factory
            if callable(key.default):
                try:
                    default = key.default()
                except Exception:
                    default = None
                    has_default = False
            else:
                default = key.default
        if hasattr(key, "description") and key.description:
            description = str(key.description)
    elif isinstance(key, str):
        field_name = key
        required = True
    else:
        # Unknown key type
        return None

    # Get the type
    field_type = _get_voluptuous_type(validator)

    # Build field info
    field_info: dict[str, object] = {
        "required": required,
        "type": field_type,
    }
    if description:
        field_info["description"] = description
    if has_default:
        field_info["default"] = default

    return field_name, field_info


def voluptuous_to_description(schema: object) -> dict[str, object]:
    """Convert a voluptuous schema to a JSON-representable description.

    Args:
        schema: A voluptuous Schema object, dict, or False

    Returns:
        {
            "fields": {
                "field_name": {
                    "required": bool,
                    "type": str,
                    "description": str | None,
                    "default": object | None,
                },
                ...
            }
        }
    """
    try:
        import voluptuous as vol
    except ImportError:
        return {"fields": {}}

    # Handle schema=False (no additional params)
    if schema is False:
        return {"fields": {}}

    # Handle None
    if schema is None:
        return {"fields": {}}

    # Extract the schema dict
    schema_dict: dict[object, object] | None = None

    if isinstance(schema, vol.Schema):
        if isinstance(schema.schema, dict):
            schema_dict = schema.schema
        else:
            # Non-dict schema (e.g., just a validator)
            return {"fields": {}}
    elif isinstance(schema, dict):
        schema_dict = schema
    else:
        _LOGGER.debug("Unknown schema type: %s", type(schema))
        return {"fields": {}}

    # Convert each field
    fields: dict[str, object] = {}
    for key, validator in schema_dict.items():
        result = _extract_field_info(key, validator)
        if result:
            field_name, field_info = result
            fields[field_name] = field_info

    return {"fields": fields}


# --- Helper functions ---


def _make_error(message: str) -> Done:
    """Create a Done result with an error."""
    return Done(
        result=CallToolResult(
            content=(TextContent(text=message),),
            is_error=True,
        )
    )


def _is_filtered_command(command_type: str) -> bool:
    """Check if a command should be filtered out.

    Filters:
    - Commands starting with "subscribe" or "unsubscribe"
    - Commands starting with "auth" or "auth/"
    """
    lower = command_type.lower()

    # Filter subscription commands
    if lower.startswith(("subscribe", "unsubscribe")):
        return True

    # Filter auth commands
    return lower == "auth" or lower.startswith("auth/")


# --- HassGroup ---


class HassGroup:
    """Source group for Home Assistant WebSocket commands.

    Discovers commands from hass.data["websocket_api"] and provides
    search, explain, schema, and call functionality.
    """

    def __init__(self, commands: dict[str, CommandInfo]) -> None:
        """Initialize with discovered commands.

        Args:
            commands: Dict mapping command_type to CommandInfo
        """
        self._commands = commands
        # Build search index
        self._entries: list[tuple[str, str, CommandInfo]] = []
        for command_type, info in commands.items():
            # Build search text from command type, description, and field names
            search_parts = [command_type]
            if info.description:
                search_parts.append(info.description)
            schema = info.schema
            if isinstance(schema, dict):
                fields = schema.get("fields")
                if isinstance(fields, dict):
                    search_parts.extend(fields.keys())
            search_text = " ".join(search_parts).lower()
            self._entries.append((command_type, search_text, info))

    @property
    def commands(self) -> dict[str, CommandInfo]:
        """Copy of the commands dict.

        Used by the docs enrichment layer to read current commands
        before merging in descriptions.
        """
        return dict(self._commands)

    @property
    def name(self) -> str:
        """Group name."""
        return "hass"

    @property
    def available(self) -> bool:
        """Hass commands are always available."""
        return True

    def search(self, query: str, *, path_filter: str | None = None) -> str:
        """Search for commands matching a keyword.

        Args:
            query: Search keyword (case-insensitive substring match)
            path_filter: Optional prefix filter (e.g., "config" for "config/*")

        Returns:
            Formatted text summary of matching commands.
        """
        query_lower = query.lower()
        matches: list[tuple[str, CommandInfo]] = []

        for command_type, search_text, info in self._entries:
            # Apply path filter if provided
            if path_filter is not None and not command_type.startswith(path_filter):
                # Also try matching after the first path segment
                if "/" in command_type:
                    first_segment = command_type.split("/")[0]
                    if first_segment != path_filter:
                        continue
                else:
                    continue

            if query_lower in search_text:
                matches.append((command_type, info))

        if not matches:
            if path_filter:
                return (
                    f'No commands found matching "{query}" '
                    f'with path filter "{path_filter}".'
                )
            return f'No commands found matching "{query}".'

        # Format results
        if path_filter:
            header = (
                f'Found {len(matches)} commands matching "{query}" '
                f'(filter: "{path_filter}"):'
            )
        else:
            header = f'Found {len(matches)} commands matching "{query}":'

        lines = [header, ""]
        for i, (cmd_type, info) in enumerate(matches, 1):
            if info.description:
                lines.append(f"{i}. **{cmd_type}** - {info.description}")
            else:
                lines.append(f"{i}. **{cmd_type}**")

        return "\n".join(lines)

    def explain(self, path: str) -> str | None:
        """Get detailed description of a command.

        Args:
            path: Command type (e.g., "get_states", "config/entity_registry/list")

        Returns:
            Formatted text with command details, or None if not found.
        """
        info = self._commands.get(path)
        if info is None:
            return None

        lines = [f"## {path}"]

        # Description
        if info.description:
            lines.append("")
            lines.append(info.description)

        # Parameters
        schema = info.schema
        if isinstance(schema, dict):
            fields = schema.get("fields")
            if isinstance(fields, dict) and fields:
                lines.append("")
                lines.append("### Parameters")
                for field_name, field_info in fields.items():
                    if not isinstance(field_info, dict):
                        continue

                    required = field_info.get("required", False)
                    field_type = field_info.get("type", "any")
                    desc = field_info.get("description")
                    default = field_info.get("default")

                    req_marker = " (required)" if required else ""
                    type_marker = f" [{field_type}]"

                    line = f"- **{field_name}**{req_marker}{type_marker}"
                    if desc:
                        line += f": {desc}"
                    if default is not None and not required:
                        line += f" (default: {default})"
                    lines.append(line)
            else:
                lines.append("")
                lines.append("No parameters required.")

        return "\n".join(lines)

    def schema(self, path: str) -> str | None:
        """Get schema information for a command.

        Args:
            path: Command type

        Returns:
            Formatted schema text, or None if not found.
        """
        info = self._commands.get(path)
        if info is None:
            return None

        lines = [f"## {path} Parameters", ""]

        schema = info.schema
        if isinstance(schema, dict):
            fields = schema.get("fields")
            if isinstance(fields, dict) and fields:
                for field_name, field_info in fields.items():
                    if not isinstance(field_info, dict):
                        continue

                    required = field_info.get("required", False)
                    field_type = field_info.get("type", "any")
                    desc = field_info.get("description")

                    req_str = " (required)" if required else ""
                    type_str = f" - type: {field_type}"

                    lines.append(f"- **{field_name}**{req_str}{type_str}")
                    if desc:
                        lines.append(f"  {desc}")
            else:
                lines.append("No parameters required.")
        else:
            lines.append("No parameters required.")

        return "\n".join(lines)

    def has_command(self, path: str) -> bool:
        """Check if a command exists (and is not filtered)."""
        if _is_filtered_command(path):
            return False
        return path in self._commands

    def parse_call_args(
        self, path: str, arguments: dict[str, object], user_id: str | None
    ) -> ToolEffect:
        """Parse and validate call arguments for a command.

        Args:
            path: Command type (e.g., "get_states")
            arguments: Tool arguments (passed as params to the command)
            user_id: Authenticated user ID for authorization

        Returns:
            HassCommand effect on success, Done with error otherwise.
        """
        # Check if command exists
        if path not in self._commands:
            return _make_error(f"Command not found: {path}")

        # Check if command is filtered
        if _is_filtered_command(path):
            return _make_error(f"Command not available: {path}")

        # Build the HassCommand effect
        return HassCommand(
            command_type=path,
            params=arguments,
            user_id=user_id,
            continuation=FormatHassResponse(),
        )


# --- Discovery helper ---


def discover_commands(
    websocket_api_registry: dict[str, tuple[Any, Any]],
) -> dict[str, CommandInfo]:
    """Discover commands from the WebSocket API registry.

    Args:
        websocket_api_registry: hass.data["websocket_api"] registry

    Returns:
        Dict mapping command_type to CommandInfo
    """
    commands: dict[str, CommandInfo] = {}

    for command_type, (_handler, schema) in websocket_api_registry.items():
        # Filter out subscription and auth commands
        if _is_filtered_command(command_type):
            continue

        # Convert schema
        schema_desc = voluptuous_to_description(schema)

        commands[command_type] = CommandInfo(
            command_type=command_type,
            schema=schema_desc,
            description=None,  # No description until docs enrichment
        )

    return commands
