# Prompt-to-Render (v0)

Turn a small JSON file into a clean studio product shot of a box (cosmetics-packaging style), rendered headless in Blender on the GPU.

```
python run.py specs/pink_three_quarter.json
```

One command builds the whole scene from scratch and saves a PNG to `renders/`. The scene has a bevelled box, a seamless curved backdrop, three soft area lights and an auto-framed camera.

v0 is fully driven by the JSON spec. The plan for v1 is to have the Claude API write that JSON from a plain-English sentence ("a pink matte serum box, three-quarter view").

---

## What you need

| | |
|---|---|
| **Windows 11** | Tested on Windows 11, native (not WSL). |
| **Blender 5.2** | Expected at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`. Other installed versions are found automatically. |
| **Python 3** | Any recent version. Only the standard library is used, so there's nothing to `pip install`. |
| **NVIDIA RTX GPU** (optional) | Rendering uses OptiX on the GPU. Without one it still works on the CPU, just much slower. |

No add-ons, downloads or HDRI files are used. Everything is built from Blender's own features.

## How to run it

Open a terminal in this folder and run:

```
python run.py specs/pink_three_quarter.json
python run.py specs/black_glossy_front.json
python run.py specs/white_top_down.json
```

You'll see something like:

```
Rendering specs/pink_three_quarter.json with C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
[render] device: GPU (OptiX) - NVIDIA GeForce RTX 5060 Laptop GPU
[render] camera: three_quarter, lighting: studio_soft, 1080x1080, 128 samples
[cycles] Path tracing on: NVIDIA GeForce RTX 5060 Laptop GPU (OptiX) [...]
[cycles] Denoising on: NVIDIA GeForce RTX 5060 Laptop GPU (OptiX) [...]
[render] render time: 3.1 s
[render] saved: C:\Projects\prompt-to-render\renders\pink_three_quarter_20261017_211224.png

Done.
  Spec:         specs/pink_three_quarter.json
  Device:       GPU (OptiX) - NVIDIA GeForce RTX 5060 Laptop GPU
  ...
  Render time:  3.1 s (total incl. Blender start-up: 4.7 s)
  Saved:        renders\pink_three_quarter_20261017_211224.png
```

The `[cycles] Path tracing on:` line comes from Blender's renderer itself. It shows which device really did the work.

The image is saved as `renders/<spec-name>_<date>_<time>.png`, so earlier renders are never overwritten.

Options:

| Option | What it does |
|---|---|
| `--verbose` | Show all of Blender's output (useful if something goes wrong). |
| `--blender "C:\path\to\blender.exe"` | Use a specific Blender. You can also set the `BLENDER_PATH` environment variable. |

## Make your own shot

Copy one of the files in `specs/`, change the values, and run it. Every field is optional; anything you leave out uses the default.

```json
{
  "description": "Tall pink matte serum carton on a blush backdrop, three-quarter view",
  "box": {
    "width_cm": 5,
    "height_cm": 14,
    "depth_cm": 5,
    "colour": "#E8A3B5",
    "roughness": 0.75,
    "bevel_cm": 0.12
  },
  "background_colour": "#F5DCE1",
  "camera": "three_quarter",
  "lighting": "studio_soft",
  "resolution": [1080, 1080],
  "samples": 128
}
```

### Spec fields

| Field | Default | Allowed | What it means |
|---|---|---|---|
| `description` | `""` | any text | A note for humans. Not used for rendering. |
| `box.width_cm` | `6` | 0.5 – 200 | Left-to-right size, seen from the front. |
| `box.height_cm` | `12` | 0.5 – 200 | Bottom-to-top size. |
| `box.depth_cm` | `4` | 0.5 – 200 | Front-to-back size. |
| `box.colour` | `"#D9D9D9"` | hex, `"#RRGGBB"` or `"#RGB"` | Box colour. |
| `box.roughness` | `0.5` | 0 – 1 | `0` = mirror-glossy, `1` = fully matte. Glossy packaging ≈ 0.1–0.2, matte card ≈ 0.6–0.8. |
| `box.bevel_cm` | `0.15` | 0 to just under half the smallest side | How rounded the edges are. `0` = razor sharp. Small values (0.1–0.3) look most realistic. |
| `background_colour` | `"#EDEDED"` | hex | Colour of the studio backdrop. |
| `camera` | `"three_quarter"` | `"front"`, `"three_quarter"`, `"top_down"` | Camera angle (see below). |
| `lighting` | `"studio_soft"` | `"studio_soft"` | Lighting setup. Only one for now. |
| `resolution` | `[1080, 1080]` | each side 16 – 8192 | Image size in pixels, `[width, height]`. Non-square works too. |
| `samples` | `128` | 1 – 8192 | Render quality. More is cleaner but slower. 128 is plenty with the denoiser on. |

Size units are centimetres and the box always stands on the floor. The camera reframes itself for any size, so a lipstick box and a gift box both fill the frame the same way.

### Camera presets

| Preset | Angle |
|---|---|
| `front` | Straight on, from just above the box's middle (8° up). |
| `three_quarter` | 35° to the right and 22° up: the classic packshot showing the front, right side and top. |
| `top_down` | Directly overhead (flat lay). The front of the box is at the bottom of the image. |

### Lighting preset: `studio_soft`

Three soft area lights (softboxes), placed relative to the camera so every angle gets the same look:

- **Key**: front-left and above. The main light; sets the shadow direction.
- **Fill**: low, straight in front. Softens shadows. On glossy boxes it also shows up as a softbox reflection on the front face.
- **Rim**: behind the box on the opposite side. Lights the top and back edges so the box separates from the backdrop.

The lights themselves are invisible to the camera; you only see their light and their reflections.

## When a spec is wrong

The spec is checked **before** Blender starts. Every problem is listed in plain English and nothing is rendered:

```
> python run.py tests/broken_colour.json
Spec error in tests/broken_colour.json:
  - box.colour: must be a hex colour like "#F4B6C2", got "pinkish"
