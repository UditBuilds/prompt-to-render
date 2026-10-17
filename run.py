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


def main():
    parser = argparse.ArgumentParser(description="Render a box product shot from a JSON spec.")
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
        print("Could not find blender.exe.")
        print(f"Expected it at: {DEFAULT_BLENDER}")
        print('Pass the path with --blender "C:\\path\\to\\blender.exe" or set BLENDER_PATH.')
        return 1

    # 2. Work out where the PNG goes.
    spec_name = os.path.splitext(os.path.basename(args.spec))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(RENDERS_DIR, f"{spec_name}_{timestamp}.png")
    os.makedirs(RENDERS_DIR, exist_ok=True)

    command = [
        blender,
        "--background",          # no window
        "--factory-startup",     # ignore saved Blender settings: the spec decides everything
        "--python-exit-code", "1",  # a Python error inside Blender = a failed run
        "--debug-cycles",        # makes Cycles report which device it really used
        "--python", RENDER_SCRIPT,
        "--",                    # everything after this goes to render_scene.py
        "--spec", os.path.abspath(args.spec),
        "--output", output_path,
    ]

    # 3. Run Blender, showing only the lines that matter.
    print(f"Rendering {args.spec} with {blender}")
    start = time.perf_counter()
    log_lines = []
    device = render_time = None
    cycles_report = []

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in process.stdout:
        line = line.rstrip()
        log_lines.append(line)
        cycles_match = CYCLES_DEVICE_LINE.search(line)

        if args.verbose:
            print(line)
        elif line.startswith("[render]"):
            print(line)
        elif cycles_match:
            print(f"[cycles] {cycles_match.group(1)}: {cycles_match.group(2)}")

        if cycles_match:
            cycles_report.append(f"{cycles_match.group(1)}: {cycles_match.group(2)}")
        if line.startswith("[render] device:"):
            device = line.split(":", 1)[1].strip()
        elif line.startswith("[render] render time:"):
            render_time = line.split(":", 1)[1].strip()
    process.wait()
    total_seconds = time.perf_counter() - start

    # 4. Report.
    if process.returncode != 0 or not os.path.isfile(output_path):
        print()
        print(f"RENDER FAILED (Blender exit code {process.returncode}).")
        if not args.verbose:
            print("Last lines of Blender's output:")
            for line in log_lines[-30:]:
                print(f"    {line}")
        return 1

    print()
    print("Done.")
    print(f"  Spec:         {args.spec}")
    print(f"  Device:       {device}")
    for report in cycles_report:
        print(f"  Cycles:       {report}")
    print(f"  Render time:  {render_time} (total incl. Blender start-up: {total_seconds:.1f} s)")
    print(f"  Saved:        {os.path.relpath(output_path, PROJECT_DIR)}")
    if device and device.startswith("CPU"):
        print()
        print("  WARNING: this render ran on the CPU, not the GPU. See the warning above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
