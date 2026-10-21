**v2-step3-final-rerun-amethyst**: model `qwen3:8b` (Ollama, local), 3 runs per case, 2026-10-21.

| Case | Sentence | Tests | Passed | Distinct specs | Failed checks |
|---|---|---|---|---|---|
| `oot_new_amethyst` | an amethyst serum box | new held-out colour name: amethyst | 0/3 | 1 | run 1: box #800080 as amethyst: hue 300 not in 258..290; HSL lightness 25% not in 30..65<br>run 2: box #800080 as amethyst: hue 300 not in 258..290; HSL lightness 25% not in 30..65<br>run 3: box #800080 as amethyst: hue 300 not in 258..290; HSL lightness 25% not in 30..65 |

- **Overall:** 0/3 runs passed (0%); 0/1 cases passed every run.
- **Out-of-table colours, new 5** (1 cases): the named-colour check passed in 0/3 runs; every check in 0/3.
- **Retry loop fired:** 0/3 runs (0%); still invalid after 2 attempts: 0.
- **Consistency:** 1/1 cases gave the same spec in every run (temperature 0.2).
- **Non-box shape listed by code, not by the model:** 0 run(s). The model named the shape in its `shape` field; the code put it in the unsupported list.
- **Average LLM time per run:** 3.0 s (4833 prompt + 129 output tokens), model already loaded. Largest prompt of any single call: 4833 tokens.
- **Peak GPU memory while the cases ran:** 6563 MiB (whole card, nvidia-smi, model loaded).
