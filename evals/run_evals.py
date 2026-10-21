"""
Evals for the spec writer: does the LLM turn sentences into the right specs?

    python evals/run_evals.py                    every case x 3 runs, specs only (no rendering)
    python evals/run_evals.py --label grounded   name the results file
    python evals/run_evals.py --render           also render one spec per case
    python evals/run_evals.py --model llama3.1:8b
    python evals/run_evals.py --runs 1 --cases red_lipstick,vague

Every case in evals/cases.json goes through the same LLM + validation loop as
prompt.py, several times (the model samples at temperature 0.2, so runs can
differ). The checks are ranges, not exact values, e.g. "glossy" means
roughness <= 0.05, and named colours must fit evals/colour_definitions.json.
A run passes when it produced a valid spec within 2 attempts AND every check
passes.

Reports the pass rate per case and overall, the named-colour score of the
in-table and out-of-table colour cases separately, the shape scores (the
out-of-table products apart), the unsupported lists, the rules code decides,
how often the retry loop fired, the average LLM time and the peak GPU memory.
Results are saved to evals/results/<timestamp>_<label>.json, with a Markdown
summary next to it.
"""

import argparse
import colorsys
import copy
import json
import os
import re
import sys
import time
from datetime import datetime

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(EVALS_DIR))

import gpu  # noqa: E402
import shapes  # noqa: E402
from check_colour import hex_to_lab  # noqa: E402
from grounding import TABLES, load_tables  # noqa: E402
from llm_backend import DEFAULT_MODEL, BackendUnavailable, OllamaBackend  # noqa: E402
from run import PROJECT_DIR, find_blender, render  # noqa: E402
from spec_writer import MAX_ATTEMPTS, write_spec  # noqa: E402

CASES_PATH = os.path.join(EVALS_DIR, "cases.json")
COLOURS_PATH = os.path.join(EVALS_DIR, "colour_definitions.json")
RESULTS_DIR = os.path.join(EVALS_DIR, "results")

with open(COLOURS_PATH, encoding="utf-8") as _f:
    COLOUR_DEFINITIONS = json.load(_f)["colours"]


# ---------------------------------------------------------------------------
# Checks. Each takes (check, result, done) and returns (passed, what was found).
# `done` holds the cases finished so far, for checks that compare two cases.
# ---------------------------------------------------------------------------

def _rgb(hex_colour):
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hex_to_hsv(hex_colour):
    hue, saturation, value = colorsys.rgb_to_hsv(*_rgb(hex_colour))
    return hue * 360, saturation, value


def hex_to_hsl(hex_colour):
    """(hue in degrees, HSL saturation in %, HSL lightness in %), rounded to 6 decimals.

    Rounded so a colour exactly on a range's edge isn't pushed past it by
    floating point: #CC9966's lightness is exactly 60% (153/255), but
    computes as 60.00000000000001.
    """
    hue, lightness, saturation = colorsys.rgb_to_hls(*_rgb(hex_colour))
    return round(hue * 360, 6), round(saturation * 100, 6), round(lightness * 100, 6)


def in_range(value, check):
    """min/max are inclusive, gt/lt are strict."""
    return (("min" not in check or value >= check["min"])
            and ("max" not in check or value <= check["max"])
            and ("gt" not in check or value > check["gt"])
            and ("lt" not in check or value < check["lt"]))


def describe_range(check):
    parts = []
    for key, symbol in (("min", ">="), ("gt", ">"), ("max", "<="), ("lt", "<")):
        if key in check:
            parts.append(f"{symbol} {check[key]:g}")
    return " and ".join(parts)


def hue_in(hue, low, high):
    # A range like 345..15 wraps round through 0 (red).
    return low <= hue <= high if low <= high else (hue >= low or hue <= high)


def shape_of(spec):
    """The spec's shape. A spec without one (v1.3 and earlier) is a box, the default."""
    return spec.get("shape", "box")


def product_of(spec):
    """The fields of the spec's own shape: spec["box"] for a box, spec["cylinder"] for a cylinder, ..."""
    return spec[shape_of(spec)]


def box_of(result):
    """The box's fields, or None if the spec's shape isn't a box (then there are none)."""
    return result.spec["box"] if shape_of(result.spec) == "box" else None


def not_a_box(result):
    return False, f"shape {shape_of(result.spec)}, not a box: no box sides to check"


# The field holding the cap or lid colour, per shape. Other shapes have none.
CAP_FIELDS = {"cylinder": "cap_colour", "bottle": "cap_colour", "jar": "lid_colour"}
# The field naming the metal a cap or lid is drawn in (v2 step 2). Code sets
# it from the sentence; a spec without it has no metal part.
METAL_FIELDS = {"cylinder": "cap_metal", "bottle": "cap_metal", "jar": "lid_metal"}


def colour_of(check, result):
    """(where, colour): the product's colour, the backdrop's with "target": "background",
    or the cap's or lid's with "target": "cap" (colour None if the shape has no cap)."""
    if check.get("target") == "background":
        return "backdrop", result.spec["background_colour"]
    shape = shape_of(result.spec)
    if check.get("target") == "cap":
        field = CAP_FIELDS.get(shape)
        return f"{shape} {field or 'cap'}", product_of(result.spec).get(field) if field else None
    return shape, product_of(result.spec)["colour"]


