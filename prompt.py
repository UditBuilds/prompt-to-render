"""
Sentence in, render out. A local LLM writes the spec, spec.py checks it, and
Blender renders it.

Usage:
    python prompt.py "luxury matte red lipstick box, three-quarter view"
    python prompt.py "a navy serum box" --model qwen3:8b

Steps:
    1. The LLM (Ollama, on this machine) turns the sentence into a JSON spec.
    2. spec.py validates it. If that fails, the errors go back to the LLM for
       one more try (2 attempts in total).
    3. The LLM is unloaded from GPU memory (checked with nvidia-smi).
    4. Blender renders the spec, exactly like run.py.

Each run is saved to runs/<timestamp>_<short-slug>/:
    prompt.txt   the sentence
    spec.json    the validated spec (re-render it with: python run.py <path>)
    render.png   the image
    log.json     model, attempts, validation errors, unsupported list, tokens,
                 timings, device and GPU memory

Runs fully offline: no API keys, nothing leaves this machine.
Standard library only.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

import gpu
from llm_backend import DEFAULT_MODEL, BackendUnavailable, BrokenFirstReply, OllamaBackend
from run import PROJECT_DIR, find_blender, print_blender_not_found, print_cpu_warning, print_render_failed, render
from spec_writer import MAX_ATTEMPTS, write_spec

RUNS_DIR = os.path.join(PROJECT_DIR, "runs")


def main():
    # A sentence (or the model's description) may hold characters the
    # terminal can't show. Print a "?" for those instead of crashing.
    sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Describe a box product shot in a sentence; get a render.")
    parser.add_argument("sentence", help='e.g. "luxury matte red lipstick box, three-quarter view"')
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--blender", help="path to blender.exe (normally found automatically)")
    parser.add_argument("--verbose", action="store_true", help="show the model's raw replies and Blender's full output")
    parser.add_argument("--break-first-reply", action="store_true",
                        help="testing: corrupt the model's first reply to show the repair loop at work")
    args = parser.parse_args()

    sentence = " ".join(args.sentence.split())
    if not sentence:
        print("Please describe the shot, e.g.:")
        print('  python prompt.py "luxury matte red lipstick box, three-quarter view"')
        return 2

    blender = find_blender(args.blender)
    if not blender:
        print_blender_not_found()
        return 1

    backend = OllamaBackend(args.model)
    if args.break_first_reply:
        backend = BrokenFirstReply(backend)

    print(f"Sentence: {sentence}")
    print(f"Model:    {backend.describe()}")
    try:
        backend.check()
    except BackendUnavailable as e:
        print()
        print(e)
        print("Nothing was generated or rendered.")
        return 1

    run_dir = new_run_dir(sentence)
    with open(os.path.join(run_dir, "prompt.txt"), "w", encoding="utf-8") as f:
        f.write(sentence + "\n")
    print(f"Run:      {os.path.relpath(run_dir, PROJECT_DIR)}")
    print()

    log = {
        "sentence": sentence,
        "created": datetime.now().isoformat(timespec="seconds"),
        "status": "started",
        "backend": backend.name,
        "model": backend.model,
        "llm_settings": backend.settings(),
    }
    try:
        return run(sentence, backend, blender, run_dir, log, args.verbose)
    finally:
        with open(os.path.join(run_dir, "log.json"), "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
            f.write("\n")


def run(sentence, backend, blender, run_dir, log, verbose):
    # 1 + 2. Sentence -> validated spec. Whatever happens, the model is
    # unloaded afterwards so the GPU is free (also on errors and Ctrl-C).
    result = None
    try:
        result = write_spec(sentence, backend, report=AttemptPrinter(backend, verbose))
    except (BackendUnavailable, RuntimeError) as e:
        print()
        print(f"LLM error: {e}")
        log.update(status="llm_error", error=str(e))
    finally:
        if result is not None:
            log_llm(log, result)
            show_spec(sentence, result)
        # 3. Free the GPU before Blender starts.
        log["gpu_memory_mib"] = unload(backend)

    if result is None:
        print("Nothing was rendered.")
        return 1
    if not result.ok:
        print()
        print(f"The model didn't produce a valid spec in {MAX_ATTEMPTS} attempts. Last problems:")
        for problem in result.errors:
            print(f"  - {problem}")
        print("Nothing was rendered. The model's replies are in log.json in the run folder.")
        log["status"] = "invalid_spec"
        return 1

    spec_path = os.path.join(run_dir, "spec.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(result.spec, f, indent=2)
        f.write("\n")

    # 4. Render.
    print()
    print(f"Rendering with {blender}")
    png_path = os.path.join(run_dir, "render.png")
    with gpu.PeakMemory() as memory:
        render_result = render(spec_path, png_path, blender, verbose)
    log["gpu_memory_mib"]["peak_during_render"] = memory.peak
    log.update(
        render_seconds=seconds(render_result["render_time"]),
        render_total_seconds=round(render_result["total_seconds"], 2),
        device=render_result["device"],
        colour_check=render_result["colour_check"],
    )
    if not render_result["ok"]:
        print_render_failed(render_result, verbose)
        log["status"] = "render_failed"
        return 1
    log["status"] = "rendered"

    show_summary(run_dir, png_path, log, result, render_result)
    print_cpu_warning(render_result)
    return 0


class AttemptPrinter:
    """Prints each LLM attempt as it happens, so a retry is easy to see."""

    def __init__(self, backend, verbose):
        self.backend = backend
        self.verbose = verbose

    def __call__(self, event, attempt):
        n = attempt.number
        if event == "start":
            if n == 1:
                print(f"[llm] attempt {n} of {MAX_ATTEMPTS}: asking {self.backend.model} for a spec ...")
            else:
                print(f"[llm] attempt {n} of {MAX_ATTEMPTS}: sending the {len(attempt.errors)} "
                      f"validation error(s) back to the model ...")
            return

        reply = attempt.reply
        load = f", {reply.load_seconds:.1f} s of it loading the model" if reply.load_seconds >= 0.5 else ""
        print(f"[llm]   reply in {reply.seconds:.1f} s{load}; "
              f"{reply.prompt_tokens} prompt + {reply.output_tokens} output tokens")
        if reply.note:
            print(f"[llm]   note: {reply.note}")
        if self.verbose or attempt.errors:
            print("[llm]   reply:")
            for line in reply.text.splitlines():
                print(f"[llm]   | {line}")
        if attempt.errors:
            print(f"[llm]   INVALID: spec.py found {len(attempt.errors)} problem(s):")
            for problem in attempt.errors:
                print(f"[llm]     - {problem}")
        else:
            print("[llm]   valid: spec.py accepted the spec")


def show_spec(sentence, result):
    if not result.ok:
        return
    box = result.spec["box"]
    print()
    print("Spec:")
    print(f"  box        {box['width_cm']:g} x {box['height_cm']:g} x {box['depth_cm']:g} cm (width x height x depth)")
    print(f"  finish     colour {box['colour']}, roughness {box['roughness']:g}, bevel {box['bevel_cm']:g} cm")
    print(f"  backdrop   {result.spec['background_colour']}")
    print(f"  camera     {result.spec['camera']}")
    print(f"  about      {result.spec['description']}")

    if result.is_box is False:
        print()
        print("=" * 72)
        what = f"a {result.shape}" if result.shape and result.shape != "box" else "not a box"
        print(f"WARNING: this is {what}, but the renderer can only draw a box.")
        print("Rendering the closest box instead. Ignored:")
        for item in result.unsupported or ["(the model listed nothing)"]:
            print(f"  - {item}")
        print("=" * 72)
    elif result.unsupported:
        print()
        print("Not rendered (the renderer can't draw these):")
        for item in result.unsupported:
            print(f"  - {item}")


def unload(backend):
    """Unload the model and show GPU memory before and after."""
    print()
    print(f"[gpu] unloading {backend.model} from GPU memory before rendering ...")
    before = gpu.memory_used_mib()
    try:
        released = backend.release()
    except (BackendUnavailable, RuntimeError) as e:
        print(f"[gpu] WARNING: could not unload the model: {e}")
        return {"model_loaded": before, "after_unload": None, "unloaded": False}
    after = gpu.wait_for_drop(before)
    if before is None or after is None:
        print("[gpu] model unloaded (nvidia-smi not available, so no memory reading)")
    else:
        print(f"[gpu] GPU memory: {before} MiB with the model loaded -> {after} MiB after unloading "
              f"({before - after} MiB freed)")
    if not released:
        print("[gpu] WARNING: Ollama still lists the model as loaded.")
    return {"model_loaded": before, "after_unload": after, "unloaded": released}


def log_llm(log, result):
    log.update(
        status="spec_valid" if result.ok else "invalid_spec",
        attempts=len(result.attempts),
        max_attempts=MAX_ATTEMPTS,
        validation_errors=[a.errors for a in result.attempts],
        is_box=result.is_box,
        shape=result.shape,
        unsupported=result.unsupported,
        model_unsupported=result.model_unsupported,
        shape_added_by_code=result.shape_added,
        prompt_tokens=result.total("prompt_tokens"),
        output_tokens=result.total("output_tokens"),
        llm_seconds=round(result.total("seconds"), 2),
        llm_load_seconds=round(result.total("load_seconds"), 2),
        llm_calls=[a.to_log() for a in result.attempts],
    )


def show_summary(run_dir, png_path, log, result, render_result):
    memory = log["gpu_memory_mib"]
    attempts = len(result.attempts)
    print()
    print("Done.")
    print(f"  Run folder:   {os.path.relpath(run_dir, PROJECT_DIR)}")
    print(f"  Image:        {os.path.relpath(png_path, PROJECT_DIR)}")
    print(f"  LLM:          {log['model']}, {attempts} attempt{'s' if attempts > 1 else ''}, "
          f"{log['llm_seconds']:.1f} s (incl. {log['llm_load_seconds']:.1f} s loading the model), "
          f"{log['prompt_tokens']} prompt + {log['output_tokens']} output tokens")
    if memory.get("model_loaded") is not None:
        print(f"  GPU memory:   {memory['model_loaded']} MiB with the model loaded -> "
              f"{memory['after_unload']} MiB after unloading -> "
              f"{memory.get('peak_during_render')} MiB peak while rendering")
    print(f"  Device:       {render_result['device']}")
    print(f"  Render time:  {render_result['render_time']} "
          f"(total incl. Blender start-up: {render_result['total_seconds']:.1f} s)")
    print(f"  Colour check: {render_result['colour_check']}")
    if result.unsupported:
        print(f"  Not rendered: {', '.join(result.unsupported)}")
    if result.is_box is False:
        print("  WARNING:      not a box; the closest box was rendered instead.")


def new_run_dir(sentence):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(RUNS_DIR, f"{stamp}_{slugify(sentence)}")
    path, n = base, 2
    while os.path.exists(path):
        path, n = f"{base}_{n}", n + 1
    os.makedirs(path)
    return path


def slugify(sentence, max_length=40):
    """'Luxury matte red lipstick box, three-quarter view' -> 'luxury-matte-red-lipstick-box-three'."""
    words = re.findall(r"[a-z0-9]+", sentence.lower())
    slug = ""
    for word in words:
        longer = f"{slug}-{word}" if slug else word
        if len(longer) > max_length:
            break
        slug = longer
    return slug or (words[0][:max_length] if words else "prompt")


def seconds(text):
    """'3.1 s' -> 3.1 (None if missing)."""
    match = re.match(r"([\d.]+)", text or "")
    return float(match.group(1)) if match else None


if __name__ == "__main__":
    sys.exit(main())
