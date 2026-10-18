"""
Evals for the spec writer: does the LLM turn sentences into the right specs?

    python evals/run_evals.py                    15 cases x 3 runs, specs only (no rendering)
    python evals/run_evals.py --render           also render one spec per case
    python evals/run_evals.py --model llama3.1:8b
    python evals/run_evals.py --runs 1 --cases red_lipstick,vague

Every case in evals/cases.json goes through the same LLM + validation loop as
prompt.py, several times (the model samples at temperature 0.2, so runs can
differ). The checks are ranges, not exact values, e.g. "glossy" means
roughness <= 0.2. A run passes when it produced a valid spec within 2
attempts AND every check passes.

Reports the pass rate per case and overall, how often the retry loop fired,
and the average LLM time. Results are saved to evals/results/<timestamp>.json,
with a Markdown summary next to it.
"""

import argparse
import colorsys
import json
import os
import sys
import time
from datetime import datetime

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(EVALS_DIR))

from check_colour import hex_to_lab  # noqa: E402
from llm_backend import DEFAULT_MODEL, BackendUnavailable, OllamaBackend  # noqa: E402
from run import PROJECT_DIR, find_blender, render  # noqa: E402
from spec_writer import MAX_ATTEMPTS, write_spec  # noqa: E402

CASES_PATH = os.path.join(EVALS_DIR, "cases.json")
RESULTS_DIR = os.path.join(EVALS_DIR, "results")


# ---------------------------------------------------------------------------
# Checks. Each takes (check, result) and returns (passed, what was found).
# ---------------------------------------------------------------------------

def hex_to_hsv(hex_colour):
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)
    return hue * 360, saturation, value


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


def check_hue(check, result):
    colour = result.spec["box"]["colour"]
    hue = hex_to_hsv(colour)[0]
    low, high = check["min"], check["max"]
    # A range like 345..15 wraps round through 0 (red).
    ok = low <= hue <= high if low <= high else (hue >= low or hue <= high)
    return ok, f"hue {hue:.0f} deg of {colour} (want {low}..{high})"


def check_saturation(check, result):
    colour = result.spec["box"]["colour"]
    saturation = hex_to_hsv(colour)[1]
    return in_range(saturation, check), f"saturation {saturation:.2f} of {colour} (want {describe_range(check)})"


def check_lightness(check, result):
    colour = result.spec["box"]["colour"]
    lightness = hex_to_lab(colour)[0]
    return in_range(lightness, check), f"L* {lightness:.0f} of {colour} (want {describe_range(check)})"


def check_hex(check, result):
    colour = result.spec["box"]["colour"]
    return colour.upper() == check["equals"].upper(), f"colour {colour} (want {check['equals']})"


def check_roughness(check, result):
    roughness = result.spec["box"]["roughness"]
    return in_range(roughness, check), f"roughness {roughness:g} (want {describe_range(check)})"


def check_camera(check, result):
    camera = result.spec["camera"]
    return camera == check["equals"], f"camera {camera} (want {check['equals']})"


def check_ratio(check, result):
    box = result.spec["box"]
    ratio = box[check["num"]] / box[check["den"]]
    return in_range(ratio, check), (f"{check['num']}/{check['den']} = {box[check['num']]:g}/{box[check['den']]:g} "
                                    f"= {ratio:.2f} (want {describe_range(check)})")


def check_size(check, result):
    box = result.spec["box"]
    sides = [box["width_cm"], box["height_cm"], box["depth_cm"]]
    side = max(sides) if check["side"] == "longest" else min(sides)
    return in_range(side, check), f"{check['side']} side {side:g} cm (want {describe_range(check)})"


def check_is_box(check, result):
    return result.is_box == check["equals"], f"is_box {json.dumps(result.is_box)} (want {json.dumps(check['equals'])})"


def check_unsupported_mentions(check, result):
    text = " | ".join(result.unsupported).lower()
    ok = any(word in text for word in check["any"])
    return ok, f"unsupported {json.dumps(result.unsupported)} (want a mention of {' or '.join(check['any'])})"


def check_unsupported_empty(check, result):
    return not result.unsupported, f"unsupported {json.dumps(result.unsupported)} (want [])"


CHECKS = {
    "hue": check_hue,
    "saturation": check_saturation,
    "lightness": check_lightness,
    "hex": check_hex,
    "roughness": check_roughness,
    "camera": check_camera,
    "ratio": check_ratio,
    "size": check_size,
    "is_box": check_is_box,
    "unsupported_mentions": check_unsupported_mentions,
    "unsupported_empty": check_unsupported_empty,
}


