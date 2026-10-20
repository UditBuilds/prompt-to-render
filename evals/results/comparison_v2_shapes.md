Columns: **v1.3** is the v2 baseline, all 52 cases on the unchanged v1.3 code (`20261020_192232_v2-baseline`; its 37 cases from before v2 match the saved v1.3 run case by case). **v2-shapes run 1** is the first full run of the v2 code (`20261020_221811_v2-shapes`). **v2-shapes** is the final run (`20261020_222817_v2-shapes-2`), after one prompt rule tuned on dev sentences only (a material or dispenser in the product's name stays unsupported). 3 runs per case, qwen3:8b, temperature 0.2. Last column: how the final run's values were set.

| Case | v1.3 | v2-shapes run 1 | v2-shapes | v2-shapes: values straight from tables or code |
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
| `not_a_box` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 1, default cap by code 3 |
| `logo` | 3/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `bottle_logo` | 3/3 | 3/3 | 3/3 | default cap by code 3 |
| `doc_lipstick` | 3/3 | 3/3 | 3/3 | style shift by code 3, typical size 3, neutral backdrop by code 3 |
| `doc_emerald` | 3/3 | 3/3 | 3/3 | table colour 3, gloss by code 3 |
| `doc_sage` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
| `emerald_serum` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3, neutral backdrop by code 3 |
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
| `oot_periwinkle` | 0/3 | 1/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `oot_sapphire` | 0/3 | 0/3 | 0/3 | typical size 3, neutral backdrop by code 3 |
| `backdrop_pink` | 3/3 | 3/3 | 3/3 | - |
| `backdrop_black` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `shape_lipstick` | 0/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `shape_lipstick_box` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `shape_perfume_bottle` | 0/3 | 3/3 | 3/3 | default cap by code 3 |
| `shape_serum_bottle` | 0/3 | 3/3 | 3/3 | default cap by code 3 |
| `shape_cream_jar` | 0/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3, default cap by code 3 |
| `shape_mascara` | 0/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `shape_gift_box` | 3/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 3 |
| `unsup_glass` | 0/3 | 0/3 | 3/3 | neutral backdrop by code 2, default cap by code 3 |
| `unsup_pump` | 0/3 | 3/3 | 3/3 | neutral backdrop by code 3, default cap by code 3 |
| `unsup_spray` | 0/3 | 0/3 | 3/3 | default cap by code 3 |
| `unsup_squeeze_tube` | 0/3 | 3/3 | 3/3 | neutral backdrop by code 3 |
| `unsup_logo` | 0/3 | 3/3 | 3/3 | typical size 3, neutral backdrop by code 2, default cap by code 3 |
| `unsup_text` | 0/3 | 3/3 | 3/3 | typical size 3 |
| `cap_jar_lid` | 0/3 | 3/3 | 3/3 | - |
| `cap_bottle` | 0/3 | 3/3 | 3/3 | table colour 3, neutral backdrop by code 3 |
| **Runs passed** | 111/156 (71%) | 145/156 (93%) | 150/156 (96%) | |
| **Runs passed, cases from before v2** | 105/111 (95%) | 106/111 (95%) | 105/111 (95%) | |
| **Runs passed, cases added in v2** | 6/45 (13%) | 39/45 (87%) | 45/45 (100%) | |
| **In-table colours: named colour right** | 30/30 (100%) | 30/30 (100%) | 30/30 (100%) | |
| **Out-of-table colours: named colour right** | 9/15 (60%) | 10/15 (67%) | 9/15 (60%) | |
| **Shape choice right** | 6/45 (13%) | 45/45 (100%) | 45/45 (100%) | |
| **Shape sizes right** | 0/15 (0%) | 15/15 (100%) | 15/15 (100%) | |
| **Cases passing every run** | 37/52 | 48/52 | 50/52 | |
| **Retry loop fired** | 0/156 | 0/156 | 0/156 | |
| **Avg prompt tokens per run** | 2291 | 4691 | 4753 | |
| **Largest prompt (one call)** | 2396 | 4795 | 4857 | |
| **Avg LLM time per run** | 2.13 s | 2.29 s | 2.30 s | |
