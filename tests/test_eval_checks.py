"""
The eval checks themselves: they are the measuring instrument, so test them.

Run all tests with:  python -m unittest discover tests
"""

import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

import llm_backend  # noqa: E402
import rescore  # noqa: E402
import run_evals  # noqa: E402
from grounding import load_finishes, load_tables, lookup  # noqa: E402
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


def box_colour_name(case):
    return next(c["name"] for c in case["checks"] if c["type"] == "named_colour" and c.get("target") != "background")


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

    def test_neutral_backdrop(self):
        neutral = {"type": "neutral_backdrop", "max_spread": 20, "min_lightness": 80}
        self.assertTrue(passes(neutral, FakeResult(background="#F5F5F5")))   # the code's default
        self.assertTrue(passes(neutral, FakeResult(background="#FAF9F6")))   # off-white, spread 4
        self.assertFalse(passes(neutral, FakeResult(background="#F8D7DA")))  # pale pink, spread 33
        self.assertFalse(passes(neutral, FakeResult(background="#F4C2C2")))  # blush
        self.assertTrue(passes(neutral, FakeResult(background="#F5F5E1")))   # spread exactly 20
        self.assertFalse(passes(neutral, FakeResult(background="#F5F5E0")))  # 21
        self.assertTrue(passes(neutral, FakeResult(background="#CCCCCC")))   # lightness exactly 80%
        self.assertFalse(passes(neutral, FakeResult(background="#C7C7C7")))  # 78%: too dark

    def test_hsl(self):
        self.assertEqual([round(v, 1) for v in run_evals.hex_to_hsl("#009473")], [166.6, 100.0, 29.0])
        self.assertEqual([round(v, 1) for v in run_evals.hex_to_hsl("#9CAF88")], [89.2, 19.6, 61.0])

    def test_hsl_on_a_range_edge(self):
        # #CC9966: lightness exactly 60% (153/255), the top of ochre's range.
        # Unrounded it computed as 60.00000000000001 and failed "<= 60".
        self.assertEqual(run_evals.hex_to_hsl("#CC9966")[2], 60.0)
        self.assertTrue(passes({"type": "named_colour", "name": "ochre"}, FakeResult({"colour": "#CC9966"})))

    def test_invalid_spec_fails_the_run(self):
        result = FakeResult()
        result.ok, result.errors = False, ["box.roughness: ..."]
        outcomes = run_evals.run_checks({"checks": []}, result)
        self.assertFalse(outcomes[0]["passed"])


def shaped(shape, background="#F5F5F5", **fields):
    """A result whose spec has a v2 shape. Built by hand, not validated, so these
    tests don't depend on spec.py."""
    result = FakeResult(background=background)
    result.spec = dict(result.spec, shape=shape)
    del result.spec["box"]
    result.spec[shape] = dict({"colour": "#C8102E", "roughness": 0.5}, **fields)
    return result


