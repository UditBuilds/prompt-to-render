"""
Compare eval runs side by side, as a Markdown table.

    python evals/compare.py evals/results/<..>_baseline.json evals/results/<..>_prompt-only.json evals/results/<..>_grounded.json

Columns follow the order of the files. The last file is also checked for
how its runs got their values: a box colour copied from a colour table row,
a colour shifted by code for a style word, a box size equal to a product's
typical size, a roughness clamped by code for "glossy", or a backdrop made
neutral by code, or a cap or lid colour set by code. Those are passes the
tables and code make easy, so they are counted, not hidden. A backdrop is counted whenever the code changed
it, even from another neutral grey; one the model had already set to the
code's #F5F5F5 isn't.
"""

import json
import os
import sys

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(EVALS_DIR))

from grounding import load_tables  # noqa: E402
from run_evals import COLOUR_GROUPS, SHAPE_SCORE_NAMES, load_cases, percent, product_of, shape_of  # noqa: E402


def load(path):
    with open(path, encoding="utf-8") as f:
        report = json.load(f)
    report["_name"] = report.get("label") or os.path.splitext(os.path.basename(path))[0]
    return report


def max_prompt_tokens(report):
    calls = []
    for case in report["cases"]:
        for run in case["runs"]:
            calls += run.get("call_prompt_tokens") or [run["prompt_tokens"]]
    return max(calls)


def how_values_came(case, tables):
    """Counts, over a case's runs, of values taken straight from the tables or set by code."""
    copied = shifted = typical = glossy = backdrop = cap = 0
    for run in case["runs"]:
        glossy += bool(run.get("finish_change"))
        backdrop += bool(run.get("backdrop_change"))
        cap += bool(run.get("cap_change"))
        rows = run.get("grounding_rows", [])
        if not run["valid"]:
            continue
        shape, product = shape_of(run["spec"]), product_of(run["spec"])
        colour = product["colour"].upper()
        before_shift = run["style_changes"][0]["from"] if run.get("style_changes") else colour
        if any(r["table"] == "colours" and tables["colours"][r["name"]]["hex"] == before_shift for r in rows):
            copied += 1
        if run.get("style_changes"):
            shifted += 1
        if shape == "box":
            size = [product["width_cm"], product["height_cm"], product["depth_cm"]]
            typicals = [tables["products"][r["name"]]["typical"] for r in rows if r["table"] == "products"]
        else:
            size = [product["diameter_cm"], product["height_cm"]]
            typicals = [tables["products"][r["name"]].get(shape, {}).get("typical")
                        for r in rows if r["table"] == "products"]
        if size in typicals:
            typical += 1
    parts = []
    if copied:
        parts.append(f"table colour {copied}")
    if shifted:
        parts.append(f"style shift by code {shifted}")
    if typical:
        parts.append(f"typical size {typical}")
    if glossy:
        parts.append(f"gloss by code {glossy}")
    if backdrop:
        parts.append(f"neutral backdrop by code {backdrop}")
    if cap:
        parts.append(f"default cap by code {cap}")
    return ", ".join(parts) or "-"


def main(paths):
    reports = [load(p) for p in paths]
    tables = load_tables()
    names = [r["_name"] for r in reports]
    last = reports[-1]
    lines = [
        "| Case | " + " | ".join(names) + f" | {names[-1]}: values straight from tables or code |",
        "|---|" + "---|" * len(names) + "---|",
    ]
    by_id = [{c["id"]: c for c in r["cases"]} for r in reports]
    for case in last["cases"]:
        cells = []
        for cases in by_id:
            c = cases.get(case["id"])
            cells.append(f"{c['passed_runs']}/{c['total_runs']}" if c else "n/a")
        lines.append(f"| `{case['id']}` | " + " | ".join(cells) + f" | {how_values_came(case, tables)} |")

    def row(title, values):
        lines.append(f"| **{title}** | " + " | ".join(values) + " | |")

    row("Runs passed", [f"{r['summary']['passed_runs']}/{r['summary']['total_runs']} "
                        f"({percent(r['summary']['passed_runs'], r['summary']['total_runs'])})" for r in reports])
    # Split by the current cases.json, so a report from before v2 (all of
    # whose cases are from before v2) is counted the same way.
    added = {c["id"]: c.get("added") for c in load_cases()}
    for title, which in (("Runs passed, cases from before v2", None), ("Runs passed, cases added in v2", "v2")):
        cells = []
        for r in reports:
            cases = [c for c in r["cases"] if added.get(c["id"]) == which]
            passed, total = sum(c["passed_runs"] for c in cases), sum(c["total_runs"] for c in cases)
            cells.append(f"{passed}/{total} ({percent(passed, total)})" if total else "n/a")
        row(title, cells)
    for group, title in COLOUR_GROUPS.items():
        cells = []
        for r in reports:
            g = r["summary"].get("colour_groups", {}).get(group)
            cells.append(f"{g['colour_passed_runs']}/{g['total_runs']} "
                         f"({percent(g['colour_passed_runs'], g['total_runs'])})" if g else "n/a")
        row(f"{title}: named colour right", cells)
    for name, title in SHAPE_SCORE_NAMES.items():
        cells = []
        for r in reports:
            g = r["summary"].get("shape_scores", {}).get(name)
            cells.append(f"{g['passed_runs']}/{g['total_runs']} ({percent(g['passed_runs'], g['total_runs'])})"
                         if g else "n/a")
        row(f"{title} right", cells)
    row("Cases passing every run", [f"{r['summary']['cases_passing_all_runs']}/{r['summary']['total_cases']}"
                                    for r in reports])
    row("Retry loop fired", [f"{r['summary']['retry_runs']}/{r['summary']['total_runs']}" for r in reports])
    row("Avg prompt tokens per run", [str(r["summary"]["avg_prompt_tokens"]) for r in reports])
    row("Largest prompt (one call)", [str(max_prompt_tokens(r)) for r in reports])
    row("Avg LLM time per run", [f"{r['summary']['avg_llm_seconds']:.2f} s" for r in reports])
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
