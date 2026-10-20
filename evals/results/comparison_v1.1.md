| Case | baseline | prompt-only | grounded | grounded: values straight from tables or code |
|---|---|---|---|---|
| `red_lipstick` | 0/3 | 0/3 | 3/3 | typical size 3 |
| `navy_serum` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3 |
| `hex_exact` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `hex_glossy` | 3/3 | 3/3 | 3/3 | - |
| `glossy_black` | 3/3 | 3/3 | 3/3 | - |
| `shiny_gold` | 0/3 | 0/3 | 3/3 | table colour 3, typical size 3 |
| `matte_white` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `camera_front` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `camera_top_down` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `camera_three_quarter` | 3/3 | 3/3 | 3/3 | typical size 3 |
| `tall` | 3/3 | 3/3 | 3/3 | - |
| `flat` | 3/3 | 3/3 | 3/3 | - |
| `vague` | 3/3 | 3/3 | 3/3 | - |
| `not_a_box` | 0/3 | 3/3 | 3/3 | - |
| `logo` | 3/3 | 3/3 | 3/3 | - |
| `bottle_logo` | 3/3 | 3/3 | 3/3 | - |
| `doc_lipstick` | 0/3 | 0/3 | 3/3 | style shift by code 3, typical size 3 |
| `doc_emerald` | 2/3 | 0/3 | 3/3 | table colour 3 |
| `doc_sage` | 0/3 | 0/3 | 3/3 | table colour 3, typical size 3 |
| `emerald_serum` | 3/3 | 0/3 | 3/3 | table colour 3, typical size 3 |
| `sage_tea` | 0/3 | 0/3 | 3/3 | table colour 3, typical size 3 |
| `crimson` | 3/3 | 3/3 | 3/3 | table colour 3 |
| `wine_gift` | 0/3 | 0/3 | 3/3 | table colour 3, typical size 3 |
| `blush` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3 |
| `champagne` | 3/3 | 3/3 | 3/3 | table colour 3, typical size 3 |
| `high_gloss_white` | 3/3 | 3/3 | 3/3 | - |
| `plain_red` | 3/3 | 3/3 | 3/3 | - |
| `luxury_red` | 3/3 | 3/3 | 3/3 | style shift by code 3 |
| `plain_blue` | 3/3 | 3/3 | 3/3 | - |
| `playful_blue` | 3/3 | 3/3 | 3/3 | style shift by code 3 |
| **Runs passed** | 68/90 (76%) | 66/90 (73%) | 90/90 (100%) | |
| **Cases passing every run** | 22/30 | 22/30 | 30/30 | |
| **Retry loop fired** | 0/90 | 0/90 | 0/90 | |
| **Avg prompt tokens per run** | 1995 | 2256 | 2348 | |
| **Largest prompt (one call)** | 2002 | 2263 | 2445 | |
| **Avg LLM time per run** | 2.25 s | 2.28 s | 2.29 s | |
