"""
The eval checks themselves: they are the measuring instrument, so test them.

Run all tests with:  python -m unittest discover tests
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

import run_evals  # noqa: E402
from spec import validate_spec  # noqa: E402


class FakeResult:
    def __init__(self, box=None, camera="three_quarter", background="#EDEDED", unsupported=(),
                 model_unsupported=None, is_box=True, shape="box"):
        self.spec = validate_spec({"box": box or {}, "camera": camera, "background_colour": background})
        self.unsupported = list(unsupported)
        self.model_unsupported = list(unsupported if model_unsupported is None else model_unsupported)
        self.is_box = is_box
        self.shape = shape
        self.ok = True


def passes(check, result, done=None):
    return run_evals.CHECKS[check["type"]](check, result, done or {})[0]


def finished_case(*colours):
    """What a finished case looks like to a style_shift check."""
    return {"runs": [{"valid": True, "spec": {"box": {"colour": c}}} for c in colours]}


class Checks(unittest.TestCase):
    def test_red_hue_wraps_round_zero(self):
        red = {"type": "hue", "min": 345, "max": 15}
        self.assertTrue(passes(red, FakeResult({"colour": "#C8102E"})))   # 351 deg
        self.assertTrue(passes(red, FakeResult({"colour": "#B22222"})))   # 0 deg
        self.assertFalse(passes(red, FakeResult({"colour": "#E75480"})))  # pink, 342 deg
        self.assertFalse(passes(red, FakeResult({"colour": "#FF8C00"})))  # orange, 33 deg

    def test_lightness(self):
        dark = {"type": "lightness", "max": 20}
        self.assertTrue(passes(dark, FakeResult({"colour": "#111111"})))
        self.assertFalse(passes(dark, FakeResult({"colour": "#555555"})))

    def test_hex_ignores_case(self):
        check = {"type": "hex", "equals": "#F4B6C2"}
        self.assertTrue(passes(check, FakeResult({"colour": "#f4b6c2"})))
        self.assertFalse(passes(check, FakeResult({"colour": "#F4B6C3"})))

    def test_ratio_strict_and_inclusive(self):
        tall = {"type": "ratio", "num": "height_cm", "den": "width_cm", "gt": 1.5}
        self.assertFalse(passes(tall, FakeResult({"width_cm": 4, "height_cm": 6})))  # exactly 1.5
        self.assertTrue(passes(tall, FakeResult({"width_cm": 4, "height_cm": 6.1})))
        flat = {"type": "ratio", "num": "height_cm", "den": "width_cm", "max": 0.5}
        self.assertTrue(passes(flat, FakeResult({"width_cm": 10, "height_cm": 5})))  # exactly 0.5

    def test_size_and_dimension(self):
        check = {"type": "size", "side": "shortest", "min": 1.5, "max": 4}
        self.assertTrue(passes(check, FakeResult({"width_cm": 2.5, "height_cm": 8.5, "depth_cm": 2.5})))
        self.assertFalse(passes(check, FakeResult({"width_cm": 5, "height_cm": 8.5, "depth_cm": 5})))
        height = {"type": "dimension", "field": "height_cm", "min": 6, "max": 10}
        self.assertTrue(passes(height, FakeResult({"width_cm": 2.5, "height_cm": 8.5, "depth_cm": 2.5})))
        self.assertFalse(passes(height, FakeResult({"width_cm": 5, "height_cm": 12, "depth_cm": 2.5})))  # v1 lipstick

    def test_top_aspect(self):
        check = {"type": "top_aspect", "max": 1.6}
        self.assertTrue(passes(check, FakeResult({"width_cm": 20, "height_cm": 8, "depth_cm": 15})))
        self.assertFalse(passes(check, FakeResult({"width_cm": 15, "height_cm": 10, "depth_cm": 5})))  # v1 gift box, 3:1
        self.assertFalse(passes(check, FakeResult({"width_cm": 5, "height_cm": 10, "depth_cm": 15})))  # either way round

    def test_unsupported_lists(self):
        mentions = {"type": "model_unsupported_mentions", "any": ["logo"]}
        self.assertTrue(passes(mentions, FakeResult(unsupported=["Gold Logo"])))
        # An item the code added doesn't count: only the model's own list does.
        added = FakeResult(unsupported=["bottle shape", "gold logo"], model_unsupported=[])
        self.assertFalse(passes(mentions, added))
        self.assertTrue(passes({"type": "unsupported_empty"}, FakeResult()))

    def test_shape_contains(self):
        check = {"type": "shape_contains", "any": ["bottle"]}
        self.assertTrue(passes(check, FakeResult(is_box=False, shape="perfume bottle")))
        self.assertFalse(passes(check, FakeResult(is_box=False, shape="cylinder")))

    def test_named_colour_on_box_and_backdrop(self):
        sage = {"type": "named_colour", "name": "sage"}
        self.assertTrue(passes(sage, FakeResult({"colour": "#9CAF88"})))
        self.assertFalse(passes(sage, FakeResult({"colour": "#B5EAD7"})))  # mint, from v1
        blush_backdrop = {"type": "named_colour", "name": "blush", "target": "background"}
        self.assertTrue(passes(blush_backdrop, FakeResult(background="#F8BBD0")))
        self.assertFalse(passes(blush_backdrop, FakeResult(background="#F5F5F5")))

    def test_style_shift(self):
        done = {"plain": finished_case("#D32F2F", "#D32F2F")}  # L* 47, saturation 0.78
        darker = {"type": "style_shift", "than": "plain", "direction": "darker_or_less_saturated",
                  "min_lightness": 5, "min_saturation": 0.1}
        self.assertTrue(passes(darker, FakeResult({"colour": "#7A1F2B"}), done))   # much darker
        self.assertFalse(passes(darker, FakeResult({"colour": "#D32F2F"}), done))  # identical
        self.assertFalse(passes(darker, FakeResult({"colour": "#7A1F2B"}), {}))    # nothing to compare with
        lighter = dict(darker, direction="lighter_or_more_saturated")
        self.assertTrue(passes(lighter, FakeResult({"colour": "#FF6B6B"}), done))
        self.assertFalse(passes(lighter, FakeResult({"colour": "#7A1F2B"}), done))

    def test_invalid_spec_fails_the_run(self):
        result = FakeResult()
        result.ok, result.errors = False, ["box.roughness: ..."]
        outcomes = run_evals.run_checks({"checks": []}, result)
        self.assertFalse(outcomes[0]["passed"])


class ColourDefinitions(unittest.TestCase):
    def test_every_reference_is_inside_its_range(self):
        for name, definition in run_evals.COLOUR_DEFINITIONS.items():
            for ref in definition["references"]:
                with self.subTest(colour=name, ref=ref["hex"]):
                    check = {"type": "named_colour", "name": name}
                    self.assertTrue(passes(check, FakeResult({"colour": ref["hex"]})))

    def test_known_wrong_colours_are_outside(self):
        wrong = {"emerald": "#008000",  # CSS green
                 "sage": "#B5EAD7",     # mint
                 "gold": "#FFD700",     # CSS gold, a golden yellow
                 "navy": "#4169E1",     # royal blue
                 "champagne": "#FFFFFF"}
        for name, colour in wrong.items():
            with self.subTest(colour=name):
                self.assertFalse(passes({"type": "named_colour", "name": name}, FakeResult({"colour": colour})))


class Cases(unittest.TestCase):
    def test_cases_use_known_checks_and_colours(self):
        cases = run_evals.load_cases()
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({c["id"] for c in cases}), 30)
        self.assertEqual(len({c["sentence"] for c in cases}), 30)
        for case in cases:
            for check in case["checks"]:
                self.assertIn(check["type"], run_evals.CHECKS, case["id"])
                if check["type"] == "named_colour":
                    self.assertIn(check["name"], run_evals.COLOUR_DEFINITIONS, case["id"])

    def test_selecting_a_case_brings_its_reference(self):
        ids = [c["id"] for c in run_evals.load_cases(["luxury_red"])]
        self.assertEqual(ids, ["plain_red", "luxury_red"])


if __name__ == "__main__":
    unittest.main()
