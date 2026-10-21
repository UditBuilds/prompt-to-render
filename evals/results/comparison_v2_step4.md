# v2 step 4: text labels

**Columns.** **v2-step3** is the step 4 baseline: the step 3 code (`117543b`) with the step 4 evals (`0ce5df3`), all 94 cases (`20261021_150133_v2-step4-baseline`). **v2-step4** is the final code (`20261021_151759_v2-step4`): the eval ran on `e079d08`'s product code (labels on every shape); the matte check and the renders below ran on `f06c25c`, which adds two fixes that touch rendering and printing only (a guard for a label with no drawable letter, and `run.py` printing a "?" for a character the terminal can't show). 3 runs per case, qwen3:8b, temperature 0.2.

| | v2-step3 | v2-step4 |
|---|---|---|
| All checks | 211/282 (75%) | 255/282 (90%) |
| Original 37 (cases from before v2) | 105/111 (95%) | 105/111 (95%) |
| Cases added in v2 / step 2 / step 3 | 45/45, 39/51, 10/18 | 45/45, 39/51, 9/18 |
| **Cases added in step 4 (labels)** | 12/57 (21%) | **57/57 (100%)** |
| Label text (code; none when nothing is quoted) | 12/54 | 54/54 |
| Label colour (named, metal, or black/white for the body) | 0/33 | 33/33 |
| Unsupported lists as the user sees them (label cases) | 20/48 | 48/48 |
| In-table colour | 30/30 | 30/30 |
| Out-of-table colour, old 5 / new 5 | 9/15, 7/15 | 9/15, 6/15 |
| Shape choice | 141/141 | 141/141 |
| Out-of-table products: shape and size in the same run | 3/15 | 3/15 |
| Rules decided by code (metal, cylinder cap, lid share) | 45/45 | 45/45 |
| Avg LLM time per run | 2.30 s | 2.26 s |
| Peak GPU memory (whole card) | 6,523 MiB | 6,550 MiB |

On the baseline, the model listed the quoted text as unsupported ("ATLAS", "gold text") and drew nothing; only the cases with nothing quoted passed, and one masking case ("BOX" in quotes: the model kept the bottle anyway). "LUXURY" in quotes darkened a white box to L* 73 (a style word, via the tables) in all 3 runs; now the box stays white.

## Regression gate: passes

- **The model's request is unchanged.** The system prompt and its schema are byte for byte those of step 3 (`tests/test_regression_gate.py` pins its sha256 at `117543b`): the label is a code-only spec field. A sentence without quotes is sent unchanged, character for character: in the final run, all 75 earlier cases' 225 runs sent the sentence as written, and none got a label.
- **Code does the same with the same reply.** Every model reply saved in `v2-step3-final` (225 runs) goes through `write_spec` on the final code and gives the same spec (plus `"label": null`), the same unsupported list and the same code changes (a test).
- **Case by case**, the 75 earlier cases pass as on the baseline except one: `oot_new_amethyst` 1/3 -> 0/3, CSS purple `#800080` every time, as in `v2-step3-final` (0/3). Its request is byte for byte the baseline's, so this is sampling. For scale: two runs of the unchanged step 3 code (`v2-step3-final` and this baseline) give the same three specs in 42 of the 75 cases; baseline and final also give the same three specs in 42 of 75.

## Matte check (no model calls): passes

The saved specs of `docs/v2_blush_pink_serum_bottle.png` and `docs/v2_step2_glossy_black_perfume_bottle_gold_cap.png` re-rendered on the final code: mean difference 0.0016 and 0.0017 levels from the docs images, no pixel off by more than 1 (step 3's check: 0.0016 and 0.0017).

## Curved text: yes

Tried once, as planned, on a bottle, a jar and a mascara from the front, three-quarter and top-down cameras: no distortion, clipping, sinking or mirroring. The label is wrapped round the body's side, centred on the camera's direction, its chord 60% of the diameter; the letters are cut into 1.5-degree strips first, so no straight edge sinks into the body. From above (top_down) it lies flat on the cap or lid, coloured for the cap or lid (black on light, white on dark). A box gets it flat on its front, or on its top from above. Every render checks that the camera sees it left to right, upright and from the front, and stops otherwise.

A/B renders of the same spec with and without a label: the same exposure (the light meter hides the label while it meters); outside the label, at most 3 levels on the box, and at most 5 levels on 446 pixels of the jar's body, 30-90 px from the label and slightly darker on average (likely the denoiser reacting to the label's sharp edge; not verified).

