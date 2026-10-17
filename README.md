# Prompt-to-Render (v0.1)

Turn a small JSON file into a clean studio product shot of a box (cosmetics-packaging style), rendered headless in Blender on the GPU.

```
python run.py specs/pink_three_quarter.json
```

One command builds the whole scene from scratch and saves a PNG to `renders/`. The scene has a bevelled box, a seamless curved backdrop, soft area lights and an auto-framed camera.

v0 is fully driven by the JSON spec. The plan for v1 is to have the Claude API write that JSON from a plain-English sentence ("a pink matte serum box, three-quarter view").

## Examples

All three are rendered in `accurate` colour mode, 1080×1080, 128 samples, about 3 seconds each on an RTX 5060 Laptop GPU.

![Pink matte box, three-quarter view](docs/pink_three_quarter.png)
`specs/pink_three_quarter.json`: tall pink matte carton (`#E8A3B5`) on a blush sweep, three-quarter view.

![Black glossy box, three-quarter view](docs/black_glossy_three_quarter.png)
`specs/black_glossy_three_quarter.json`: black glossy box (`#111111`, roughness 0.12) on a warm grey sweep, three-quarter view.

![White matte box, top-down view](docs/white_top_down.png)
`specs/white_top_down.json`: flat white matte carton (`#F4F3EF`) on sage, seen from directly above.

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
python run.py specs/black_glossy_three_quarter.json
python run.py specs/white_top_down.json
```

You'll see something like:

```
Rendering specs/pink_three_quarter.json with C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
[render] device: GPU (OptiX) - NVIDIA GeForce RTX 5060 Laptop GPU
[render] camera: three_quarter, lighting: studio_soft, colour mode: accurate, 1080x1080, 128 samples
[cycles] Path tracing on: NVIDIA GeForce RTX 5060 Laptop GPU (OptiX) [...]
[cycles] Denoising on: NVIDIA GeForce RTX 5060 Laptop GPU (OptiX) [...]
[render] light meter: exposure -0.64 stops (0.3 s)
[render] render time: 3.0 s
[render] saved: C:\Projects\prompt-to-render\renders\pink_three_quarter_20261017_214802.png
[render] colour check: spec #E8A3B5, measured #E29DAF, Delta E 2.2 (small)

Done.
  Spec:         specs/pink_three_quarter.json
  Device:       GPU (OptiX) - NVIDIA GeForce RTX 5060 Laptop GPU
  Cycles:       Path tracing on: NVIDIA GeForce RTX 5060 Laptop GPU (OptiX) [...]
  Cycles:       Denoising on: NVIDIA GeForce RTX 5060 Laptop GPU (OptiX) [...]
  Render time:  3.0 s (total incl. Blender start-up: 5.2 s)
  Colour check: spec #E8A3B5, measured #E29DAF, Delta E 2.2 (small)
  Saved:        renders\pink_three_quarter_20261017_214802.png
```

- The `[cycles] Path tracing on:` line comes from Blender's renderer itself. It shows which device really did the work.
- The colour check line tells you how close the box came out to the colour in your spec (see [Checking colour](#checking-colour)).
- The image is saved as `renders/<spec-name>_<date>_<time>.png`, so earlier renders are never overwritten.

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
  "colour_mode": "accurate",
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
| `colour_mode` | `"accurate"` | `"accurate"`, `"realistic"` | `accurate`: the box colour matches your hex as closely as possible. `realistic`: filmic AgX look; nice highlights, but colours come out paler. See below. |
| `camera` | `"three_quarter"` | `"front"`, `"three_quarter"`, `"top_down"` | Camera angle (see below). |
| `lighting` | `"studio_soft"` | `"studio_soft"` | Lighting setup. Only one for now. |
| `resolution` | `[1080, 1080]` | each side 16 – 8192 | Image size in pixels, `[width, height]`. Non-square works too. |
| `samples` | `128` | 1 – 8192 | Render quality. More is cleaner but slower. 128 is plenty with the denoiser on. |

Size units are centimetres and the box always stands on the floor. The camera reframes itself for any size, so a lipstick box and a gift box both fill the frame the same way.

### Colour modes

**`accurate`** (default) is for when the brand colour matters.
- **View transform:** Blender's *Khronos PBR Neutral*, which was designed for product images. Colours up to about 80% brightness come out nearly unchanged; it subtracts a small amount to cancel surface sheen, so matte colours can come out very slightly darker. Brighter highlights are gently compressed instead of clipping to flat white.
- **Exposure:** set by a **light meter**. Before the real render, the box is briefly made pure matte white and a tiny patch at the centre of its main lit face is rendered (about 0.3 s). This is like a photographer holding a white card where the product is. Exposure is set so that card reads exactly 100%, which makes a matte box show its own colour.
- **White balance:** the same card also sets it. Light bouncing off a coloured backdrop would otherwise tint the box. To counter that, all lights get a slight opposite tint.
- **What it matches:** only the box colour is matched. The backdrop is lit more brightly than the box, so it usually comes out a bit lighter than its hex.

**`realistic`** is the filmic look.
- It uses AgX with the "Medium High Contrast" look. Light and shadow look more film-like, but colours shift: pastels come out noticeably paler, and blacks come out grey.
- Exposure is fixed rather than metered.

Measured colour of the box (see [Checking colour](#checking-colour)). Delta E is the colour difference: under 2 is hard to see, 2–5 small, 5–10 noticeable, over 10 obvious.

| Example | Spec hex | `accurate` measured | ΔE | `realistic` measured | ΔE |
|---|---|---|---|---|---|
| Pink matte | `#E8A3B5` | `#E29DAF` | 2.2 | `#DEBEC5` | 16.6 |
| Black glossy | `#111111` | `#242220` | 8.5 | `#474542` | 24.4 |
| White matte | `#F4F3EF` | `#EBEAE7` | 3.2 | `#D5D5D3` | 10.6 |

