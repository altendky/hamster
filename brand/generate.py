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
    - "eyes": Eye ellipse — gets white fill + black stroke

Requirements:
    - Inkscape CLI (`inkscape` in PATH)
    - cairosvg, Pillow (Python packages)

Usage:
    python brand/generate.py
    # or via mise:
    mise run generate-icons
"""

from __future__ import annotations

import copy
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
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
    "eyes": {"halo": False, "fill": WHITE},
}

# Paths
BRAND_DIR = Path(__file__).parent
SOURCE_SVG = BRAND_DIR / "source.svg"
HACS_BRAND_DIR = BRAND_DIR.parent / "custom_components" / "hamster" / "brand"

# SVG namespaces
SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"


def check_inkscape() -> None:
    """Verify Inkscape CLI is available."""
    if shutil.which("inkscape") is None:
        msg = (
            "Inkscape CLI not found in PATH. "
            "Install Inkscape and ensure 'inkscape' is accessible."
        )
        raise RuntimeError(msg)


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


def create_temp_svg_for_layer(
    layer: ET.Element,
    viewbox: str = "0 0 256 256",
    include_mirror: bool = True,
) -> Path:
    """Create a temporary SVG file containing just a layer's content.

    Args:
        layer: The layer element to extract.
        viewbox: The viewBox for the temp SVG.
        include_mirror: If True, include mirrored content.

    Returns:
        Path to the temporary SVG file.
    """
    ET.register_namespace("", SVG_NS)

    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "viewBox": viewbox,
            "width": "256",
            "height": "256",
        },
    )

    # Add original content
    for child in layer:
        root.append(deep_copy_element(child))

    # Add mirrored content
    if include_mirror:
        mirror_group = ET.Element(f"{{{SVG_NS}}}g", {"transform": MIRROR_TRANSFORM})
        for child in layer:
            mirror_group.append(deep_copy_element(child))
        root.append(mirror_group)

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w") as tmp:
        tmp.write(ET.tostring(root, encoding="unicode"))
        return Path(tmp.name)


def extract_outer_paths(path_d: str, count: int = 1) -> str:
    """Extract outer contours from a path with holes.

    The stroke-to-path + union operation creates a path where the first
    subpath(s) are outer boundaries and subsequent subpaths are inner holes.
    This function extracts the specified number of outer boundaries.

    Args:
        path_d: The full path 'd' attribute.
        count: Number of outer contours to extract.

    Returns:
        The 'd' attribute containing only the outer contour(s).
    """
    # Find 'z' or 'Z' commands that close subpaths
    # Extract the first `count` subpaths
    z_count = 0
    for i, char in enumerate(path_d):
        if char in "zZ":
            z_count += 1
            if z_count >= count:
                return path_d[: i + 1]
    return path_d


def create_fill_shape_for_layer(layer: ET.Element, outer_count: int | None = 1) -> str:
    """Use Inkscape to create a fill shape from a layer's strokes.

    Args:
        layer: The layer element containing stroke paths.
        outer_count: Number of outer contours to extract. Use None to keep all.
            When mirroring creates two separate shapes (like eyes), use 2.

    Returns:
        The 'd' attribute of the resulting filled path.
    """
    # Create temp SVG with layer content (original + mirrored)
    temp_svg = create_temp_svg_for_layer(layer, include_mirror=True)

    # Output temp file
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        # Run Inkscape to convert strokes to paths and union
        subprocess.run(
            [
                "inkscape",
                str(temp_svg),
                "--actions="
                "select-all;"
                "object-stroke-to-path;"
                "select-all;"
                "verb:SelectionUnion;"
                f"export-filename:{output_path};"
                "export-plain-svg;"
                "export-do",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse the output SVG to extract the path
        output_root = ET.parse(output_path).getroot()

        # Find the resulting path element
        path_elem = output_root.find(f".//{{{SVG_NS}}}path")
        if path_elem is None:
            msg = "Inkscape did not produce a path element"
            raise RuntimeError(msg)

        path_d = path_elem.get("d")
        if not path_d:
            msg = "Inkscape path has no 'd' attribute"
            raise RuntimeError(msg)

        # Extract only outer contours if requested
        if outer_count is not None:
            path_d = extract_outer_paths(path_d, outer_count)

        return path_d

    finally:
        temp_svg.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


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

    # 7. Eyes fill
    if "eyes" in fills:
        ET.SubElement(
            root,
            f"{{{SVG_NS}}}path",
            {
                "id": "eyes-fill",
                "d": fills["eyes"],
                "fill": LAYER_CONFIG["eyes"]["fill"],
                "stroke": "none",
            },
        )

    # 8. All black strokes (skip layers that use clip_to - they have fills, not strokes)
    strokes_group = ET.SubElement(root, f"{{{SVG_NS}}}g", {"id": "strokes"})

    for label, config in LAYER_CONFIG.items():
        if config.get("clip_to"):
            continue  # Skip clipped layers - they don't have strokes
        layer_strokes = create_layer_with_mirror(
            layers[label],
            stroke=BLACK,
            stroke_width=stroke_width,
            fill="none",
            add_round_caps=False,
            group_id=f"{label}-strokes",
        )
        strokes_group.append(layer_strokes)

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

    # Check prerequisites
    check_inkscape()
    print("  Inkscape CLI: OK")  # noqa: T201

    print(f"  Source: {SOURCE_SVG}")  # noqa: T201

    # Parse source SVG
    tree = ET.parse(SOURCE_SVG)
    source_root = tree.getroot()

    # Find all required layers
    print("  Finding layers...")  # noqa: T201
    layers: dict[str, ET.Element] = {}
    for label in LAYER_CONFIG:
        layers[label] = find_layer_by_label(source_root, label)
        print(f"    Found: {label}")  # noqa: T201

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
        if not fill_config or config.get("clip_to"):
            continue
        print(f"    {label}...")  # noqa: T201
        # Extract outer contours only (stroke-to-path creates inner holes)
        # Eyes need 2 contours (left and right eye)
        outer_count = 2 if label == "eyes" else 1
        fills[label] = create_fill_shape_for_layer(layers[label], outer_count)
        print(f"    {label}: OK")  # noqa: T201

    # Compose output SVG
    print("  Composing icon SVG...")  # noqa: T201
    icon_svg = compose_icon_svg(source_root, layers, fills, stroke_width)

    # Write icon.svg
    icon_svg_path = BRAND_DIR / "icon.svg"
    icon_svg_path.write_text(icon_svg)
    print(f"  Wrote: {icon_svg_path}")  # noqa: T201

    # Export PNGs
    for size in ICON_SIZES:
        png_name = "icon.png" if size == 256 else f"icon@{size // 256}x.png"
        png_path = BRAND_DIR / png_name
        export_png(icon_svg_path, png_path, size)
        print(f"  Wrote: {png_path}")  # noqa: T201

    # Copy to HACS brand directory
    print(f"  Copying to {HACS_BRAND_DIR}...")  # noqa: T201
    HACS_BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for size in ICON_SIZES:
        png_name = "icon.png" if size == 256 else f"icon@{size // 256}x.png"
        src = BRAND_DIR / png_name
        dst = HACS_BRAND_DIR / png_name
        shutil.copy2(src, dst)
        print(f"    Copied: {dst}")  # noqa: T201

    print("Done!")  # noqa: T201


if __name__ == "__main__":
    main()
