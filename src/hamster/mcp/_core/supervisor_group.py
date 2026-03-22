"""SupervisorGroup: Supervisor API endpoint definitions and invocation.

Provides static endpoint definitions for Supervisor API and implements
the SourceGroup protocol for search, explain, schema, and command invocation.

Unlike the hass group (discovered at runtime), Supervisor endpoints are
defined statically.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import Done, FormatSupervisorResponse, SupervisorCall, ToolEffect
from .types import CallToolResult, TextContent

# --- Types ---


@dataclass(frozen=True, slots=True)
class EndpointInfo:
    """Metadata for a Supervisor API endpoint.

    Attributes:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., "/core/logs", "/addons/{slug}/logs")
        description: Human-readable description
        params_schema: Parameter definitions (JSON-schema-like)
        path_params: Template parameters in the path, e.g., ("slug",)
        returns_text: True for log endpoints that return plain text
    """

    method: str
    path: str
    description: str
    params_schema: dict[str, object]
    path_params: tuple[str, ...] = ()
    returns_text: bool = False


# --- Endpoint definitions ---


SUPERVISOR_ENDPOINTS: dict[str, EndpointInfo] = {
    "core/logs": EndpointInfo(
        method="GET",
        path="/core/logs",
        description="Get Home Assistant Core logs",
        params_schema={},
        returns_text=True,
    ),
    "core/info": EndpointInfo(
        method="GET",
        path="/core/info",
        description="Get Home Assistant Core information",
        params_schema={},
    ),
    "supervisor/info": EndpointInfo(
        method="GET",
        path="/supervisor/info",
        description="Get Supervisor information",
        params_schema={},
    ),
    "supervisor/logs": EndpointInfo(
        method="GET",
        path="/supervisor/logs",
        description="Get Supervisor logs",
        params_schema={},
        returns_text=True,
    ),
    "host/info": EndpointInfo(
        method="GET",
        path="/host/info",
        description="Get host system information",
        params_schema={},
    ),
    "host/logs": EndpointInfo(
        method="GET",
        path="/host/logs",
        description="Get host system logs",
        params_schema={},
        returns_text=True,
    ),
    "addons": EndpointInfo(
        method="GET",
        path="/addons",
        description="List installed add-ons",
        params_schema={},
    ),
    "addons/{slug}/info": EndpointInfo(
        method="GET",
        path="/addons/{slug}/info",
        description="Get add-on information",
        params_schema={"slug": {"type": "string", "description": "Add-on slug"}},
        path_params=("slug",),
    ),
    "addons/{slug}/logs": EndpointInfo(
        method="GET",
        path="/addons/{slug}/logs",
        description="Get add-on logs",
        params_schema={"slug": {"type": "string", "description": "Add-on slug"}},
        path_params=("slug",),
        returns_text=True,
    ),
    "backups": EndpointInfo(
        method="GET",
        path="/backups",
        description="List backups",
        params_schema={},
    ),
    "network/info": EndpointInfo(
        method="GET",
        path="/network/info",
        description="Get network information",
        params_schema={},
    ),
}


# --- Helper functions ---


def _make_error(message: str) -> Done:
    """Create a Done result with an error."""
    return Done(
        result=CallToolResult(
            content=(TextContent(text=message),),
            is_error=True,
        )
    )


# --- SupervisorGroup ---


class SupervisorGroup:
    """Source group for Supervisor API endpoints.

    Provides search, explain, schema, and call functionality for
    Supervisor API endpoints. Uses static endpoint definitions.
    """

    def __init__(self, available: bool) -> None:
        """Initialize with availability status.

        Args:
            available: Whether Supervisor is available on this installation
        """
        self._available = available
        # Build search index
        self._entries: list[tuple[str, str, EndpointInfo]] = []
        for endpoint_path, info in SUPERVISOR_ENDPOINTS.items():
            # Build search text from endpoint path and description
            search_text = f"{endpoint_path} {info.description}".lower()
            self._entries.append((endpoint_path, search_text, info))

    @property
    def name(self) -> str:
        """Group name."""
        return "supervisor"

    @property
    def available(self) -> bool:
        """Whether Supervisor is available."""
        return self._available

    def search(self, query: str, *, path_filter: str | None = None) -> str:
        """Search for endpoints matching a keyword.

        Args:
            query: Search keyword (case-insensitive substring match)
            path_filter: Optional prefix filter (e.g., "core" for "core/*")

        Returns:
            Formatted text summary of matching endpoints.
        """
        if not self._available:
            return "Supervisor is not available on this installation."

        query_lower = query.lower()
        matches: list[tuple[str, EndpointInfo]] = []

        for endpoint_path, search_text, info in self._entries:
            # Apply path filter if provided
            if path_filter is not None and not endpoint_path.startswith(path_filter):
                continue

            if query_lower in search_text:
                matches.append((endpoint_path, info))

        if not matches:
            if path_filter:
                return (
                    f'No endpoints found matching "{query}" '
                    f'with path filter "{path_filter}".'
                )
            return f'No endpoints found matching "{query}".'

        # Format results
        if path_filter:
            header = (
                f'Found {len(matches)} endpoints matching "{query}" '
                f'(filter: "{path_filter}"):'
            )
        else:
            header = f'Found {len(matches)} endpoints matching "{query}":'

        lines = [header, ""]
        for i, (ep_path, info) in enumerate(matches, 1):
            lines.append(f"{i}. **{ep_path}** - {info.description}")

        return "\n".join(lines)

    def explain(self, path: str) -> str | None:
        """Get detailed description of an endpoint.

        Args:
            path: Endpoint path (e.g., "core/logs", "addons/{slug}/info")

        Returns:
            Formatted text with endpoint details, or None if not found or unavailable.
        """
        if not self._available:
            return None

        info = SUPERVISOR_ENDPOINTS.get(path)
        if info is None:
            return None

        lines = [f"## {path}"]

        # Description
        lines.append("")
        lines.append(info.description)

        # Method
        lines.append("")
        lines.append(f"**Method:** {info.method}")

        # API path
        lines.append(f"**API Path:** {info.path}")

        # Response type
        if info.returns_text:
            lines.append("**Returns:** Plain text (logs)")
        else:
            lines.append("**Returns:** JSON")

        # Path parameters
        if info.path_params:
            lines.append("")
            lines.append("### Path Parameters")
            for param in info.path_params:
                param_info = info.params_schema.get(param, {})
                if isinstance(param_info, dict):
                    desc = param_info.get("description", "")
                    param_type = param_info.get("type", "string")
                    lines.append(f"- **{param}** (required) [{param_type}]: {desc}")
                else:
                    lines.append(f"- **{param}** (required)")

        # Additional parameters
        other_params = {
            k: v for k, v in info.params_schema.items() if k not in info.path_params
        }
        if other_params:
            lines.append("")
            lines.append("### Parameters")
            for param_name, param_info in other_params.items():
                if isinstance(param_info, dict):
                    desc = param_info.get("description", "")
                    param_type = param_info.get("type", "any")
                    lines.append(f"- **{param_name}** [{param_type}]: {desc}")
                else:
                    lines.append(f"- **{param_name}**")

        return "\n".join(lines)

    def schema(self, path: str) -> str | None:
        """Get schema information for an endpoint.

        Args:
            path: Endpoint path

        Returns:
            Formatted schema text, or None if not found.
        """
        if not self._available:
            return None

        info = SUPERVISOR_ENDPOINTS.get(path)
        if info is None:
            return None

        lines = [f"## {path} Parameters", ""]

        if info.params_schema:
            for param_name, param_info in info.params_schema.items():
                if isinstance(param_info, dict):
                    param_type = param_info.get("type", "any")
                    desc = param_info.get("description")
                    required = param_name in info.path_params

                    req_str = " (required)" if required else ""
                    type_str = f" - type: {param_type}"

                    lines.append(f"- **{param_name}**{req_str}{type_str}")
                    if desc:
                        lines.append(f"  {desc}")
                else:
                    lines.append(f"- **{param_name}**")
        else:
            lines.append("No parameters required.")

        return "\n".join(lines)

    def has_command(self, path: str) -> bool:
        """Check if an endpoint exists.

        Returns False if Supervisor is not available.
        """
        if not self._available:
            return False
        return path in SUPERVISOR_ENDPOINTS

    def parse_call_args(
        self, path: str, arguments: dict[str, object], user_id: str | None
    ) -> ToolEffect:
        """Parse and validate call arguments for an endpoint.

        Args:
            path: Endpoint path (e.g., "core/logs", "addons/{slug}/logs")
            arguments: Tool arguments with path parameters
            user_id: Authenticated user ID for authorization

        Returns:
            SupervisorCall effect on success, Done with error otherwise.
        """
        if not self._available:
            return _make_error("Supervisor is not available on this installation.")

        info = SUPERVISOR_ENDPOINTS.get(path)
        if info is None:
            return _make_error(f"Endpoint not found: {path}")

        # Substitute path parameters
        api_path = info.path
        remaining_args = dict(arguments)

        for param in info.path_params:
            param_value = remaining_args.pop(param, None)
            if param_value is None:
                return _make_error(f"Missing required path parameter: {param}")
            if not isinstance(param_value, str):
                return _make_error(
                    f"Invalid path parameter '{param}' (must be a string)"
                )
            api_path = api_path.replace(f"{{{param}}}", param_value)

        return SupervisorCall(
            method=info.method,
            path=api_path,
            params=remaining_args,
            user_id=user_id,
            continuation=FormatSupervisorResponse(),
        )
