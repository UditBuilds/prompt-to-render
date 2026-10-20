"""
Re-score saved eval results with the current checks. No model is called.

    python evals/rescore.py evals/results/<..>_v1-2.json [more.json ...]

Every result file keeps every spec the model produced, so when a check in
evals/cases.json changes, the old runs can be scored again on exactly the
new checks and stay comparable with new runs. Writes <name>_rescored.json
and .md next to the original, which is left as it was.
"""

import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(EVALS_DIR))

from run_evals import load_cases, markdown_table, run_checks, summarise  # noqa: E402


def saved_result(run):
    """What the checks need from a saved run, in the shape write_spec returns."""
    return SimpleNamespace(ok=run["valid"], spec=run["spec"], errors=run["validation_errors"][-1],
                           is_box=run["is_box"], shape=run["shape"], unsupported=run["unsupported"],
                           model_unsupported=run["model_unsupported"])


def rescore(report, cases):
    """The report with every run's checks run again from `cases`, and a new summary."""
    by_id = {c["id"]: c for c in cases}
    done = {}
    for case in report["cases"]:
        current = by_id[case["id"]]
        case["checks"] = current["checks"]
        for run in case["runs"]:
            run["checks"] = run_checks(current, saved_result(run), done)
            run["passed"] = all(o["passed"] for o in run["checks"])
        case["passed_runs"] = sum(r["passed"] for r in case["runs"])
        done[case["id"]] = case
    report["summary"] = summarise(report["cases"])
    return report


def main(paths):
    cases = load_cases()
    for path in paths:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        before = report["summary"]["passed_runs"]
        report = rescore(report, cases)
        report["rescored"] = {"on": datetime.now().isoformat(timespec="seconds"),
                              "from": os.path.basename(path),
                              "why": "re-scored on the current evals/cases.json checks, no new model runs"}
        stem = os.path.splitext(path)[0] + "_rescored"
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        with open(stem + ".md", "w", encoding="utf-8") as f:
            f.write(f"_Re-scored on {report['rescored']['on'][:10]} from `{report['rescored']['from']}` "
                    f"with the current checks; no new model runs._\n\n" + markdown_table(report))
        s = report["summary"]
        print(f"{os.path.basename(path)}: {before} -> {s['passed_runs']}/{s['total_runs']} runs passed; "
              f"saved {os.path.basename(stem)}.json")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
