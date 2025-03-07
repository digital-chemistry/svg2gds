#!/usr/bin/env python3
"""
This script converts an SVG file into a GDSII file.
It flattens transforms using picosvg and approximates paths
into polygons. Optionally, it can convert text elements into paths
(using Inkscape's command‐line conversion) so that text is included
in the final lithography.
"""

import sys
import argparse
import math
from io import StringIO
import subprocess
import os

import gdstk
from picosvg.picosvg import SVG as PicoSVG
from svgpathtools import svg2paths2
import xml.etree.ElementTree as ET


def ensure_default_namespace(svg_data: str) -> str:
    """
    Ensures the root <svg> has xmlns="http://www.w3.org/2000/svg".
    If missing, sets it. Returns the updated SVG string.
    """
    root = ET.fromstring(svg_data)
    if 'xmlns' not in root.attrib or not root.attrib['xmlns']:
        root.set('xmlns', 'http://www.w3.org/2000/svg')
    return ET.tostring(root, encoding='unicode')


def convert_text_to_paths(input_svg: str, temp_svg: str = "temp_converted.svg") -> str:
    """
    Uses Inkscape to convert text elements in the SVG to paths.
    This requires Inkscape (version 1.x recommended) to be installed and in your PATH.
    
    The command used is:
      inkscape input.svg --export-type=svg --export-plain-svg=temp_converted.svg --export-text-to-path

    Returns the content of the converted SVG.
    """
    cmd = [
        "inkscape",
        input_svg,
        "--export-type=svg",
        f"--export-plain-svg={temp_svg}",
        "--export-text-to-path"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error converting text to paths via Inkscape:")
        print(result.stderr)
        sys.exit(1)
    with open(temp_svg, "r", encoding="utf-8") as f:
        new_svg_data = f.read()
    os.remove(temp_svg)
    return new_svg_data


def flatten_svg_to_string(svg_input: str) -> str:
    """
    Takes an SVG string, flattens any transforms via picosvg,
    and returns a flattened SVG string.
    """
    svg_obj = PicoSVG.fromstring(svg_input)
    flattened = svg_obj.topicosvg()  # flatten transforms
    return flattened.tostring()


def approximate_path_fixed(path_obj, steps=1000):
    """
    Convert an svgpathtools Path object into a list of (x, y) points.
    Each segment is subdivided into 'steps' linear segments.
    """
    pts = []
    for seg in path_obj:
        for i in range(steps + 1):
            t = i / steps
            c = seg.point(t)
            pts.append((c.real, c.imag))
    return pts


def adaptive_approximate_segment(seg, max_error=0.01):
    """
    Recursively subdivide a segment until chord error <= max_error.
    Returns a list of complex points.
    """
    def recursive_subdivide(s, t0, t1, err):
        p0 = s.point(t0)
        p1 = s.point((t0 + t1) * 0.5)
        p2 = s.point(t1)
        chord_len = abs(p2 - p0)
        if chord_len == 0:
            return [p0, p2]
        # 2D cross product magnitude for chord error
        chord_vec = p2 - p0
        mid_vec = p1 - p0
        error = abs(chord_vec.real * mid_vec.imag - chord_vec.imag * mid_vec.real) / chord_len
        if error <= err:
            return [p0, p2]
        else:
            tm = 0.5 * (t0 + t1)
            left_pts = recursive_subdivide(s, t0, tm, err)
            right_pts = recursive_subdivide(s, tm, t1, err)
            return left_pts[:-1] + right_pts

    return recursive_subdivide(seg, 0.0, 1.0, max_error)


def approximate_path_adaptive(path_obj, max_error=0.01):
    """
    For each segment in path_obj, subdivide adaptively until chord error < max_error.
    Returns list of (x,y) points.
    """
    pts = []
    for seg in path_obj:
        seg_points = adaptive_approximate_segment(seg, max_error)
        if not pts:
            pts.extend(seg_points)
        else:
            # Avoid duplicating the join point
            last_pt = pts[-1]
            first_new = seg_points[0]
            if abs(last_pt[0] - first_new.real) < 1e-12 and abs(last_pt[1] - first_new.imag) < 1e-12:
                pts.extend(seg_points[1:])
            else:
                pts.extend(seg_points)
    return [(p.real, p.imag) for p in pts]


def convert_svg_string_to_gds(svg_string, gds_filename,
                              method="fixed", steps=1000, max_error=0.01,
                              desired_width_um=None, flip_y=True):
    """
    Takes an SVG string (already flattened), parses it with svgpathtools,
    approximates paths into polygons, optionally scales and flips Y,
    and writes the geometry to a GDSII file.
    """
    # Parse paths from the SVG string
    paths, attributes, svg_attrs = svg2paths2(StringIO(svg_string))
    all_polygons = []
    for path_obj in paths:
        if method == "fixed":
            poly_pts = approximate_path_fixed(path_obj, steps=steps)
        elif method == "adaptive":
            poly_pts = approximate_path_adaptive(path_obj, max_error=max_error)
        else:
            raise ValueError("Unknown method. Use 'fixed' or 'adaptive'.")
        if poly_pts:
            all_polygons.append(poly_pts)
    if not all_polygons:
        print("No geometry found in SVG after path approximation.")
        return

    # Compute bounding box
    xs = [p[0] for poly in all_polygons for p in poly]
    ys = [p[1] for poly in all_polygons for p in poly]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    cx = 0.5 * (xmin + xmax)
    cy = 0.5 * (ymin + ymax)

    # Determine scale factor
    if desired_width_um is not None and (xmax - xmin) > 0:
        scale_factor = desired_width_um / (xmax - xmin)
    else:
        scale_factor = 1.0

    # Create GDS library and cell
    lib = gdstk.Library("MY_SVG_CONVERT")
    cell = lib.new_cell("SVG_CELL")

    # Transform and add each polygon to the cell
    for poly in all_polygons:
        transformed = []
        for (x, y) in poly:
            # Center the geometry and scale it
            tx = (x - cx) * scale_factor
            ty = (y - cy) * scale_factor
            if flip_y:
                ty = -ty
            transformed.append((tx, ty))
        gds_poly = gdstk.Polygon(transformed, layer=0)
        cell.add(gds_poly)

    lib.write_gds(gds_filename)
    print(f"Conversion complete: wrote {gds_filename}")


def main():
    parser = argparse.ArgumentParser(
        description="Flatten an SVG and convert it to GDS. Optionally convert text to outlines using Inkscape."
    )
    parser.add_argument("input_svg", help="Input SVG filename")
    parser.add_argument("output_gds", help="Output GDS filename")
    parser.add_argument("--flattened_svg", default=None,
                        help="Optional file to save flattened SVG (before GDS conversion)")
    parser.add_argument("--method", default="fixed", choices=["fixed", "adaptive"],
                        help="Path approximation method: 'fixed' uses --steps, 'adaptive' uses --max_error.")
    parser.add_argument("--steps", type=int, default=1000,
                        help="Number of steps for fixed approximation (default=1000)")
    parser.add_argument("--max_error", type=float, default=0.01,
                        help="Maximum chord error for adaptive approximation (default=0.01)")
    parser.add_argument("--desired_width_um", type=float, default=None,
                        help="Scale geometry so that the bounding box width equals this (in microns)")
    parser.add_argument("--no_flip_y", action="store_true",
                        help="Disable Y-flip (by default Y is flipped to match GDS conventions)")
    parser.add_argument("--convert_text", action="store_true",
                        help="Convert text elements to paths using Inkscape (required if text is part of your lithography)")

    args = parser.parse_args()

    # If converting text, call Inkscape to process the file
    if args.convert_text:
        print("Converting text to paths using Inkscape...")
        svg_data = convert_text_to_paths(args.input_svg)
    else:
        with open(args.input_svg, "r", encoding="utf-8") as f:
            svg_data = f.read()

    # Ensure the SVG has the default namespace
    svg_data = ensure_default_namespace(svg_data)

    # Flatten transforms via picosvg
    flattened_str = flatten_svg_to_string(svg_data)

    # Optionally save the flattened SVG
    if args.flattened_svg:
        with open(args.flattened_svg, "w", encoding="utf-8") as f_out:
            f_out.write(flattened_str)
        print("Flattened SVG saved to", args.flattened_svg)

    # Convert flattened SVG to GDS
    flip_y = not args.no_flip_y
    convert_svg_string_to_gds(
        flattened_str,
        args.output_gds,
        method=args.method,
        steps=args.steps,
        max_error=args.max_error,
        desired_width_um=args.desired_width_um,
        flip_y=flip_y
    )

if __name__ == "__main__":
    main()
