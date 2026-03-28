#!/usr/bin/env python3
"""Generate brand icons from source SVG line art.

This script takes a source SVG containing black stroke-based line art organized
into layers and generates Home Assistant brand icons with amber fill and halo
effects.

Layer requirements:
    - "boundary": Face outline — gets amber halo + amber fill
    - "spots": Spot ellipses — gets cream fill clipped to boundary
    - "whiskers": Whisker lines — gets amber halo only
    - "nose": Nose curve — gets pink fill (forms closed region when mirrored)
    - "mouth": Mouth curves — gets pink fill (forms closed region when mirrored)
    - "eyes": Eye ellipse — gets black fill + black stroke
    - "eye highlights": Highlight shapes — passthrough (mirrored, preserved orientation)

Requirements:
    - cairosvg (Python package) — for PNG export

Usage:
    python brand/generate.py
    # or via mise:
    mise run generate-icons
"""

from __future__ import annotations

import copy
from pathlib import Path
import re
import xml.etree.ElementTree as ET

# Brand colors
AMBER = "#c87f43"
BLACK = "#000000"
WHITE = "#ffffff"
PINK = "#f09b9b"  # Nose and mouth fill
CREAM = "#e6e2cf"  # Spot fill

# Halo stroke width multiplier
HALO_MULTIPLIER = 3

# Output sizes for PNG export
ICON_SIZES = [256, 512]

# Margin at 256px scale (pixels)
MARGIN = 4

# Mirror transform (horizontal flip around x=128)
MIRROR_TRANSFORM = "matrix(-1,0,0,1,256,0)"

# Layer configuration: which processing each layer gets
# "fill" can be False or a color string
# "clip_to" specifies a layer whose fill path is used as a clip mask
# "mirror" defaults to True; set to False for layers already covering full canvas
# "passthrough" means render as-is (just mirror if needed), no fill/stroke processing
LAYER_CONFIG = {
    "boundary": {"halo": True, "fill": AMBER},
    "spots": {
        "halo": False,
        "fill": False,
        "clip_to": "boundary",
        "color": CREAM,
        "mirror": False,  # Ellipses already cover full face
    },
    "whiskers": {"halo": True, "fill": False},
    "nose": {"halo": False, "fill": PINK},
    "mouth": {"halo": False, "fill": PINK},
    "eyes": {"halo": False, "fill": BLACK},
    "eye highlights": {
        "halo": False,
        "fill": False,
        "passthrough": True,
        # Mirror to other eye but keep same orientation (double mirror)
        # Disabled for now - highlights done manually in source SVG
        "mirror_preserve_orientation": False,
        "mirror": False,  # Don't mirror at all - source has both eyes' highlights
    },
}

# Paths
BRAND_DIR = Path(__file__).parent
SOURCE_SVG = BRAND_DIR / "source.svg"
OUTPUT_DIR = BRAND_DIR.parent / "custom_components" / "hamster" / "brand"

# SVG namespaces
SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"


# ---------------------------------------------------------------------------
# SVG path parsing and manipulation
# ---------------------------------------------------------------------------

# A "segment" is (command, [(x, y), ...]) where all coordinates are absolute.
PathSegment = tuple[str, list[tuple[float, float]]]


def _tokenize_path_d(d: str) -> list[str]:
    """Split an SVG path 'd' attribute into command letters and number tokens."""
    # Insert space before every command letter (but not inside numbers like 1e-5)
    # and before minus signs that start a new number.
    tokens: list[str] = []
    buf = ""
    for ch in d:
        if ch in "MmLlCcSsQqTtAaHhVvZz":
            if buf.strip():
                tokens.append(buf.strip())
            tokens.append(ch)
            buf = ""
        elif ch in " ,\t\n\r":
            if buf.strip():
                tokens.append(buf.strip())
            buf = ""
        elif ch == "-" and buf.strip() and buf.strip()[-1] not in "eE":
            # Minus sign starts a new number (unless after exponent)
            if buf.strip():
                tokens.append(buf.strip())
            buf = ch
        else:
            buf += ch
    if buf.strip():
        tokens.append(buf.strip())
    return tokens


