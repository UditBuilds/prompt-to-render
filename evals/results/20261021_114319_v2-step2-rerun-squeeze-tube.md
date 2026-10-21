**v2-step2-rerun-squeeze-tube**: model `qwen3:8b` (Ollama, local), 3 runs per case, 2026-10-21.

| Case | Sentence | Tests | Passed | Distinct specs | Failed checks |
|---|---|---|---|---|---|
| `unsup_squeeze_tube` | a sunscreen squeeze tube | unsupported: squeeze tube, drawn as the closest shape (cylinder) | 0/3 | 1 | run 1: spec shape jar (want cylinder)<br>run 2: spec shape jar (want cylinder)<br>run 3: spec shape jar (want cylinder) |

- **Overall:** 0/3 runs passed (0%); 0/1 cases passed every run.
- **Shape choice** (1 cases): passed in 0/3 runs (0%).
- **Unsupported lists (the model's own)** (1 cases): passed in 3/3 runs (100%).
- **Retry loop fired:** 0/3 runs (0%); still invalid after 2 attempts: 0.
- **Consistency:** 1/1 cases gave the same spec in every run (temperature 0.2).
- **Non-box shape listed by code, not by the model:** 0 run(s). The model named the shape in its `shape` field; the code put it in the unsupported list.
- **Average LLM time per run:** 2.6 s (4740 prompt + 110 output tokens), model already loaded. Largest prompt of any single call: 4740 tokens.
- **Peak GPU memory while the cases ran:** 6480 MiB (whole card, nvidia-smi, model loaded).
