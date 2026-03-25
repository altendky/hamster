"""Static MCP resource documents.

Loads insight markdown files from the package at import time and exposes
them via list_resources() and read_resource().  All data is static and
embedded in the package --- no I/O at call time.

Index files use the same format as onshape-mcp:

    - [Title](filename.md) --- Description text

The URI scheme is ``{group}:{name}`` (e.g. ``insights:entity-ids``).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources as _resources
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


def _parse_index(text: str) -> list[tuple[str, str, str]]:
    """Parse an index.md into (title, filename, description) triples."""
    entries: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        m = _INDEX_RE.match(line.strip())
        if m:
            entries.append((m.group("title"), m.group("file"), m.group("desc")))
    return entries


# --- Loading ---


def _load_group(group_name: str) -> list[ResourceEntry]:
    """Load all resources from a single group subdirectory."""
    group_dir = _resources.files(__package__).joinpath(group_name)

    index_file = group_dir.joinpath("index.md")
    index_text = index_file.read_text(encoding="utf-8")

    entries: list[ResourceEntry] = []
    for title, filename, description in _parse_index(index_text):
        # Derive the name from the filename (strip .md)
        if not filename.endswith(".md"):
            continue
        name = filename.removesuffix(".md")

        content_file = group_dir.joinpath(filename)
        content = content_file.read_text(encoding="utf-8")

        entries.append(
            ResourceEntry(
                group=group_name,
                name=name,
                title=title,
                description=description,
                uri=f"{group_name}:{name}",
                content=content,
            )
        )
    return entries


# --- Module-level constants ---

# Resource groups to load.  Add new subdirectories here.
_GROUPS = ("insights",)

RESOURCES: tuple[ResourceEntry, ...] = tuple(
    entry for group in _GROUPS for entry in _load_group(group)
)


# --- Public API ---


def list_resources() -> tuple[ResourceEntry, ...]:
    """Return all available resource entries."""
    return RESOURCES


def read_resource(uri: str) -> ResourceEntry | None:
    """Look up a resource by URI.  Returns None if not found."""
    for entry in RESOURCES:
        if entry.uri == uri:
            return entry
    return None