def _parse_path_to_absolute(d: str) -> list[PathSegment]:
    """Parse an SVG path 'd' string into a list of absolute-coordinate segments.

    Only handles M/m, L/l, C/c commands (and Z/z) which are what the boundary
    layer uses.  Returns segments as (command, points) where command is one of
    'M', 'L', 'C', 'Z' and points are absolute (x, y) tuples.
    """
    tokens = _tokenize_path_d(d)
    segments: list[PathSegment] = []
    cx, cy = 0.0, 0.0  # current point
    i = 0

    while i < len(tokens):
        cmd = tokens[i]
        i += 1

        if cmd in "Zz":
            segments.append(("Z", []))
            continue

        # Collect numbers for this command
        nums: list[float] = []
        while i < len(tokens) and tokens[i] not in "MmLlCcSsQqTtAaHhVvZz":
            nums.append(float(tokens[i]))
            i += 1

        if cmd == "M":
            # Absolute moveto (first pair is moveto, subsequent pairs are lineto)
            j = 0
            while j < len(nums):
                cx, cy = nums[j], nums[j + 1]
                segments.append(("M" if j == 0 else "L", [(cx, cy)]))
                j += 2
        elif cmd == "m":
            j = 0
            while j < len(nums):
                cx += nums[j]
                cy += nums[j + 1]
                segments.append(("M" if j == 0 else "L", [(cx, cy)]))
                j += 2
        elif cmd == "L":
            j = 0
            while j < len(nums):
                cx, cy = nums[j], nums[j + 1]
                segments.append(("L", [(cx, cy)]))
                j += 2
        elif cmd == "l":
            j = 0
            while j < len(nums):
                cx += nums[j]
                cy += nums[j + 1]
                segments.append(("L", [(cx, cy)]))
                j += 2
        elif cmd == "C":
            j = 0
            while j < len(nums):
                p1 = (nums[j], nums[j + 1])
                p2 = (nums[j + 2], nums[j + 3])
                p3 = (nums[j + 4], nums[j + 5])
                segments.append(("C", [p1, p2, p3]))
                cx, cy = p3
                j += 6
        elif cmd == "c":
            j = 0
            while j < len(nums):
                p1 = (cx + nums[j], cy + nums[j + 1])
                p2 = (cx + nums[j + 2], cy + nums[j + 3])
                p3 = (cx + nums[j + 4], cy + nums[j + 5])
                segments.append(("C", [p1, p2, p3]))
                cx, cy = p3
                j += 6
        else:
            msg = f"Unsupported SVG path command: {cmd}"
            raise ValueError(msg)

    return segments


def _segments_endpoint(segments: list[PathSegment]) -> tuple[float, float]:
    """Return the endpoint of the last drawing segment."""
    for seg in reversed(segments):
        cmd, pts = seg
        if cmd == "Z":
            continue
        if pts:
            return pts[-1]
    msg = "No drawable segments found"
    raise ValueError(msg)


def _segments_startpoint(segments: list[PathSegment]) -> tuple[float, float]:
    """Return the start point of the first segment (should be M)."""
    for seg in segments:
        cmd, pts = seg
        if cmd == "M" and pts:
            return pts[0]
    msg = "No moveto segment found"
    raise ValueError(msg)


def _reverse_segments(segments: list[PathSegment]) -> list[PathSegment]:
    """Reverse the drawing direction of a list of path segments.

    The input must start with an M segment and contain only M, L, C segments
    (no Z).  Returns a new segment list that draws the same shape in reverse,
    starting with an M at the old endpoint.
    """
    # Build list of (segment, start_point) working forwards
    drawing: list[tuple[str, list[tuple[float, float]], tuple[float, float]]] = []
    current = _segments_startpoint(segments)
    for cmd, pts in segments:
        if cmd == "M":
            current = pts[0]
            continue
        drawing.append((cmd, pts, current))
        current = pts[-1]

    # Walk backwards
    result: list[PathSegment] = [("M", [current])]  # start at old endpoint
    for cmd, pts, start in reversed(drawing):
        if cmd == "L":
            result.append(("L", [start]))
        elif cmd == "C":
            # C has [cp1, cp2, end] — reversed becomes [cp2, cp1, old_start]
            cp1, cp2, _end = pts
            result.append(("C", [cp2, cp1, start]))
        else:
            msg = f"Cannot reverse command: {cmd}"
            raise ValueError(msg)

    return result


def _mirror_x_segments(
    segments: list[PathSegment], axis: float = 256.0
) -> list[PathSegment]:
    """Mirror segments horizontally around x = axis/2 (i.e., x' = axis - x)."""
    result: list[PathSegment] = []
    for cmd, pts in segments:
        mirrored_pts = [(axis - x, y) for x, y in pts]
        result.append((cmd, mirrored_pts))
    return result


def _segments_to_d(segments: list[PathSegment]) -> str:
    """Convert absolute-coordinate segments back to an SVG path 'd' string."""
    parts: list[str] = []
    for cmd, pts in segments:
        if cmd == "Z":
            parts.append("Z")
        elif cmd == "M":
            x, y = pts[0]
            parts.append(f"M {x},{y}")
        elif cmd == "L":
            x, y = pts[0]
            parts.append(f"L {x},{y}")
        elif cmd == "C":
            coords = " ".join(f"{x},{y}" for x, y in pts)
            parts.append(f"C {coords}")
    return " ".join(parts)


