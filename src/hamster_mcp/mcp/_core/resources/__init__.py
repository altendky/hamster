"""Static MCP resource types and pure parsing logic.

Defines :class:`ResourceEntry` and the index-file parser.  All functions
in this module are pure --- they perform no I/O and reference no global
state.  Resource *loading* (file reads) lives in
``hamster_mcp.mcp._io.resources``.

Index files use the same format as onshape-mcp:

    - [Title](filename.md) --- Description text

The URI scheme is ``{group}:{name}`` (e.g. ``insights:entity-ids``).
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# --- Types ---


@dataclass(frozen=True, slots=True)
class ResourceEntry:
    """A single static resource document."""

    group: str
    name: str
    title: str
    description: str
    uri: str
    content: str


# --- Index parsing ---

# Matches:  - [Title](filename.md) --- Description
_INDEX_RE = re.compile(
    r"^-\s+\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s+---\s+(?P<desc>.+)$",
)


def parse_index(text: str) -> list[tuple[str, str, str]]:
    """Parse an index.md into (title, filename, description) triples."""
    entries: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        m = _INDEX_RE.match(line.strip())
        if m:
            entries.append((m.group("title"), m.group("file"), m.group("desc")))
    return entries


# --- Constants ---

# Resource groups to load.  Add new subdirectories here.
GROUPS: tuple[str, ...] = ("insights",)


# --- Pure lookup ---


def read_resource(
    resources: tuple[ResourceEntry, ...], uri: str
) -> ResourceEntry | None:
    """Look up a resource by URI.  Returns None if not found."""
    for entry in resources:
        if entry.uri == uri:
            return entry
    return None
