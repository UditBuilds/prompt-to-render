"""
Scene spec: defaults, validation, and the JSON schema an LLM must follow.

This file uses only the Python standard library so it can be imported both by
run.py (normal Python) and by render_scene.py (Blender's built-in Python).
Validation happens here, BEFORE Blender starts, so a bad spec gives a clear
message instead of a Blender crash.

Every field is declared once, in FIELDS: its default, the values it allows and
what it means. validate_spec() checks a spec against FIELDS, and json_schema()
turns FIELDS into the JSON schema the LLM is held to. Both come from the same
table, so they can't drift apart.
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

HEX_COLOUR = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

MIN_SIZE_CM, MAX_SIZE_CM = 0.5, 200.0
MIN_RES, MAX_RES = 16, 8192
MIN_SAMPLES, MAX_SAMPLES = 1, 8192

# The edge radius may be at most this share of the box's smallest side. Then
# every face stays at least 80% flat, so it always reads as a box. Real cartons
# sit at 1-5% (0.1-0.3 cm on 3-30 cm sides); 10% leaves room for soft-edged
# rigid boxes but rules out a "bar of soap" (1.5 cm on an 8 cm side is 19%).
BEVEL_MAX_SHARE = 0.10


class SpecError(Exception):
    """Raised when a spec is invalid. Holds a list of human-readable problems."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("\n".join(problems))


# ---------------------------------------------------------------------------
# Field types. Each one knows its default, how to check a value (appending a
# readable message to `problems` on failure) and how to describe itself as
# JSON schema.
# ---------------------------------------------------------------------------

class Field:
    def __init__(self, default, doc):
        self.default = default
        self.doc = doc

    def check(self, value, name, problems):
        raise NotImplementedError

    def schema(self):
        raise NotImplementedError


class Text(Field):
    def check(self, value, name, problems):
        if not isinstance(value, str):
            problems.append(f"{name}: must be text")
            return False
        return True

    def schema(self):
        return {"type": "string", "description": self.doc}


class Number(Field):
    def __init__(self, default, low, high, doc):
        super().__init__(default, doc)
        self.low, self.high = low, high

    def check(self, value, name, problems):
        return _check_number(value, name, self.low, self.high, problems)

    def schema(self):
        return {"type": "number", "minimum": self.low, "maximum": self.high, "description": self.doc}


class Integer(Number):
    def check(self, value, name, problems):
        return _check_int(value, name, self.low, self.high, problems)

    def schema(self):
        return dict(super().schema(), type="integer")


class Colour(Field):
    def check(self, value, name, problems):
        if not (isinstance(value, str) and HEX_COLOUR.match(value)):
            problems.append(f'{name}: must be a hex colour like "#F4B6C2", got {_show(value)}')
            return False
        return True

    def schema(self):
        return {"type": "string", "pattern": HEX_COLOUR.pattern, "description": self.doc}


class Choice(Field):
    def __init__(self, default, choices, doc):
        super().__init__(default, doc)
        self.choices = choices

    def check(self, value, name, problems):
        if value not in self.choices:
            options = ", ".join(f'"{c}"' for c in self.choices)
            problems.append(f"{name}: must be one of {options}, got {_show(value)}")
            return False
        return True

    def schema(self):
        return {"type": "string", "enum": list(self.choices), "description": self.doc}


class Resolution(Field):
    AXES = ("width", "height")

    def check(self, value, name, problems):
        if not (isinstance(value, list) and len(value) == 2):
            problems.append(f"{name}: must be [width, height], e.g. [1080, 1080], got {_show(value)}")
            return False
        results = [_check_int(v, f"{name} {axis}", MIN_RES, MAX_RES, problems)
                   for v, axis in zip(value, self.AXES)]
        return all(results)

    def schema(self):
        return {
            "type": "array", "minItems": 2, "maxItems": 2,
            "items": {"type": "integer", "minimum": MIN_RES, "maximum": MAX_RES},
            "description": self.doc,
        }


# ---------------------------------------------------------------------------
# The spec. Every field is optional in a spec file; anything left out uses
# its default. The docs are written for whoever fills the spec in, human or
# LLM: they end up in the JSON schema the LLM sees.
# ---------------------------------------------------------------------------