def _extract_path_d(element: ET.Element) -> str:
    """Get the 'd' attribute from a path element."""
    d = element.get("d")
    if d is None:
        msg = f"Element {element.get('id', '?')} has no 'd' attribute"
        raise ValueError(msg)
    return d


def create_boundary_center_path(layer: ET.Element) -> str:
    """Build a closed path tracing the center of the boundary strokes.

    Takes the boundary layer's paths, parses them into absolute coordinates,
    then assembles a closed contour by connecting them (with line segments
    where gaps exist) and mirroring to form the complete face outline.

    The ordering of paths in the source layer matters:
        - path2344 (ear/head curve): connects ear tip to forehead area
        - path3544 (cheek curve): connects cheek to chin
        - path4458 (forehead connector): connects forehead to center line

    The closed contour traces:
        path3 (fwd) → path1 (rev) → path2 (fwd) →
        mirror-path2 (rev) → mirror-path1 (fwd) → mirror-path3 (rev) → Z

    Gaps between paths are bridged with straight line segments.

    Returns:
        An SVG path 'd' attribute for the closed center-line boundary.
    """
    # Extract path elements from the layer
    path_elements = [
        elem
        for elem in layer.iter()
        if elem.tag == f"{{{SVG_NS}}}path" or elem.tag == "path"
    ]

    if len(path_elements) != 3:
        msg = (
            f"Expected 3 boundary paths, found {len(path_elements)}. "
            f"IDs: {[e.get('id', '?') for e in path_elements]}"
        )
        raise ValueError(msg)

    # Parse all three paths to absolute coordinates
    # Order in source: path2344 (ear), path3544 (cheek), path4458 (forehead)
    parsed = [_parse_path_to_absolute(_extract_path_d(e)) for e in path_elements]

    ear_segs = parsed[0]  # path2344: ear/head curve
    cheek_segs = parsed[1]  # path3544: cheek curve
    forehead_segs = parsed[2]  # path4458: forehead connector

    # Build the closed contour.
    #
    # Working order (going clockwise around the left side of the face,
    # then the mirrored right side):
    #
    #   forehead reversed:  (128, ~52) → (~88, ~60)
    #   line to ear end:    → (~98, ~52)
    #   ear reversed:       → (~55, ~132)
    #   line to cheek start: → (~64, ~124)
    #   cheek forward:      → (128, ~251)
    #   --- mirror side ---
    #   mirror cheek rev:   → (~192, ~124)
    #   line to mirror ear start: → (~201, ~132)
    #   mirror ear fwd:     → (~158, ~52)
    #   line to mirror forehead start: → (~168, ~60)
    #   mirror forehead fwd: → (~128, ~52)
    #   Z (close)

    forehead_rev = _reverse_segments(forehead_segs)
    ear_rev = _reverse_segments(ear_segs)

    mirror_cheek_rev = _mirror_x_segments(_reverse_segments(cheek_segs))
    mirror_ear_fwd = _mirror_x_segments(ear_segs)
    mirror_forehead_fwd = _mirror_x_segments(forehead_segs)

    # Assemble: start with the M from forehead_rev, then append the rest
    contour: list[PathSegment] = []

    # 1. Forehead reversed (starts with M at ~128, ~52)
    contour.extend(forehead_rev)

    # 2. Line bridge to ear end, then ear reversed
    ear_rev_start = _segments_startpoint(ear_rev)
    contour.append(("L", [ear_rev_start]))
    contour.extend(ear_rev[1:])  # skip M

    # 3. Line bridge to cheek start, then cheek forward
    cheek_start = _segments_startpoint(cheek_segs)
    contour.append(("L", [cheek_start]))
    contour.extend(cheek_segs[1:])  # skip M

    # 4. Cross to mirror side: mirror cheek reversed
    mirror_cheek_rev_start = _segments_startpoint(mirror_cheek_rev)
    contour.append(("L", [mirror_cheek_rev_start]))
    contour.extend(mirror_cheek_rev[1:])  # skip M

    # 5. Line bridge to mirror ear start, then mirror ear forward
    mirror_ear_start = _segments_startpoint(mirror_ear_fwd)
    contour.append(("L", [mirror_ear_start]))
    contour.extend(mirror_ear_fwd[1:])  # skip M

    # 6. Line bridge to mirror forehead start, then mirror forehead forward
    mirror_forehead_start = _segments_startpoint(mirror_forehead_fwd)
    contour.append(("L", [mirror_forehead_start]))
    contour.extend(mirror_forehead_fwd[1:])  # skip M

    # 7. Close
    contour.append(("Z", []))

    return _segments_to_d(contour)


