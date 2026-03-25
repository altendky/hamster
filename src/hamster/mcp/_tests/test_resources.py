"""Tests for MCP resource support.

Covers the resources module, protocol handlers (resources/list,
resources/read), and the tool-based access path (list_resources,
read_resource tools).
"""

from __future__ import annotations

from hamster.mcp._core.events import Done
from hamster.mcp._core.groups import GroupRegistry
from hamster.mcp._core.jsonrpc import (
    INVALID_PARAMS,
    JsonRpcNotification,
    JsonRpcRequest,
    build_resource_list_response,
    build_resource_read_response,
    serialize_resource,
    serialize_resource_contents,
)
from hamster.mcp._core.resources import (
    ResourceEntry,
    read_resource,
)
from hamster.mcp._core.session import (
    MCPServerSession,
    SessionError,
    SessionResponse,
    SessionState,
)
from hamster.mcp._core.tools import call_tool
from hamster.mcp._core.types import (
    Resource,
    ResourceContents,
    ServerCapabilities,
    ServerInfo,
)
from hamster.mcp._io.resources import load_all_resources

# --- Resources module tests ---


class TestResourcesModule:
    """Tests for _core/resources/__init__.py and _io/resources.py."""

    def test_resources_loaded(self) -> None:
        """At least one resource is loaded from the insights group."""
        resources = load_all_resources()
        assert len(resources) > 0

    def test_all_entries_are_resource_entry(self) -> None:
        resources = load_all_resources()
        for entry in resources:
            assert isinstance(entry, ResourceEntry)

    def test_entry_fields_populated(self) -> None:
        resources = load_all_resources()
        for entry in resources:
            assert entry.group, "group must not be empty"
            assert entry.name, "name must not be empty"
            assert entry.title, "title must not be empty"
            assert entry.description, "description must not be empty"
            assert entry.uri, "uri must not be empty"
            assert entry.content, "content must not be empty"

    def test_uri_format(self) -> None:
        """URIs follow the group:name scheme."""
        resources = load_all_resources()
        for entry in resources:
            assert ":" in entry.uri
            group, name = entry.uri.split(":", 1)
            assert group == entry.group
            assert name == entry.name

    def test_expected_insights(self) -> None:
        """Expected insight documents are present."""
        resources = load_all_resources()
        uris = {e.uri for e in resources}
        assert "insights:service-targeting" in uris
        assert "insights:entity-ids" in uris
        assert "insights:selectors" in uris

    def test_read_resource_found(self) -> None:
        resources = load_all_resources()
        entry = read_resource(resources, "insights:service-targeting")
        assert entry is not None
        assert entry.name == "service-targeting"
        assert "target" in entry.content.lower()

    def test_read_resource_not_found(self) -> None:
        resources = load_all_resources()
        entry = read_resource(resources, "nonexistent:resource")
        assert entry is None

    def test_content_is_markdown(self) -> None:
        """Resource content starts with a markdown heading."""
        resources = load_all_resources()
        for entry in resources:
            assert entry.content.startswith("#")


# --- Resource type serialization tests ---


class TestSerializeResource:
    """Tests for resource wire format serialization."""

    def test_full_resource(self) -> None:
        resource = Resource(
            uri="insights:test",
            name="test",
            description="A test resource",
            mime_type="text/markdown",
        )
        result = serialize_resource(resource)
        assert result == {
            "uri": "insights:test",
            "name": "test",
            "description": "A test resource",
            "mimeType": "text/markdown",
        }

    def test_minimal_resource(self) -> None:
        resource = Resource(uri="test:minimal", name="minimal")
        result = serialize_resource(resource)
        assert result == {"uri": "test:minimal", "name": "minimal"}
        assert "description" not in result
        assert "mimeType" not in result

    def test_resource_contents(self) -> None:
        contents = ResourceContents(
            uri="insights:test",
            text="# Test\n\nContent here.",
            mime_type="text/markdown",
        )
        result = serialize_resource_contents(contents)
        assert result == {
            "uri": "insights:test",
            "text": "# Test\n\nContent here.",
            "mimeType": "text/markdown",
        }

    def test_resource_contents_no_mime(self) -> None:
        contents = ResourceContents(uri="test:x", text="plain text")
        result = serialize_resource_contents(contents)
        assert result == {"uri": "test:x", "text": "plain text"}
        assert "mimeType" not in result


# --- Resource response builder tests ---


class TestBuildResourceResponses:
    """Tests for resource response builders."""

    def test_resource_list_response(self) -> None:
        resources = [
            Resource(
                uri="insights:a",
                name="a",
                description="Desc A",
                mime_type="text/markdown",
            ),
            Resource(uri="insights:b", name="b"),
        ]
        result = build_resource_list_response(42, resources)
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 42
        inner = result["result"]
        assert isinstance(inner, dict)
        assert len(inner["resources"]) == 2

    def test_resource_read_response(self) -> None:
        contents = [
            ResourceContents(
                uri="insights:test", text="# Content", mime_type="text/markdown"
            )
        ]
        result = build_resource_read_response(7, contents)
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 7
        inner = result["result"]
        assert isinstance(inner, dict)
        assert len(inner["contents"]) == 1
        assert inner["contents"][0]["text"] == "# Content"


# --- Session dispatch tests ---