## Renders (three_quarter, final code)

| Sentence | File | What came out |
|---|---|---|
| a glossy black perfume bottle with a gold cap and "NOIR" in gold | `docs/v2_step4_glossy_black_perfume_bottle_noir.png` | NOIR in gold metal, wrapped round the black bottle; gold cap |
| a matte pink box with "GLOW" | `docs/v2_step4_matte_pink_box_glow.png` | GLOW in black (the default on a light body) on CSS pink `#FFC0CB` |
| a sage green face cream jar with "CALM" | `docs/v2_step4_sage_green_face_cream_jar_calm.png` | CALM in black, wrapped round the jar |
| a black mascara with a silver cap and "LASH" in white | `docs/v2_step4_black_mascara_lash.png` | LASH in white on the black base; small (1.1 x 0.3 cm: 60% of a 1.7 cm tube); silver cap |
| a glossy emerald perfume box with a logo | `docs/v2_step4_glossy_emerald_perfume_box_logo.png` | no text; "logo" listed as not rendered |

## What got worse, or changed

- Nothing earlier scores lower except `oot_new_amethyst` (sampling, above).
- In a render with a label, the colour check's patch moves below the label, so its Delta E isn't comparable with the same product without one. Black glossy bodies read about as before: Delta E 14.2 (bottle) and 14.7 (mascara), step 2's renders 14.8 and 17.1.
- A metal label brings the strip lights (`spec.has_shine`), so a matte box with gold text gets faint strip highlights it wouldn't get without the label.
- `run.py` now prints a "?" for a character the terminal can't show, as `prompt.py` already did (a label is printed in the render log).

## Choices made by default (not asked)

- Only double quotes count, straight `"` and curly `“ ”`, never apostrophes or single quotes. Spaces at the ends are trimmed, a line break becomes a space, empty quotes are no label, and "first" is the leftmost. A first text over 20 characters is not drawn, and the next one is not drawn in its place.
- The colour phrase is `in <colour>` right after the text (also "printed in", and with "letters", "text" or "label" around it). Any word after "in" that isn't a known colour is listed as an unknown label colour (so "in bold" would be too); "in the ..." and similar are left alone.
- The label is never taller than half the face (or wall) it is on: a flat scarf box's front is 30 cm wide but 4 cm high.
- From top_down the side facing the camera is the top: a box's top face, a round shape's cap or lid.

## Known limits

- An inch mark pairs with the next quote: `a 12" box with "NOIR"` reads ` box with ` as the label.
- A label in the same metal as its cap is invisible from above (gold on a gold cap).
- Only Blender's built-in font. Tried and drawn: Latin accents (`maison Lumière`), `º`, `&`, `★`, and Chinese (`香水`, `NOIR 香`; Blender bundles fallback fonts). If a text had no letter the font can draw, the renderer would skip the label with a warning instead of crashing; nothing tried triggers that guard.

## Per case