def create_mirrored_center_path(layer: ET.Element) -> str:
    """Build a closed path from a layer's strokes and their mirror.

    For layers where every path starts or ends on the center line (x=128),
    this creates a closed contour by tracing the original paths and their
    mirrored counterparts.

    Single-path layers (e.g., nose):
        The path runs from center to center on the left side.  The mirror
        runs center to center on the right.  Together: original forward →
        mirror reversed → Z.

    Multi-path layers (e.g., mouth):
        Paths are sorted by their start-y coordinate (topmost first).
        The contour traces: path1 reversed → line → path2 forward →
        mirror-path2 reversed → line → mirror-path1 forward → Z.

    Returns:
        An SVG path 'd' attribute for the closed center-line shape.
    """
    path_elements = [
        elem
        for elem in layer.iter()
        if elem.tag == f"{{{SVG_NS}}}path" or elem.tag == "path"
    ]

    if not path_elements:
        msg = "No path elements found in layer"
        raise ValueError(msg)

    parsed = [_parse_path_to_absolute(_extract_path_d(e)) for e in path_elements]

    if len(parsed) == 1:
        # Single path (e.g., nose): fwd + mirror reversed + Z
        segs = parsed[0]
        mirror_rev = _mirror_x_segments(_reverse_segments(segs))

        contour: list[PathSegment] = []
        contour.extend(segs)
        contour.extend(mirror_rev[1:])  # skip M
        contour.append(("Z", []))
        return _segments_to_d(contour)

    # Multi-path: sort by start-y so we have a consistent winding order.
    # For the mouth: path1 ends at top (186), path2 ends at bottom (227).
    # We want: path1 reversed (top→left) → path2 forward (left→bottom)
    #        → mirror-path2 reversed (bottom→right) → mirror-path1 forward
    #          (right→top) → Z
    # Sort paths so the one ending at the highest y (smallest y) is first.
    parsed.sort(key=lambda s: _segments_endpoint(s)[1])

    contour = []

    # Left side: first path reversed, then bridge + subsequent paths forward
    first_rev = _reverse_segments(parsed[0])
    contour.extend(first_rev)

    for i in range(1, len(parsed)):
        seg_start = _segments_startpoint(parsed[i])
        contour.append(("L", [seg_start]))
        contour.extend(parsed[i][1:])  # skip M

    # Right side (mirror): last path reversed, then bridge + earlier paths forward
    for i in range(len(parsed) - 1, -1, -1):
        if i == len(parsed) - 1:
            mirror_last_rev = _mirror_x_segments(_reverse_segments(parsed[i]))
            mirror_start = _segments_startpoint(mirror_last_rev)
            contour.append(("L", [mirror_start]))
            contour.extend(mirror_last_rev[1:])  # skip M
        else:
            mirror_fwd = _mirror_x_segments(parsed[i])
            mirror_start = _segments_startpoint(mirror_fwd)
            contour.append(("L", [mirror_start]))
            contour.extend(mirror_fwd[1:])  # skip M

    contour.append(("Z", []))
    return _segments_to_d(contour)


def parse_style_attribute(style: str) -> dict[str, str]:
    """Parse a CSS style attribute into a dictionary."""
    result = {}
    for part in style.split(";"):
        part = part.strip()
        if ":" in part:
            key, value = part.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def style_dict_to_string(style_dict: dict[str, str]) -> str:
    """Convert a style dictionary back to a CSS style string."""
    return ";".join(f"{k}:{v}" for k, v in style_dict.items())


def get_stroke_width(element: ET.Element) -> float | None:
    """Extract stroke-width from an element, checking both attribute and style."""
    # Check direct attribute first
    stroke_width = element.get("stroke-width")
    if stroke_width is not None:
        return float(stroke_width)

    # Check style attribute
    style = element.get("style")
    if style:
        style_dict = parse_style_attribute(style)
        if "stroke-width" in style_dict:
            width_str = style_dict["stroke-width"]
            match = re.match(r"([\d.]+)", width_str)
            if match:
                return float(match.group(1))

    return None


def has_stroke(element: ET.Element) -> bool:
    """Check if an element has a stroke defined."""
    # Check direct attribute
    if element.get("stroke") and element.get("stroke") != "none":
        return True

    # Check style attribute
    style = element.get("style")
    if style:
        style_dict = parse_style_attribute(style)
        stroke = style_dict.get("stroke", "")
        if stroke and stroke != "none":
            return True

    return False


