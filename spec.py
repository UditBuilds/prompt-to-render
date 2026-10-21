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

# What the product is drawn as. Each shape has its own fields in the spec,
# under its own name; only the one the spec's "shape" names may be given.
SHAPES = ("box", "cylinder", "bottle", "jar")
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

# The cap or lid colour when none is given: black on a light body, a light
# silver-grey on a dark one, as is common in cosmetics. Both are flat colours,
# not metal: only a metal named for the cap or lid makes it metal (METALS).
# Light means CIE L* of at least 50.
CAP_ON_LIGHT, CAP_ON_DARK = "#1A1A1A", "#C0C0C0"
CAP_LIGHTNESS_SPLIT = 50

# The metals a cap or lid can be drawn in, and the colour each one reflects
# (its base colour as a metal, sRGB). Code picks the metal from the sentence
# ("with a gold cap"); the model never does. Gold, silver, chrome and copper
# are measured values (Unreal Engine docs, "Physically Based Materials":
# linear 1.000/0.766/0.336, 0.972/0.960/0.915, 0.550/0.556/0.554,
# 0.955/0.637/0.538). Bronze and rose gold have no measured value there;
# theirs are estimates: bronze a browner copper (0.78/0.52/0.28), rose gold
# a paler, pinker copper (0.96/0.68/0.60).
METALS = {
    "gold": "#FFE39D",
    "silver": "#FCFAF5",
    "chrome": "#C4C5C4",
    "copper": "#FAD1C2",
    "bronze": "#E5BF90",
    "rose gold": "#FAD7CB",
}
# Polished metal: sharp but not mirror-perfect reflections, whatever the body's finish.
METAL_ROUGHNESS = 0.15

# Proportion limits of the round shapes, held by code after the model (v2 step
# 3, spec_writer.write_spec). They clamp only clearly impossible values, never
# a sensible one, so code doesn't pick sizes. Written from general product
# knowledge, not from the eval ranges:
# - cylinder (a stick, a tube, a can): 0.5 to 15 cm across, from a slim pencil
#   to a wide tin or pillar candle; 2 to 40 cm tall, from a mini lip balm to a
#   tall candle or a poster tube.
# - bottle: at least 1.5 cm across: the narrowest bottles with a shoulder, a
#   neck and a cap (roller and sample bottles) are 1.5-2 cm; narrower is a
#   vial. At most 6 times as tall as it is wide: slim bottles (rollers, oil
#   bottles) reach about 5; taller is a vial or a tube. At least as tall as it
#   is wide is a validation rule; it is held here too, after the diameter.
# - jar: never taller than it is wide: a jar is squat; taller is a canister.
# Sizes are (lowest, highest) in cm, None for no limit, and are clamped first.
# height_per_diameter is (lowest, highest) height / diameter, held by changing
# the height, so the model's diameter stays.
PROPORTION_LIMITS = {
    "cylinder": {"diameter_cm": (0.5, 15.0), "height_cm": (2.0, 40.0)},
    "bottle": {"diameter_cm": (1.5, None), "height_per_diameter": (1.0, 6.0)},
    "jar": {"height_per_diameter": (None, 1.0)},
}

# The renderer adds strip lights for sharp highlights only when something in
# the scene is glossy (roughness at most this) or metal, so a matte render
# stays exactly as it was. The model's own "glossy" is 0.1-0.3, code's 0.05.
GLOSSY_ROUGHNESS = 0.2


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
    # An optional field may be left out of the LLM's reply; code then sets it.
    optional = False

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
            # The format, never a real colour: the LLM reads this message on a retry.
            problems.append(f'{name}: must be a hex colour in the form "#RRGGBB", got {_show(value)}')
            return False
        return True

    def schema(self):
        return {"type": "string", "pattern": HEX_COLOUR.pattern, "description": self.doc}


class CapColour(Colour):
    """A cap or lid colour. Left out (or null), it is worked out from the body colour."""
    optional = True

    def __init__(self, doc):
        super().__init__(None, doc)


