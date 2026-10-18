"""
The eval checks themselves: they are the measuring instrument, so test them.

Run all tests with:  python -m unittest discover tests
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

import run_evals  # noqa: E402
from spec import validate_spec  # noqa: E402


class FakeResult:
    def __init__(self, box=None, camera="three_quarter", unsupported=(), is_box=True):
        self.spec = validate_spec({"box": box or {}, "camera": camera})
        self.unsupported = list(unsupported)
        self.is_box = is_box
        self.ok = True


def passes(check, result):
    return run_evals.CHECKS[check["type"]](check, result)[0]


class Checks(unittest.TestCase):
    def test_red_hue_wraps_round_zero(self):
        red = {"type": "hue", "min": 345, "max": 15}
        self.assertTrue(passes(red, FakeResult({"colour": "#C8102E"})))   # 351 deg
        self.assertTrue(passes(red, FakeResult({"colour": "#B22222"})))   # 0 deg
        self.assertFalse(passes(red, FakeResult({"colour": "#E75480"})))  # pink, 340 deg
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

    def test_size(self):
        check = {"type": "size", "side": "shortest", "min": 1.5, "max": 4}
        self.assertTrue(passes(check, FakeResult({"width_cm": 2.5, "height_cm": 8.5, "depth_cm": 2.5})))
        self.assertFalse(passes(check, FakeResult({"width_cm": 5, "height_cm": 8.5, "depth_cm": 5})))

    def test_unsupported(self):
        mentions = {"type": "unsupported_mentions", "any": ["logo"]}
        self.assertTrue(passes(mentions, FakeResult(unsupported=["Gold Logo"])))
        self.assertFalse(passes(mentions, FakeResult(unsupported=[])))
        self.assertTrue(passes({"type": "unsupported_empty"}, FakeResult()))

    def test_invalid_spec_fails_the_run(self):
        result = FakeResult()
        result.ok, result.errors = False, ["box.roughness: ..."]
        outcomes = run_evals.run_checks({"checks": []}, result)
        self.assertFalse(outcomes[0]["passed"])

    def test_every_case_uses_known_checks(self):
        import json
        with open(run_evals.CASES_PATH, encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        self.assertEqual(len(cases), 15)
        for case in cases:
            for check in case["checks"]:
                self.assertIn(check["type"], run_evals.CHECKS, case["id"])


if __name__ == "__main__":
    unittest.main()