def find_layer_by_label(root: ET.Element, label: str) -> ET.Element:
    """Find a layer group by its inkscape:label attribute.

    Args:
        root: SVG root element.
        label: The inkscape:label value to search for.

    Returns:
        The layer group element.

    Raises:
        ValueError: If the layer is not found.
    """
    for elem in root.iter():
        is_layer = elem.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
        has_label = elem.get(f"{{{INKSCAPE_NS}}}label") == label
        if is_layer and has_label:
            return elem

    msg = f"Layer '{label}' not found in source SVG"
    raise ValueError(msg)


def get_layer_stroke_width(layer: ET.Element) -> float | None:
    """Get the stroke width used in a layer (assumes uniform width)."""
    for elem in layer.iter():
        if has_stroke(elem):
            width = get_stroke_width(elem)
            if width is not None:
                return width
    return None


def deep_copy_element(elem: ET.Element) -> ET.Element:
    """Create a deep copy of an element and all its children."""
    return copy.deepcopy(elem)


def modify_stroke_style(
    elem: ET.Element,
    stroke: str | None = None,
    stroke_width: float | None = None,
    fill: str | None = None,
    add_round_caps: bool = False,
) -> None:
    """Modify stroke/fill style attributes on an element in place.

    Only modifies elements that already have a stroke.
    """
    if not has_stroke(elem):
        return

    style = elem.get("style")
    if style:
        style_dict = parse_style_attribute(style)
        if stroke is not None:
            style_dict["stroke"] = stroke
        if stroke_width is not None:
            style_dict["stroke-width"] = str(stroke_width)
        if fill is not None:
            style_dict["fill"] = fill
        if add_round_caps:
            style_dict["stroke-linecap"] = "round"
            style_dict["stroke-linejoin"] = "round"
        elem.set("style", style_dict_to_string(style_dict))
    else:
        # Handle direct attributes
        if stroke is not None:
            elem.set("stroke", stroke)
        if stroke_width is not None:
            elem.set("stroke-width", str(stroke_width))
        if fill is not None:
            elem.set("fill", fill)


def modify_layer_strokes(
    layer: ET.Element,
    stroke: str | None = None,
    stroke_width: float | None = None,
    fill: str | None = None,
    add_round_caps: bool = False,
) -> None:
    """Modify stroke styles on all elements in a layer."""
    for elem in layer.iter():
        modify_stroke_style(elem, stroke, stroke_width, fill, add_round_caps)


def create_mirrored_group(elem: ET.Element) -> ET.Element:
    """Wrap an element in a group with a mirror transform."""
    group = ET.Element(f"{{{SVG_NS}}}g", {"transform": MIRROR_TRANSFORM})
    group.append(deep_copy_element(elem))
    return group


def create_layer_with_mirror(
    layer: ET.Element,
    stroke: str | None = None,
    stroke_width: float | None = None,
    fill: str | None = None,
    add_round_caps: bool = False,
    group_id: str | None = None,
) -> ET.Element:
    """Create a group containing a layer's content plus its mirror.

    Args:
        layer: Source layer element.
        stroke: Override stroke color.
        stroke_width: Override stroke width.
        fill: Override fill color.
        add_round_caps: Add round linecaps/joins.
        group_id: ID for the output group.

    Returns:
        A group element containing original + mirrored content.
    """
    output_group = ET.Element(f"{{{SVG_NS}}}g")
    if group_id:
        output_group.set("id", group_id)

    # Original content
    original = deep_copy_element(layer)
    # Remove layer-specific attributes
    for attr in list(original.attrib.keys()):
        if INKSCAPE_NS in attr:
            del original.attrib[attr]
    modify_layer_strokes(original, stroke, stroke_width, fill, add_round_caps)
    output_group.append(original)

    # Mirrored content
    mirrored = create_mirrored_group(layer)
    modify_layer_strokes(mirrored, stroke, stroke_width, fill, add_round_caps)
    output_group.append(mirrored)

    return output_group


def create_clipped_layer(
    layer: ET.Element,
    clip_path_id: str,
    fill_color: str,
    group_id: str,
    *,
    mirror: bool = True,
) -> ET.Element:
    """Create a layer's content with a clip-path applied.

    Args:
        layer: The layer element containing shapes to clip.
        clip_path_id: ID of the clipPath to apply.
        fill_color: Fill color for the shapes.
        group_id: ID for the output group.
        mirror: If True, include mirrored copy of shapes.

    Returns:
        A group element containing the clipped shapes.
    """
    output_group = ET.Element(
        f"{{{SVG_NS}}}g",
        {
            "id": group_id,
            "clip-path": f"url(#{clip_path_id})",
        },
    )

    # Add original shapes with updated fill
    for child in layer:
        elem = deep_copy_element(child)
        # Update style to set fill color and remove stroke
        style = elem.get("style", "")
        style_dict = parse_style_attribute(style) if style else {}
        style_dict["fill"] = fill_color
        style_dict["stroke"] = "none"
        elem.set("style", style_dict_to_string(style_dict))
        output_group.append(elem)

    # Add mirrored shapes if requested
    if mirror:
        mirror_group = ET.Element(f"{{{SVG_NS}}}g", {"transform": MIRROR_TRANSFORM})
        for child in layer:
            elem = deep_copy_element(child)
            style = elem.get("style", "")
            style_dict = parse_style_attribute(style) if style else {}
            style_dict["fill"] = fill_color
            style_dict["stroke"] = "none"
            elem.set("style", style_dict_to_string(style_dict))
            mirror_group.append(elem)
        output_group.append(mirror_group)

    return output_group


