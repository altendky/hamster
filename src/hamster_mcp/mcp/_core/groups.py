"""Source group protocol and registry for multi-source architecture.

Provides the SourceGroup protocol and GroupRegistry for managing multiple
command sources (services, hass, supervisor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .events import Done, FormatServiceResponse, ServiceCall, ToolEffect
from .types import CallToolResult, TextContent

if TYPE_CHECKING:
    from collections.abc import Mapping


@runtime_checkable
class SourceGroup(Protocol):
    """Protocol for command source groups.

    Each group exposes commands from a different source (services, hass,
    supervisor) with group-specific discovery and metadata.
    """

    @property
    def name(self) -> str:
        """Group name (e.g., 'services', 'hass', 'supervisor')."""
        ...

    @property
    def available(self) -> bool:
        """Whether this group is available. Default True for most groups."""
        ...

    def search(self, query: str, *, path_filter: str | None = None) -> str:
        """Search for commands matching query, optionally filtered by path prefix.

        Returns a formatted markdown string with search results.
        """
        ...

    def explain(self, path: str) -> str | None:
        """Get description for a command.

        Returns None if not found or unavailable.
        """
        ...

    def schema(self, path: str) -> str | None:
        """Get schema/type info for a command.

        Returns None if not found.
        """
        ...

    def has_command(self, path: str) -> bool:
        """Check if a command exists."""
        ...

    def parse_call_args(
        self, path: str, arguments: dict[str, object], user_id: str | None
    ) -> ToolEffect:
        """Parse and validate call arguments, return effect or error."""
        ...


class GroupRegistry:
    """Registry for source groups.

    Manages registration and lookup of groups, and provides aggregate
    operations across all groups.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._groups: dict[str, SourceGroup] = {}

    def register(self, group: SourceGroup) -> None:
        """Register a group.

        Raises ValueError if a group with the same name is already registered.
        """
        if group.name in self._groups:
            raise ValueError(f"Group already registered: {group.name}")
        self._groups[group.name] = group

    def update_group(self, group: SourceGroup) -> None:
        """Replace an existing group by name.

        Raises ValueError if the group is not found.
        """
        if group.name not in self._groups:
            raise ValueError(f"Group not found: {group.name}")
        self._groups[group.name] = group

    def get(self, name: str) -> SourceGroup | None:
        """Get a group by name, or None if not found."""
        return self._groups.get(name)

    def all_groups(self) -> list[SourceGroup]:
        """Return all registered groups."""
        return list(self._groups.values())

    def search_all(self, query: str, *, path_filter: str | None = None) -> str:
        """Aggregate search across all groups.

        If path_filter targets a specific group (e.g., "services" or
        "services/light"), only that group is searched.
        """
        # Parse path_filter to determine which groups to search
        target_group: str | None = None
        sub_filter: str | None = None

        if path_filter:
            if "/" in path_filter:
                target_group, sub_filter = path_filter.split("/", 1)
            else:
                target_group = path_filter
                sub_filter = None

        # Collect results from each group
        results: list[str] = []

        for group in self._groups.values():
            # Skip unavailable groups
            if not group.available:
                continue

            # Skip if we're filtering to a specific group
            if target_group and group.name != target_group:
                continue

            # Search the group
            group_result = group.search(query, path_filter=sub_filter)

            # Skip empty results (check for "No " at start which indicates no matches)
            if group_result.startswith("No "):
                continue

            results.append(f"## {group.name}\n\n{group_result}")

        if not results:
            if target_group:
                return (
                    f'No commands found matching "{query}" in group "{target_group}".'
                )
            return f'No commands found matching "{query}".'

        return "\n\n".join(results)

    def resolve_path(self, full_path: str) -> tuple[SourceGroup, str] | None:
        """Parse 'group/path' and return (group, in-group-path).

        Returns None if the path is invalid or the group is not found.
        """
        if not full_path:
            return None

        if "/" not in full_path:
            return None

        group_name, in_group_path = full_path.split("/", 1)

        group = self._groups.get(group_name)
        if group is None:
            return None

        return (group, in_group_path)


# --- Helper functions ---


def _make_error(message: str) -> Done:
    """Create a Done result with an error."""
    return Done(
        result=CallToolResult(
            content=(TextContent(text=message),),
            is_error=True,
        )
    )


# --- ServicesGroup ---