class ShapeChecks(unittest.TestCase):
    """The v2 checks. On a spec from v1.3 (no shape field: a box) they must fail, never raise."""

    def test_shape_of_a_spec_without_one_is_box(self):
        self.assertTrue(passes({"type": "shape", "equals": "box"}, FakeResult()))
        self.assertFalse(passes({"type": "shape", "equals": "cylinder"}, FakeResult()))
        self.assertTrue(passes({"type": "shape", "equals": "cylinder"}, shaped("cylinder", diameter_cm=2)))

    def test_shape_size_reads_the_shapes_own_fields(self):
        diameter = {"type": "shape_size", "field": "diameter_cm", "min": 1.5, "max": 2.5}
        self.assertTrue(passes(diameter, shaped("cylinder", diameter_cm=2, height_cm=8)))
        self.assertFalse(passes(diameter, shaped("cylinder", diameter_cm=3, height_cm=8)))
        # A box has no diameter, whatever its width: the v1.3 lipstick box fails.
        lipstick_box = FakeResult({"width_cm": 2, "height_cm": 8.5, "depth_cm": 2})
        self.assertFalse(passes(diameter, lipstick_box))
        height = {"type": "shape_size", "field": "height_cm", "min": 7, "max": 9}
        self.assertTrue(passes(height, lipstick_box))

    def test_shape_ratio(self):
        wider = {"type": "shape_ratio", "num": "height_cm", "den": "diameter_cm", "lt": 1}
        self.assertTrue(passes(wider, shaped("jar", diameter_cm=7, height_cm=5)))
        self.assertFalse(passes(wider, shaped("jar", diameter_cm=5, height_cm=5)))  # exactly 1
        self.assertFalse(passes(wider, FakeResult({"width_cm": 7, "height_cm": 5, "depth_cm": 7})))

    def test_box_checks_fail_on_other_shapes(self):
        cylinder = shaped("cylinder", diameter_cm=2, height_cm=8)
        for check in ({"type": "dimension", "field": "height_cm", "min": 6, "max": 10},
                      {"type": "ratio", "num": "height_cm", "den": "width_cm", "gt": 1.5},
                      {"type": "size", "side": "longest", "min": 5, "max": 60},
                      {"type": "top_aspect", "max": 1.6}):
            with self.subTest(check=check["type"]):
                self.assertFalse(passes(check, cylinder))

    def test_colour_and_finish_are_the_products(self):
        jar = shaped("jar", diameter_cm=7, height_cm=5, colour="#9CAF88", roughness=0.8, lid_colour="#D4AF37")
        self.assertTrue(passes({"type": "named_colour", "name": "sage"}, jar))
        self.assertTrue(passes({"type": "roughness", "min": 0.6}, jar))
        self.assertTrue(passes({"type": "named_colour", "name": "gold", "target": "cap"}, jar))
        self.assertFalse(passes({"type": "named_colour", "name": "sage", "target": "cap"}, jar))
        done = {"plain": finished_case("#D32F2F")}
        darker = {"type": "style_shift", "than": "plain", "direction": "darker_or_less_saturated",
                  "min_lightness": 5, "min_saturation": 0.1}
        self.assertTrue(passes(darker, shaped("cylinder", colour="#7A1F2B"), done))

    def test_cap_colour(self):
        gold_cap = {"type": "named_colour", "name": "gold", "target": "cap"}
        self.assertTrue(passes(gold_cap, shaped("bottle", diameter_cm=3, height_cm=10, cap_colour="#D4AF37")))
        self.assertFalse(passes(gold_cap, shaped("bottle", diameter_cm=3, height_cm=10, cap_colour="#1C1C1C")))
        # Shapes without a cap, and v1.3 specs, fail.
        self.assertFalse(passes(gold_cap, shaped("cylinder", diameter_cm=2, height_cm=8)))
        self.assertFalse(passes(gold_cap, FakeResult({"colour": "#D4AF37"})))

    def test_model_unsupported_excludes(self):
        check = {"type": "model_unsupported_excludes", "any": ["lid", "cap"]}
        self.assertTrue(passes(check, FakeResult(unsupported=["metallic finish"])))
        self.assertFalse(passes(check, FakeResult(unsupported=["Gold Lid"])))
        # Only the model's own list counts.
        self.assertTrue(passes(check, FakeResult(unsupported=["gold lid"], model_unsupported=[])))

    def test_shape_scores_count_their_checks_alone(self):
        checks = [{"type": "shape", "equals": "jar"},
                  {"type": "shape_size", "field": "diameter_cm", "min": 5, "max": 9},
                  {"type": "neutral_backdrop", "max_spread": 20, "min_lightness": 80}]

        def run(shape_ok, size_ok, backdrop_ok=True, valid=True):
            outcomes = [{"passed": shape_ok}, {"passed": size_ok}, {"passed": backdrop_ok}] if valid else [
                {"passed": False}]
            return {"valid": valid, "passed": valid and shape_ok and size_ok and backdrop_ok, "checks": outcomes}

        results = [{"id": "jar", "checks": checks,
                    "runs": [run(True, True, False), run(True, False), run(False, True), run(True, True, valid=False)]},
                   {"id": "other", "checks": checks[2:], "runs": [run(True, True)]}]
        self.assertEqual(run_evals.summarise_shapes(results),
                         {"choice": {"cases": 1, "total_runs": 4, "passed_runs": 2, "clamp_only_runs": 0},
                          "sizes": {"cases": 1, "total_runs": 4, "passed_runs": 2, "clamp_only_runs": 0},
                          # v2 step 3: shape and size both right in the same run.
                          "both": {"cases": 1, "total_runs": 4, "passed_runs": 1, "clamp_only_runs": 0}})

    def test_cases_added_in_v2_are_counted_apart(self):
        results = [{"id": "old", "total_runs": 3, "passed_runs": 3},
                   {"id": "new", "added": "v2", "total_runs": 3, "passed_runs": 1}]
        self.assertEqual(run_evals.summarise_added(results),
                         {"before_v2": {"cases": 1, "total_runs": 3, "passed_runs": 3, "clamp_only_runs": 0},
                          "v2": {"cases": 1, "total_runs": 3, "passed_runs": 1, "clamp_only_runs": 0}})
        results.append({"id": "newer", "added": "v2-step2", "total_runs": 3, "passed_runs": 2})
        self.assertEqual(run_evals.summarise_added(results)["v2_step2"],
                         {"cases": 1, "total_runs": 3, "passed_runs": 2, "clamp_only_runs": 0})
        results.append({"id": "newest", "added": "v2-step3", "total_runs": 3, "passed_runs": 3})
        self.assertEqual(run_evals.summarise_added(results)["v2_step3"],
                         {"cases": 1, "total_runs": 3, "passed_runs": 3, "clamp_only_runs": 0})


