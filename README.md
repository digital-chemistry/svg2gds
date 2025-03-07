# svg2gds

A Python script that:

- **Flattens** an input SVG's transforms using [picosvg](https://github.com/googlefonts/picosvg)
- **Approximates** all paths into polygons using [svgpathtools](https://pypi.org/project/svgpathtools/)
- **Optionally scales** the final geometry to a user-specified width
- **Exports** to GDSII using [gdstk](https://heitzmann.github.io/gdstk/)

## Features

- **Flatten Transforms**: All transformations (e.g. `matrix()`, rotate, translate, scale) are baked into path coordinates via `picosvg`.
- **Approximation Methods**:
  - **Fixed**: Subdivide curves into a fixed number of line segments.
  - **Adaptive**: Recursively refine curves until the chord error is below a specified threshold.
- **Optional Scaling**: Scale the bounding box of your geometry to a specified width in micrometers (`--desired_width_um`).
- **Optional Y-Flip**: By default, Y is flipped to match conventional GDS coordinates. Disable with `--no_flip_y`.

## Usage

```bash
python svg2gds.py INPUT.svg OUTPUT.gds [OPTIONS]
```

### Main Arguments

- `INPUT.svg`: Input SVG file
- `OUTPUT.gds`: Output GDS file

### Options

- `--flattened_svg FLAT.svg`: Saves an intermediate, flattened SVG (all transforms baked in).
- `--method {fixed,adaptive}`:
  - `fixed`: Subdivide each path segment into `--steps` line segments.
  - `adaptive`: Recursively subdivide each path segment until chord error < `--max_error`.
- `--steps <int>` (default 1000): Subdivisions per segment (only used in fixed mode).
- `--max_error <float>` (default 0.01): Chord error threshold for adaptive mode.
- `--desired_width_um <float>`: Scales the final design to this bounding-box width in micrometers.
- `--no_flip_y`: Disables Y-axis flipping.

## Examples

### Basic Usage (Fixed Subdivision)
```bash
python svg2gds.py my_logo.svg my_logo.gds
```
- Flattens `my_logo.svg` in memory
- Uses 1000 steps per path segment (default)
- No scaling or additional options

### Flattened SVG + Adaptive Mode
```bash
python svg2gds.py in.svg out.gds \
    --flattened_svg=flattened.svg \
    --method=adaptive \
    --max_error=0.001
```
- Creates `flattened.svg` as an intermediate result
- Uses adaptive subdivision until chord error < 0.001

### Scale the Design to 10 µm Wide
```bash
python svg2gds.py in.svg out.gds --desired_width_um=10
```
- Bounding box is measured and scaled to 10 micrometers

### Disable Y-Flip
```bash
python svg2gds.py in.svg out.gds --no_flip_y
```
- Keeps the SVG’s original Y orientation (positive Y downward)


> **Note on Text**: If your SVG contains `<text>` elements, **picosvg** cannot flatten them directly.  
> 1) **Manually** convert text to outlines in a vector editor like Inkscape by selecting text → _Path_ → _Object to Path_ and **save as Plain SVG**.  
> 2) Then run `svg2gds.py` on the resulting path-based file.  
> Alternatively, if Inkscape is installed and on your PATH, you can use the `--convert_text` option to auto-convert text to outlines before flattening.