def no_colour(where):
    return False, f"no {where}: this shape has none"


def check_hue(check, result, done):
    where, colour = colour_of(check, result)
    if colour is None:
        return no_colour(where)
    hue = hex_to_hsv(colour)[0]
    return (hue_in(hue, check["min"], check["max"]),
            f"hue {hue:.0f} deg of {where} {colour} (want {check['min']}..{check['max']})")


def check_saturation(check, result, done):
    where, colour = colour_of(check, result)
    if colour is None:
        return no_colour(where)
    saturation = hex_to_hsv(colour)[1]
    return in_range(saturation, check), f"saturation {saturation:.2f} of {where} {colour} (want {describe_range(check)})"


def check_lightness(check, result, done):
    where, colour = colour_of(check, result)
    if colour is None:
        return no_colour(where)
    lightness = hex_to_lab(colour)[0]
    return in_range(lightness, check), f"L* {lightness:.0f} of {where} {colour} (want {describe_range(check)})"


def check_named_colour(check, result, done):
    """The colour must fit evals/colour_definitions.json for that name.

    A definition with "space": "hsl" is in HSL (saturation and lightness in
    %); the others use HSV hue and saturation (0-1) and CIE L*.
    """
    name = check["name"]
    definition = COLOUR_DEFINITIONS[name]
    where, colour = colour_of(check, result)
    if colour is None:
        return no_colour(where)
    if definition.get("space") == "hsl":
        hue, saturation, lightness = hex_to_hsl(colour)
        names = ("HSL saturation", "HSL lightness")
        show_s, show_l = f"{saturation:.0f}%", f"{lightness:.0f}%"
    else:
        hue, saturation, _ = hex_to_hsv(colour)
        lightness = hex_to_lab(colour)[0]
        names = ("saturation", "L*")
        show_s, show_l = f"{saturation:.2f}", f"{lightness:.0f}"
    (h_lo, h_hi), (s_lo, s_hi), (l_lo, l_hi) = definition["hue"], definition["saturation"], definition["lightness"]
    misses = []
    if not hue_in(hue, h_lo, h_hi):
        misses.append(f"hue {hue:.0f} not in {h_lo}..{h_hi}")
    if not s_lo <= saturation <= s_hi:
        misses.append(f"{names[0]} {show_s} not in {s_lo:g}..{s_hi:g}")
    if not l_lo <= lightness <= l_hi:
        misses.append(f"{names[1]} {show_l} not in {l_lo}..{l_hi}")
    detail = "; ".join(misses) if misses else f"hue {hue:.0f}, {names[0]} {show_s}, {names[1]} {show_l}"
    return not misses, f"{where} {colour} as {name}: {detail}"


def check_neutral_backdrop(check, result, done):
    """A sentence that names no backdrop must get a neutral one: near-grey and light.

    Near-grey: the R, G and B values (0-255) differ by at most max_spread, so
    a warm off-white passes and a pale tint doesn't. (HSL saturation can't
    tell them apart: near white, any tint at all reads as highly saturated.)
    """
    colour = result.spec["background_colour"]
    rgb = [round(c * 255) for c in _rgb(colour)]
    spread = max(rgb) - min(rgb)
    lightness = hex_to_hsl(colour)[2]
    ok = spread <= check["max_spread"] and lightness >= check["min_lightness"]
    return ok, (f"backdrop {colour}: RGB spread {spread}, HSL lightness {lightness:.0f}% "
                f"(want spread <= {check['max_spread']}, lightness >= {check['min_lightness']}%)")


def check_hex(check, result, done):
    where, colour = colour_of(check, result)
    if colour is None:
        return no_colour(where)
    return colour.upper() == check["equals"].upper(), f"{where} colour {colour} (want {check['equals']})"


def check_roughness(check, result, done):
    roughness = product_of(result.spec)["roughness"]
    return in_range(roughness, check), f"roughness {roughness:g} (want {describe_range(check)})"


def check_camera(check, result, done):
    camera = result.spec["camera"]
    return camera == check["equals"], f"camera {camera} (want {check['equals']})"


def check_ratio(check, result, done):
    box = box_of(result)
    if box is None:
        return not_a_box(result)
    ratio = box[check["num"]] / box[check["den"]]
    return in_range(ratio, check), (f"{check['num']}/{check['den']} = {box[check['num']]:g}/{box[check['den']]:g} "
                                    f"= {ratio:.2f} (want {describe_range(check)})")


def check_size(check, result, done):
    box = box_of(result)
    if box is None:
        return not_a_box(result)
    sides = [box["width_cm"], box["height_cm"], box["depth_cm"]]
    side = max(sides) if check["side"] == "longest" else min(sides)
    return in_range(side, check), f"{check['side']} side {side:g} cm (want {describe_range(check)})"


def check_dimension(check, result, done):
    box = box_of(result)
    if box is None:
        return not_a_box(result)
    value = box[check["field"]]
    return in_range(value, check), f"{check['field']} {value:g} cm (want {describe_range(check)})"


