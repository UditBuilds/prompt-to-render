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

from spec import SpecError, validate_spec

MAX_ATTEMPTS = 2


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
    def __init__(self, attempts, spec=None, unsupported=None, is_box=None, shape=None,
                 shape_added=False):
        self.attempts = attempts
        self.spec = spec                    # full validated spec, or None
        self.unsupported = unsupported or []
        self.is_box = is_box
        self.shape = shape
        self.shape_added = shape_added      # True if the code added the shape to `unsupported`

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


def parse_reply(text):
    """Turn the model's reply into a dict: spec, unsupported, is_box, shape, shape_added.

    The spec is validated by spec.validate_spec, with defaults filled in. The
    rest is kept apart from it: it is reported to the user and never reaches
    the renderer. Raises SpecError listing every problem found.

    When the object isn't a box, its shape always goes first in the
    unsupported list. The model names the shape in its own field; a small
    model often forgets to also list it once something else (a logo, a
    label) is unsupported, so the code adds it.
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
        try:
            spec = validate_spec(raw_spec)
        except SpecError as e:
            problems += e.problems
    if problems:
        raise SpecError(problems)

    # Tidy the list: no blanks, no repeats.
    cleaned = []
    for item in unsupported:
        item = item.strip()
        if item and item.lower() not in (c.lower() for c in cleaned):
            cleaned.append(item)

    shape_added = False
    if not is_box:
        named = shape if shape and shape != "box" else "non-box"
        if not any(named in item.lower() for item in cleaned):
            cleaned.insert(0, f"{named} shape")
            shape_added = True
    return {"spec": spec, "unsupported": cleaned, "is_box": is_box, "shape": shape,
            "shape_added": shape_added}


def write_spec(sentence, backend, max_attempts=MAX_ATTEMPTS, report=None):
    """Run the LLM + validation loop. Returns a SpecResult (check .ok).

    report(event, attempt) is called with "start" before each LLM call and
    "done" after it, so the caller can show progress. Backend errors
    (BackendUnavailable, RuntimeError) are not caught here.
    """
    attempts = []
    previous_output = previous_errors = None
    for number in range(1, max_attempts + 1):
        if report:
            report("start", Attempt(number, None, previous_errors or []))
        reply = backend.generate_spec(sentence, previous_errors, previous_output)
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
            return SpecResult(attempts, **parsed)
        previous_output, previous_errors = reply.text, errors
    return SpecResult(attempts)
