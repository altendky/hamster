"""Meta-tool definitions, ServiceIndex, call_tool(), and resume().

Uses the "meta-tool" pattern: instead of generating one MCP tool per HA service,
4 fixed tools let the LLM discover and invoke any HA service dynamically.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .events import Continuation, Done, FormatServiceResponse, ServiceCall, ToolEffect
from .types import CallToolResult, ServiceCallResult, TextContent, Tool

if TYPE_CHECKING:
    from collections.abc import Mapping

# --- Fixed tool definitions ---

TOOLS: tuple[Tool, ...] = (
    Tool(
        name="hamster_services_search",
        description="Find HA services by keyword, optionally filtered by domain",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to find matching services",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (e.g. 'light', 'switch')",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="hamster_services_explain",
        description="Get field/target/selector details for a specific HA service",
        input_schema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g. 'light')",
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g. 'turn_on')",
                },
            },
            "required": ["domain", "service"],
        },
    ),
    Tool(
        name="hamster_services_call",
        description="Invoke an HA service with separate target and data parameters",
        input_schema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g. 'light')",
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g. 'turn_on')",
                },
                "target": {
                    "type": "object",
                    "description": "Target entities/devices/areas",
                    "properties": {
                        "entity_id": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "device_id": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "area_id": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "floor_id": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "label_id": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "data": {
                    "type": "object",
                    "description": "Service data parameters",
                },
            },
            "required": ["domain", "service"],
        },
    ),
    Tool(
        name="hamster_services_schema",
        description="Describe what a selector type expects as input",
        input_schema={
            "type": "object",
            "properties": {
                "selector_type": {
                    "type": "string",
                    "description": "Selector type (e.g. 'boolean', 'entity', 'target')",
                },
            },
            "required": ["selector_type"],
        },
    ),
)


# --- Selector descriptions ---

SELECTOR_DESCRIPTIONS: dict[str, str] = {
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
    "number": "Numeric value; may have min/max/step constraints defined by the service",
    "object": "Arbitrary JSON object",
    "qr_code": "QR code data (string)",
    "schedule": "Schedule definition object",
    "select": "One of a fixed set of string options (see service description)",
    "selector": "A selector definition object",
    "state": "Entity state value (string)",
    "statistic": "Statistic ID (string)",
    "stt": "Speech-to-text engine ID (string)",
    "target": (
        "Dict with optional keys: entity_id, device_id, area_id, floor_id, label_id "
        "(each can be a string or array of strings)"
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


def describe_selector(selector_type: str) -> str:
    """Look up description for a selector type.

    Returns a fallback message for unknown types.
    """
    if selector_type in SELECTOR_DESCRIPTIONS:
        return f"{selector_type}: {SELECTOR_DESCRIPTIONS[selector_type]}"
    return (
        f"{selector_type}: Unknown selector type. Check Home Assistant documentation."
    )


# --- ServiceIndex ---


class ServiceIndex:
    """Searchable index of HA service descriptions.

    Built from the output of homeassistant.helpers.service.async_get_all_descriptions().
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

    def search(self, query: str, *, domain: str | None = None) -> str:
        """Search for services matching a keyword.

        Args:
            query: Search keyword (case-insensitive substring match)
            domain: Optional domain filter

        Returns:
            Formatted text summary of matching services.
        """
        query_lower = query.lower()
        matches: list[tuple[str, str, dict[str, object]]] = []

        for entry_domain, service_name, search_text, service_data in self._entries:
            if domain is not None and entry_domain != domain:
                continue
            if query_lower in search_text:
                matches.append((entry_domain, service_name, service_data))

        if not matches:
            if domain:
                return f'No services found in domain "{domain}" matching "{query}".'
            return f'No services found matching "{query}".'

        # Format results
        if domain:
            header = (
                f'Found {len(matches)} services in domain "{domain}" '
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

    def explain(self, domain: str, service: str) -> str | None:
        """Get detailed description of a single service.

        Args:
            domain: Service domain
            service: Service name

        Returns:
            Formatted text with full service details, or None if not found.
        """
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

    def has_service(self, domain: str, service: str) -> bool:
        """Check if a service exists in the index."""
        domain_services = self._descriptions.get(domain)
        if not isinstance(domain_services, dict):
            return False
        return service in domain_services


# --- Tool dispatch ---


def _make_error(message: str) -> Done:
    """Create a Done result with an error."""
    return Done(
        result=CallToolResult(
            content=(TextContent(text=message),),
            is_error=True,
        )
    )


def _make_text(text: str) -> Done:
    """Create a Done result with text content."""
    return Done(result=CallToolResult(content=(TextContent(text=text),)))


def call_tool(
    name: str,
    arguments: dict[str, object],
    index: ServiceIndex,
) -> ToolEffect:
    """Dispatch a tool call by name.

    Args:
        name: Tool name
        arguments: Tool arguments
        index: Current service index

    Returns:
        ToolEffect (Done for immediate results, ServiceCall for I/O)
    """
    if name == "hamster_services_search":
        return _call_search(arguments, index)
    if name == "hamster_services_explain":
        return _call_explain(arguments, index)
    if name == "hamster_services_call":
        return _call_service(arguments, index)
    if name == "hamster_services_schema":
        return _call_schema(arguments)
    return _make_error(f"Unknown tool: {name}")


def _call_search(arguments: dict[str, object], index: ServiceIndex) -> ToolEffect:
    """Handle hamster_services_search."""
    query = arguments.get("query")
    if not isinstance(query, str):
        return _make_error("Missing or invalid 'query' parameter (must be a string)")

    domain = arguments.get("domain")
    if domain is not None and not isinstance(domain, str):
        return _make_error("Invalid 'domain' parameter (must be a string)")

    result = index.search(query, domain=domain)
    return _make_text(result)


def _call_explain(arguments: dict[str, object], index: ServiceIndex) -> ToolEffect:
    """Handle hamster_services_explain."""
    domain = arguments.get("domain")
    if not isinstance(domain, str):
        return _make_error("Missing or invalid 'domain' parameter (must be a string)")

    service = arguments.get("service")
    if not isinstance(service, str):
        return _make_error("Missing or invalid 'service' parameter (must be a string)")

    result = index.explain(domain, service)
    if result is None:
        return _make_error(f"Service not found: {domain}.{service}")
    return _make_text(result)


def _call_service(arguments: dict[str, object], index: ServiceIndex) -> ToolEffect:
    """Handle hamster_services_call."""
    domain = arguments.get("domain")
    if not isinstance(domain, str):
        return _make_error("Missing or invalid 'domain' parameter (must be a string)")

    service = arguments.get("service")
    if not isinstance(service, str):
        return _make_error("Missing or invalid 'service' parameter (must be a string)")

    # Validate service exists
    if not index.has_service(domain, service):
        return _make_error(f"Service not found: {domain}.{service}")

    target = arguments.get("target")
    if target is not None and not isinstance(target, dict):
        return _make_error("Invalid 'target' parameter (must be an object)")

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
        continuation=FormatServiceResponse(),
    )