def check_top_aspect(check, result, done):
    """Long side / short side of the top face (width x depth)."""
    box = box_of(result)
    if box is None:
        return not_a_box(result)
    width, depth = box["width_cm"], box["depth_cm"]
    aspect = max(width, depth) / min(width, depth)
    return (in_range(aspect, check),
            f"top face {width:g} x {depth:g} cm, aspect {aspect:.2f} (want {describe_range(check)})")


def check_is_box(check, result, done):
    return result.is_box == check["equals"], f"is_box {json.dumps(result.is_box)} (want {json.dumps(check['equals'])})"


def check_shape_contains(check, result, done):
    shape = (result.shape or "").lower()
    ok = any(word in shape for word in check["any"])
    return ok, f"shape {json.dumps(result.shape)} (want it to contain {' or '.join(check['any'])})"


def check_model_unsupported_mentions(check, result, done):
    """Only the model's own list counts, not items the code added."""
    text = " | ".join(result.model_unsupported).lower()
    ok = any(word in text for word in check["any"])
    return ok, (f"model's own unsupported list {json.dumps(result.model_unsupported)} "
                f"(want a mention of {' or '.join(check['any'])})")


def check_model_unsupported_excludes(check, result, done):
    """The model must not list these as unsupported (e.g. a cap or lid, which v2 draws)."""
    text = " | ".join(result.model_unsupported).lower()
    found = [word for word in check["any"] if word in text]
    return not found, (f"model's own unsupported list {json.dumps(result.model_unsupported)} "
                       f"(want no mention of {' or '.join(check['any'])})")


def check_shape(check, result, done):
    """The shape the spec draws (box, cylinder, bottle or jar), not the model's free-text shape."""
    shape = shape_of(result.spec)
    return shape == check["equals"], f"spec shape {shape} (want {check['equals']})"


def check_shape_size(check, result, done):
    """A size field of the spec's own shape. A shape without that field fails: a box has no diameter_cm."""
    shape, fields = shape_of(result.spec), product_of(result.spec)
    if check["field"] not in fields:
        return False, f"shape {shape} has no {check['field']} (want {describe_range(check)})"
    value = fields[check["field"]]
    return in_range(value, check), f"{shape} {check['field']} {value:g} cm (want {describe_range(check)})"


def check_shape_ratio(check, result, done):
    shape, fields = shape_of(result.spec), product_of(result.spec)
    missing = [f for f in (check["num"], check["den"]) if f not in fields]
    if missing:
        return False, (f"shape {shape} has no {' or '.join(missing)} "
                       f"(want {check['num']}/{check['den']} {describe_range(check)})")
    ratio = fields[check["num"]] / fields[check["den"]]
    return in_range(ratio, check), (f"{shape} {check['num']}/{check['den']} = {fields[check['num']]:g}/"
                                    f"{fields[check['den']]:g} = {ratio:.2f} (want {describe_range(check)})")


def round_parts(result):
    """(shape, the names of the parts the renderer draws), from shapes.py. A box is one part."""
    shape = shape_of(result.spec)
    if shape == "box":
        return shape, ["Box"]
    return shape, [part.name for part in shapes.parts(shape, product_of(result.spec))]


def check_cap_part(check, result, done):
    """The product is drawn with a separate cap or lid (e.g. a lipstick: base + cap). Decided by code."""
    shape, names = round_parts(result)
    return (any(name in ("Cap", "Lid") for name in names),
            f"{shape} drawn as {' + '.join(names)} (want a cap or lid part)")


def check_lid_share(check, result, done):
    """The lid's height as a share of the whole jar's, measured on the profile the renderer draws. Decided by code.

    Rounded to 6 decimals, like hex_to_hsl, so a lid exactly on a range's
    edge isn't pushed past it by floating point: a lid of 0.30 of a 3.5 cm
    jar computes as 0.30000000000000004, of a 4.5 cm jar as 0.3.
    """
    shape = shape_of(result.spec)
    lid = None
    if shape != "box":
        lid = next((p for p in shapes.parts(shape, product_of(result.spec)) if p.name == "Lid"), None)
    if lid is None:
        return False, f"shape {shape} has no lid (want lid share {describe_range(check)})"
    heights = [z for _, z in lid.profile]
    share = round((max(heights) - min(heights)) / (product_of(result.spec)["height_cm"] / 100), 6)
    return in_range(share, check), f"lid {share:.3f} of the jar's height (want {describe_range(check)})"


def check_metal(check, result, done):
    """The metal the cap or lid is drawn in, null for none. Set by code from the sentence, never by the model.

    A spec without the field (v2 step 1 and earlier) has no metal part.
    """
    shape = shape_of(result.spec)
    field = METAL_FIELDS.get(shape)
    if field is None:
        return False, f"shape {shape} has no cap or lid (want metal {json.dumps(check['equals'])})"
    metal = product_of(result.spec).get(field)
    return metal == check["equals"], f"{shape} {field} {json.dumps(metal)} (want {json.dumps(check['equals'])})"


def check_unsupported_empty(check, result, done):
    return not result.unsupported, f"unsupported {json.dumps(result.unsupported)} (want [])"