| Case | v2-step3 | v2-step4 | v2-step4: values straight from tables or code |
|---|---|---|---|
| `red_lipstick` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `navy_serum` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `hex_exact` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `hex_glossy` | 3/3 | 3/3 | gloss by code 3, neutral backdrop by code 3 |
| `glossy_black` | 3/3 | 3/3 | gloss by code 3, neutral backdrop by code 3 |
| `shiny_gold` | 3/3 | 3/3 | table colour 3, typical size 3, gloss by code 3, neutral backdrop by code 3 |
| `matte_white` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `camera_front` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `camera_top_down` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `camera_three_quarter` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `tall` | 3/3 | 3/3 | neutral backdrop by code 3 |
| `flat` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `vague` | 3/3 | 3/3 | neutral backdrop by code 3 |
| `not_a_box` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `logo` | 3/3 | 3/3 | neutral backdrop by code 3 |
| `bottle_logo` | 3/3 | 3/3 | default cap by code 3 |
| `doc_lipstick` | 3/3 | 3/3 | style shift by code 3, typical size 3, neutral backdrop by code 2 |
| `doc_emerald` | 3/3 | 3/3 | table colour 3, gloss by code 3 |
| `doc_sage` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `emerald_serum` | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `sage_tea` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `crimson` | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `wine_gift` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `blush` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `champagne` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `high_gloss_white` | 3/3 | 3/3 | gloss by code 3, neutral backdrop by code 3 |
| `plain_red` | 3/3 | 3/3 | neutral backdrop by code 3 |
| `luxury_red` | 3/3 | 3/3 | style shift by code 3, neutral backdrop by code 3 |
| `plain_blue` | 3/3 | 3/3 | neutral backdrop by code 3 |
| `playful_blue` | 3/3 | 3/3 | style shift by code 3, neutral backdrop by code 3 |
| `oot_rust` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_ochre` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_fuchsia` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_periwinkle` | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_sapphire` | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `backdrop_pink` | 3/3 | 3/3 | - |
| `backdrop_black` | 3/3 | 3/3 | typical size 3 |
| `shape_lipstick` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_lipstick_box` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `shape_perfume_bottle` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `shape_serum_bottle` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `shape_cream_jar` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_mascara` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_gift_box` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `unsup_glass` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_pump` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_spray` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_squeeze_tube` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3, shape redrawn by code 3 |
| `unsup_logo` | 3/3 | 3/3 | typical size 3, default cap by code 3 |
| `unsup_text` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `cap_jar_lid` | 3/3 | 3/3 | metal by code 3, size clamped by code 3 |
| `cap_bottle` | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3, metal by code 3 |
| `oot_shape_micellar_water` | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_beard_oil` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_eyebrow_pencil` | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3, size clamped by code 3 |
| `oot_shape_marker_pen` | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3, size clamped by code 3 |
| `oot_shape_body_butter` | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3, size clamped by code 3 |
| `capcyl_lipstick` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `capcyl_mascara` | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `capcyl_lip_balm` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `metal_lipstick_cap` | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_silver_cap` | 3/3 | 3/3 | metal by code 3 |
| `metal_rose_gold_cap` | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_chrome_cap` | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_copper_lid` | 3/3 | 3/3 | typical size 3, metal by code 3 |
| `metal_bronze_lid` | 3/3 | 3/3 | table colour 3, neutral backdrop by code 2, metal by code 3, size clamped by code 3 |
| `metal_not_logo` | 3/3 | 3/3 | default cap by code 3 |
| `metal_not_body` | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `lid_share_jar` | 3/3 | 3/3 | table colour 3, typical size 3, default cap by code 3 |
| `oot_new_vermilion` | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_new_marigold` | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_new_chartreuse` | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_new_prussian_blue` | 3/3 | 3/3 | neutral backdrop by code 3 |
| `oot_new_amethyst` | 1/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `lid_quarter_jar` | 3/3 | 3/3 | table colour 3, typical size 3, default cap by code 3 |
| `label_quoted` | 0/3 | 3/3 | neutral backdrop by code 3 |
| `label_curly_quotes` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `label_case_and_accent` | 0/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `label_apostrophes` | 0/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `label_none_brand` | 3/3 | 3/3 | style shift by code 3, typical size 3, neutral backdrop by code 3 |
| `label_unquoted_logo` | 3/3 | 3/3 | table colour 3, gloss by code 3, neutral backdrop by code 3 |
| `label_unquoted_brand_name` | 3/3 | 3/3 | neutral backdrop by code 1, default cap by code 3 |
| `label_two_quoted` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `label_metal_gold` | 0/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `label_named_white` | 0/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `label_named_table_colour` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `label_unknown_colour` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `label_too_long` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `label_style_word_quoted` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `label_shape_word_quoted` | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `label_render_noir_bottle` | 0/3 | 3/3 | gloss by code 3, neutral backdrop by code 3, metal by code 3 |
| `label_render_glow_box` | 0/3 | 3/3 | neutral backdrop by code 3 |
| `label_render_calm_jar` | 0/3 | 3/3 | table colour 3, typical size 3, default cap by code 3 |
| `label_render_lash_mascara` | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3, metal by code 3 |