def parse_viewbox(root: ET.Element) -> tuple[float, float, float, float]:
    """Parse viewBox from SVG root element.

    Returns:
        Tuple of (min_x, min_y, width, height).
    """
    viewbox = root.get("viewBox")
    if viewbox:
        parts = viewbox.split()
        return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))

    # Fall back to width/height attributes
    width = float(root.get("width", "256"))
    height = float(root.get("height", "256"))
    return (0, 0, width, height)


def compute_auto_fit_viewbox(
    original_viewbox: tuple[float, float, float, float],
    stroke_width: float,
    target_size: int = 256,
) -> tuple[float, float, float, float]:
    """Compute viewBox that auto-fits content with halo to target size.

    Args:
        original_viewbox: Original (min_x, min_y, width, height).
        stroke_width: Original stroke width in source units.
        target_size: Target output size in pixels.

    Returns:
        New viewBox as (min_x, min_y, width, height).
    """
    min_x, min_y, width, height = original_viewbox

    # The halo extends by (halo_width - original_width) / 2 on each side
    halo_extension = (HALO_MULTIPLIER - 1) * stroke_width / 2

    # Add margin (scaled from 256px target to source units)
    max_dim = max(width, height)
    margin_in_source = MARGIN * (max_dim / target_size)

    # Total expansion on each side
    expansion = halo_extension + margin_in_source

    # New viewBox with expansion
    new_min_x = min_x - expansion
    new_min_y = min_y - expansion
    new_width = width + 2 * expansion
    new_height = height + 2 * expansion

    # Make it square (use the larger dimension)
    if new_width > new_height:
        diff = new_width - new_height
        new_min_y -= diff / 2
        new_height = new_width
    elif new_height > new_width:
        diff = new_height - new_width
        new_min_x -= diff / 2
        new_width = new_height

    return (new_min_x, new_min_y, new_width, new_height)


