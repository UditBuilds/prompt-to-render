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
from grounding import lookup
from llm_backend import DEFAULT_MODEL, BackendUnavailable, BrokenFirstReply, OllamaBackend
from run import PROJECT_DIR, find_blender, print_blender_not_found, print_cpu_warning, print_render_failed, render
from spec import METAL_FIELDS
from spec_writer import MAX_ATTEMPTS, write_spec

RUNS_DIR = os.path.join(PROJECT_DIR, "runs")


def main():
    # A sentence (or the model's description) may hold characters the
    # terminal can't show. Print a "?" for those instead of crashing.
    sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Describe a product shot (a box, cylinder, bottle or jar) in a sentence; get a render.")
    parser.add_argument("sentence", help='e.g. "luxury matte red lipstick box, three-quarter view"')
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--blender", help="path to blender.exe (normally found automatically)")
    parser.add_argument("--verbose", action="store_true", help="show the model's raw replies and Blender's full output")
    parser.add_argument("--no-grounding", action="store_true",
                        help="don't add the matching rows of the data/ tables to the request, "
                             "and don't let code set any value")
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
        "grounding": not args.no_grounding,
    }
    try:
        return run(sentence, backend, blender, run_dir, log, args.verbose, not args.no_grounding)
    finally:
        with open(os.path.join(run_dir, "log.json"), "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
            f.write("\n")


def run(sentence, backend, blender, run_dir, log, verbose, grounding):
    # 1 + 2. Sentence -> validated spec. Whatever happens, the model is
    # unloaded afterwards so the GPU is free (also on errors and Ctrl-C).
    result = None
    show_grounding(sentence, grounding, verbose)
    try:
        result = write_spec(sentence, backend, report=AttemptPrinter(backend, verbose), grounding=grounding)
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
    if result.shape_fixed:
        change = result.shape_fixed
        print(f"[shape] the model named a {change['real']} but drew a {change['from']}; "
              f"drawn as the closest shape, a {change['to']}")
    for change in result.style_changes:
        print(f"[grounding] style \"{change['style']}\" applied to the product colour: "
              f"{change['from']} -> {change['to']}")
    if result.finish_change:
        change = result.finish_change
        print(f"[grounding] finish \"{change['finish']}\" applied to the roughness: "
              f"{change['from']:g} -> {change['to']:g}")
    if result.backdrop_change:
        change = result.backdrop_change
        print(f"[grounding] the sentence gives the backdrop no colour, so it is neutral: "
              f"{change['from'] or '(left out by the model)'} -> {change['to']}")
    if result.cap_change:
        change = result.cap_change
        part = "lid" if change["field"] == "lid_colour" else "cap"
        print(f"[grounding] the sentence gives the {part} no colour, so it is the default for the body: "
              f"{change['from'] or '(left out by the model)'} -> {change['to']}")
    if result.metal_change:
        change = result.metal_change
        part = "lid" if change["field"] == "lid_metal" else "cap"
        print(f"[grounding] the sentence names a metal for the {part}, so it is drawn in {change['metal']}")
    for change in result.hex_changes:
        print(f"[grounding] the sentence gives an exact hex, used as given: "
              f"{change['field']} {change['from'] or '(left out by the model)'} -> {change['to']}")
    for change in result.proportion_changes:
        print(f"[proportions] clamped by code, {change['rule']}: "
              f"{change['field']} {change['from']:g} -> {change['to']:g}")
    shape = result.spec["shape"]
    product = result.spec[shape]
    print()
    print("Spec:")
    if shape == "box":
        print(f"  box        {product['width_cm']:g} x {product['height_cm']:g} x {product['depth_cm']:g} cm "
              f"(width x height x depth)")
        print(f"  finish     colour {product['colour']}, roughness {product['roughness']:g}, "
              f"bevel {product['bevel_cm']:g} cm")
    else:
        print(f"  {shape:<10} {product['diameter_cm']:g} cm across x {product['height_cm']:g} cm tall")
        cap = ", lid {lid_colour}" if shape == "jar" else ", cap {cap_colour}"
        metal = product.get(METAL_FIELDS[shape])
        cap = cap.format(**product) + (f" ({metal})" if metal else "")
        print(f"  finish     colour {product['colour']}{cap}, roughness {product['roughness']:g}")
    print(f"  backdrop   {result.spec['background_colour']}")
    print(f"  camera     {result.spec['camera']}")
    print(f"  about      {result.spec['description']}")

    if result.shape_added:
        print()
        print("=" * 72)
        what = f"a {result.shape}" if result.shape and result.shape != "box" else "not a box"
        print(f"WARNING: this is {what}, but the renderer can only draw a box, cylinder, bottle or jar.")
        print(f"Rendering the closest shape ({shape}) instead. Ignored:")
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


def show_grounding(sentence, enabled, verbose):
    if not enabled:
        print("[grounding] off (--no-grounding): the model decides everything on its own")
        return
    found = lookup(sentence)
    if found:
        print(f"[grounding] table rows for this sentence: {found.summary()}")
        if verbose:
            for line in found.text.splitlines():
                print(f"[grounding] | {line}")
    else:
        print("[grounding] no table rows match this sentence; the model decides on its own")


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
        grounding_rows=result.grounding.rows,
        style_changes=result.style_changes,
        finish_change=result.finish_change,
        backdrop_change=result.backdrop_change,
        backdrop_given=result.backdrop_given,
        cap_change=result.cap_change,
        cap_given=result.cap_given,
        metal_change=result.metal_change,
        shape_fixed=result.shape_fixed,
        proportion_changes=result.proportion_changes,
        model_colours=result.model_colours,
        hex_changes=result.hex_changes,
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
    if result.shape_added:
        print(f"  WARNING:      a {result.shape or 'shape'} the renderer can't draw; "
              f"the closest shape ({result.spec['shape']}) was rendered instead.")


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
