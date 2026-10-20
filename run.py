"""
Render a JSON scene spec to a PNG, headless, using Blender.

Usage:
    python run.py specs/pink_three_quarter.json
    python run.py specs/pink_three_quarter.json --verbose   (show all Blender output)

The PNG is saved to renders/<spec-name>_<timestamp>.png.

This file uses only the Python standard library. It checks the spec first
(so mistakes are reported in plain English), then starts Blender in the
background to run render_scene.py.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

from spec import SpecError, load_spec

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RENDER_SCRIPT = os.path.join(PROJECT_DIR, "render_scene.py")
RENDERS_DIR = os.path.join(PROJECT_DIR, "renders")

DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# Lines from Blender we always show (the rest is hidden unless --verbose).
#   "[render] ..."          messages from render_scene.py
#   "Path tracing on: ..."  Cycles itself reporting the device it really used
CYCLES_DEVICE_LINE = re.compile(r"(Path tracing on|Denoising on): (.+)")


def find_blender(explicit_path=None):
    """Return the path to blender.exe, or None if it can't be found.

    Checked in order: --blender argument, BLENDER_PATH environment variable,
    the default install folder, any other version in Program Files, then PATH.
    """
    candidates = [explicit_path, os.environ.get("BLENDER_PATH"), DEFAULT_BLENDER]
    installed = glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe")
    candidates += sorted(installed, key=_version_key, reverse=True)
    candidates.append(shutil.which("blender"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _version_key(path):
    """'...\\Blender 5.2\\blender.exe' -> (5, 2), so newer versions sort first."""
    match = re.search(r"Blender (\d+)\.(\d+)", path)
    return tuple(int(n) for n in match.groups()) if match else (0, 0)


def render(spec_path, output_path, blender, verbose=False):
    """Render a (valid) spec file to output_path with Blender, headless.

    Shows only the lines that matter while Blender runs (everything with
    verbose=True). Returns a dict: ok, returncode, device, cycles (the
    devices Cycles reported), render_time, colour_check, total_seconds and,
    on failure, log_tail (Blender's last lines).
    """
    command = [
        blender,
        "--background",          # no window
        "--factory-startup",     # ignore saved Blender settings: the spec decides everything
        "--python-exit-code", "1",  # a Python error inside Blender = a failed run
        "--debug-cycles",        # makes Cycles report which device it really used
        "--python", RENDER_SCRIPT,
        "--",                    # everything after this goes to render_scene.py
        "--spec", os.path.abspath(spec_path),
        "--output", output_path,
    ]

    start = time.perf_counter()
    log_lines = []
    device = render_time = colour_check = None
    cycles_report = []

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in process.stdout:
        line = line.rstrip()
        log_lines.append(line)
        cycles_match = CYCLES_DEVICE_LINE.search(line)
        cycles_line = f"{cycles_match.group(1)}: {cycles_match.group(2)}" if cycles_match else None
        # Accurate mode renders twice (light meter, then the image), so Cycles
        # reports the device twice. Show each line once.
        new_cycles_line = cycles_line is not None and cycles_line not in cycles_report

        if verbose:
            print(line)
        elif line.startswith("[render]"):
            print(line)
        elif new_cycles_line:
            print(f"[cycles] {cycles_line}")

        if new_cycles_line:
            cycles_report.append(cycles_line)
        if line.startswith("[render] device:"):
            device = line.split(":", 1)[1].strip()
        elif line.startswith("[render] render time:"):
            render_time = line.split(":", 1)[1].strip()
        elif line.startswith("[render] colour check:"):
            colour_check = line.split(":", 1)[1].strip()
    process.wait()

    ok = process.returncode == 0 and os.path.isfile(output_path)
    return {
        "ok": ok,
        "returncode": process.returncode,
        "device": device,
        "cycles": cycles_report,
        "render_time": render_time,
        "colour_check": colour_check,
        "total_seconds": time.perf_counter() - start,
        "log_tail": [] if ok else log_lines[-30:],
    }


def main():
    parser = argparse.ArgumentParser(description="Render a product shot from a JSON spec.")
    parser.add_argument("spec", help="path to a JSON spec, e.g. specs/pink_three_quarter.json")
    parser.add_argument("--blender", help="path to blender.exe (normally found automatically)")
    parser.add_argument("--verbose", action="store_true", help="show Blender's full output")
    args = parser.parse_args()

    # 1. Check the spec before starting Blender.
    try:
        load_spec(args.spec)
    except SpecError as e:
        print(f"Spec error in {args.spec}:")
        for problem in e.problems:
            print(f"  - {problem}")
        print("Nothing was rendered. Fix the spec and try again.")
        return 1

    blender = find_blender(args.blender)
    if not blender:
        print_blender_not_found()
        return 1

    # 2. Work out where the PNG goes.
    spec_name = os.path.splitext(os.path.basename(args.spec))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(RENDERS_DIR, f"{spec_name}_{timestamp}.png")
    os.makedirs(RENDERS_DIR, exist_ok=True)

    # 3. Run Blender, showing only the lines that matter.
    print(f"Rendering {args.spec} with {blender}")
    result = render(args.spec, output_path, blender, args.verbose)

    # 4. Report.
    if not result["ok"]:
        print_render_failed(result, args.verbose)
        return 1

    print()
    print("Done.")
    print(f"  Spec:         {args.spec}")
    print(f"  Device:       {result['device']}")
    for report in result["cycles"]:
        print(f"  Cycles:       {report}")
    print(f"  Render time:  {result['render_time']} "
          f"(total incl. Blender start-up: {result['total_seconds']:.1f} s)")
    print(f"  Colour check: {result['colour_check']}")
    print(f"  Saved:        {os.path.relpath(output_path, PROJECT_DIR)}")
    print_cpu_warning(result)
    return 0


def print_blender_not_found():
    print("Could not find blender.exe.")
    print(f"Expected it at: {DEFAULT_BLENDER}")
    print('Pass the path with --blender "C:\\path\\to\\blender.exe" or set BLENDER_PATH.')


def print_render_failed(result, verbose):
    print()
    print(f"RENDER FAILED (Blender exit code {result['returncode']}).")
    if not verbose:
        print("Last lines of Blender's output:")
        for line in result["log_tail"]:
            print(f"    {line}")


def print_cpu_warning(result):
    if result["device"] and result["device"].startswith("CPU"):
        print()
        print("  WARNING: this render ran on the CPU, not the GPU. See the warning above.")


if __name__ == "__main__":
    sys.exit(main())
