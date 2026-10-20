"""
Compare eval runs side by side, as a Markdown table.

    python evals/compare.py evals/results/<..>_baseline.json evals/results/<..>_prompt-only.json evals/results/<..>_grounded.json

Columns follow the order of the files. The last file is also checked for
how its runs got their values: a box colour copied from a colour table row,
a colour shifted by code for a style word, or a box size equal to a
product's typical size. Those are passes the tables make easy, so they are
counted, not hidden.
"""

import json
import os
import sys

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(EVALS_DIR))

from grounding import load_tables  # noqa: E402
from run_evals import COLOUR_GROUPS  # noqa: E402


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
    copied = shifted = typical = 0
    for run in case["runs"]:
        rows = run.get("grounding_rows", [])
        if not run["valid"]:
            continue
        box = run["spec"]["box"]
        colour = box["colour"].upper()
        before_shift = run["style_changes"][0]["from"] if run.get("style_changes") else colour
        if any(r["table"] == "colours" and tables["colours"][r["name"]]["hex"] == before_shift for r in rows):
            copied += 1
        if run.get("style_changes"):
            shifted += 1
        size = [box["width_cm"], box["height_cm"], box["depth_cm"]]
        if any(r["table"] == "products" and tables["products"][r["name"]]["typical"] == size for r in rows):
            typical += 1
    parts = []
    if copied:
        parts.append(f"table colour {copied}")
    if shifted:
        parts.append(f"style shift by code {shifted}")
    if typical:
        parts.append(f"typical size {typical}")
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
                        f"({r['summary']['pass_rate']:.0%})" for r in reports])
    for group, title in COLOUR_GROUPS.items():
        cells = []
        for r in reports:
            g = r["summary"].get("colour_groups", {}).get(group)
            cells.append(f"{g['colour_passed_runs']}/{g['total_runs']} ({g['colour_passed_runs'] / g['total_runs']:.0%})"
                         if g else "n/a")
        row(f"{title}: named colour right", cells)
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
