"""
The LLM + validation loop, with a scripted fake backend (no Ollama needed).

Run all tests with:  python -m unittest discover tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_backend import BrokenFirstReply, LLMBackend, Reply  # noqa: E402
from spec_writer import parse_reply, write_spec  # noqa: E402

GOOD = {
    "is_box": True,
    "shape": "box",
    "unsupported": ["gold logo"],
    "spec": {
        "description": "A matte red carton.",
        "box": {"width_cm": 2.5, "height_cm": 8.5, "depth_cm": 2.5, "colour": "#9E1B32",
                "roughness": 0.8, "bevel_cm": 0.1},
        "background_colour": "#F2E6E6",
        "camera": "three_quarter",
    },
}


def bad():
    """GOOD with two errors only the validator can catch (the grammar can't)."""
    data = json.loads(json.dumps(GOOD))
    data["spec"]["box"]["roughness"] = 1.4
    data["spec"]["box"]["bevel_cm"] = 2.5
    return data


class FakeBackend(LLMBackend):
    """Replies with the scripted texts in order and records every call."""

    def __init__(self, replies):
        super().__init__("fake")
        self.replies = list(replies)
        self.calls = []

    def generate_spec(self, sentence, previous_errors=None, previous_output=None, reference=None):
        self.calls.append({"sentence": sentence, "previous_errors": previous_errors,
                           "previous_output": previous_output, "reference": reference})
        text = self.replies.pop(0)
        return Reply(text if isinstance(text, str) else json.dumps(text), 100, 50, 0.1)


class Grounded(unittest.TestCase):
    def test_rows_reach_every_attempt(self):
        backend = FakeBackend([bad(), GOOD])
        result = write_spec("a luxury emerald green lipstick box", backend)
        names = [r["name"] for r in result.grounding.rows]
        self.assertEqual(names, ["luxury", "emerald", "lipstick"])
        for call in backend.calls:  # the retry gets the same reference data
            self.assertIn('"emerald green" = #009473', call["reference"])

    def test_a_table_can_be_left_out(self):
        from grounding import load_tables
        tables = {k: v for k, v in load_tables().items() if k != "colours"}
        backend = FakeBackend([GOOD])
        result = write_spec("a luxury emerald green lipstick box", backend, tables=tables)
        self.assertEqual([r["name"] for r in result.grounding.rows], ["luxury", "lipstick"])
        self.assertNotIn("emerald", backend.calls[0]["reference"])

    def test_no_grounding_and_no_match_send_nothing(self):
        backend = FakeBackend([GOOD, GOOD])
        write_spec("a luxury emerald green lipstick box", backend, grounding=False)
        write_spec("a nice box", backend)
        self.assertEqual([c["reference"] for c in backend.calls], [None, None])

    def test_break_first_reply_keeps_the_reference(self):
        inner = FakeBackend([GOOD, GOOD])
        write_spec("an emerald serum box", BrokenFirstReply(inner))
        self.assertIn("#009473", inner.calls[0]["reference"])
        self.assertIn("#009473", inner.calls[1]["reference"])

    def test_code_sets_gloss_and_backdrop_after_the_model(self):
        glossy = json.loads(json.dumps(GOOD))
        glossy["spec"]["box"]["roughness"] = 0.1
        result = write_spec("a glossy red lipstick box", FakeBackend([glossy]))
        self.assertEqual(result.spec["box"]["roughness"], 0.05)
        self.assertEqual(result.finish_change, {"finish": "glossy", "from": 0.1, "to": 0.05})
        self.assertEqual(result.spec["background_colour"], "#F5F5F5")  # GOOD's is #F2E6E6
        self.assertEqual(result.backdrop_change, {"from": "#F2E6E6", "to": "#F5F5F5"})
        # A backdrop the sentence names is the model's.
        result = write_spec("a red lipstick box on a blush backdrop", FakeBackend([GOOD]))
        self.assertEqual(result.spec["background_colour"], "#F2E6E6")
        self.assertIsNone(result.backdrop_change)
        # The model may leave the backdrop out; code then sets the neutral one.
        no_backdrop = json.loads(json.dumps(GOOD))
        del no_backdrop["spec"]["background_colour"]
        result = write_spec("a red lipstick box", FakeBackend([no_backdrop]))
        self.assertFalse(result.backdrop_given)
        self.assertEqual(result.spec["background_colour"], "#F5F5F5")
        self.assertEqual(result.backdrop_change, {"from": None, "to": "#F5F5F5"})
        # Without grounding the model decides everything.
        result = write_spec("a glossy red lipstick box", FakeBackend([glossy]), grounding=False)
        self.assertEqual(result.spec["box"]["roughness"], 0.1)
        self.assertEqual(result.spec["background_colour"], "#F2E6E6")


class RetryLoop(unittest.TestCase):
    def test_valid_first_time(self):
        backend = FakeBackend([GOOD])
        result = write_spec("a red lipstick box", backend)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.attempts), 1)
        self.assertIsNone(backend.calls[0]["previous_errors"])

    def test_invalid_then_fixed(self):
        backend = FakeBackend([bad(), GOOD])
        result = write_spec("a red lipstick box", backend)
        self.assertTrue(result.ok)
        self.assertTrue(result.retried)
        first_errors = result.attempts[0].errors
        self.assertEqual(first_errors, [
            "box.roughness: must be between 0 and 1, got 1.4",
            "box.bevel_cm: must be at most 10% of the smallest box side (0.25 cm for this box), got 2.5",
        ])
        # The exact validator messages and the bad reply went back to the model.
        retry = backend.calls[1]
        self.assertEqual(retry["previous_errors"], first_errors)
        self.assertEqual(json.loads(retry["previous_output"]), bad())

    def test_gives_up_after_two_attempts(self):
        backend = FakeBackend([bad(), bad(), GOOD])
        result = write_spec("a red lipstick box", backend)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(len(result.errors), 2)

    def test_not_json_is_an_error_the_model_sees(self):
        backend = FakeBackend(['{"is_box": true, "unsupp', GOOD])
        result = write_spec("a box", backend)
        self.assertTrue(result.ok)
        self.assertTrue(backend.calls[1]["previous_errors"][0].startswith("Not valid JSON"))

    def test_unsupported_never_reaches_the_spec(self):
        result = write_spec("a red lipstick box with a gold logo", FakeBackend([GOOD]))
        self.assertEqual(result.unsupported, ["gold logo"])
        self.assertTrue(result.is_box)
        self.assertNotIn("unsupported", result.spec)
        self.assertNotIn("is_box", result.spec)
        # Render settings the LLM doesn't write get their defaults.
        self.assertEqual(result.spec["samples"], 128)
        self.assertEqual(result.spec["colour_mode"], "accurate")

    def test_messages_sent_on_retry(self):
        # The real message building (no network): system, user, the bad
        # reply as the assistant, then the errors.
        sent = {}

        class Capture(LLMBackend):
            def _chat(self, messages, schema):
                sent["messages"], sent["schema"] = messages, schema
                return Reply(json.dumps(GOOD))

        Capture("x").generate_spec("a box", ["box.roughness: bad"], '{"old": 1}')
        roles = [m["role"] for m in sent["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(sent["messages"][2]["content"], '{"old": 1}')
        self.assertIn("- box.roughness: bad", sent["messages"][3]["content"])


class ParseReply(unittest.TestCase):
    def test_wrapper_problems_listed(self):
        with self.assertRaises(Exception) as ctx:
            parse_reply(json.dumps({"is_box": "yes", "unsupported": "logo", "spec": []}))
        problems = ctx.exception.problems
        self.assertEqual(len(problems), 4)  # is_box, shape (missing), unsupported, spec

    def test_unsupported_tidied(self):
        data = dict(GOOD, unsupported=[" gold logo ", "Gold logo", "", "stripes"])
        self.assertEqual(parse_reply(json.dumps(data))["unsupported"], ["gold logo", "stripes"])

    def test_non_box_shape_always_listed_first(self):
        # The model named the shape but only listed the logo.
        data = dict(GOOD, is_box=False, shape="Bottle", unsupported=["gold logo"])
        parsed = parse_reply(json.dumps(data))
        self.assertEqual(parsed["unsupported"], ["bottle shape", "gold logo"])
        self.assertTrue(parsed["shape_added"])
        # The model's own list is kept apart: the evals only count that one.
        self.assertEqual(parsed["model_unsupported"], ["gold logo"])

    def test_non_box_shape_not_repeated(self):
        data = dict(GOOD, is_box=False, shape="jar", unsupported=["glass jar", "wooden lid"])
        parsed = parse_reply(json.dumps(data))
        self.assertEqual(parsed["unsupported"], ["glass jar", "wooden lid"])
        self.assertFalse(parsed["shape_added"])

    def test_box_shape_never_added(self):
        parsed = parse_reply(json.dumps(GOOD))
        self.assertEqual(parsed["unsupported"], ["gold logo"])
        self.assertFalse(parsed["shape_added"])


if __name__ == "__main__":
    unittest.main()
