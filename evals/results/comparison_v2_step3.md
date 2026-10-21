# v2 step 3: proportions, jar lid, colour format

**Columns.** **v2-step2** is the step 3 baseline: the step 2 code (`981e2a6`) with the step 3 evals (`51aa9c4`), all 75 cases (`20261021_123756_v2-step3-baseline`); its 69 earlier cases match `v2-step2-final` case by case. **v2-step3** is the final code (`9dd7872`): hex colours as before, code-held proportions, the jar lid at 25% and a lower three-quarter camera for jars (`20261021_141144_v2-step3-final`). The **HSL run** (`20261021_134614_v2-step3`, code `0248a5e`) had the same changes plus colours written as HSL; HSL was reverted (below). 3 runs per case, qwen3:8b, temperature 0.2.

| | v2-step2 | v2-step3 |
|---|---|---|
| All checks | 199/225 (88%) | 198/225 (88%) |
| Original 37 (cases from before v2) | 105/111 (95%) | 105/111 (95%) |
| Cases added in v2 / v2 step 2 | 45/45, 39/51 | 45/45, 39/51 |
| In-table colour | 30/30 | 30/30 |
| Out-of-table colour, old 5 | 9/15 | 9/15 |
| Out-of-table colour, NEW 5 | 7/15 | 6/15 |
| Shape choice | 84/84 | 84/84 |
| Out-of-table products: shape and size in the same run | 3/15 | 3/15 |
| Rules decided by code (metal, cylinder cap, lid share) | 39/39 | 39/39 |
| Passes only because a size clamp fired | - | none (clamps fired in 15 runs) |
| Avg LLM time per run | 2.28 s | 2.27 s |
| Peak GPU memory (whole card) | 6,465 MiB | 6,565 MiB |

**Regression gate: passes.** All 69 earlier cases give the same pass count as the baseline, case by case. The only change is a new case: `oot_new_amethyst` 1/3 -> 0/3. The request the model gets for that box sentence is byte for byte the baseline's (the clamp runs after the reply), so this is sampling: a rerun gave 0/3 again (`20261021_142040_v2-step3-final-rerun-amethyst`), CSS purple `#800080` every time; the baseline's one pass was `#6A0DAD`. Amethyst passes 1 run in 9 on hex. `hex_exact` and `hex_glossy` pass as before, by the model copying the hex.

## Did HSL help? On the NEW 5, yes; overall, no. Hex kept, by the user's choice

On the NEW 5, the HSL run scored **9/15** against hex's **7/15** (baseline) and **6/15** (final): vermilion 0 -> 3 and amethyst 1 -> 3, but prussian blue 3 -> 0. That would have kept HSL, but HSL broke the regression gate: the original 37 fell from 105/111 to 102/111.

- `tall`, "a tall, slim grey box": 3/3 -> 0/3. Grey written as hue 210 at 57-100% saturation, a blue.
- `oot_rust`: 3/3 -> 0/3. Rust written as hue 35 at 50% lightness, an orange.
- Both held on a rerun, 0/3 each (`20261021_135834_v2-step3-rerun-tall-rust`). That rerun had an uncommitted change in the working tree (an exact hex for a logo or label left to the model), which touches only sentences with a hex code, so not these two.

The old 5 stayed at 9/15 under HSL only because sapphire went 0/3 -> 3/3, on `#007FFF` (hue 210, 100%, 50%), the same value HSL gave prussian blue (now wrong, too light) and the grey box. That looks like a default the model falls back on in HSL, not colour knowledge. HSL also cost about 1,500 prompt tokens per call (each colour became a three-number object; 4,828 -> 6,323) and 0.85 s per run (2.28 -> 3.13 s). Asked which rule wins, the user chose hex (`8bac148` reverts the HSL commit; its runs stay as evidence). That overrides the plan's rule to keep whichever format scores better on the NEW 5: the final code scores lower there (6/15) than HSL did (9/15).