FIELDS = {
    "description": Text("", "One short sentence describing the shot. A note for humans, not used for rendering."),
    "box": {
        "width_cm": Number(6.0, MIN_SIZE_CM, MAX_SIZE_CM, "Left-to-right size in cm, as seen from the front."),
        "height_cm": Number(12.0, MIN_SIZE_CM, MAX_SIZE_CM, "Bottom-to-top size in cm."),
        "depth_cm": Number(4.0, MIN_SIZE_CM, MAX_SIZE_CM, "Front-to-back size in cm."),
        "colour": Colour("#D9D9D9", 'Box colour as a hex code, e.g. "#E8A3B5".'),
        "roughness": Number(0.5, 0.0, 1.0, "Surface finish: 0 = mirror-glossy, 1 = fully matte."),
        "bevel_cm": Number(0.15, 0.0, MAX_SIZE_CM,
                           "Radius of the rounded edges in cm (0 = razor sharp). "
                           f"At most {BEVEL_MAX_SHARE:.0%} of the smallest box side."),
    },
    "background_colour": Colour("#EDEDED", "Studio backdrop colour as a hex code."),
    "colour_mode": Choice("accurate", COLOUR_MODES,
                          "accurate: the box colour matches the hex closely. realistic: filmic look, paler colours."),
    "camera": Choice("three_quarter", CAMERA_PRESETS,
                     "front: straight on. three_quarter: angled from the front-right and above, "
                     "showing front, side and top. top_down: directly overhead (flat lay)."),
    "lighting": Choice("studio_soft", LIGHTING_PRESETS, "Lighting setup."),
    "resolution": Resolution([1080, 1080], "Image size in pixels, [width, height]."),
    "samples": Integer(128, MIN_SAMPLES, MAX_SAMPLES, "Render quality. More is cleaner but slower."),
}


def _defaults(fields):
    return {key: _defaults(field) if isinstance(field, dict) else copy.deepcopy(field.default)
            for key, field in fields.items()}


DEFAULTS = _defaults(FIELDS)


def json_schema(fields=FIELDS, only=None):
    """The JSON schema for a spec, built from FIELDS.

    `only` limits it to some top-level fields. Every field in the schema is
    required, so whoever fills it in has to choose each value. One rule can't
    be written as JSON schema (the bevel must suit the box); it is in the
    bevel's description and validate_spec() checks it.
    """
    properties = {}
    for key, field in fields.items():
        if only is None or key in only:
            properties[key] = json_schema(field) if isinstance(field, dict) else field.schema()
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


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

    _check_unknown_keys(raw, FIELDS, "", problems)
    if isinstance(raw.get("box"), dict):
        _check_unknown_keys(raw["box"], FIELDS["box"], "box.", problems)
    elif "box" in raw:
        problems.append('box: must be an object like { "width_cm": 6, ... }')

    spec = copy.deepcopy(DEFAULTS)
    for key, value in raw.items():
        if key == "box" and isinstance(value, dict):
            spec["box"].update(value)
        elif key in spec and key != "box":
            spec[key] = value

    for key, field in FIELDS.items():
        if key == "box":
            _check_box(spec["box"], problems)
        else:
            field.check(spec[key], key, problems)

    if problems:
        raise SpecError(problems)
    return spec


def _check_box(box, problems):
    ok = {key: field.check(box[key], f"box.{key}", problems)
          for key, field in FIELDS["box"].items()}

    # The bevel can only be checked against the box once all sizes are valid
    # numbers. This is the one rule the JSON schema can't express.
    sizes = [box[f] for f in ("width_cm", "height_cm", "depth_cm")]
    if ok["bevel_cm"] and all(_is_number(s) for s in sizes):
        limit = min(sizes) * BEVEL_MAX_SHARE
        if box["bevel_cm"] > limit + 1e-9:  # tolerance for float rounding
            problems.append(
                f"box.bevel_cm: must be at most {BEVEL_MAX_SHARE:.0%} of the smallest box side "
                f"({limit:g} cm for this box), got {box['bevel_cm']:g}"
            )


# ---------------------------------------------------------------------------
# Small helpers. Each check appends a readable message to `problems` on failure.
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