def check_style_shift(check, result, done):
    """Compare the box colour with another case's (e.g. "a luxury red box" vs "a red box").

    The reference is the mean L* and saturation over that case's valid runs.
    The colour is the product's, whatever its shape.
    The colour must move in the given direction by at least min_lightness L*
    OR by min_saturation of saturation.
    """
    reference = done.get(check["than"])
    colours = [product_of(r["spec"])["colour"] for r in reference["runs"] if r["valid"]] if reference else []
    if not colours:
        return False, f"no valid spec from {check['than']} to compare with"
    ref_lightness = sum(hex_to_lab(c)[0] for c in colours) / len(colours)
    ref_saturation = sum(hex_to_hsv(c)[1] for c in colours) / len(colours)
    colour = product_of(result.spec)["colour"]
    lightness, saturation = hex_to_lab(colour)[0], hex_to_hsv(colour)[1]
    if check["direction"] == "darker_or_less_saturated":
        light_shift, sat_shift = ref_lightness - lightness, ref_saturation - saturation
        words = ("darker", "less saturated")
    else:  # lighter_or_more_saturated
        light_shift, sat_shift = lightness - ref_lightness, saturation - ref_saturation
        words = ("lighter", "more saturated")
    ok = light_shift >= check["min_lightness"] or sat_shift >= check["min_saturation"]
    return ok, (f"{colour} vs {check['than']} (mean L* {ref_lightness:.0f}, saturation {ref_saturation:.2f}): "
                f"{light_shift:+.0f} L* {words[0]}, {sat_shift:+.2f} {words[1]} "
                f"(want >= {check['min_lightness']} L* {words[0]} or >= {check['min_saturation']} {words[1]})")


CHECKS = {
    "hue": check_hue,
    "saturation": check_saturation,
    "lightness": check_lightness,
    "named_colour": check_named_colour,
    "neutral_backdrop": check_neutral_backdrop,
    "hex": check_hex,
    "roughness": check_roughness,
    "camera": check_camera,
    "ratio": check_ratio,
    "size": check_size,
    "dimension": check_dimension,
    "top_aspect": check_top_aspect,
    "is_box": check_is_box,
    "shape_contains": check_shape_contains,
    "model_unsupported_mentions": check_model_unsupported_mentions,
    "model_unsupported_excludes": check_model_unsupported_excludes,
    "unsupported_empty": check_unsupported_empty,
    "shape": check_shape,
    "shape_size": check_shape_size,
    "shape_ratio": check_shape_ratio,
    "style_shift": check_style_shift,
    "cap_part": check_cap_part,
    "lid_share": check_lid_share,
    "metal": check_metal,
}


def run_checks(case, result, done=None):
    """Returns a list of {check, passed, found}. An invalid spec fails outright."""
    if not result.ok:
        return [{"check": "valid spec", "passed": False,
                 "found": f"no valid spec in {MAX_ATTEMPTS} attempts: {result.errors}"}]
    outcomes = []
    for check in case["checks"]:
        passed, found = CHECKS[check["type"]](check, result, done or {})
        outcomes.append({"check": check["type"], "passed": passed, "found": found})
    return outcomes


def unclamped_spec(spec, changes):
    """The spec as the model wrote it, before code clamped its proportions (v2 step 3).

    `changes` is the run's proportion_changes: {"rule", "field", "from", "to"}
    per clamp, in the order they fired, each on a field of the spec's own shape.
    """
    spec = json.loads(json.dumps(spec))
    for change in reversed(changes):
        product_of(spec)[change["field"]] = change["from"]
    return spec


