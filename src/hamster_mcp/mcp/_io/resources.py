"""Resource loading from package data.

Reads resource markdown files from the ``hamster_mcp.mcp._core.resources``
package and returns :class:`ResourceEntry` objects.  This is the I/O
boundary for static resources --- the ``_core`` layer contains only the
pure types and parsing logic.
"""

from __future__ import annotations

from importlib import resources as _resources

from hamster_mcp.mcp._core.resources import GROUPS, ResourceEntry, parse_index


def load_group(group_name: str) -> list[ResourceEntry]:
    """Load all resources from a single group subdirectory.

    Reads ``index.md`` and each referenced markdown file from the
    ``hamster_mcp.mcp._core.resources`` package.
    """
    group_dir = _resources.files("hamster_mcp.mcp._core.resources").joinpath(group_name)

    index_file = group_dir.joinpath("index.md")
    index_text = index_file.read_text(encoding="utf-8")

    entries: list[ResourceEntry] = []
    for title, filename, description in parse_index(index_text):
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


def load_all_resources() -> tuple[ResourceEntry, ...]:
    """Load all resource entries from all groups.

    Performs file I/O via ``importlib.resources``.  Call from the I/O or
    component layer, never from ``_core``.
    """
    return tuple(entry for group in GROUPS for entry in load_group(group))