Nothing was rendered. Fix the spec and try again.
```

The checks also catch:
- numbers out of range;
- text where a number should be;
- unknown camera names;
- bevels too big for the box;
- broken JSON (with the line and column);
- misspelled field names, with a suggestion such as `box.color: unknown field. Did you mean "box.colour"?`.

## GPU vs CPU

`render_scene.py` forces Cycles onto the GPU itself, so it doesn't depend on the settings saved in Blender's UI (headless runs don't reliably use them). It:

1. sets the Cycles compute device to **OptiX** and enables only the RTX GPU (not the CPU, which would make a slower hybrid render);
2. uses the **OptiX denoiser**;
3. if no OptiX GPU is found, falls back to the **CPU** with the OpenImageDenoise denoiser. It also prints a loud `WARNING` banner, and repeats the warning in the final summary.

On an RTX 5060 Laptop GPU a 1080×1080, 128-sample render takes about 3 seconds. The same render on the CPU took about 24 seconds.

## How it works

| File | Job |
|---|---|
| `run.py` | What you run. Checks the spec, finds Blender, starts it in the background, shows the important lines, saves the PNG, prints the timing. Standard-library Python only. |
| `spec.py` | Defaults and validation for the spec. Used by both `run.py` and `render_scene.py`. |
| `render_scene.py` | Runs inside Blender. Builds the box, backdrop, lights, world and camera from scratch, sets up Cycles + AgX, renders. |
| `specs/` | Example specs. |
| `tests/broken_colour.json` | A deliberately broken spec, to see the error message. |
| `renders/` | Output images (ignored by git). |

Scene details:

- **Box**: a mesh with a Bevel modifier. "Harden normals" keeps the big faces perfectly flat, so glossy reflections don't smear. The material is a Principled BSDF with your colour and roughness.
- **Backdrop**: a floor that curves smoothly up into a back wall, meeting both tangentially, so there is no horizon line.
- **Camera**: an 85 mm lens. The distance is solved so the box fills about 62% of the frame on its tightest side. The lens is shifted so the box sits dead centre.
- **Colour**: the AgX view transform with the "Medium High Contrast" look. Hex colours are converted from sRGB to Blender's linear colour space.

A note on colour: AgX handles bright light gracefully, but it renders very light pastel colours a little softer and paler than their exact hex value. Mid and dark colours stay close.

You can also run the Blender part directly:

```
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python render_scene.py -- --spec specs/pink_three_quarter.json --output renders/test.png
```

## Troubleshooting

- **"Could not find blender.exe"**: pass `--blender "C:\path\to\blender.exe"` or set `BLENDER_PATH`.
- **The WARNING banner says it rendered on the CPU**: update the NVIDIA driver. In Blender, check *Edit → Preferences → System → Cycles Render Devices → OptiX* lists the RTX GPU.
- **"RENDER FAILED"**: run again with `--verbose` to see Blender's full output.

## Roadmap

- **v0 (this)**: JSON spec → studio render of a box.
- **v1**: the Claude API turns a sentence into the JSON spec. `spec.py`'s validator checks Claude's output before anything is rendered.