def checks_without_clamps(case, result, changes, done=None):
    """The checks run again on the spec before any proportion clamp, or None if no clamp fired.

    A run that passes with the clamps but not without them passed only
    because code clamped a size: that is code's pass, not the model's.
    """
    if not (result.ok and changes):
        return None
    model = copy.copy(result)
    model.spec = unclamped_spec(result.spec, changes)
    return run_checks(case, model, done)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Run the spec-writer evals.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--runs", type=int, default=3, help="runs per case (default: 3)")
    parser.add_argument("--label", help='a name for this run, e.g. "baseline"; added to the file name')
    parser.add_argument("--no-grounding", action="store_true",
                        help="don't add the matching rows of the data/ tables to the requests, "
                             "and don't let code set any value")
    parser.add_argument("--without-table", action="append", default=[], choices=sorted(TABLES),
                        help="leave one data/ table out of grounding, e.g. colours (code rules stay on)")
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--cases-file", default=CASES_PATH,
                        help="another cases file, e.g. evals/dev_cases.json; its results go to runs/dev_evals/")
    parser.add_argument("--render", action="store_true", help="also render one spec per case (after unloading the model)")
    parser.add_argument("--blender", help="path to blender.exe (for --render)")
    args = parser.parse_args()

    try:
        cases = load_cases(args.cases.split(",") if args.cases else None, args.cases_file)
    except ValueError as e:
        print(e)
        return 2

    blender = None
    if args.render:
        blender = find_blender(args.blender)
        if not blender:
            print("--render: could not find blender.exe. Pass --blender or set BLENDER_PATH.")
            return 1

    backend = OllamaBackend(args.model)
    try:
        backend.check()
        print(f"Model: {backend.describe()}")
        print(f"Loading the model ... {backend.load():.1f} s (not counted in the LLM times below)")
    except BackendUnavailable as e:
        print(e)
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.label:
        stamp += "_" + re.sub(r"[^A-Za-z0-9-]+", "-", args.label)
    print(f"{len(cases)} cases x {args.runs} runs\n")
    tables = {name: rows for name, rows in load_tables().items() if name not in args.without_table}
    results = []
    done = {}
    stopped_early = None
    started = time.perf_counter()
    memory = gpu.PeakMemory()
    try:
        with memory:
            for case in cases:
                results.append(run_case(case, backend, args.runs, done, not args.no_grounding, tables))
                done[case["id"]] = results[-1]
    except (BackendUnavailable, RuntimeError, KeyboardInterrupt) as e:
        # Keep what was collected so far rather than losing it all.
        stopped_early = str(e) or type(e).__name__
        print(f"\nStopped early: {stopped_early}")
    finally:
        try:
            backend.release()
        except (BackendUnavailable, RuntimeError):
            pass
    eval_seconds = time.perf_counter() - started
    if not results:
        print("No case finished, so there are no results to save.")
        return 1

    summary = summarise(results, memory.peak)
    report = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "label": args.label,
        "cases_file": os.path.relpath(args.cases_file, PROJECT_DIR),
        "grounding": not args.no_grounding,
        "without_tables": args.without_table,
        "model": backend.model,
        "backend": backend.name,
        "llm_settings": backend.settings(),
        "runs_per_case": args.runs,
        "max_attempts": MAX_ATTEMPTS,
        "eval_seconds": round(eval_seconds, 1),
        "stopped_early": stopped_early,
        "summary": summary,
        "cases": results,
    }

    if args.render:
        report["renders"] = render_cases(results, blender, stamp)

    # Only the frozen eval set is saved with the project; other case files
    # (the dev set) go to the git-ignored runs/ folder.
    is_eval_set = os.path.abspath(args.cases_file) == os.path.abspath(CASES_PATH)
    results_dir = RESULTS_DIR if is_eval_set else os.path.join(PROJECT_DIR, "runs", "dev_evals")
    os.makedirs(results_dir, exist_ok=True)
    json_path = os.path.join(results_dir, f"{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    table = markdown_table(report)
    with open(os.path.join(results_dir, f"{stamp}.md"), "w", encoding="utf-8") as f:
        f.write(table)

    print()
    print(table)
    print(f"Saved: {os.path.relpath(json_path, PROJECT_DIR)} (and .md)")
    return 1 if stopped_early else 0


def load_cases(wanted=None, path=CASES_PATH):
    """The cases from cases.json (or another file), optionally only some ids.

    A case may compare itself with an earlier one (style_shift); that case is
    always run too, before it.
    """
    with open(path, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    ids = [c["id"] for c in cases]
    for i, case in enumerate(cases):
        for check in case["checks"]:
            if "than" in check and check["than"] not in ids[:i]:
                raise ValueError(f"{case['id']}: compares with {check['than']}, which must be an earlier case")
    if wanted is None:
        return cases
    unknown = set(wanted) - set(ids)
    if unknown:
        raise ValueError(f"Unknown case id(s): {', '.join(sorted(unknown))}")
    keep = set(wanted)
    for case in reversed(cases):
        if case["id"] in keep:
            keep.update(check["than"] for check in case["checks"] if "than" in check)
    return [c for c in cases if c["id"] in keep]


def run_case(case, backend, runs, done=None, grounding=True, tables=None):
    print(f"{case['id']}: \"{case['sentence']}\"")
    case_runs = []
    for n in range(1, runs + 1):
        result = write_spec(case["sentence"], backend, grounding=grounding, tables=tables)
        outcomes = run_checks(case, result, done)
        passed = all(o["passed"] for o in outcomes)
        # v2 step 3: the sizes code clamped ({"rule", "field", "from", "to"}), and the
        # checks on the spec before them (None if no clamp fired).
        clamps = getattr(result, "proportion_changes", None) or []
        unclamped = checks_without_clamps(case, result, clamps, done)
        retry_note = ", retried" if result.retried else ""
        print(f"  run {n}: {'PASS' if passed else 'FAIL'}  "
              f"({len(result.attempts)} attempt{'s' if result.retried else ''}{retry_note}, "
              f"{result.total('seconds'):.1f} s)")
        for o in outcomes:
            if not o["passed"]:
                print(f"         x {o['found']}")
        if passed and unclamped and not all(o["passed"] for o in unclamped):
            print("         (passed only because code clamped a size)")
        case_runs.append({
            "run": n,
            "passed": passed,
            "attempts": len(result.attempts),
            "retried": result.retried,
            "valid": result.ok,
            "llm_seconds": round(result.total("seconds"), 2),
            "prompt_tokens": result.total("prompt_tokens"),
            "output_tokens": result.total("output_tokens"),
            "call_prompt_tokens": [a.reply.prompt_tokens for a in result.attempts],
            "checks": outcomes,
            "is_box": result.is_box,
            "shape": result.shape,
            "unsupported": result.unsupported,
            "model_unsupported": result.model_unsupported,
            "shape_added_by_code": result.shape_added,
            "grounding_rows": [{"table": r["table"], "name": r["name"], "matched": r["matched"]}
                               for r in result.grounding.rows],
            "style_changes": result.style_changes,
            "finish_change": result.finish_change,
            "backdrop_change": result.backdrop_change,
            "backdrop_given": result.backdrop_given,
            "cap_change": result.cap_change,
            "cap_given": result.cap_given,
            # v2 step 2: the metal code gave a cap or lid ({"field", "metal"}), None if none.
            "metal_change": getattr(result, "metal_change", None),
            # v2 step 2: a tube or can code redrew as a cylinder ({"real", "from", "to"}), None if none.
            "shape_fixed": getattr(result, "shape_fixed", None),
            # v2 step 3: proportion clamps, and whether the run passes without them (None: no clamp fired).
            "proportion_changes": clamps,
            # v2 step 3: the model's own colours (hue, saturation, lightness), and the
            # exact hex codes code copied from the sentence ({"field", "from", "to"}).
            "model_colours": getattr(result, "model_colours", None),
            "hex_changes": getattr(result, "hex_changes", None) or [],
            "checks_without_clamps": unclamped,
            "passed_without_clamps": None if unclamped is None else all(o["passed"] for o in unclamped),
            "spec": result.spec,
            "validation_errors": [a.errors for a in result.attempts],
            "outputs": [a.reply.text for a in result.attempts],
        })
    passes = sum(r["passed"] for r in case_runs)
    # At a low temperature the runs often come out identical. Counting the
    # distinct specs shows how much the runs actually varied.
    distinct = len({json.dumps(r["spec"], sort_keys=True) for r in case_runs if r["valid"]})
    return {"id": case["id"], "sentence": case["sentence"], "covers": case.get("covers", ""),
            "colour_group": case.get("colour_group"), "shape_group": case.get("shape_group"),
            "added": case.get("added"),
            "checks": case["checks"], "passed_runs": passes,
            "total_runs": len(case_runs), "distinct_specs": distinct, "runs": case_runs}


# colour_group in cases.json -> how the summary names it. The five held-out
# names of v1.1 and the five of v2 step 3 are scored apart: the first five had
# been looked at across many sessions, so only the new five are fully clean.
COLOUR_GROUPS = {"in_table": "In-table colours", "out_of_table": "Out-of-table colours, old 5",
                 "out_of_table_new": "Out-of-table colours, new 5"}


def box_colour_passed(case, run):
    """Did the run pass the case's named-colour check on the box (the product, not its
    backdrop or cap)? None if the case has none.

    An invalid spec has no colour, so it counts as a fail.
    """
    index = next((i for i, c in enumerate(case["checks"])
                  if c["type"] == "named_colour" and c.get("target") is None), None)
    if index is None:
        return None
    return run["valid"] and run["checks"][index]["passed"]


def summarise_groups(results):
    """Per colour_group: the named-colour check on the box alone, and every check.

    The named-colour check alone is the headline: the other checks of these
    cases (e.g. the neutral backdrop) can be set by code, the colour of an
    out-of-table name can't.
    """
    groups = {}
    for group in COLOUR_GROUPS:
        cases = [c for c in results if c.get("colour_group") == group]
        runs = [(c, r) for c in cases for r in c["runs"]]
        if not runs:
            continue
        groups[group] = {
            "cases": len(cases),
            "total_runs": len(runs),
            "colour_passed_runs": sum(bool(box_colour_passed(c, r)) for c, r in runs),
            "passed_runs": sum(r["passed"] for _, r in runs),
        }
    return groups


# The check types behind the shape scores: the shape chosen, the sizes of
# that shape, and both in the same run (v2 step 3; only over the cases that
# check both, since a size check on the wrong shape reads that shape's
# fields). The products in no table and no prompt example (shape_group
# "out_of_table", v2 step 2) are scored apart: only they measure the model's
# own knowledge of shapes.
SHAPE_SCORES = {"choice": ("shape",), "sizes": ("shape_size", "shape_ratio"),
                "both": ("shape", "shape_size", "shape_ratio")}
SHAPE_SCORE_NAMES = {"choice": "Shape choice", "sizes": "Shape sizes",
                     "both": "Shape choice and sizes in the same run",
                     "oot_choice": "Out-of-table products: shape choice",
                     "oot_sizes": "Out-of-table products: shape sizes",
                     "oot_both": "Out-of-table products: shape and size in the same run"}
# Other checks scored on their own, over every case that has them. The rules
# code decides measure the code, not the model.
CHECK_SCORES = {"unsupported": ("model_unsupported_mentions", "model_unsupported_excludes"),
                "code_rules": ("cap_part", "lid_share", "metal")}
CHECK_SCORE_NAMES = {"unsupported": "Unsupported lists (the model's own)",
                     "code_rules": "Rules decided by code (metal cap or lid, cylinder cap, lid share)"}
# "added" in cases.json -> the summary's group, and how it is named.
ADDED_GROUPS = {"before_v2": (None, "Cases from before v2"), "v2": ("v2", "Cases added in v2"),
                "v2_step2": ("v2-step2", "Cases added in v2 step 2"),
                "v2_step3": ("v2-step3", "Cases added in v2 step 3")}


def checks_passed(case, run, types, unclamped=False):
    """Did the run pass every check of these types? None if the case has none.

    An invalid spec counts as a fail. With unclamped, the checks on the spec
    before code clamped its proportions (the same checks if no clamp fired).
    """
    indexes = [i for i, c in enumerate(case["checks"]) if c["type"] in types]
    if not indexes:
        return None
    checks = (unclamped and run.get("checks_without_clamps")) or run["checks"]
    return run["valid"] and all(checks[i]["passed"] for i in indexes)


def clamp_only(run):
    """True if the run passed only because code clamped a size: it fails on the spec before the clamps."""
    return run["passed"] and run.get("passed_without_clamps") is False


def score(results, types):
    """Runs passing every check of these types, over the cases that have any. None if no case has one.

    clamp_only_runs: of those passes, the ones that pass only because code
    clamped a size. They count for the code, not the model.
    """
    runs = [(c, r) for c in results for r in c["runs"] if checks_passed(c, r, types) is not None]
    if not runs:
        return None
    return {"cases": len({c["id"] for c, _ in runs}), "total_runs": len(runs),
            "passed_runs": sum(bool(checks_passed(c, r, types)) for c, r in runs),
            "clamp_only_runs": sum(bool(checks_passed(c, r, types)) and not checks_passed(c, r, types, True)
                                   for c, r in runs)}


def summarise_shapes(results):
    """The shape checks alone, the size checks alone, and both in the same run, over the cases
    that have them; the out-of-table products ("oot_choice", "oot_sizes", "oot_both") apart
    from the others.

    Counted like the named-colour check of the colour groups: the other
    checks of these cases (e.g. the neutral backdrop) are set by code.
    """
    groups = {"": [c for c in results if c.get("shape_group") != "out_of_table"],
              "oot_": [c for c in results if c.get("shape_group") == "out_of_table"]}
    scores = {}
    for prefix, cases in groups.items():
        for name, types in SHAPE_SCORES.items():
            scored = cases
            if name == "both":
                scored = [c for c in cases if "shape" in check_types(c)
                          and {"shape_size", "shape_ratio"} & check_types(c)]
            found = score(scored, types)
            if found:
                scores[prefix + name] = found
    return scores


def check_types(case):
    return {c["type"] for c in case["checks"]}


def summarise_checks(results):
    """CHECK_SCORES: each set of check types alone, over every case that has them."""
    scores = {name: score(results, types) for name, types in CHECK_SCORES.items()}
    return {name: found for name, found in scores.items() if found}


def summarise_added(results):
    """Every check, for the cases from before v2, those v2 added and those v2 step 2 added, separately.

    The cases from before v2 and the ones v2 added are the regression gate: they must not get worse.
    """
    groups = {}
    for name, (added, _) in ADDED_GROUPS.items():
        cases = [c for c in results if c.get("added") == added]
        if cases:
            groups[name] = {"cases": len(cases), "total_runs": sum(c["total_runs"] for c in cases),
                            "passed_runs": sum(c["passed_runs"] for c in cases),
                            "clamp_only_runs": sum(clamp_only(r) for c in cases for r in c.get("runs", []))}
    return groups


def summarise(results, peak_gpu_mib=None):
    runs = [r for case in results for r in case["runs"]]
    total = len(runs)
    return {
        "colour_groups": summarise_groups(results),
        "shape_scores": summarise_shapes(results),
        "check_scores": summarise_checks(results),
        "added_groups": summarise_added(results),
        "passed_runs": sum(r["passed"] for r in runs),
        "total_runs": total,
        "pass_rate": round(sum(r["passed"] for r in runs) / total, 3) if total else None,
        "cases_passing_all_runs": sum(c["passed_runs"] == c["total_runs"] for c in results),
        "cases_with_identical_runs": sum(c["distinct_specs"] == 1 for c in results),
        "total_cases": len(results),
        "retry_runs": sum(r["retried"] for r in runs),
        "retry_rate": round(sum(r["retried"] for r in runs) / total, 3) if total else None,
        "invalid_after_retries": sum(not r["valid"] for r in runs),
        # Runs where the "<shape> shape" item in unsupported came from the
        # code (from the model's shape field), not from the model's own list.
        "shape_added_by_code_runs": sum(bool(r.get("shape_added_by_code")) for r in runs),
        # v2 step 3: runs where code clamped a size, and the passes that hold only because of it.
        "clamp_runs": sum(bool(r.get("proportion_changes")) for r in runs),
        "clamp_only_runs": sum(clamp_only(r) for r in runs),
        "clamp_only": [f"{case['id']} run {r['run']}" for case in results for r in case["runs"] if clamp_only(r)],
        "avg_llm_seconds": round(sum(r["llm_seconds"] for r in runs) / total, 2) if total else None,
        "avg_prompt_tokens": round(sum(r["prompt_tokens"] for r in runs) / total) if total else None,
        # Per LLM call, not per run: a retry sends a longer prompt, and the
        # context limit applies to each call.
        "max_prompt_tokens_per_call": max(
            (max(r["call_prompt_tokens"]) for r in runs if r.get("call_prompt_tokens")), default=None),
        "avg_output_tokens": round(sum(r["output_tokens"] for r in runs) / total) if total else None,
        # Whole card (nvidia-smi), sampled while the cases ran: the model plus
        # the desktop's few hundred MiB. None if it wasn't measured.
        "peak_gpu_mib": peak_gpu_mib,
    }


def percent(part, total):
    """part/total as a whole percentage, rounded once from the counts (halves round up).

    Not from the stored pass_rate: that is already rounded to 3 decimals, and
    rounding it again turned 66/111 (59.46%) into 0.595 and then 60%.
    """
    return f"{(200 * part + total) // (2 * total)}%"


def clamped(group):
    """ ", N of them only because code clamped a size", or "" if none."""
    n = group.get("clamp_only_runs", 0)
    return f", {n} of them only because code clamped a size" if n else ""


def markdown_table(report):
    s = report["summary"]
    label = f"**{report['label']}**: " if report.get("label") else ""
    lines = [
        f"{label}model `{report['model']}` (Ollama, local), {report['runs_per_case']} runs per case, "
        f"{report['created'][:10]}.",
        "",
    ]
    if report.get("stopped_early"):
        lines += [f"**Incomplete:** the run stopped early ({report['stopped_early']}).", ""]
    lines += [
        "| Case | Sentence | Tests | Passed | Distinct specs | Failed checks |",
        "|---|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        failures = []
        for run in case["runs"]:
            for o in run["checks"]:
                if not o["passed"]:
                    failures.append(f"run {run['run']}: {o['found']}")
        lines.append(f"| `{case['id']}` | {case['sentence']} | {case['covers']} | "
                     f"{case['passed_runs']}/{case['total_runs']} | {case['distinct_specs']} | "
                     f"{'<br>'.join(failures) or '-'} |")
    lines += [
        "",
        f"- **Overall:** {s['passed_runs']}/{s['total_runs']} runs passed "
        f"({percent(s['passed_runs'], s['total_runs'])}){clamped(s)}; "
        f"{s['cases_passing_all_runs']}/{s['total_cases']} cases passed every run.",
    ]
    added = s.get("added_groups", {})
    if len(added) > 1:
        for name, (_, title) in ADDED_GROUPS.items():
            g = added.get(name)
            if g:
                lines.append(f"- **{title}** ({g['cases']} cases): {g['passed_runs']}/{g['total_runs']} runs "
                             f"passed ({percent(g['passed_runs'], g['total_runs'])}){clamped(g)}.")
    for group, g in s.get("colour_groups", {}).items():
        lines.append(f"- **{COLOUR_GROUPS[group]}** ({g['cases']} cases): the named-colour check passed in "
                     f"{g['colour_passed_runs']}/{g['total_runs']} runs; every check in "
                     f"{g['passed_runs']}/{g['total_runs']}.")
    for names, scores in ((SHAPE_SCORE_NAMES, s.get("shape_scores", {})),
                          (CHECK_SCORE_NAMES, s.get("check_scores", {}))):
        for name, g in scores.items():
            lines.append(f"- **{names[name]}** ({g['cases']} cases): passed in {g['passed_runs']}/"
                         f"{g['total_runs']} runs ({percent(g['passed_runs'], g['total_runs'])}){clamped(g)}.")
    if s.get("clamp_runs"):
        lines.append(f"- **Sizes clamped by code:** in {s['clamp_runs']}/{s['total_runs']} runs. Passed only "
                     f"because of a clamp (they fail on the model's own sizes): "
                     f"{', '.join(s['clamp_only']) or 'none'}.")
    lines += [
        f"- **Retry loop fired:** {s['retry_runs']}/{s['total_runs']} runs "
        f"({percent(s['retry_runs'], s['total_runs'])}); "
        f"still invalid after {report['max_attempts']} attempts: {s['invalid_after_retries']}.",
        f"- **Consistency:** {s['cases_with_identical_runs']}/{s['total_cases']} cases gave the same spec "
        f"in every run (temperature {report['llm_settings']['temperature']}).",
        f"- **Non-box shape listed by code, not by the model:** {s['shape_added_by_code_runs']} run(s). "
        f"The model named the shape in its `shape` field; the code put it in the unsupported list.",
        f"- **Average LLM time per run:** {s['avg_llm_seconds']:.1f} s "
        f"({s['avg_prompt_tokens']} prompt + {s['avg_output_tokens']} output tokens), model already loaded. "
        f"Largest prompt of any single call: {s['max_prompt_tokens_per_call']} tokens.",
    ]
    if s.get("peak_gpu_mib") is not None:
        lines.append(f"- **Peak GPU memory while the cases ran:** {s['peak_gpu_mib']} MiB "
                     f"(whole card, nvidia-smi, model loaded).")
    lines.append("")
    return "\n".join(lines)


def render_cases(results, blender, stamp):
    """Render the first valid spec of each case. The model is already unloaded."""
    out_dir = os.path.join(PROJECT_DIR, "runs", f"evals_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"\nRendering one spec per case into {os.path.relpath(out_dir, PROJECT_DIR)}")
    renders = {}
    for case in results:
        run = next((r for r in case["runs"] if r["valid"]), None)
        if run is None:
            continue
        spec_path = os.path.join(out_dir, f"{case['id']}.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(run["spec"], f, indent=2)
        png_path = os.path.join(out_dir, f"{case['id']}.png")
        print(f"\n{case['id']}:")
        outcome = render(spec_path, png_path, blender)
        renders[case["id"]] = {"png": os.path.relpath(png_path, PROJECT_DIR), "ok": outcome["ok"],
                               "render_time": outcome["render_time"], "colour_check": outcome["colour_check"]}
    return renders


if __name__ == "__main__":
    sys.exit(main())