class Metal(Field):
    """The metal a cap or lid is drawn in (a METALS name), or null for none.

    Set by code from the sentence, never by the model: it is left out of the
    JSON schema the model reads. A spec file may set it.
    """
    optional = True
    code_only = True

    def __init__(self, doc):
        super().__init__(None, doc)

    def check(self, value, name, problems):
        if value is not None and value not in METALS:
            options = ", ".join(f'"{m}"' for m in METALS)
            problems.append(f"{name}: must be null or one of {options}, got {_show(value)}")
            return False
        return True


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
    "shape": Choice("box", SHAPES, "What the product is drawn as. Fill in only the object of the same name, "
                                   "and leave the other shapes out."),
    "box": {
        "width_cm": Number(6.0, MIN_SIZE_CM, MAX_SIZE_CM, "Left-to-right size in cm, as seen from the front."),
        "height_cm": Number(12.0, MIN_SIZE_CM, MAX_SIZE_CM, "Bottom-to-top size in cm."),
        "depth_cm": Number(4.0, MIN_SIZE_CM, MAX_SIZE_CM, "Front-to-back size in cm."),
        # No example colour here: qwen3:8b copied one ("#E8A3B5") for a colour it didn't know.
        "colour": Colour("#D9D9D9", 'Box colour as a hex code, "#RRGGBB".'),
        "roughness": Number(0.5, 0.0, 1.0, "Surface finish: 0 = mirror-glossy, 1 = fully matte."),
        "bevel_cm": Number(0.15, 0.0, MAX_SIZE_CM,
                           "Radius of the rounded edges in cm (0 = razor sharp). "
                           f"At most {BEVEL_MAX_SHARE:.0%} of the smallest box side."),
    },
    # Round shapes stand upright. The renderer rounds their edges itself, and
    # works out a cylinder's cap, a bottle's shoulder, neck and cap, and a
    # jar's lid, from the diameter and height. The metal of a cap or lid is
    # set by code only (see Metal).
    "cylinder": {
        "diameter_cm": Number(4.0, MIN_SIZE_CM, MAX_SIZE_CM, "Width across in cm."),
        "height_cm": Number(10.0, MIN_SIZE_CM, MAX_SIZE_CM, "Bottom-to-top size in cm, with the cap on."),
        "colour": Colour("#D9D9D9", 'Body colour as a hex code, "#RRGGBB".'),
        "roughness": Number(0.5, 0.0, 1.0, "Surface finish: 0 = mirror-glossy, 1 = fully matte."),
        "cap_colour": CapColour('Cap colour as a hex code, "#RRGGBB". Only if the sentence names one.'),
        "cap_metal": Metal("The metal the cap is drawn in, or null. Set by code from the sentence."),
    },
    "bottle": {
        "diameter_cm": Number(5.0, MIN_SIZE_CM, MAX_SIZE_CM, "Width of the body across in cm, at its widest."),
        "height_cm": Number(12.0, MIN_SIZE_CM, MAX_SIZE_CM,
                            "Bottom-to-top size in cm, with the cap on. At least the diameter."),
        "colour": Colour("#D9D9D9", 'Body colour as a hex code, "#RRGGBB".'),
        "roughness": Number(0.5, 0.0, 1.0, "Surface finish: 0 = mirror-glossy, 1 = fully matte."),
        "cap_colour": CapColour('Cap colour as a hex code, "#RRGGBB". Only if the sentence names one.'),
        "cap_metal": Metal("The metal the cap is drawn in, or null. Set by code from the sentence."),
    },
    "jar": {
        "diameter_cm": Number(7.0, MIN_SIZE_CM, MAX_SIZE_CM, "Width across in cm."),
        "height_cm": Number(5.0, MIN_SIZE_CM, MAX_SIZE_CM,
                            "Bottom-to-top size in cm, with the lid on. Usually less than the diameter."),
        "colour": Colour("#D9D9D9", 'Jar colour as a hex code, "#RRGGBB".'),
        "roughness": Number(0.5, 0.0, 1.0, "Surface finish: 0 = mirror-glossy, 1 = fully matte."),
        "lid_colour": CapColour('Lid colour as a hex code, "#RRGGBB". Only if the sentence names one.'),
        "lid_metal": Metal("The metal the lid is drawn in, or null. Set by code from the sentence."),
    },
    "background_colour": Colour("#EDEDED", 'Studio backdrop colour as a hex code, "#RRGGBB".'),
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

# The fields holding the cap or lid colour, and its metal, for the shapes that
# have one: every round shape.
CAP_FIELDS = {"cylinder": "cap_colour", "bottle": "cap_colour", "jar": "lid_colour"}
METAL_FIELDS = {"cylinder": "cap_metal", "bottle": "cap_metal", "jar": "lid_metal"}