How HSL was built, for the record: the model wrote `{"hue", "saturation", "lightness"}`, with only the scales in the schema (no example colour), the table was shown in whole-number HSL, code turned it into hex, and code copied an exact hex from the sentence (integer HSL can't hold every hex: `#1B4D3E` -> `#1B4B3D`).

## Proportions held by code

Limits from general product knowledge (`spec.PROPORTION_LIMITS`). Not blind, though: the eval cases, size ranges included, had been read before the limits were written (commit `3170187` wrongly says "before looking at any eval range"), and the choice to keep the diameter and lower the height was made knowing how it would fall on the out-of-table cases. No pass depends on a clamp (below). a jar is never taller than it is wide; a bottle is at least 1.5 cm across and at most 6 times as tall as it is wide; a cylinder is 0.5-15 cm across and 2-40 cm tall. A ratio limit lowers the height and keeps the model's diameter. No size in the product table is ever clamped (a test checks).

In the final run they fired in 15 runs, 5 cases, 3 runs each, and no pass depends on one:

| Case | The model's size | Clamped to | Case passes? |
|---|---|---|---|
| `oot_shape_body_butter` (jar) | 6.5 x 10 cm, taller than wide | 6.5 x 6.5 | no: as tall as wide, the check wants wider (`lt 1`) |
| `oot_shape_eyebrow_pencil` (drawn as a bottle) | 1.2 x 12 | 1.5 x 9 | no: wrong shape |
| `oot_shape_marker_pen` (drawn as a bottle) | 1.2 x 18 | 1.5 x 9 | no: wrong shape |
| `cap_jar_lid`, `metal_bronze_lid` (jars) | 6-6.5 x 8-8.5 | height = diameter | yes, 3/3 each, as before (they check no size) |

So the clamps make the drawn shapes plausible but don't raise the out-of-table score, which stays 3/15: the code holds limits; it doesn't pick sizes. Micellar water is still 2.5 cm across: slim, but a real bottle, so it isn't clamped. (In the HSL run the model itself wrote 3.5 cm there, which passed; that was the longer prompt, not a clamp.)

## Jar

The lid is 25% of the jar's height (step 2: 30%), and the three-quarter camera looks at a jar from 15 degrees up instead of 22; every other shape and camera is unchanged (a test reads the presets). Both lid checks pass 3/3: the new 20-30% (`lid_quarter_jar`) and step 2's 25-35% (`lid_share_jar`). The baseline's 30% also passes the new one (its top edge counts as inside, the user's choice), so the check can't show the change; the render does. `lid_share` is measured to 6 decimals since step 3's evals (re-scoring `v2-step2-final` changed no run).

## Matte check (no model calls)

The saved specs of `docs/v2_blush_pink_serum_bottle.png` (`runs/20261020_223532_a-blush-pink-serum-bottle`) and `docs/v2_step2_glossy_black_perfume_bottle_gold_cap.png` (`runs/20261021_121050_a-glossy-black-perfume-bottle-with-a`, whose render.png is byte for byte the docs image) re-rendered on the final code: both within 1 level of 255 of the docs images, mean difference 0.0016 and 0.0017 levels, no pixel off by more than 1. The same re-render on the unchanged step 2 code gave 0.0015 and 0.0017: render noise. Bottles don't get the jar camera.

## Renders (three_quarter, final code)

| Sentence | File | What came out |
|---|---|---|
| a sapphire perfume bottle with a silver cap | `docs/v2_step3_sapphire_perfume_bottle_silver_cap.png` | `#4F81BC`, a muted mid blue (saturation 45%, sapphire wants 70%+): still too light; silver metal cap |
| a periwinkle serum bottle | `docs/v2_step3_periwinkle_serum_bottle.png` | `#B8A7D8`, hue 261: still lavender (wants 215-255) |
| a sage green face cream jar | `docs/v2_step3_sage_green_face_cream_jar.png` | the lid now a quarter, seen from 15 degrees |
| a body butter jar | `docs/v2_step3_body_butter_jar.png` | **a clamp fired**: the model's 6.5 x 9.5 cm became 6.5 x 6.5 (as tall as wide); yellow `#F4D03F` |
| an amethyst perfume bottle | `docs/v2_step3_amethyst_perfume_bottle.png` | `#6A0DAD`, inside amethyst's range; chosen before any result |

