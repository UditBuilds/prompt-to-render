Columns: **v2-shapes** is the step 2 baseline: the v2 step 1 code (`d0a8154`) run on all 69 cases, the step 2 evals included (`20261021_111643_v2-step2-baseline`; its 52 earlier cases match `v2-shapes-2` case by case). **v2-step2 run 1** is the first full run of the step 2 code (`20261021_113449_v2-step2`, commit `1bafae1`). **v2-step2** is the final run (`20261021_120151_v2-step2-final`), after one code rule: a real shape the prompt maps to a cylinder ("tube", "can") is drawn as a cylinder. That rule is not independent of the eval: it was added after `unsup_squeeze_tube` dropped from 3/3 to 0/3 in run 1 (rerun: 0/3, `20261021_114319_v2-step2-rerun-squeeze-tube`), and diagnosed on dev tube sentences only. **Run 1 is the clean measurement of `unsup_squeeze_tube`**; the final 3/3 there is fitted. The rule fired in no other eval run. 3 runs per case, qwen3:8b, temperature 0.2. Last column: how the final run's values were set.

| Case | v2-shapes | v2-step2 run 1 | v2-step2 | v2-step2: values straight from tables or code |
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
| `tall` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `flat` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `vague` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `not_a_box` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `logo` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `bottle_logo` | 3/3 | 3/3 | 3/3 | default cap by code 3 |
| `doc_lipstick` | 3/3 | 3/3 | 3/3 | style shift by code 3, typical size 3, neutral backdrop by code 1 |
| `doc_emerald` | 3/3 | 3/3 | 3/3 | table colour 3, gloss by code 3 |
| `doc_sage` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `emerald_serum` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
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
| `oot_rust` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_ochre` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_fuchsia` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `oot_periwinkle` | 0/3 | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_sapphire` | 0/3 | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
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
| `unsup_squeeze_tube` | 3/3 | 0/3 | 3/3 | neutral backdrop by code 3, default cap by code 3, shape redrawn by code 3 |
| `unsup_logo` | 3/3 | 3/3 | 3/3 | typical size 3, default cap by code 3 |
| `unsup_text` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `cap_jar_lid` | 3/3 | 3/3 | 3/3 | metal by code 3 |
| `cap_bottle` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3, metal by code 3 |
| `oot_shape_micellar_water` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_beard_oil` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_eyebrow_pencil` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_marker_pen` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3 |
| `oot_shape_body_butter` | 0/3 | 0/3 | 0/3 | neutral backdrop by code 3, default cap by code 3 |
| `capcyl_lipstick` | 0/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `capcyl_mascara` | 0/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `capcyl_lip_balm` | 0/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `metal_lipstick_cap` | 0/3 | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_silver_cap` | 0/3 | 3/3 | 3/3 | metal by code 3 |
| `metal_rose_gold_cap` | 0/3 | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_chrome_cap` | 0/3 | 3/3 | 3/3 | neutral backdrop by code 3, metal by code 3 |
| `metal_copper_lid` | 0/3 | 3/3 | 3/3 | typical size 3, metal by code 3 |
| `metal_bronze_lid` | 0/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 1, metal by code 3 |
| `metal_not_logo` | 3/3 | 3/3 | 3/3 | default cap by code 3 |
| `metal_not_body` | 3/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| `lid_share_jar` | 0/3 | 3/3 | 3/3 | table colour 3, typical size 3, default cap by code 3 |
| **Runs passed** | 159/207 (77%) | 186/207 (90%) | 189/207 (91%) | |
| **Runs passed, cases from before v2** | 105/111 (95%) | 105/111 (95%) | 105/111 (95%) | |
| **Runs passed, cases added in v2** | 45/45 (100%) | 42/45 (93%) | 45/45 (100%) | |
| **Runs passed, cases added in v2 step 2** | 9/51 (18%) | 39/51 (76%) | 39/51 (76%) | |
| **In-table colours: named colour right** | 30/30 (100%) | 30/30 (100%) | 30/30 (100%) | |
| **Out-of-table colours: named colour right** | 9/15 (60%) | 9/15 (60%) | 9/15 (60%) | |
| **Shape choice right** | 78/81 (96%) | 78/81 (96%) | 81/81 (100%) | |
| **Shape sizes right** | 15/15 (100%) | 15/15 (100%) | 15/15 (100%) | |
| **Out-of-table products: shape choice right** | 9/15 (60%) | 9/15 (60%) | 9/15 (60%) | |
| **Out-of-table products: shape sizes right** | 6/15 (40%) | 6/15 (40%) | 6/15 (40%) | |
| **Unsupported lists (the model's own) right** | 51/51 (100%) | 51/51 (100%) | 51/51 (100%) | |
| **Rules decided by code (metal cap or lid, cylinder cap, lid share) right** | 6/36 (17%) | 36/36 (100%) | 36/36 (100%) | |
| **Cases passing every run** | 53/69 | 62/69 | 63/69 | |
| **Retry loop fired** | 0/207 | 0/207 | 0/207 | |
| **Avg prompt tokens per run** | 4752 | 4827 | 4827 | |
| **Largest prompt (one call)** | 4857 | 4932 | 4932 | |
| **Avg LLM time per run** | 2.29 s | 2.27 s | 2.27 s | |
| **Peak GPU memory (whole card)** | 6482 MiB | 6480 MiB | 6566 MiB | |

**Regression gate.** The 37 cases from before v2 are 105/111 in all three columns, the same in every case (still failing: `oot_periwinkle` 0/3, `oot_sapphire` 0/3, as since v1.3). The 15 cases added in v2 (step 1): 45/45 in the baseline and the final run. In run 1, `unsup_squeeze_tube` fell to 0/3: "a sunscreen squeeze tube" drawn as a jar, though the model's own shape was still "tube"; a rerun gave 0/3 again. On dev tube sentences, any prompt line saying a cylinder has a cap turned "squeeze tube" sentences into jars, and dropping those lines turned "a ... with a gold/silver cap" cylinders into bottles, so the fix is in code (above), not in the prompt. `unsup_glass` and `unsup_spray` stayed 3/3 with the glass/spray rule's new examples ("a ceramic jar", "a roll-on bottle"); on the dev set, the two spray sentences that passed with the old examples now fail (the model lists nothing). That rule was written once and not tuned after either result.

**Matte check** (no model calls). The saved specs of `docs/v1.3_sage_green_gift_box.png` (`runs/20261020_173001_a-sage-green-gift-box`) and `docs/v2_blush_pink_serum_bottle.png` (`runs/20261020_223532_a-blush-pink-serum-bottle`) re-rendered on the step 2 code: both within 1 level of 255 of the docs images, mean difference 0.002 levels, no pixel off by more than 1. The same re-render on the unchanged step 1 code gave the same numbers, so that is render noise. Neither scene is glossy (roughness 0.4) or metal, so neither gets the strip lights.

**Out-of-table shapes** (the model's own knowledge: products named in no table, no prompt example, no dev sentence). Per product, final run; the baseline was the same:

| Product | Expected | What the model drew (3 runs) | Shape | Size |
|---|---|---|---|---|
| a micellar water | bottle, 3.5-9 x 10-26 cm | bottle 2.5 x 12.5, 3 times | 3/3 | 0/3 (too narrow) |
| a beard oil | bottle, 2.5-6 x 7-16 | bottle 2.5 x 12, 3 times | 3/3 | 3/3 |
| an eyebrow pencil | cylinder, 0.5-1.6 x 9-19 | bottle 1.2 x 12, 3 times | 0/3 | 3/3 |
| a marker pen | cylinder, 0.8-2.6 x 10-17 | bottle 1.2-1.5 x 18, 3 times | 0/3 | 0/3 (too tall) |
| a body butter | jar, 5-12 x 3-9, wider than tall | jar 6.5 x 10-10.5, 3 times | 3/3 | 0/3 (taller than wide) |

Shape choice 9/15, sizes 6/15. Right shape and right size in the same run: 3/15 (beard oil only): the sizes row reads the drawn shape's fields, so the eyebrow pencil's 3 size passes are for a bottle. No step 2 change targets this score.

**Reading the shape rows.** "Shape choice" is not step 1's row any more: it covered step 1's 15 cases (45/45) and now covers 27, the 12 step 2 cases with a shape check included (the capped cylinders, the metal caps and lids, the jar lid), and in the final run one shape (the squeeze tube) is redrawn by code. Those products are named in the size table or in the sentence ("bottle", "jar"), so 81/81 is still mostly copying. The out-of-table rows are the honest shape score.

**What code decides** (scored apart, it measures code, not the model): metal caps and lids, the two-part cylinder and the jar lid's share, 36/36. Metal comes only from a metal word for the cap or lid; both negatives (a gold logo, a gold body with a black cap) stay plain in every run.