class StepTwoChecks(unittest.TestCase):
    """The v2 step 2 checks: what code decides (metal, cylinder cap, lid share). They read
    fields and parts that step 1 specs don't have, and must then fail, never raise."""

    def test_cap_part(self):
        check = {"type": "cap_part"}
        self.assertTrue(passes(check, shaped("bottle", diameter_cm=3, height_cm=10, cap_colour="#1A1A1A")))
        self.assertTrue(passes(check, shaped("jar", diameter_cm=7, height_cm=5, lid_colour="#1A1A1A")))
        self.assertFalse(passes(check, FakeResult()))  # a box

    def test_lid_share_is_measured_on_the_drawn_lid(self):
        check = {"type": "lid_share", "min": 0.25, "max": 0.35}
        jar = shaped("jar", diameter_cm=6.5, height_cm=4.5, lid_colour="#1A1A1A")
        lid = next(p for p in run_evals.shapes.parts("jar", jar.spec["jar"]) if p.name == "Lid")
        heights = [z for _, z in lid.profile]
        share = round((max(heights) - min(heights)) / 0.045, 6)  # as the check measures it (v2 step 3)
        self.assertEqual(passes(check, jar), 0.25 <= share <= 0.35)
        self.assertIn(f"lid {share:.3f}", run_evals.CHECKS["lid_share"](check, jar, {})[1])
        self.assertFalse(passes(check, shaped("bottle", diameter_cm=3, height_cm=10, cap_colour="#1A1A1A")))
        self.assertFalse(passes(check, FakeResult()))

    def test_lid_share_on_a_range_edge(self):
        # v2 step 3: the share is rounded to 6 decimals, like hex_to_hsl. Unrounded,
        # a lid of 0.30 of a 3.5 cm jar computed as 0.30000000000000004 and one of
        # 0.25 of a 4.5 cm jar as 0.24999999999999992.
        top = {"type": "lid_share", "min": 0.20, "max": 0.30}
        bottom = {"type": "lid_share", "min": 0.25, "max": 0.35}
        with mock.patch.object(run_evals.shapes, "JAR_LID_HEIGHT", 0.30):
            self.assertTrue(passes(top, shaped("jar", diameter_cm=5.5, height_cm=3.5, lid_colour="#1A1A1A")))
        with mock.patch.object(run_evals.shapes, "JAR_LID_HEIGHT", 0.25):
            self.assertTrue(passes(bottom, shaped("jar", diameter_cm=6.5, height_cm=4.5, lid_colour="#1A1A1A")))
        with mock.patch.object(run_evals.shapes, "JAR_LID_HEIGHT", 0.31):
            self.assertFalse(passes(top, shaped("jar", diameter_cm=5.5, height_cm=3.5, lid_colour="#1A1A1A")))

    def test_metal(self):
        gold = {"type": "metal", "target": "cap", "equals": "gold"}
        none = {"type": "metal", "target": "cap", "equals": None}
        metal_cap = shaped("bottle", diameter_cm=3, height_cm=10, cap_colour="#D4AF37", cap_metal="gold")
        self.assertTrue(passes(gold, metal_cap))
        self.assertFalse(passes(none, metal_cap))
        self.assertFalse(passes({"type": "metal", "target": "cap", "equals": "rose gold"}, metal_cap))
        lid = shaped("jar", diameter_cm=7, height_cm=5, lid_colour="#B87333", lid_metal="copper")
        self.assertTrue(passes({"type": "metal", "target": "cap", "equals": "copper"}, lid))
        # A step 1 spec has no metal field: its cap is a plain colour.
        plain = shaped("bottle", diameter_cm=3, height_cm=10, cap_colour="#D4AF37")
        self.assertFalse(passes(gold, plain))
        self.assertTrue(passes(none, plain))
        # No cap at all: fails either way.
        self.assertFalse(passes(none, FakeResult()))

    def test_cap_colour_of_a_cylinder(self):
        cap = {"type": "hex", "target": "cap", "equals": "#1A1A1A"}
        self.assertTrue(passes(cap, shaped("cylinder", diameter_cm=2, height_cm=8, cap_colour="#1a1a1a")))
        self.assertFalse(passes(cap, shaped("cylinder", diameter_cm=2, height_cm=8)))  # step 1: no cap

    def test_scores_of_their_own(self):
        def case(id, checks, outcomes, shape_group=None):
            runs = [{"valid": True, "passed": all(o), "checks": [{"passed": p} for p in o]} for o in outcomes]
            return {"id": id, "checks": checks, "shape_group": shape_group, "runs": runs}

        shape = [{"type": "shape", "equals": "jar"}, {"type": "shape_size", "field": "height_cm", "max": 9}]
        results = [case("in", shape, [(True, True), (True, False)]),
                   case("oot", shape, [(False, True), (True, True), (True, True)], "out_of_table"),
                   case("metal", [{"type": "metal", "target": "cap", "equals": "gold"},
                                  {"type": "model_unsupported_excludes", "any": ["cap"]}],
                        [(True, False), (True, True)])]
        self.assertEqual(run_evals.summarise_shapes(results),
                         {"choice": {"cases": 1, "total_runs": 2, "passed_runs": 2, "clamp_only_runs": 0},
                          "sizes": {"cases": 1, "total_runs": 2, "passed_runs": 1, "clamp_only_runs": 0},
                          "both": {"cases": 1, "total_runs": 2, "passed_runs": 1, "clamp_only_runs": 0},
                          "oot_choice": {"cases": 1, "total_runs": 3, "passed_runs": 2, "clamp_only_runs": 0},
                          "oot_sizes": {"cases": 1, "total_runs": 3, "passed_runs": 3, "clamp_only_runs": 0},
                          "oot_both": {"cases": 1, "total_runs": 3, "passed_runs": 2, "clamp_only_runs": 0}})
        self.assertEqual(run_evals.summarise_checks(results),
                         {"unsupported": {"cases": 1, "total_runs": 2, "passed_runs": 1, "clamp_only_runs": 0},
                          "code_rules": {"cases": 1, "total_runs": 2, "passed_runs": 2, "clamp_only_runs": 0}})