class ServicesGroup:
    """Source group for Home Assistant services.

    Wraps the service descriptions from async_get_all_descriptions() and
    provides search, explain, schema, and call functionality.
    """

    def __init__(self, descriptions: Mapping[str, Any]) -> None:
        """Build index from HA service descriptions.

        Args:
            descriptions: Dict keyed by domain, then service name.
                Each service value contains 'name', 'description', 'fields', etc.
        """
        self._descriptions = descriptions
        self._entries: list[tuple[str, str, str, dict[str, object]]] = []

        for domain, services in descriptions.items():
            if not isinstance(services, dict):
                continue
            for service_name, service_data in services.items():
                if not isinstance(service_data, dict):
                    continue
                # Build search text from domain, service name, description, field names
                search_parts = [domain, service_name]
                desc = service_data.get("description")
                if isinstance(desc, str):
                    search_parts.append(desc)
                fields = service_data.get("fields")
                if isinstance(fields, dict):
                    search_parts.extend(fields.keys())
                search_text = " ".join(search_parts).lower()
                self._entries.append((domain, service_name, search_text, service_data))

    @property
    def name(self) -> str:
        """Group name."""
        return "services"

    @property
    def available(self) -> bool:
        """Services are always available."""
        return True

    def search(self, query: str, *, path_filter: str | None = None) -> str:
        """Search for services matching a keyword.

        Args:
            query: Search keyword (case-insensitive substring match)
            path_filter: Optional domain filter

        Returns:
            Formatted text summary of matching services.
        """
        query_lower = query.lower()
        matches: list[tuple[str, str, dict[str, object]]] = []

        for entry_domain, service_name, search_text, service_data in self._entries:
            if path_filter is not None and entry_domain != path_filter:
                continue
            if query_lower in search_text:
                matches.append((entry_domain, service_name, service_data))

        if not matches:
            if path_filter:
                return (
                    f'No services found in domain "{path_filter}" matching "{query}".'
                )
            return f'No services found matching "{query}".'

        # Format results
        if path_filter:
            header = (
                f'Found {len(matches)} services in domain "{path_filter}" '
                f'matching "{query}":'
            )
        else:
            header = f'Found {len(matches)} services matching "{query}":'

        lines = [header, ""]
        for i, (d, s, data) in enumerate(matches, 1):
            desc = data.get("description", "")
            if isinstance(desc, str) and desc:
                lines.append(f"{i}. **{d}.{s}** - {desc}")
            else:
                lines.append(f"{i}. **{d}.{s}**")

        return "\n".join(lines)

    def explain(self, path: str) -> str | None:
        """Get detailed description of a single service.

        Args:
            path: Service path in "domain.service" format

        Returns:
            Formatted text with full service details, or None if not found.
        """
        if "." not in path:
            return None

        domain, service = path.split(".", 1)

        domain_services = self._descriptions.get(domain)
        if not isinstance(domain_services, dict):
            return None

        service_data = domain_services.get(service)
        if not isinstance(service_data, dict):
            return None

        lines = [f"## {domain}.{service}"]

        # Description
        desc = service_data.get("description")
        if isinstance(desc, str):
            lines.append("")
            lines.append(desc)

        # Target config
        target = service_data.get("target")
        if target:
            lines.append("")
            lines.append("### Target")
            if isinstance(target, dict):
                if entity := target.get("entity"):
                    lines.append(f"- Entity: {entity}")
                if device := target.get("device"):
                    lines.append(f"- Device: {device}")
                if area := target.get("area"):
                    lines.append(f"- Area: {area}")
            else:
                lines.append("Accepts target specification")

        # Fields
        fields = service_data.get("fields")
        if isinstance(fields, dict) and fields:
            lines.append("")
            lines.append("### Fields")
            self._format_fields(fields, lines)

        return "\n".join(lines)

    def _format_fields(
        self,
        fields: dict[str, object],
        lines: list[str],
        indent: str = "",
    ) -> None:
        """Format field definitions recursively."""
        for field_name, field_data in fields.items():
            if not isinstance(field_data, dict):
                continue

            # Check if this is a section (has 'fields' key)
            if "fields" in field_data:
                section_name = field_data.get("name", field_name)
                lines.append(f"{indent}- **{section_name}** (section)")
                nested_fields = field_data.get("fields")
                if isinstance(nested_fields, dict):
                    self._format_fields(nested_fields, lines, indent + "  ")
                continue

            # Regular field
            field_desc = field_data.get("description", "")
            required = field_data.get("required", False)
            selector = field_data.get("selector", {})

            req_marker = " (required)" if required else ""
            selector_info = ""
            if isinstance(selector, dict) and selector:
                selector_types = list(selector.keys())
                if selector_types:
                    selector_info = f" [{selector_types[0]}]"

            base = f"{indent}- **{field_name}**{req_marker}{selector_info}"
            if isinstance(field_desc, str) and field_desc:
                lines.append(f"{base}: {field_desc}")
            else:
                lines.append(base)

    def schema(self, path: str) -> str | None:
        """Get schema/type info for a service or selector.

        For selectors, use path like "selector/duration".
        For services, use path like "light.turn_on" to get field schema.
        """
        # Check for selector path
        if path.startswith("selector/"):
            selector_type = path[9:]  # Remove "selector/" prefix
            return self._describe_selector(selector_type)

        # Service field schema
        if "." not in path:
            return None

        domain, service = path.split(".", 1)
        domain_services = self._descriptions.get(domain)
        if not isinstance(domain_services, dict):
            return None

        service_data = domain_services.get(service)
        if not isinstance(service_data, dict):
            return None

        # Format field schema
        fields = service_data.get("fields")
        if not isinstance(fields, dict) or not fields:
            return f"Service {domain}.{service} has no parameters."

        lines = [f"## {domain}.{service} Parameters", ""]
        for field_name, field_data in fields.items():
            if not isinstance(field_data, dict):
                continue

            required = field_data.get("required", False)
            selector = field_data.get("selector", {})
            desc = field_data.get("description", "")

            req_str = " (required)" if required else ""
            selector_str = ""
            if isinstance(selector, dict) and selector:
                selector_types = list(selector.keys())
                if selector_types:
                    selector_str = f" - type: {selector_types[0]}"

            lines.append(f"- **{field_name}**{req_str}{selector_str}")
            if isinstance(desc, str) and desc:
                lines.append(f"  {desc}")

        return "\n".join(lines)

    def _describe_selector(self, selector_type: str) -> str:
        """Look up description for a selector type."""
        descriptions = {
            "action": "An automation action sequence (list of action objects)",
            "addon": "Home Assistant add-on slug (string)",
            "area": "Area ID string (e.g. 'living_room')",
            "assist_pipeline": "Assist pipeline ID (string)",
            "attribute": "Entity attribute name (string)",
            "backup_location": "Backup location identifier (string)",
            "boolean": "true or false",
            "color_rgb": "Array of 3 integers [R, G, B], each 0-255",
            "color_temp": "Color temperature in mireds (integer) or Kelvin",
            "condition": "An automation condition (condition object)",
            "config_entry": "Config entry ID (string)",
            "constant": "A fixed constant value",
            "conversation_agent": "Conversation agent ID (string)",
            "country": "ISO 3166-1 alpha-2 country code (string, e.g. 'US')",
            "date": "Date string in ISO format (YYYY-MM-DD)",
            "datetime": "Date and time string in ISO format (YYYY-MM-DDTHH:MM:SS)",
            "device": "Device ID string",
            "duration": (
                "Dict with optional keys: days, hours, minutes, seconds, milliseconds "
                '(all numbers). Example: {"hours": 1, "minutes": 30}'
            ),
            "entity": "Entity ID string (e.g. 'light.living_room')",
            "file": "File path or file content",
            "floor": "Floor ID string",
            "icon": "Material Design Icon name (string, e.g. 'mdi:lightbulb')",
            "label": "Label ID string",
            "language": "Language code (string, e.g. 'en')",
            "location": (
                "Dict with latitude, longitude (required), and radius (optional). "
                'Example: {"latitude": 40.7, "longitude": -74.0}'
            ),
            "media": "Media content ID and type",
            "navigation": "Navigation path within Home Assistant",
            "number": (
                "Numeric value; may have min/max/step constraints "
                "defined by the service"
            ),
            "object": "Arbitrary JSON object",
            "qr_code": "QR code data (string)",
            "schedule": "Schedule definition object",
            "select": "One of a fixed set of string options (see service description)",
            "selector": "A selector definition object",
            "state": "Entity state value (string)",
            "statistic": "Statistic ID (string)",
            "stt": "Speech-to-text engine ID (string)",
            "target": (
                "Dict with optional keys: entity_id, device_id, area_id, floor_id, "
                "label_id (each can be a string or array of strings)"
            ),
            "template": "Jinja2 template string",
            "text": "String value; may have multiline or regex constraints",
            "theme": "Theme name (string)",
            "time": "Time string in HH:MM:SS format",
            "trigger": "An automation trigger definition",
            "tts": "Text-to-speech engine ID (string)",
            "ui_action": "UI action definition",
            "ui_color": "UI color value",
        }

        if selector_type in descriptions:
            return f"{selector_type}: {descriptions[selector_type]}"
        return (
            f"{selector_type}: Unknown selector type. "
            "Check Home Assistant documentation."
        )

    def has_command(self, path: str) -> bool:
        """Check if a service exists."""
        if "." not in path:
            return False

        domain, service = path.split(".", 1)
        domain_services = self._descriptions.get(domain)
        if not isinstance(domain_services, dict):
            return False
        return service in domain_services

    def parse_call_args(
        self, path: str, arguments: dict[str, object], user_id: str | None
    ) -> ToolEffect:
        """Parse and validate call arguments for a service.

        Args:
            path: Service path in "domain.service" format
            arguments: Tool arguments with optional "target" and "data" keys
            user_id: Authenticated user ID for authorization

        Returns:
            ServiceCall effect on success, Done with error otherwise.
        """
        if "." not in path:
            return _make_error(f"Invalid service path: {path}")

        domain, service = path.split(".", 1)

        # Validate service exists
        if not self.has_command(path):
            return _make_error(f"Service not found: {domain}.{service}")

        # Validate target
        target = arguments.get("target")
        if target is not None and not isinstance(target, dict):
            return _make_error("Invalid 'target' parameter (must be an object)")

        # Validate data
        data = arguments.get("data")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return _make_error("Invalid 'data' parameter (must be an object)")

        return ServiceCall(
            domain=domain,
            service=service,
            target=target,
            data=data,
            user_id=user_id,
            continuation=FormatServiceResponse(),
        )