def compose_icon_svg(
    source_root: ET.Element,
    layers: dict[str, ET.Element],
    fills: dict[str, str],
    stroke_width: float,
) -> str:
    """Compose the final icon SVG with layers in correct stacking order.

    Args:
        source_root: Original SVG root element.
        layers: Dict mapping layer labels to layer elements.
        fills: Dict mapping layer labels to fill path 'd' attributes.
        stroke_width: Original stroke width.

    Returns:
        Complete SVG document as a string.

    Stacking order (bottom to top):
        1. Boundary halo
        2. Boundary fill
        3. Nose-mouth fill
        4. Whiskers halo
        5. All black strokes (boundary, whiskers, nose-mouth, eyes)
    """
    # Get original viewBox and compute auto-fit viewBox
    original_viewbox = parse_viewbox(source_root)
    new_viewbox = compute_auto_fit_viewbox(original_viewbox, stroke_width)

    # Create new SVG root
    ET.register_namespace("", SVG_NS)
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "viewBox": f"{new_viewbox[0]} {new_viewbox[1]} "
            f"{new_viewbox[2]} {new_viewbox[3]}",
            "width": "256",
            "height": "256",
        },
    )

    # Create defs section with clip paths
    defs = ET.SubElement(root, f"{{{SVG_NS}}}defs")
    if "boundary" in fills:
        clip_path = ET.SubElement(
            defs, f"{{{SVG_NS}}}clipPath", {"id": "boundary-clip"}
        )
        ET.SubElement(clip_path, f"{{{SVG_NS}}}path", {"d": fills["boundary"]})

    halo_width = stroke_width * HALO_MULTIPLIER

    # Stacking order (bottom to top):
    # 1. Boundary halo
    # 2. Boundary fill
    # 3. Whiskers halo (behind spots so cream patches cover whisker halos)
    # 4. Spots fill (clipped to boundary)
    # 5. Nose fill
    # 6. Mouth fill
    # 7. Eyes fill
    # 8. All black strokes
    # 9. Eye reflections (passthrough, above strokes)

    # 1. Boundary halo (bottom)
    boundary_halo = create_layer_with_mirror(
        layers["boundary"],
        stroke=AMBER,
        stroke_width=halo_width,
        fill="none",
        add_round_caps=True,
        group_id="boundary-halo",
    )
    root.append(boundary_halo)

    # 2. Boundary fill
    if "boundary" in fills:
        ET.SubElement(
            root,
            f"{{{SVG_NS}}}path",
            {
                "id": "boundary-fill",
                "d": fills["boundary"],
                "fill": LAYER_CONFIG["boundary"]["fill"],
                "fill-rule": "nonzero",
                "stroke": "none",
            },
        )

    # 3. Whiskers halo (behind spots)
    whiskers_halo = create_layer_with_mirror(
        layers["whiskers"],
        stroke=AMBER,
        stroke_width=halo_width,
        fill="none",
        add_round_caps=True,
        group_id="whiskers-halo",
    )
    root.append(whiskers_halo)

    # 4. Spots fill (clipped to boundary)
    spots_config = LAYER_CONFIG.get("spots", {})
    if spots_config.get("clip_to") and "boundary" in fills:
        spots_group = create_clipped_layer(
            layers["spots"],
            "boundary-clip",
            spots_config.get("color", CREAM),
            "spots-fill",
            mirror=spots_config.get("mirror", True),
        )
        root.append(spots_group)

    # 5. Nose fill
    if "nose" in fills:
        ET.SubElement(
            root,
            f"{{{SVG_NS}}}path",
            {
                "id": "nose-fill",
                "d": fills["nose"],
                "fill": LAYER_CONFIG["nose"]["fill"],
                "stroke": "none",
            },
        )

    # 6. Mouth fill
    if "mouth" in fills:
        ET.SubElement(
            root,
            f"{{{SVG_NS}}}path",
            {
                "id": "mouth-fill",
                "d": fills["mouth"],
                "fill": LAYER_CONFIG["mouth"]["fill"],
                "stroke": "none",
            },
        )

    # 7. Eyes fill - render directly as filled ellipses (not via path conversion)
    eyes_config = LAYER_CONFIG.get("eyes", {})
    if eyes_config.get("fill"):
        eyes_fill_group = ET.Element(f"{{{SVG_NS}}}g", {"id": "eyes-fill"})

        # Add original eye with fill
        for child in layers["eyes"]:
            elem = deep_copy_element(child)
            style = elem.get("style", "")
            style_dict = parse_style_attribute(style) if style else {}
            style_dict["fill"] = eyes_config["fill"]
            style_dict["stroke"] = "none"
            elem.set("style", style_dict_to_string(style_dict))
            eyes_fill_group.append(elem)

        # Add mirrored eye with fill
        mirror_group = ET.Element(f"{{{SVG_NS}}}g", {"transform": MIRROR_TRANSFORM})
        for child in layers["eyes"]:
            elem = deep_copy_element(child)
            style = elem.get("style", "")
            style_dict = parse_style_attribute(style) if style else {}
            style_dict["fill"] = eyes_config["fill"]
            style_dict["stroke"] = "none"
            elem.set("style", style_dict_to_string(style_dict))
            mirror_group.append(elem)
        eyes_fill_group.append(mirror_group)

        root.append(eyes_fill_group)

    # 8. All black strokes (skip clipped and passthrough layers)
    strokes_group = ET.SubElement(root, f"{{{SVG_NS}}}g", {"id": "strokes"})

    for label, config in LAYER_CONFIG.items():
        # Skip clipped/passthrough layers - they don't get stroke processing
        if config.get("clip_to") or config.get("passthrough"):
            continue
        layer_strokes = create_layer_with_mirror(
            layers[label],
            stroke=BLACK,
            stroke_width=stroke_width,
            fill="none",
            add_round_caps=False,
            group_id=f"{label}-strokes",
        )
        strokes_group.append(layer_strokes)

    # 9. Eye highlights (passthrough - render as-is, above strokes)
    eye_highlights_config = LAYER_CONFIG.get("eye highlights", {})
    if eye_highlights_config.get("passthrough") and "eye highlights" in layers:
        eye_highlights_group = ET.Element(f"{{{SVG_NS}}}g", {"id": "eye-highlights"})

        # Add original highlights
        for child in layers["eye highlights"]:
            eye_highlights_group.append(deep_copy_element(child))

        # Add highlights for the other eye (if mirroring enabled)
        should_mirror = eye_highlights_config.get("mirror", True)
        if should_mirror:
            if eye_highlights_config.get("mirror_preserve_orientation"):
                # Translate all highlights by the same amount to move them to the
                # other eye while preserving their relative positions/orientations.
                # Translation = 256 - 2 * eye_center_x (distance between eye centers)
                # Get eye center from the eyes layer (accounting for transform).
                eye_center_x = None
                for child in layers["eyes"]:
                    cx = child.get("cx")
                    if cx is not None:
                        # Apply transform if present
                        transform = child.get("transform", "")
                        if transform.startswith("matrix("):
                            # Parse matrix(a,b,c,d,e,f)
                            values = transform[7:-1].split(",")
                            a, c, e = (
                                float(values[0]),
                                float(values[2]),
                                float(values[4]),
                            )
                            cy_val = child.get("cy")
                            if cy_val is not None:
                                eye_center_x = a * float(cx) + c * float(cy_val) + e
                        else:
                            eye_center_x = float(cx)
                        break

                if eye_center_x is not None:
                    translation = 256 - 2 * eye_center_x
                    translated_group = ET.Element(
                        f"{{{SVG_NS}}}g", {"transform": f"translate({translation}, 0)"}
                    )
                    for child in layers["eye highlights"]:
                        translated_group.append(deep_copy_element(child))
                    eye_highlights_group.append(translated_group)
            else:
                # Simple mirror
                mirror_group = ET.Element(
                    f"{{{SVG_NS}}}g", {"transform": MIRROR_TRANSFORM}
                )
                for child in layers["eye highlights"]:
                    mirror_group.append(deep_copy_element(child))
                eye_highlights_group.append(mirror_group)

        root.append(eye_highlights_group)

    # Convert to string
    return ET.tostring(root, encoding="unicode")


