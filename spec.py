"""
Scene spec: defaults + validation.

This file uses only the Python standard library so it can be imported both by
run.py (normal Python) and by render_scene.py (Blender's built-in Python).
Validation happens here, BEFORE Blender starts, so a bad spec gives a clear
message instead of a Blender crash.
"""

import copy
import difflib
import json
import math
import re

CAMERA_PRESETS = ("front", "three_quarter", "top_down")
LIGHTING_PRESETS = ("studio_soft",)
# accurate:  the box colour matches the spec hex as closely as possible.
# realistic: filmic AgX look; nicer highlights, but colours shift a little.
COLOUR_MODES = ("accurate", "realistic")

# Every field is optional in a spec file. Anything left out uses these values.
DEFAULTS = {
    "description": "",
    "box": {
        "width_cm": 6.0,   # left-to-right, as seen from the front
        "height_cm": 12.0,  # bottom-to-top
        "depth_cm": 4.0,   # front-to-back
        "colour": "#D9D9D9",
        "roughness": 0.5,  # 0 = mirror-glossy, 1 = fully matte
        "bevel_cm": 0.15,  # radius of the rounded edges (0 = sharp)
    },
    "background_colour": "#EDEDED",
    "colour_mode": "accurate",
    "camera": "three_quarter",
    "lighting": "studio_soft",
    "resolution": [1080, 1080],  # [width, height] in pixels
    "samples": 128,
}

HEX_COLOUR = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

MIN_SIZE_CM, MAX_SIZE_CM = 0.5, 200.0
MIN_RES, MAX_RES = 16, 8192
MIN_SAMPLES, MAX_SAMPLES = 1, 8192


class SpecError(Exception):
    """Raised when a spec is invalid. Holds a list of human-readable problems."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("\n".join(problems))


def load_spec(path):
    """Read a JSON spec file, fill in defaults, validate it, and return it.

    Raises SpecError listing every problem found.
    """
    try:
        # utf-8-sig also accepts files saved by Notepad/PowerShell with a BOM.
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except FileNotFoundError:
        raise SpecError([f"File not found: {path}"])
    except OSError as e:
        raise SpecError([f"Could not read {path}: {e}"])

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError([f"Not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}"])

    return validate_spec(raw)


def validate_spec(raw):
    """Merge a spec dict with DEFAULTS, check every value, return the full spec."""
    problems = []

    if not isinstance(raw, dict):
        raise SpecError(["The spec must be a JSON object, i.e. { ... }"])

    _check_unknown_keys(raw, DEFAULTS, "", problems)
    if isinstance(raw.get("box"), dict):
        _check_unknown_keys(raw["box"], DEFAULTS["box"], "box.", problems)
    elif "box" in raw:
        problems.append('box: must be an object like { "width_cm": 6, ... }')

    spec = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key == "box" and isinstance(value, dict):
            spec["box"].update(value)
        elif key in spec and key != "box":
            spec[key] = value

    box = spec["box"]
    if not isinstance(spec["description"], str):
        problems.append("description: must be text")

    for field in ("width_cm", "height_cm", "depth_cm"):
        _check_number(box[field], f"box.{field}", MIN_SIZE_CM, MAX_SIZE_CM, problems)
    _check_colour(box["colour"], "box.colour", problems)
    _check_number(box["roughness"], "box.roughness", 0.0, 1.0, problems)

    # The bevel can only be checked once the box size is known to be valid.
    if _check_number(box["bevel_cm"], "box.bevel_cm", 0.0, MAX_SIZE_CM, problems):
        sizes = [box[f] for f in ("width_cm", "height_cm", "depth_cm")]
        if all(_is_number(s) for s in sizes):
            limit = min(sizes) / 2
            if box["bevel_cm"] >= limit:
                problems.append(
                    f"box.bevel_cm: must be less than half the smallest box side "
                    f"({limit:g} cm for this box), got {box['bevel_cm']}"
                )

    _check_colour(spec["background_colour"], "background_colour", problems)
    _check_choice(spec["colour_mode"], "colour_mode", COLOUR_MODES, problems)
    _check_choice(spec["camera"], "camera", CAMERA_PRESETS, problems)
    _check_choice(spec["lighting"], "lighting", LIGHTING_PRESETS, problems)

    res = spec["resolution"]
    if not (isinstance(res, list) and len(res) == 2):
        problems.append(f"resolution: must be [width, height], e.g. [1080, 1080], got {_show(res)}")
    else:
        for i, axis in enumerate(("width", "height")):
            _check_int(res[i], f"resolution {axis}", MIN_RES, MAX_RES, problems)

    _check_int(spec["samples"], "samples", MIN_SAMPLES, MAX_SAMPLES, problems)

    if problems:
        raise SpecError(problems)
    return spec


# ---------------------------------------------------------------------------
# Small helpers. Each one appends a readable message to `problems` on failure.
# ---------------------------------------------------------------------------

def _show(value):
    return json.dumps(value)


def _is_number(value):
    # bool is a subclass of int in Python, so rule it out explicitly.
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _check_number(value, name, low, high, problems):
    if not _is_number(value):
        problems.append(f"{name}: must be a number, got {_show(value)}")
        return False
    if not low <= value <= high:
        problems.append(f"{name}: must be between {low:g} and {high:g}, got {value:g}")
        return False
    return True


def _check_int(value, name, low, high, problems):
    if not (isinstance(value, int) and not isinstance(value, bool)):
        problems.append(f"{name}: must be a whole number, got {_show(value)}")
        return False
    if not low <= value <= high:
        problems.append(f"{name}: must be between {low} and {high}, got {value}")
        return False
    return True


def _check_colour(value, name, problems):
    if not (isinstance(value, str) and HEX_COLOUR.match(value)):
        problems.append(f'{name}: must be a hex colour like "#F4B6C2", got {_show(value)}')


def _check_choice(value, name, choices, problems):
    if value not in choices:
        options = ", ".join(f'"{c}"' for c in choices)
        problems.append(f"{name}: must be one of {options}, got {_show(value)}")


def _check_unknown_keys(given, allowed, prefix, problems):
    for key in given:
        if key not in allowed:
            hint = difflib.get_close_matches(key, list(allowed), n=1)
            suggestion = f' Did you mean "{prefix}{hint[0]}"?' if hint else ""
            problems.append(f'{prefix}{key}: unknown field.{suggestion}')


def hex_to_linear_rgb(hex_colour):
    """Convert "#RRGGBB" (sRGB, as used on the web) to Blender's linear RGB."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb
    )