class ClampedSizes(unittest.TestCase):
    """v2 step 3: a pass that holds only because code clamped a size is code's, not the model's."""

    def test_checks_run_again_on_the_models_own_sizes(self):
        case = {"id": "jar", "checks": [{"type": "shape", "equals": "jar"},
                                        {"type": "shape_ratio", "num": "height_cm", "den": "diameter_cm", "max": 1}]}
        result = shaped("jar", diameter_cm=6.5, height_cm=6.5, lid_colour="#1A1A1A")
        changes = [{"rule": "jar height at most its diameter", "field": "height_cm", "from": 10.5, "to": 6.5}]
        self.assertEqual(run_evals.unclamped_spec(result.spec, changes)["jar"]["height_cm"], 10.5)
        self.assertEqual(result.spec["jar"]["height_cm"], 6.5)  # the run's own spec is left as it is
        self.assertTrue(all(o["passed"] for o in run_evals.run_checks(case, result)))
        without = run_evals.checks_without_clamps(case, result, changes)
        self.assertEqual([o["passed"] for o in without], [True, False])
        self.assertIsNone(run_evals.checks_without_clamps(case, result, []))

    def test_clamp_only_passes_are_counted_apart(self):
        checks = [{"type": "shape", "equals": "jar"}, {"type": "shape_size", "field": "height_cm", "max": 9}]

        def run(passed, without=None):
            unclamped = None if without is None else [{"passed": True}, {"passed": without}]
            return {"valid": True, "passed": passed, "checks": [{"passed": True}, {"passed": passed}],
                    "checks_without_clamps": unclamped,
                    "passed_without_clamps": None if without is None else without}

        runs = [run(True), run(True, without=False), run(True, without=True), run(False, without=False)]
        self.assertEqual([run_evals.clamp_only(r) for r in runs], [False, True, False, False])
        results = [{"id": "oot", "checks": checks, "shape_group": "out_of_table", "runs": runs,
                    "total_runs": 4, "passed_runs": 3, "added": "v2-step2"}]
        self.assertEqual(run_evals.summarise_shapes(results)["oot_both"],
                         {"cases": 1, "total_runs": 4, "passed_runs": 3, "clamp_only_runs": 1})
        self.assertEqual(run_evals.summarise_added(results)["v2_step2"]["clamp_only_runs"], 1)

    def test_rescore_reruns_the_checks_without_clamps(self):
        spec = validate_spec({"shape": "jar", "jar": {"diameter_cm": 6.5, "height_cm": 6.5},
                              "background_colour": "#F5F5F5"})
        run = {"valid": True, "spec": spec, "validation_errors": [[]], "is_box": False, "shape": "jar",
               "unsupported": [], "model_unsupported": [], "passed": False, "retried": False,
               "llm_seconds": 2.0, "prompt_tokens": 100, "output_tokens": 50, "call_prompt_tokens": [100],
               "checks": [],
               "proportion_changes": [{"rule": "jar height at most its diameter", "field": "height_cm",
                                       "from": 10.5, "to": 6.5}]}
        report = {"cases": [{"id": "oot_shape_body_butter", "checks": [], "runs": [run], "passed_runs": 0,
                             "total_runs": 1, "distinct_specs": 1}]}
        rescore.rescore(report, run_evals.load_cases())
        self.assertFalse(run["passed_without_clamps"])  # 10.5 tall: outside 3-9, not wider than tall
        self.assertFalse(run["passed"])  # 6.5 x 6.5: not wider than tall either, so no clamp-only pass