def json_schema(fields=FIELDS, only=None, optional=SHAPES):
    """The JSON schema for a spec, built from FIELDS.

    `only` limits it to some top-level fields. Every field in the schema is
    required, so whoever fills it in has to choose each value, except the
    top-level fields named in `optional` (by default the shapes' objects:
    only the spec's own shape is given) and the cap and lid colours. The
    fields code sets alone (a cap's or lid's metal) are left out. Three
    rules can't be written as JSON schema (only the spec's own shape may be
    given, the bevel must suit the box, a bottle is at least as tall as it is
    wide); they are in the descriptions and validate_spec() checks them.
    """
    properties = {}
    for key, field in fields.items():
        if getattr(field, "code_only", False):
            continue
        if only is None or key in only:
            properties[key] = json_schema(field, optional=()) if isinstance(field, dict) else field.schema()
    return {
        "type": "object",
        "properties": properties,
        "required": [key for key in properties
                     if key not in optional and not getattr(fields[key], "optional", False)],
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
    """Merge a spec dict with DEFAULTS, check every value, return the full spec.

    The full spec holds the fields of its own shape only (a box spec has
    "box", a jar spec has "jar"), and a cap or lid colour that was left out
    is filled in from the body colour (default_cap_colour).
    """
    problems = []

    if not isinstance(raw, dict):
        raise SpecError(["The spec must be a JSON object, i.e. { ... }"])

    _check_unknown_keys(raw, FIELDS, "", problems)
    shape = raw.get("shape", DEFAULTS["shape"])
    shape_ok = FIELDS["shape"].check(shape, "shape", problems)
    for key in SHAPES:
        if key not in raw:
            continue
        if not isinstance(raw[key], dict):
            example = '{ "width_cm": 6, ... }' if key == "box" else '{ "diameter_cm": ..., ... }'
            problems.append(f"{key}: must be an object like {example}")
            continue
        _check_unknown_keys(raw[key], FIELDS[key], f"{key}.", problems)
        if shape_ok and key != shape:
            problems.append(f'{key}: only used when shape is "{key}", but shape is "{shape}". '
                            f'Remove {key}, or set shape to "{key}".')

    spec = {}
    for key in FIELDS:
        if key in SHAPES:
            if shape_ok and key == shape:
                spec[key] = copy.deepcopy(DEFAULTS[key])
                if isinstance(raw.get(key), dict):
                    spec[key].update(raw[key])
        else:
            spec[key] = copy.deepcopy(raw[key]) if key in raw else copy.deepcopy(DEFAULTS[key])

    for key, field in FIELDS.items():
        if key in SHAPES:
            if key in spec:
                _check_product(key, spec[key], problems)
        elif key != "shape":  # checked above
            field.check(spec[key], key, problems)

    if problems:
        raise SpecError(problems)
    return spec


def _check_product(shape, fields, problems):
    """Check the fields of the spec's own shape, and fill in a cap colour that was left out."""
    cap = CAP_FIELDS.get(shape)
    if cap and fields[cap] is None and _is_colour(fields["colour"]):
        fields[cap] = default_cap_colour(fields["colour"])
    ok = {key: field.check(fields[key], f"{shape}.{key}", problems)
          for key, field in FIELDS[shape].items() if not (key == cap and fields[key] is None)}
    if shape == "box":
        _check_box(fields, ok, problems)
    elif shape == "bottle" and ok["diameter_cm"] and ok["height_cm"]:
        # Shorter than it is wide, it would be a jar.
        if fields["height_cm"] < fields["diameter_cm"]:
            problems.append(
                f"bottle.height_cm: a bottle is at least as tall as it is wide (diameter_cm "
                f"{fields['diameter_cm']:g}), got {fields['height_cm']:g}. A shorter, wider container is a jar."
            )


def clamp_proportions(spec):
    """Hold a full spec's round shape to PROPORTION_LIMITS, in place. A box is left alone.

    The sizes first, then the height against the diameter. Returns the
    changes, {"rule", "field", "from", "to"} each, in the order they were
    made, [] if none: every clamp is logged.
    """
    shape = spec["shape"]
    fields = spec[shape]
    limits = PROPORTION_LIMITS.get(shape, {})
    changes = []

    def hold(field, low, high, name, why=("", "")):
        """Clamp fields[field] into low..high (None: no limit). why: a note for each side."""
        value = fields[field]
        if low is not None and value < low:
            rule, to = f"{name} at least {low:g} cm{why[0]}", low
        elif high is not None and value > high:
            rule, to = f"{name} at most {high:g} cm{why[1]}", high
        else:
            return
        changes.append({"rule": f"{shape} {rule}", "field": field, "from": value, "to": to})
        fields[field] = to

    for field, name in (("diameter_cm", "diameter"), ("height_cm", "height")):
        if field in limits:
            hold(field, *limits[field], name)
    if "height_per_diameter" in limits:
        low, high = limits["height_per_diameter"]
        diameter = fields["diameter_cm"]
        hold("height_cm", None if low is None else low * diameter, None if high is None else high * diameter,
             "height", (f" ({low:g} x its diameter)" if low else "", f" ({high:g} x its diameter)" if high else ""))
    return changes


def default_cap_colour(body_colour):
    """The cap or lid colour for a body colour, when none is given: CAP_ON_LIGHT or CAP_ON_DARK."""
    return CAP_ON_LIGHT if lightness(body_colour) >= CAP_LIGHTNESS_SPLIT else CAP_ON_DARK


def _check_box(box, ok, problems):
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


def _is_colour(value):
    return isinstance(value, str) and bool(HEX_COLOUR.match(value))


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


def product(spec):
    """The fields of a full spec's own shape, e.g. spec["jar"] for a jar."""
    return spec[spec["shape"]]


def has_shine(spec):
    """True if anything in a full spec is glossy (roughness <= GLOSSY_ROUGHNESS) or metal.

    The renderer adds its strip lights only then.
    """
    fields = product(spec)
    metal = METAL_FIELDS.get(spec["shape"])
    return fields["roughness"] <= GLOSSY_ROUGHNESS or bool(metal and fields[metal])


def lightness(hex_colour):
    """CIE L* (0 = black, 100 = white) of "#RRGGBB"."""
    r, g, b = hex_to_linear_rgb(hex_colour)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 116 * y ** (1 / 3) - 16 if y > (6 / 29) ** 3 else y * (29 / 3) ** 3


def hex_to_linear_rgb(hex_colour):
    """Convert "#RRGGBB" (sRGB, as used on the web) to Blender's linear RGB."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb
    )