def _make_active_session() -> tuple[MCPServerSession, GroupRegistry]:
    """Create a session in ACTIVE state."""
    info = ServerInfo(name="test", version="1.0")
    resources = load_all_resources()
    session = MCPServerSession(info, ServerCapabilities(), resources)
    registry = GroupRegistry()

    session.handle(
        JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        ),
        registry,
        user_id=None,
    )
    session.handle(
        JsonRpcNotification(method="notifications/initialized", params={}),
        registry,
        user_id=None,
    )
    assert session.state == SessionState.ACTIVE
    return session, registry


class TestResourcesListDispatch:
    """Tests for resources/list via session dispatch."""

    def test_returns_resources(self) -> None:
        session, registry = _make_active_session()
        msg = JsonRpcRequest(id=2, method="resources/list", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)

        inner = result.body["result"]
        assert isinstance(inner, dict)
        resources = inner["resources"]
        assert isinstance(resources, list)

        uris = {r["uri"] for r in resources}
        assert "insights:service-targeting" in uris
        assert "insights:entity-ids" in uris
        assert "insights:selectors" in uris

    def test_resources_have_mime_type(self) -> None:
        session, registry = _make_active_session()
        msg = JsonRpcRequest(id=2, method="resources/list", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)

        inner = result.body["result"]
        assert isinstance(inner, dict)
        for resource in inner["resources"]:
            assert isinstance(resource, dict)
            assert resource["mimeType"] == "text/markdown"


class TestResourcesReadDispatch:
    """Tests for resources/read via session dispatch."""

    def test_read_existing_resource(self) -> None:
        session, registry = _make_active_session()
        msg = JsonRpcRequest(
            id=3, method="resources/read", params={"uri": "insights:entity-ids"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)

        inner = result.body["result"]
        assert isinstance(inner, dict)
        contents = inner["contents"]
        assert isinstance(contents, list)
        assert len(contents) == 1
        assert "entity" in contents[0]["text"].lower()
        assert contents[0]["uri"] == "insights:entity-ids"
        assert contents[0]["mimeType"] == "text/markdown"

    def test_read_missing_resource(self) -> None:
        session, registry = _make_active_session()
        msg = JsonRpcRequest(
            id=3, method="resources/read", params={"uri": "nonexistent:foo"}
        )
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_PARAMS
        assert "not found" in result.message.lower()

    def test_read_missing_uri_param(self) -> None:
        session, registry = _make_active_session()
        msg = JsonRpcRequest(id=3, method="resources/read", params={})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_PARAMS

    def test_read_uri_wrong_type(self) -> None:
        session, registry = _make_active_session()
        msg = JsonRpcRequest(id=3, method="resources/read", params={"uri": 123})
        result = session.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionError)
        assert result.code == INVALID_PARAMS


# --- Tool-based access tests ---


class TestListResourcesTool:
    """Tests for the list_resources tool."""

    def test_returns_resource_list(self) -> None:
        registry = GroupRegistry()
        resources = load_all_resources()
        result = call_tool(
            "list_resources", {}, registry, user_id=None, resources=resources
        )
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "insights:service-targeting" in text
        assert "insights:entity-ids" in text
        assert "insights:selectors" in text


class TestReadResourceTool:
    """Tests for the read_resource tool."""

    def test_read_existing(self) -> None:
        registry = GroupRegistry()
        resources = load_all_resources()
        result = call_tool(
            "read_resource",
            {"uri": "insights:selectors"},
            registry,
            user_id=None,
            resources=resources,
        )
        assert isinstance(result, Done)
        assert not result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "selector" in text.lower()

    def test_read_nonexistent(self) -> None:
        registry = GroupRegistry()
        resources = load_all_resources()
        result = call_tool(
            "read_resource",
            {"uri": "nonexistent:thing"},
            registry,
            user_id=None,
            resources=resources,
        )
        assert isinstance(result, Done)
        assert result.result.is_error
        text = result.result.content[0].text  # type: ignore[union-attr]
        assert "not found" in text.lower()
        assert "insights:" in text  # Lists available URIs

    def test_missing_uri_param(self) -> None:
        registry = GroupRegistry()
        resources = load_all_resources()
        result = call_tool(
            "read_resource", {}, registry, user_id=None, resources=resources
        )
        assert isinstance(result, Done)
        assert result.result.is_error

    def test_uri_wrong_type(self) -> None:
        registry = GroupRegistry()
        resources = load_all_resources()
        result = call_tool(
            "read_resource", {"uri": 42}, registry, user_id=None, resources=resources
        )
        assert isinstance(result, Done)
        assert result.result.is_error


# --- Capabilities advertisement tests ---


class TestCapabilitiesIncludeResources:
    """Tests that the server advertises resource support."""

    def test_initialize_response_includes_resources(self) -> None:
        """The initialize response advertises resources capability."""
        _session, registry = _make_active_session()
        # Re-create session to inspect init response
        info = ServerInfo(name="test", version="1.0")
        resources = load_all_resources()
        session2 = MCPServerSession(info, ServerCapabilities(), resources)
        msg = JsonRpcRequest(
            id=1, method="initialize", params={"protocolVersion": "2025-03-26"}
        )
        result = session2.handle(msg, registry, user_id=None)
        assert isinstance(result, SessionResponse)
        inner = result.body["result"]
        assert isinstance(inner, dict)
        capabilities = inner["capabilities"]
        assert isinstance(capabilities, dict)
        assert "resources" in capabilities
