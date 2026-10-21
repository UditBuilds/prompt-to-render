"""
The v2 step 4 regression gate, made a proof rather than a sampling comparison:
a sentence without quotes must give the same spec as before step 4.

Two parts, neither needs Ollama:
- The model's request is unchanged: the system prompt (with its schema) is
  byte for byte the one of v2 step 3 (117543b). Labels are set by code only,
  so nothing about them reaches the model.
- Code does the same with the same reply: every model reply saved in v2
  step 3's final eval run (all 75 cases x 3 runs) goes through write_spec
  again, and must give the same spec, unsupported list and code changes. A
  spec may now hold a "label" field; for these sentences (none has quotes)
  it must be null.

Run all tests with:  python -m unittest discover tests
"""

import hashlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import llm_backend  # noqa: E402
from llm_backend import LLMBackend, Reply  # noqa: E402
from spec_writer import write_spec  # noqa: E402

STEP3_FINAL = os.path.join(ROOT, "evals", "results", "20261021_141144_v2-step3-final.json")
# sha256 of llm_backend.system_prompt() at 117543b, the end of v2 step 3.
STEP3_PROMPT_SHA256 = "e89a98fbc195ab5c786ebbcc15ae207b0a90aad75aac82b2fc763e48161fdc46"
# What code set after the model, as the eval run saved it.
CODE_CHANGES = ("style_changes", "finish_change", "backdrop_change", "backdrop_given", "cap_change",
                "cap_given", "metal_change", "shape_fixed", "proportion_changes")


class SavedReplies(LLMBackend):
    """Replies with one saved run's model outputs, in order."""

    def __init__(self, outputs):
        super().__init__("saved")
        self.outputs = list(outputs)

    def generate_spec(self, sentence, previous_errors=None, previous_output=None, reference=None):
        return Reply(self.outputs.pop(0), 100, 50, 0.1)


class RegressionGate(unittest.TestCase):
    def test_the_model_gets_the_step_3_prompt(self):
        digest = hashlib.sha256(llm_backend.system_prompt().encode("utf-8")).hexdigest()
        self.assertEqual(digest, STEP3_PROMPT_SHA256)

    def test_step_3_replies_give_the_same_specs(self):
        with open(STEP3_FINAL, encoding="utf-8") as f:
            report = json.load(f)
        runs = 0
        for case in report["cases"]:
            self.assertNotRegex(case["sentence"], "[\"“”]")  # no quoted text in any of them
            for run in case["runs"]:
                with self.subTest(case=case["id"], run=run["run"]):
                    result = write_spec(case["sentence"], SavedReplies(run["outputs"]))
                    self.assertEqual(len(result.attempts), run["attempts"])
                    if not run["valid"]:
                        self.assertFalse(result.ok)
                        continue
                    spec = dict(result.spec)
                    self.assertIsNone(spec.pop("label", None))
                    self.assertEqual(spec, run["spec"])
                    self.assertEqual(result.unsupported, run["unsupported"])
                    self.assertEqual(result.model_unsupported, run["model_unsupported"])
                    for field in CODE_CHANGES:
                        self.assertEqual(getattr(result, field), run[field], field)
                runs += 1
        self.assertEqual(runs, 225)


if __name__ == "__main__":
    unittest.main()