def export_png(svg_path: Path, output_path: Path, size: int) -> None:
    """Export SVG to PNG at specified size.

    Args:
        svg_path: Path to source SVG.
        output_path: Path for output PNG.
        size: Output size in pixels (square).
    """
    import cairosvg

    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(output_path),
        output_width=size,
        output_height=size,
    )


def main() -> None:
    """Generate brand icons from source SVG."""
    print("Generating brand icons...")  # noqa: T201
    print(f"  Source: {SOURCE_SVG}")  # noqa: T201

    # Parse source SVG
    tree = ET.parse(SOURCE_SVG)
    source_root = tree.getroot()

    # Find all required layers (passthrough layers are optional)
    print("  Finding layers...")  # noqa: T201
    layers: dict[str, ET.Element] = {}
    for label, config in LAYER_CONFIG.items():
        try:
            layers[label] = find_layer_by_label(source_root, label)
            print(f"    Found: {label}")  # noqa: T201
        except ValueError:
            if config.get("passthrough"):
                print(f"    Optional layer not found: {label}")  # noqa: T201
            else:
                raise

    # Get stroke width (from boundary layer)
    stroke_width = get_layer_stroke_width(layers["boundary"])
    if stroke_width is None:
        msg = "Could not determine stroke width from boundary layer"
        raise ValueError(msg)
    print(f"  Stroke width: {stroke_width}")  # noqa: T201

    # Generate fills for layers that need them
    # Layers with clip_to use their source shapes directly (clipped via SVG clipPath)
    print("  Generating fills...")  # noqa: T201
    fills: dict[str, str] = {}
    for label, config in LAYER_CONFIG.items():
        fill_config = config.get("fill")
        # Skip layers with no fill or that use clip_to (handled via clipPath in SVG)
        # Also skip eyes - they'll be rendered directly as filled ellipses
        if not fill_config or config.get("clip_to") or label == "eyes":
            continue
        print(f"    {label}...")  # noqa: T201
        if label == "boundary":
            fills[label] = create_boundary_center_path(layers[label])
        else:
            # Nose, mouth — paths start/end on the x=128 center line and
            # form closed shapes when mirrored.
            fills[label] = create_mirrored_center_path(layers[label])
        print(f"    {label}: OK")  # noqa: T201

    # Compose output SVG
    print("  Composing icon SVG...")  # noqa: T201
    icon_svg = compose_icon_svg(source_root, layers, fills, stroke_width)

    # Write outputs to HACS brand directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write icon.svg
    icon_svg_path = OUTPUT_DIR / "icon.svg"
    icon_svg_path.write_text(icon_svg)
    print(f"  Wrote: {icon_svg_path}")  # noqa: T201

    # Export PNGs
    for size in ICON_SIZES:
        png_name = "icon.png" if size == 256 else f"icon@{size // 256}x.png"
        png_path = OUTPUT_DIR / png_name
        export_png(icon_svg_path, png_path, size)
        print(f"  Wrote: {png_path}")  # noqa: T201

    print("Done!")  # noqa: T201


if __name__ == "__main__":
    main()
