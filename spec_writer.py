"""
Sentence -> validated spec: the LLM call plus the validation loop.

    result = write_spec("a matte red lipstick box", backend)

1. The backend asks the model for a spec (JSON, constrained to a schema).
2. spec.py validates it, exactly as it validates a hand-written spec file.
3. If that fails, the exact error messages go back to the model with its
   reply, and it gets one more try. After MAX_ATTEMPTS it stops.

Used by prompt.py and by the evals, so both run the same loop.
"""

import json
import re

from grounding import (Grounding, apply_finish, apply_metal, default_cap, lookup, neutral_backdrop,
                       style_box_colour)
from labels import apply_label, read_label
from spec import CAP_FIELDS, SHAPES, SpecError, clamp_proportions, validate_spec

MAX_ATTEMPTS = 2

# The closest drawn shape for a real shape the renderer can't draw, as the
# prompt itself gives it: "a squeeze tube or a can as a cylinder". The model
# names such a shape right in its "shape" field, but once cylinders had a cap
# (v2 step 2) it often drew a squeeze tube as a jar, so code draws it as the
# prompt says.
CLOSEST_SHAPES = {"tube": "cylinder", "tubes": "cylinder", "can": "cylinder", "cans": "cylinder"}


class Attempt:
    def __init__(self, number, reply, errors):
        self.number = number
        self.reply = reply    # llm_backend.Reply
        self.errors = errors  # validation errors; [] if the spec was valid

    def to_log(self):
        r = self.reply
        entry = {
            "attempt": self.number,
            "valid": not self.errors,
            "errors": self.errors,
            "seconds": round(r.seconds, 2),
            "load_seconds": round(r.load_seconds, 2),
            "prompt_tokens": r.prompt_tokens,
            "output_tokens": r.output_tokens,
            "output": r.text,
        }
        if r.note:
            entry["note"] = r.note
        return entry


class SpecResult:
    def __init__(self, attempts, spec=None, unsupported=None, model_unsupported=None,
                 is_box=None, shape=None, shape_added=False, grounding=None, style_changes=None,
                 backdrop_change=None, finish_change=None, backdrop_given=None, cap_change=None,
                 cap_given=None, metal_change=None, shape_fixed=None, proportion_changes=None,
                 label_change=None, model_sentence=None):
        self.attempts = attempts
        self.grounding = grounding or Grounding([])  # the table rows the model was given
        self.style_changes = style_changes or []   # style-word colour shifts applied by code
        self.backdrop_change = backdrop_change     # {"from", "to"} if code set the neutral backdrop
        self.backdrop_given = backdrop_given       # False if the model left the backdrop out
        self.finish_change = finish_change         # {"finish", "from", "to"} if code clamped the roughness
        self.cap_change = cap_change               # {"field", "from", "to"} if code set the cap or lid colour
        self.cap_given = cap_given                 # False if the model left the cap or lid colour out
        self.metal_change = metal_change           # {"field", "metal"} if code drew the cap or lid in metal
        # {"rule", "field", "from", "to"} per size code clamped (spec.PROPORTION_LIMITS), [] if none
        self.proportion_changes = proportion_changes or []
        # {"text", "colour", "metal", "colour_from"} if code drew a label (labels.py), else None
        self.label_change = label_change
        self.model_sentence = model_sentence  # what the model and the tables got: no quoted text
        self.spec = spec                    # full validated spec, or None
        self.unsupported = unsupported or []  # what the user is told was ignored
        self.model_unsupported = model_unsupported or []  # the model's own list, before the code added anything
        self.is_box = is_box
        self.shape = shape                  # the model's word for the real shape; spec["shape"] is what is drawn
        self.shape_added = shape_added      # True if the code added the shape to `unsupported`
        self.shape_fixed = shape_fixed      # {"real", "from", "to"} if code redrew it in the closest shape

    @property
    def ok(self):
        return self.spec is not None

    @property
    def errors(self):
        """The errors of the last attempt."""
        return self.attempts[-1].errors if self.attempts else []

    @property
    def retried(self):
        return len(self.attempts) > 1

    def total(self, field):
        values = [getattr(a.reply, field) for a in self.attempts]
        return sum(v for v in values if v is not None)