def _call_schema(arguments: dict[str, object]) -> ToolEffect:
    """Handle hamster_services_schema."""
    selector_type = arguments.get("selector_type")
    if not isinstance(selector_type, str):
        return _make_error(
            "Missing or invalid 'selector_type' parameter (must be a string)"
        )

    result = describe_selector(selector_type)
    return _make_text(result)


# --- Continuation ---


def resume(continuation: Continuation, io_result: ServiceCallResult) -> ToolEffect:
    """Resume tool execution after I/O completes.

    Args:
        continuation: The continuation from ServiceCall
        io_result: Result of the I/O operation

    Returns:
        Next ToolEffect (usually Done)
    """
    if isinstance(continuation, FormatServiceResponse):
        return _format_service_response(io_result)

    # Should not happen with proper typing, but handle gracefully
    return _make_error(
        f"Unknown continuation type: {type(continuation)}"
    )  # pragma: no cover


def _format_service_response(io_result: ServiceCallResult) -> Done:
    """Format a service call result into MCP content."""
    if not io_result.success:
        return Done(
            result=CallToolResult(
                content=(TextContent(text=f"Error: {io_result.error}"),),
                is_error=True,
            )
        )

    if io_result.data:
        text = json.dumps(io_result.data, indent=2, default=str)
    else:
        text = "Service call completed successfully."

    return Done(result=CallToolResult(content=(TextContent(text=text),)))
