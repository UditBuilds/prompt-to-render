"""
Measure how close a render's box colour is to the colour in its spec.

Usage:
    python check_colour.py specs/pink_three_quarter.json renders/pink_three_quarter_20261017_211532.png

It finds the centre of the box's main lit face in the image (the front face
for the "front" and "three_quarter" cameras, the top face for "top_down"),
averages a small patch of pixels there, and reports:

    spec hex, measured hex, and Delta E (CIE76): the distance between the two
    colours. Rough guide: under 2 hard to see, 2-5 small, 5-10 noticeable,
    over 10 obvious.

The patch location is worked out by rebuilding the scene from the spec in
Blender (no rendering), so it runs Blender in the background for you. The
colour maths at the top of this file is plain Python.
"""

import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec import hex_to_linear_rgb  # noqa: E402

PREFIX = "[check]"


# ---------------------------------------------------------------------------
# Colour maths (plain Python)
# ---------------------------------------------------------------------------

def rgb255_to_hex(rgb):
    return "#" + "".join(f"{round(c):02X}" for c in rgb)


def hex_to_lab(hex_colour):
    """sRGB hex -> CIE L*a*b* (D65 white point)."""
    r, g, b = hex_to_linear_rgb(hex_colour)
    # Linear sRGB -> XYZ, normalised to the D65 white point.
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 1.00000
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e76(hex_a, hex_b):
    """CIE76 colour difference: straight-line distance in L*a*b*."""
    return math.dist(hex_to_lab(hex_a), hex_to_lab(hex_b))


def describe_delta_e(de):
    if de < 2:
        return "hard to see"
    if de < 5:
        return "small"
    if de < 10:
        return "noticeable"
    return "obvious"


# ---------------------------------------------------------------------------
# Image sampling (runs inside Blender)
# ---------------------------------------------------------------------------

def measure_patch(png_path, patch):
    """Average colour of a patch of a PNG, as a hex string.

    patch = (min_x, max_x, min_y, max_y) in 0-1 image coordinates, origin at
    the bottom-left (Blender's convention).
    """
    import bpy
    import numpy as np

    image = bpy.data.images.load(png_path)
    width, height = image.size
    # For an 8-bit PNG, .pixels holds the stored sRGB values divided by 255.
    pixels = np.array(image.pixels[:]).reshape(height, width, image.channels)
    bpy.data.images.remove(image)

    min_x, max_x, min_y, max_y = patch
    x0, x1 = int(min_x * width), max(int(max_x * width), int(min_x * width) + 1)
    y0, y1 = int(min_y * height), max(int(max_y * height), int(min_y * height) + 1)
    mean = pixels[y0:y1, x0:x1, :3].reshape(-1, 3).mean(axis=0) * 255
    return rgb255_to_hex(mean), (x1 - x0, y1 - y0)


def check(spec_path, png_path):
    """Rebuild the scene to find the patch, then measure it. Returns a dict."""
    import render_scene
    from spec import load_spec

    spec = load_spec(spec_path)
    scene = render_scene.build_scene(spec)
    patch = render_scene.hero_patch(scene, spec)
    measured, size = measure_patch(png_path, patch)
    target = spec["box"]["colour"].upper()
    return {"spec": target, "measured": measured, "delta_e": delta_e76(target, measured),
            "patch_px": size, "face": render_scene.CAMERA_PRESETS[spec["camera"]]["hero_face"]}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def main_in_blender():
    args = sys.argv[sys.argv.index("--") + 1:]
    spec_path, png_path = args
    result = check(spec_path, png_path)
    w, h = result["patch_px"]
    print(f"{PREFIX} Spec:          {spec_path}")
    print(f"{PREFIX} Image:         {png_path}")
    print(f"{PREFIX} Patch:         centre of the {result['face']} face, {w}x{h} px")
    print(f"{PREFIX} Spec colour:   {result['spec']}")
    print(f"{PREFIX} Measured:      {result['measured']}")
    print(f"{PREFIX} Delta E (76):  {result['delta_e']:.1f}  ({describe_delta_e(result['delta_e'])})")


def main_launcher():
    """Started with normal Python: re-run this file inside Blender."""
    from run import find_blender

    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    spec_path, png_path = sys.argv[1], sys.argv[2]
    for path in (spec_path, png_path):
        if not os.path.isfile(path):
            print(f"File not found: {path}")
            return 1
    blender = find_blender()
    if not blender:
        print("Could not find blender.exe (see run.py --help).")
        return 1

    result = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1",
         "--python", os.path.abspath(__file__), "--",
         os.path.abspath(spec_path), os.path.abspath(png_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    lines = result.stdout.splitlines()
    shown = [line[len(PREFIX) + 1:] for line in lines if line.startswith(PREFIX)]
    if result.returncode != 0 or not shown:
        print("Colour check FAILED. Last lines of Blender's output:")
        for line in (lines + result.stderr.splitlines())[-20:]:
            print(f"    {line}")
        return 1
    print("\n".join(shown))
    return 0


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401
    except ImportError:
        sys.exit(main_launcher())
    main_in_blender()