def closest_shape(shape):
    """The shape code draws for the model's word for the real shape (CLOSEST_SHAPES), or None."""
    return next((CLOSEST_SHAPES[word] for word in re.findall(r"[a-z]+", shape) if word in CLOSEST_SHAPES), None)


def redraw(raw_spec, spec, shape):
    """raw_spec with its product drawn as `shape` instead: the same size, colour and
    finish, and the cap or lid colour if the model gave one."""
    old = spec["shape"]
    fields = spec[old]
    product = {"diameter_cm": fields.get("diameter_cm", fields.get("width_cm")), "height_cm": fields["height_cm"],
               "colour": fields["colour"], "roughness": fields["roughness"]}
    cap = CAP_FIELDS.get(old)
    if cap and cap in raw_spec[old]:
        product[CAP_FIELDS[shape]] = fields[cap]
    redrawn = {key: value for key, value in raw_spec.items() if key not in SHAPES}
    redrawn.update({"shape": shape, shape: product})
    return redrawn


def parse_reply(text):
    """Turn the model's reply into a dict: spec, unsupported, model_unsupported,
    is_box, shape, shape_added, backdrop_given, cap_given, shape_fixed.

    The spec is validated by spec.validate_spec, with defaults filled in. The
    rest is kept apart from it: it is reported to the user and never reaches
    the renderer. Raises SpecError listing every problem found.

    Three rules apply to the model's reply only, not to a spec file: the spec
    must give the object of its own shape (a spec file may leave it out and
    get the defaults; the model must choose the sizes), a box (is_box true)
    is drawn as a box, and a real shape the prompt gives a closest shape for
    (a tube or a can: a cylinder) is drawn in that shape (shape_fixed).

    When the real shape isn't the one drawn (a squeeze tube drawn as a
    cylinder), it always goes first in the unsupported list. The model names
    the shape in its own field; a small model often forgets to also list it
    once something else (a logo, a label) is unsupported, so the code adds it.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError([f"Not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}"])
    if not isinstance(data, dict):
        raise SpecError(['The reply must be a JSON object: '
                         '{ "is_box": ..., "shape": ..., "unsupported": [...], "spec": {...} }'])

    problems = []
    is_box = data.get("is_box")
    if not isinstance(is_box, bool):
        problems.append(f"is_box: must be true or false, got {json.dumps(is_box)}")
    shape = data.get("shape")
    if not isinstance(shape, str):
        problems.append(f'shape: must be text like "box" or "bottle", got {json.dumps(shape)}')
        shape = ""
    shape = shape.strip().lower()
    unsupported = data.get("unsupported")
    if not (isinstance(unsupported, list) and all(isinstance(u, str) for u in unsupported)):
        problems.append('unsupported: must be a list of short texts, e.g. ["gold logo"]')
        unsupported = []
    raw_spec = data.get("spec")
    if not isinstance(raw_spec, dict):
        problems.append('spec: must be an object like { "box": {...}, ... }')
        raw_spec = None

    spec = None
    if raw_spec is not None:
        drawn = raw_spec.get("shape", "box")
        if drawn in SHAPES and drawn not in raw_spec:
            problems.append(f'{drawn}: missing. The shape is "{drawn}", so its size, colour and finish '
                            f'go in "{drawn}".')
        if is_box is True and drawn in SHAPES and drawn != "box":
            problems.append(f'shape: is_box is true, so the shape is "box", got "{drawn}". '
                            "If the product isn't a box, set is_box to false.")
        try:
            spec = validate_spec(raw_spec)
        except SpecError as e:
            problems += e.problems
    if problems:
        raise SpecError(problems)

    shape_fixed = None
    closest = closest_shape(shape)
    if not is_box and closest and spec["shape"] != closest:
        shape_fixed = {"real": shape, "from": spec["shape"], "to": closest}
        raw_spec = redraw(raw_spec, spec, closest)
        spec = validate_spec(raw_spec)

    # Tidy the list: no blanks, no repeats.
    cleaned = []
    for item in unsupported:
        item = item.strip()
        if item and item.lower() not in (c.lower() for c in cleaned):
            cleaned.append(item)

    final = list(cleaned)
    shape_added = False
    if not is_box and spec["shape"] not in shape:  # "perfume bottle" is drawn as a bottle
        named = shape if shape and shape != "box" else "non-box"
        if not any(named in item.lower() for item in final):
            final.insert(0, f"{named} shape")
            shape_added = True
    # The model may leave the backdrop out (when the sentence names none),
    # and the cap or lid colour (when the sentence names none).
    backdrop_given = "background_colour" in raw_spec
    cap = CAP_FIELDS.get(spec["shape"])
    cap_given = cap in raw_spec[spec["shape"]] if cap else None
    return {"spec": spec, "unsupported": final, "model_unsupported": cleaned, "is_box": is_box,
            "shape": shape, "shape_added": shape_added, "backdrop_given": backdrop_given,
            "cap_given": cap_given, "shape_fixed": shape_fixed}


def write_spec(sentence, backend, max_attempts=MAX_ATTEMPTS, report=None, grounding=True, tables=None):
    """Run the LLM + validation loop. Returns a SpecResult (check .ok).

    With grounding on, the rows of the data/ tables that match the
    sentence's words are added to the request, and code then applies the
    style shift, the glossy finish, the neutral backdrop, the default cap
    or lid colour and the metal of a cap or lid (see grounding.py), holds a
    round shape's proportions to spec.PROPORTION_LIMITS, and draws the
    sentence's quoted text as a label (labels.py). The model and the tables
    get the sentence without its quoted text and that text's colour
    (labels.read_label: a sentence without quotes is sent as it is). With
    grounding off, the model gets the whole sentence and decides everything
    but parse_reply's rules on its own: no label is drawn. `tables`
    replaces the data/ tables (e.g. without the colour table).

    report(event, attempt) is called with "start" before each LLM call and
    "done" after it, so the caller can show progress. Backend errors
    (BackendUnavailable, RuntimeError) are not caught here.
    """
    label = read_label(sentence) if grounding else None
    sentence = label.model_sentence if label else sentence
    found = lookup(sentence, tables) if grounding else Grounding([])
    attempts = []
    previous_output = previous_errors = None
    for number in range(1, max_attempts + 1):
        if report:
            report("start", Attempt(number, None, previous_errors or []))
        reply = backend.generate_spec(sentence, previous_errors, previous_output, found.text or None)
        try:
            parsed = parse_reply(reply.text)
            errors = []
        except SpecError as e:
            errors = e.problems
        attempt = Attempt(number, reply, errors)
        attempts.append(attempt)
        if report:
            report("done", attempt)
        if not errors:
            # Code sets what the model can't be relied on for (see grounding.py).
            changes = style_box_colour(sentence, parsed["spec"], found)
            backdrop = finish = cap = metal = clamps = label_change = None
            if grounding:
                clamps = clamp_proportions(parsed["spec"])
                backdrop = neutral_backdrop(sentence, parsed["spec"], parsed["backdrop_given"])
                finish = apply_finish(sentence, parsed["spec"], tables)
                cap = default_cap(sentence, parsed["spec"], parsed["cap_given"])
                metal = apply_metal(sentence, parsed["spec"])
                # Last: a label's default colour depends on the product's final colour.
                label_change, listed = apply_label(label, parsed["spec"])
                parsed["unsupported"] += listed
            return SpecResult(attempts, grounding=found, style_changes=changes, backdrop_change=backdrop,
                              finish_change=finish, cap_change=cap, metal_change=metal,
                              proportion_changes=clamps, label_change=label_change, model_sentence=sentence,
                              **parsed)
        previous_output, previous_errors = reply.text, errors
    return SpecResult(attempts, grounding=found, model_sentence=sentence)