A glossy black box can never measure exactly `#111111`. Its shiny surface reflects the bright studio around it, just as it would in a real photo.

### Camera presets

| Preset | Angle |
|---|---|
| `front` | Straight on, from just above the box's middle (8° up). |
| `three_quarter` | 35° to the right and 22° up: the classic packshot showing the front, right side and top. |
| `top_down` | Directly overhead (flat lay). The front of the box is at the bottom of the image. |

The backdrop sweep is always turned to face the camera, like in a real studio, so the camera looks straight into the curve.

### Lighting preset: `studio_soft`

Soft area lights (softboxes), placed relative to the camera so every angle gets the same look:

- **Key**: front-left and above. The main light; sets the shadow direction.
- **Fill**: low, straight in front. Softens shadows. On glossy boxes it also shows up as a softbox reflection on the front face.
- **Rim**: behind the box on the opposite side. Lights the top and back edges so the box separates from the backdrop.
- **Backdrop**: a big softbox behind the box, aimed away from it at the sweep. It lights the far backdrop evenly so it doesn't fall off into dark corners.

For `top_down` the setup changes. From straight above, a rim light only adds a second shadow that crosses the first, and the backdrop light's edge would land in the frame. So top-down uses only the key and fill: a higher, larger key for a short soft shadow, and the fill moved overhead to lighten that shadow.

The lights themselves are invisible to the camera; you only see their light and their reflections.

## Checking colour

`check_colour.py` measures how close a render's box colour is to its spec:

```
> python check_colour.py specs/pink_three_quarter.json renders/pink_three_quarter_20261017_214802.png
Spec:          C:\Projects\prompt-to-render\specs\pink_three_quarter.json
Image:         C:\Projects\prompt-to-render\renders\pink_three_quarter_20261017_214802.png
Patch:         centre of the front face, 37x51 px
Spec colour:   #E8A3B5
Measured:      #E29DAF
Delta E (76):  2.2  (small)
```

It rebuilds the scene from the spec to find exactly where the centre of the box's main lit face is in the image. That's the front face for `front` and `three_quarter`, and the top face for `top_down`. It then averages the pixels in a small patch there and compares them with the spec colour using CIE76 Delta E. It runs Blender in the background for you; nothing extra to install.

`run.py` already runs the same check after every render (the `colour check` line), so you only need this script to re-check an existing image.

Note: in `accurate` mode the light meter and the colour check use the same patch. So the *brightness* of a matte box matches largely by design. The Delta E still catches everything else: wrong hue or saturation, reflections on glossy boxes, and the view transform's effect on colour.

## When a spec is wrong

The spec is checked **before** Blender starts. Every problem is listed in plain English and nothing is rendered:

```
> python run.py tests/broken_colour.json
Spec error in tests/broken_colour.json:
  - box.colour: must be a hex colour like "#F4B6C2", got "pinkish"
Nothing was rendered. Fix the spec and try again.

> python run.py tests/broken_colour_mode.json
Spec error in tests/broken_colour_mode.json:
  - colour_mode: must be one of "accurate", "realistic", got "vivid"
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

On an RTX 5060 Laptop GPU a 1080×1080, 128-sample render takes about 3 seconds, plus 0.3 s for the light meter in `accurate` mode. The same render on the CPU took about 24 seconds.

## How it works

| File | Job |
|---|---|
| `run.py` | What you run. Checks the spec, finds Blender, starts it in the background, shows the important lines, saves the PNG, prints the timing and colour check. Standard-library Python only. |
| `spec.py` | Defaults and validation for the spec. Used by `run.py`, `render_scene.py` and `check_colour.py`. |
| `render_scene.py` | Runs inside Blender. Builds the box, backdrop, lights, world and camera from scratch, runs the light meter (`accurate` mode), renders, checks the colour. |
| `check_colour.py` | Measures the box colour in a render against the spec (spec hex, measured hex, Delta E). |
| `specs/` | Example specs. |
| `tests/` | Deliberately broken specs, to see the error messages. |
| `docs/` | The example images shown above. |
| `renders/` | Output images (ignored by git). |

Scene details:

- **Box**: a mesh with a Bevel modifier. "Harden normals" keeps the big faces perfectly flat, so glossy reflections don't smear. The material is a Principled BSDF with your colour and roughness.
- **Backdrop**: a floor that curves smoothly up into a back wall, meeting both tangentially, so there is no horizon line. It is turned to face the camera.
- **Camera**: an 85 mm lens. The distance is solved so the box fills about 62% of the frame on its tightest side. The lens is shifted so the box sits dead centre.
- **Colour**: hex colours are converted from sRGB to Blender's linear colour space. The view transform depends on `colour_mode` (see above).

You can also run the Blender part directly:

```
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python render_scene.py -- --spec specs/pink_three_quarter.json --output renders/test.png
```

## Troubleshooting

- **"Could not find blender.exe"**: pass `--blender "C:\path\to\blender.exe"` or set `BLENDER_PATH`.
- **The WARNING banner says it rendered on the CPU**: update the NVIDIA driver. In Blender, check *Edit → Preferences → System → Cycles Render Devices → OptiX* lists the RTX GPU.
- **"RENDER FAILED"**: run again with `--verbose` to see Blender's full output.

## Roadmap

- **v0**: JSON spec → studio render of a box.
- **v0.1 (this)**: colour modes with a measured colour check, cleaner backdrops, softer top-down lighting.
- **v1**: the Claude API turns a sentence into the JSON spec. `spec.py`'s validator checks Claude's output before anything is rendered.