## Per case

| Case | v2-step2 | HSL run (reverted) | v2-step3 | v2-step3: values straight from tables or code |
|---|---|---|---|---|
| `red_lipstick` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `navy_serum` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `hex_exact` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `hex_glossy` | 3/3 | 3/3 | 3/3 | gloss by code 3, neutral backdrop by code 3 |
| `glossy_black` | 3/3 | 3/3 | 3/3 | gloss by code 3, neutral backdrop by code 3 |
| `shiny_gold` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, gloss by code 3, neutral backdrop by code 3 |
| `matte_white` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `camera_front` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `camera_top_down` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `camera_three_quarter` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `tall` | 3/3 | 0/3 | 3/3 | neutral backdrop by code 3 |
| `flat` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `vague` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `not_a_box` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `logo` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `bottle_logo` | 3/3 | 3/3 | 3/3 | default cap by code 3 |
| `doc_lipstick` | 3/3 | 3/3 | 3/3 | style shift by code 3, typical size 3, neutral backdrop by code 3 |
| `doc_emerald` | 3/3 | 3/3 | 3/3 | table colour 3, gloss by code 3 |
| `doc_sage` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `emerald_serum` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 1, neutral backdrop by code 3 |
| `sage_tea` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `crimson` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `wine_gift` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `blush` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `champagne` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `high_gloss_white` | 3/3 | 3/3 | 3/3 | gloss by code 3, neutral backdrop by code 3 |
| `plain_red` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `luxury_red` | 3/3 | 3/3 | 3/3 | style shift by code 3, neutral backdrop by code 3 |
| `plain_blue` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `playful_blue` | 3/3 | 3/3 | 3/3 | style shift by code 3, neutral backdrop by code 3 |
| `oot_rust` | 3/3 | 0/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_ochre` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_fuchsia` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_periwinkle` | 0/3 | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_sapphire` | 0/3 | 3/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `backdrop_pink` | 3/3 | 3/3 | 3/3 | - |
| `backdrop_black` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `shape_lipstick` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_lipstick_box` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `shape_perfume_bottle` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `shape_serum_bottle` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `shape_cream_jar` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_mascara` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_gift_box` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `unsup_glass` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_pump` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_spray` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_squeeze_tube` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3, shape redrawn by code 3 |
| `unsup_logo` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 1, default cap by code 3 |
| `unsup_text` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `cap_jar_lid` | 3/3 | 3/3 | 3/3 | metal by code 3, size clamped by code 3 |
| `cap_bottle` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3, metal by code 3 |
| `oot_shape_micellar_water` | 0/3 | 3/3 | 0/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_beard_oil` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_eyebrow_pencil` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3, size clamped by code 3 |
| `oot_shape_marker_pen` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3, size clamped by code 3 |
| `oot_shape_body_butter` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3, size clamped by code 3 |
| `capcyl_lipstick` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `capcyl_mascara` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `capcyl_lip_balm` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `metal_lipstick_cap` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_silver_cap` | 3/3 | 3/3 | 3/3 | metal by code 3 |
| `metal_rose_gold_cap` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_chrome_cap` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_copper_lid` | 3/3 | 3/3 | 3/3 | typical size 3, metal by code 3 |
| `metal_bronze_lid` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 1, metal by code 3, size clamped by code 3 |
| `metal_not_logo` | 3/3 | 3/3 | 3/3 | default cap by code 3 |
| `metal_not_body` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `lid_share_jar` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, default cap by code 3 |
| `oot_new_vermilion` | 0/3 | 3/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_new_marigold` | 0/3 | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_new_chartreuse` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_new_prussian_blue` | 3/3 | 0/3 | 3/3 | neutral backdrop by code 3 |
| `oot_new_amethyst` | 1/3 | 3/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `lid_quarter_jar` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, default cap by code 3 |