class ColourDefinitions(unittest.TestCase):
    def test_every_reference_is_inside_its_range(self):
        for name, definition in run_evals.COLOUR_DEFINITIONS.items():
            for ref in definition["references"]:
                with self.subTest(colour=name, ref=ref["hex"]):
                    check = {"type": "named_colour", "name": name}
                    self.assertTrue(passes(check, FakeResult({"colour": ref["hex"]})))

    def test_every_must_fail_colour_is_outside(self):
        for name, definition in run_evals.COLOUR_DEFINITIONS.items():
            for wrong in definition.get("must_fail", []):
                with self.subTest(colour=name, wrong=wrong["hex"]):
                    check = {"type": "named_colour", "name": name}
                    self.assertFalse(passes(check, FakeResult({"colour": wrong["hex"]})))

    def test_emerald_and_sage_v1_2_ranges(self):
        # Set in the v1.2 review of the v1.1 renders.
        emerald = {"type": "named_colour", "name": "emerald"}
        self.assertFalse(passes(emerald, FakeResult({"colour": "#50C878"})))  # Wikipedia: grass green
        self.assertFalse(passes(emerald, FakeResult({"colour": "#208040"})))  # v1's emerald
        self.assertTrue(passes(emerald, FakeResult({"colour": "#009473"})))   # Pantone Emerald
        sage = {"type": "named_colour", "name": "sage"}
        self.assertFalse(passes(sage, FakeResult({"colour": "#BCB88A"})))     # Wikipedia: khaki
        self.assertTrue(passes(sage, FakeResult({"colour": "#9CAF88"})))

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
        self.assertEqual(len(cases), 75)  # 30 from v1.1, 7 added in v1.2, 15 in v2, 17 in v2 step 2, 6 in step 3
        self.assertEqual(sum(c.get("added") == "v2" for c in cases), 15)
        self.assertEqual(sum(c.get("added") == "v2-step2" for c in cases), 17)
        self.assertEqual(sum(c.get("added") == "v2-step3" for c in cases), 6)
        self.assertEqual(len({c["id"] for c in cases}), 75)
        # One sentence on purpose twice: shape_lipstick_box checks only the shape of red_lipstick's.
        sentences = [c["sentence"] for c in cases]
        repeated = {s for s in sentences if sentences.count(s) > 1}
        self.assertEqual(repeated, {"a red lipstick box"})
        self.assertEqual(len(set(sentences)), 74)
        for case in cases:
            for check in case["checks"]:
                self.assertIn(check["type"], run_evals.CHECKS, case["id"])
                if check["type"] == "named_colour":
                    self.assertIn(check["name"], run_evals.COLOUR_DEFINITIONS, case["id"])

    def test_every_sentence_without_a_backdrop_checks_for_a_neutral_one(self):
        for case in run_evals.load_cases():
            names_backdrop = re.search(r"\b(?:backdrop|background)\b", case["sentence"])
            has_check = any(c["type"] == "neutral_backdrop" for c in case["checks"])
            self.assertEqual(has_check, not names_backdrop, case["id"])

    def test_in_table_colour_cases_use_a_table_row(self):
        cases = [c for c in run_evals.load_cases() if c.get("colour_group") == "in_table"]
        self.assertEqual(len(cases), 10)
        for case in cases:
            name = box_colour_name(case)
            self.assertIn(name, load_tables()["colours"], case["id"])
            self.assertIn(("colours", name), [(r["table"], r["name"]) for r in lookup(case["sentence"]).rows])

    def test_out_of_table_colours_stay_out_of_the_table(self):
        # They measure the model on its own. Never add these names to data/colours.json.
        cases = [c for c in run_evals.load_cases() if c.get("colour_group") == "out_of_table"]
        names = [box_colour_name(c) for c in cases]
        self.assertEqual(names, ["rust", "ochre", "fuchsia", "periwinkle", "sapphire"])
        table_words = {word for name, row in load_tables()["colours"].items()
                       for phrase in [name] + row.get("aliases", []) for word in re.findall(r"[a-z]+", phrase)}
        for case, name in zip(cases, names):
            with self.subTest(case=case["id"]):
                self.assertNotIn(name, table_words)
                # No colour row and no style shift reach the model or the code for these sentences.
                rows = lookup(case["sentence"]).rows
                self.assertEqual([r["name"] for r in rows if r["table"] in ("colours", "styles")], [])
                self.assertNotRegex(case["sentence"], r"\b(?:backdrop|background)\b")

    def test_new_out_of_table_colours_stay_out_of_everything(self):
        # v2 step 3's five held-out names, kept apart from the first five (looked at
        # across many sessions). Never add them to a data/ table, the prompt or its
        # schema, the dev set, or another eval sentence.
        cases = [c for c in run_evals.load_cases() if c.get("colour_group") == "out_of_table_new"]
        names = [box_colour_name(c) for c in cases]
        self.assertEqual(names, ["vermilion", "marigold", "chartreuse", "prussian blue", "amethyst"])
        tables = dict(load_tables(), finishes=load_finishes())
        texts = {
            "data/ tables": " | ".join(phrase.lower() for entries in tables.values() for name, row in entries.items()
                                       for phrase in [name] + row.get("aliases", [])),
            "the prompt and its schema": llm_backend.system_prompt().lower(),
            "other eval sentences": " | ".join(c["sentence"].lower() for c in run_evals.load_cases()
                                               if c not in cases),
        }
        with open(os.path.join(ROOT, "evals", "dev_cases.json"), encoding="utf-8") as f:
            texts["the dev set"] = " | ".join(c["sentence"].lower() for c in json.load(f)["cases"])
        for case, name in zip(cases, names):
            word = name.split()[0]  # "prussian": "blue" alone is in the table's "navy blue"
            for where, text in texts.items():
                with self.subTest(colour=name, where=where):
                    self.assertNotRegex(text, r"\b" + re.escape(word) + r"\b")
            with self.subTest(colour=name, where="grounding"):
                # No colour row and no style shift reach the model or the code for these sentences.
                rows = lookup(case["sentence"]).rows
                self.assertEqual([r["name"] for r in rows if r["table"] in ("colours", "styles")], [])
                self.assertNotRegex(case["sentence"], r"\b(?:backdrop|background)\b")
                # Box sentences, like the first five: no round shape's rule can touch them.
                self.assertRegex(case["sentence"], r"\bbox$")

    def test_out_of_table_shape_products_stay_out_of_the_tables_prompt_and_dev_set(self):
        # They measure the model's own knowledge of shapes and sizes. Never add these
        # products to data/product_sizes.json, to the prompt's examples, or to the dev set.
        cases = [c for c in run_evals.load_cases() if c.get("shape_group") == "out_of_table"]
        products = [re.sub(r"^(?:a|an) ", "", c["sentence"]) for c in cases]
        self.assertEqual(products, ["micellar water", "beard oil", "eyebrow pencil", "marker pen", "body butter"])
        table_phrases = {phrase for name, row in load_tables()["products"].items()
                         for phrase in [name] + row.get("aliases", [])}
        with open(os.path.join(ROOT, "prompts", "spec_writer.md"), encoding="utf-8") as f:
            prompt = f.read().lower()
        with open(os.path.join(ROOT, "evals", "dev_cases.json"), encoding="utf-8") as f:
            dev = " | ".join(c["sentence"].lower() for c in json.load(f)["cases"])
        for case, product in zip(cases, products):
            with self.subTest(case=case["id"]):
                self.assertNotIn(product, table_phrases)
                # No product row reaches the model: no size, no shape.
                self.assertEqual([r["name"] for r in lookup(case["sentence"]).rows if r["table"] == "products"], [])
                self.assertNotRegex(prompt, r"\b" + re.escape(product) + r"\b")
                self.assertNotRegex(dev, r"\b" + re.escape(product) + r"\b")
                # The sentence names the product only, never a shape.
                self.assertNotRegex(case["sentence"], r"\b(?:box|carton|case|package|cylinder|bottle|jar|tube|stick)\b")

    def test_the_material_rule_examples_are_in_no_eval_sentence(self):
        # The prompt rule that a material or dispenser in the product's name stays
        # unsupported was written after unsup_glass and unsup_spray failed in v2's
        # first run, with examples close to them ("a glass bottle", "a spray
        # bottle"). Since v2 step 2 its examples share no word with any eval sentence.
        with open(os.path.join(ROOT, "prompts", "spec_writer.md"), encoding="utf-8") as f:
            rule = next(line for line in f if "plain and opaque" in line)
        examples = re.findall(r'"([^"]+)"', rule)
        self.assertGreaterEqual(len(examples), 4)
        words = {w for e in examples for w in re.findall(r"[a-z]+(?:-[a-z]+)*", e.lower())} - {"a", "an", "bottle", "jar"}
        sentences = " ".join(c["sentence"].lower() for c in run_evals.load_cases())
        for word in sorted(words):
            with self.subTest(word=word):
                self.assertNotRegex(sentences, r"(?<![\w-])" + re.escape(word) + r"(?![\w-])")

    def test_colour_group_summary_counts_the_box_colour_only(self):
        checks = [{"type": "named_colour", "name": "blush", "target": "background"},
                  {"type": "named_colour", "name": "emerald"}]

        def run(backdrop_ok, box_ok, valid=True):
            outcomes = [{"passed": backdrop_ok}, {"passed": box_ok}] if valid else [{"passed": False}]
            return {"valid": valid, "passed": valid and backdrop_ok and box_ok, "checks": outcomes}

        results = [{"colour_group": "in_table", "checks": checks,
                    "runs": [run(False, True), run(True, True), run(True, False), run(True, True, valid=False)]}]
        self.assertEqual(run_evals.summarise_groups(results),
                         {"in_table": {"cases": 1, "total_runs": 4, "colour_passed_runs": 2, "passed_runs": 1}})

    def test_percentages_round_once_from_the_counts(self):
        # 66/111 is 59.46%; rounding the stored pass_rate (0.595) again gave 60%.
        self.assertEqual(run_evals.percent(66, 111), "59%")
        self.assertEqual(run_evals.percent(1, 8), "13%")  # 12.5%: halves round up
        self.assertEqual(run_evals.percent(0, 111), "0%")
        self.assertEqual(run_evals.percent(30, 30), "100%")

    def test_rescore_runs_the_current_checks_on_saved_specs(self):
        spec = validate_spec({"box": {"colour": "#1B4D3E"}, "background_colour": "#FAF9F6"})
        run = {"valid": True, "spec": spec, "validation_errors": [[]], "is_box": True, "shape": "box",
               "unsupported": [], "model_unsupported": [], "passed": False, "retried": False,
               "llm_seconds": 2.0, "prompt_tokens": 100, "output_tokens": 50, "call_prompt_tokens": [100],
               "checks": [{"check": "neutral_backdrop", "passed": False, "found": "an older check"}]}
        report = {"cases": [{"id": "hex_exact", "checks": [], "runs": [run], "passed_runs": 0,
                             "total_runs": 1, "distinct_specs": 1}]}
        rescored = rescore.rescore(report, run_evals.load_cases())
        self.assertEqual([o["check"] for o in run["checks"]], ["hex", "neutral_backdrop"])
        self.assertTrue(run["passed"])
        self.assertEqual(rescored["summary"]["passed_runs"], 1)

    def test_selecting_a_case_brings_its_reference(self):
        ids = [c["id"] for c in run_evals.load_cases(["luxury_red"])]
        self.assertEqual(ids, ["plain_red", "luxury_red"])


if __name__ == "__main__":
    unittest.main()