def run_checks(case, result):
    """Returns a list of {check, passed, found}. An invalid spec fails outright."""
    if not result.ok:
        return [{"check": "valid spec", "passed": False,
                 "found": f"no valid spec in {MAX_ATTEMPTS} attempts: {result.errors}"}]
    outcomes = []
    for check in case["checks"]:
        passed, found = CHECKS[check["type"]](check, result)
        outcomes.append({"check": check["type"], "passed": passed, "found": found})
    return outcomes


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Run the spec-writer evals.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--runs", type=int, default=3, help="runs per case (default: 3)")
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--render", action="store_true", help="also render one spec per case (after unloading the model)")
    parser.add_argument("--blender", help="path to blender.exe (for --render)")
    args = parser.parse_args()

    with open(CASES_PATH, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if args.cases:
        wanted = args.cases.split(",")
        unknown = set(wanted) - {c["id"] for c in cases}
        if unknown:
            print(f"Unknown case id(s): {', '.join(sorted(unknown))}")
            return 2
        cases = [c for c in cases if c["id"] in wanted]

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
    print(f"{len(cases)} cases x {args.runs} runs\n")
    results = []
    stopped_early = None
    started = time.perf_counter()
    try:
        for case in cases:
            results.append(run_case(case, backend, args.runs))
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

    summary = summarise(results)
    report = {
        "created": datetime.now().isoformat(timespec="seconds"),
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

    os.makedirs(RESULTS_DIR, exist_ok=True)
    json_path = os.path.join(RESULTS_DIR, f"{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    table = markdown_table(report)
    with open(os.path.join(RESULTS_DIR, f"{stamp}.md"), "w", encoding="utf-8") as f:
        f.write(table)

    print()
    print(table)
    print(f"Saved: {os.path.relpath(json_path, PROJECT_DIR)} (and .md)")
    return 1 if stopped_early else 0


def run_case(case, backend, runs):
    print(f"{case['id']}: \"{case['sentence']}\"")
    case_runs = []
    for n in range(1, runs + 1):
        result = write_spec(case["sentence"], backend)
        outcomes = run_checks(case, result)
        passed = all(o["passed"] for o in outcomes)
        retry_note = ", retried" if result.retried else ""
        print(f"  run {n}: {'PASS' if passed else 'FAIL'}  "
              f"({len(result.attempts)} attempt{'s' if result.retried else ''}{retry_note}, "
              f"{result.total('seconds'):.1f} s)")
        for o in outcomes:
            if not o["passed"]:
                print(f"         x {o['found']}")
        case_runs.append({
            "run": n,
            "passed": passed,
            "attempts": len(result.attempts),
            "retried": result.retried,
            "valid": result.ok,
            "llm_seconds": round(result.total("seconds"), 2),
            "prompt_tokens": result.total("prompt_tokens"),
            "output_tokens": result.total("output_tokens"),
            "checks": outcomes,
            "is_box": result.is_box,
            "shape": result.shape,
            "unsupported": result.unsupported,
            "shape_added_by_code": result.shape_added,
            "spec": result.spec,
            "validation_errors": [a.errors for a in result.attempts],
            "outputs": [a.reply.text for a in result.attempts],
        })
    passes = sum(r["passed"] for r in case_runs)
    # At a low temperature the runs often come out identical. Counting the
    # distinct specs shows how much the runs actually varied.
    distinct = len({json.dumps(r["spec"], sort_keys=True) for r in case_runs if r["valid"]})
    return {"id": case["id"], "sentence": case["sentence"], "covers": case.get("covers", ""),
            "checks": case["checks"], "passed_runs": passes, "total_runs": len(case_runs),
            "distinct_specs": distinct, "runs": case_runs}


def summarise(results):
    runs = [r for case in results for r in case["runs"]]
    total = len(runs)
    return {
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
        "avg_llm_seconds": round(sum(r["llm_seconds"] for r in runs) / total, 2) if total else None,
        "avg_prompt_tokens": round(sum(r["prompt_tokens"] for r in runs) / total) if total else None,
        "avg_output_tokens": round(sum(r["output_tokens"] for r in runs) / total) if total else None,
    }


def markdown_table(report):
    s = report["summary"]
    lines = [
        f"Model `{report['model']}` (Ollama, local), {report['runs_per_case']} runs per case, "
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
        f"({s['pass_rate']:.0%}); {s['cases_passing_all_runs']}/{s['total_cases']} cases passed every run.",
        f"- **Retry loop fired:** {s['retry_runs']}/{s['total_runs']} runs ({s['retry_rate']:.0%}); "
        f"still invalid after {report['max_attempts']} attempts: {s['invalid_after_retries']}.",
        f"- **Consistency:** {s['cases_with_identical_runs']}/{s['total_cases']} cases gave the same spec "
        f"in every run (temperature {report['llm_settings']['temperature']}).",
        f"- **Non-box shape listed by code, not by the model:** {s['shape_added_by_code_runs']} run(s). "
        f"The model named the shape in its `shape` field; the code put it in the unsupported list.",
        f"- **Average LLM time per run:** {s['avg_llm_seconds']:.1f} s "
        f"({s['avg_prompt_tokens']} prompt + {s['avg_output_tokens']} output tokens), model already loaded.",
        "",
    ]
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
