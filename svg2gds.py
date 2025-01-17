#!/usr/bin/env python3

import sys
import argparse
import math
from io import StringIO

import gdstk
from picosvg.picosvg import SVG as PicoSVG
from svgpathtools import svg2paths2

def flatten_svg_to_string(svg_input: str) -> str:
    """
    Takes an SVG string, flattens any transforms via picosvg,
    and returns a 'flattened' SVG string.
    """
    svg_obj = PicoSVG.fromstring(svg_input)
    flattened = svg_obj.topicosvg()  # flatten
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
    Recursively subdivide a segment until the chord error
    between midpoint and endpoints is below 'max_error'.
    Returns a list of complex points.
    """
    def recursive_subdivide(s, t0, t1, err):
        p0 = s.point(t0)
        p1 = s.point(0.5 * (t0 + t1))
        p2 = s.point(t1)
        chord_len = abs(p2 - p0)
        if chord_len == 0:
            return [p0, p2]
        # cross product magnitude in 2D for chord error
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
    For each segment in path_obj, subdivide adaptively until
    the chord error is below max_error. Returns list of (x,y).
    """
    pts = []
    for seg in path_obj:
        seg_points = adaptive_approximate_segment(seg, max_error)
        if not pts:
            pts.extend(seg_points)
        else:
            # avoid duplicating the join
            if abs(pts[-1][0] - seg_points[0].real) < 1e-12 and abs(pts[-1][1] - seg_points[0].imag) < 1e-12:
                pts.extend(seg_points[1:])
            else:
                pts.extend(seg_points)
    return [(p.real, p.imag) if hasattr(p, 'real') else (p[0], p[1]) for p in pts]

def convert_svg_string_to_gds(svg_string, gds_filename,
                              method="fixed", steps=1000, max_error=0.01,
                              desired_width_um=None, flip_y=True):
    """
    Takes an SVG string (already flattened or not),
    parses paths with svgpathtools, approximates them
    into polygons, optionally scales to 'desired_width_um',
    flips Y if desired, then writes GDSII.
    """
    # Parse directly from string
    paths, attributes, svg_attrs = svg2paths2(StringIO(svg_string))

    all_polygons = []
    for path_obj in paths:
        if method == "fixed":
            polygon_points = approximate_path_fixed(path_obj, steps=steps)
        elif method == "adaptive":
            polygon_points = approximate_path_adaptive(path_obj, max_error=max_error)
        else:
            raise ValueError("Unknown method. Use 'fixed' or 'adaptive'.")

        if polygon_points:
            all_polygons.append(polygon_points)

    if not all_polygons:
        print("No geometry found in SVG. Exiting.")
        return

    # Compute bounding box
    xs = [p[0] for poly in all_polygons for p in poly]
    ys = [p[1] for poly in all_polygons for p in poly]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    width = xmax - xmin
    height = ymax - ymin
    cx = 0.5 * (xmin + xmax)
    cy = 0.5 * (ymin + ymax)

    # Determine scale
    if desired_width_um is not None and width > 0:
        scale_factor = desired_width_um / width
    else:
        scale_factor = 1.0

    # Create GDS library / cell
    lib = gdstk.Library("MY_SVG_CONVERT")
    cell = lib.new_cell("SVG_CELL")

    # Transform each polygon
    for poly in all_polygons:
        transformed = []
        for (x, y) in poly:
            # Translate to center at 0, then scale
            tx = (x - cx) * scale_factor
            ty = (y - cy) * scale_factor
            if flip_y:
                # optional y-flip to match typical GDS orientation
                ty = -ty
            transformed.append((tx, ty))

        gds_poly = gdstk.Polygon(transformed, layer=0)
        cell.add(gds_poly)

    lib.write_gds(gds_filename)
    print(f"Conversion complete: wrote {gds_filename}")

def main():
    parser = argparse.ArgumentParser(
        description="Flatten an SVG (optional) and convert to GDS."
    )
    parser.add_argument("input_svg", help="Input SVG filename")
    parser.add_argument("output_gds", help="Output GDS filename")
    parser.add_argument("--flattened_svg", default=None,
                        help="Optional file to save flattened SVG (before GDS conversion)")
    parser.add_argument("--method", default="fixed", choices=["fixed", "adaptive"],
                        help="Approximation method. 'fixed' uses steps, 'adaptive' uses max_error.")
    parser.add_argument("--steps", type=int, default=1000,
                        help="Number of steps (only for method='fixed'). Default=1000")
    parser.add_argument("--max_error", type=float, default=0.01,
                        help="Max chord error (only for method='adaptive'). Default=0.01")
    parser.add_argument("--desired_width_um", type=float, default=None,
                        help="Scale geometry so bounding box = desired_width_um. Default=None (no scale)")
    parser.add_argument("--no_flip_y", action="store_true",
                        help="Disable Y-flip (GDS usually has Y increasing upward).")

    args = parser.parse_args()

    # 1) Read the input SVG file
    with open(args.input_svg, "r", encoding="utf-8") as f:
        svg_data = f.read()

    # 2) Flatten transforms via picosvg
    flattened_str = flatten_svg_to_string(svg_data)

    # 2a) If the user wants a flattened SVG file saved:
    if args.flattened_svg:
        with open(args.flattened_svg, "w", encoding="utf-8") as f_out:
            f_out.write(flattened_str)
        print(f"Flattened SVG saved to {args.flattened_svg}")

    # 3) Convert flattened string to GDS
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
