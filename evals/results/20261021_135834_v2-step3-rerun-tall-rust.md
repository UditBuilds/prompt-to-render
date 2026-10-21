**v2-step3-rerun-tall-rust**: model `qwen3:8b` (Ollama, local), 3 runs per case, 2026-10-21.

| Case | Sentence | Tests | Passed | Distinct specs | Failed checks |
|---|---|---|---|---|---|
| `tall` | a tall, slim grey box | tall proportions, named colour | 0/3 | 2 | run 1: saturation 0.57 of box #5C99D6 (want <= 0.2)<br>run 2: saturation 0.57 of box #5C99D6 (want <= 0.2)<br>run 3: saturation 0.57 of box #5C99D6 (want <= 0.2) |
| `oot_rust` | a rust coloured candle box | colour name not in the table: rust | 0/3 | 2 | run 1: box #E69019 as rust: hue 35 not in 8..30; HSL lightness 50% not in 22..48<br>run 2: box #E69019 as rust: hue 35 not in 8..30; HSL lightness 50% not in 22..48<br>run 3: box #CF8217 as rust: hue 35 not in 8..30 |

- **Overall:** 0/6 runs passed (0%); 0/2 cases passed every run.
- **Out-of-table colours, old 5** (1 cases): the named-colour check passed in 0/3 runs; every check in 0/3.
- **Retry loop fired:** 0/6 runs (0%); still invalid after 2 attempts: 0.
- **Consistency:** 0/2 cases gave the same spec in every run (temperature 0.2).
- **Non-box shape listed by code, not by the model:** 0 run(s). The model named the shape in its `shape` field; the code put it in the unsupported list.
- **Average LLM time per run:** 3.2 s (6276 prompt + 147 output tokens), model already loaded. Largest prompt of any single call: 6318 tokens.
- **Peak GPU memory while the cases ran:** 6477 MiB (whole card, nvidia-smi, model loaded).
