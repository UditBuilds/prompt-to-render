"""
The JSON schema the LLM is held to and the validator must agree.

Both are built from spec.FIELDS. These tests check that the result really
agrees: every value at the edge of the schema's ranges passes the validator,
and every value just outside fails it.

Run all tests with:  python -m unittest discover tests
"""

import glob
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm_backend  # noqa: E402
import spec  # noqa: E402


def leaf_schemas():
    """(path, schema) for every field in the full spec schema."""
    full = spec.json_schema()
    for key, prop in full["properties"].items():
        if prop.get("type") == "object":
            for sub, sub_prop in prop["properties"].items():
                yield (key, sub), sub_prop
        else:
            yield (key,), prop


def with_value(path, value):
    if path == ("shape",):
        return {"shape": value}  # with that shape's defaults
    shape = path[0] if path[0] in spec.SHAPES else "box"
    raw = spec.validate_spec({"shape": shape})  # all defaults
    if len(path) == 2:
        raw[path[0]][path[1]] = value
    else:
        raw[path[0]] = value
    # Keep the bevel rule (a share of the smallest side) out of the way: sharp
    # edges when testing sizes, a big box for everything else. The same for
    # the bottle's rule (at least as tall as wide).
    if path in (("box", "width_cm"), ("box", "height_cm"), ("box", "depth_cm")):
        raw["box"]["bevel_cm"] = 0
    elif shape == "box":
        raw["box"].update(width_cm=200, height_cm=200, depth_cm=200)
    elif path == ("bottle", "diameter_cm"):
        raw["bottle"]["height_cm"] = 200
    elif path == ("bottle", "height_cm"):
        raw["bottle"]["diameter_cm"] = 0.5
    return raw


def is_valid(raw):
    try:
        spec.validate_spec(raw)
        return True
    except spec.SpecError:
        return False


class SchemaMatchesValidator(unittest.TestCase):
    def test_schema_covers_every_field(self):
        full = spec.json_schema()
        self.assertEqual(list(full["properties"]), list(spec.DEFAULTS))
        for shape in spec.SHAPES:
            self.assertEqual(list(full["properties"][shape]["properties"]), list(spec.DEFAULTS[shape]))
            # Every field of a shape is required, except a cap or lid colour (code sets it).
            self.assertEqual(full["properties"][shape]["required"],
                             [k for k in spec.DEFAULTS[shape] if k != spec.CAP_FIELDS.get(shape)])
        # Only the spec's own shape is given, so no shape's object is required.
        self.assertEqual(full["required"], [k for k in spec.DEFAULTS if k not in spec.SHAPES])
        self.assertFalse(full["additionalProperties"])

    def test_defaults_are_valid(self):
        self.assertTrue(is_valid({}))
        for shape in spec.SHAPES:
            with self.subTest(shape=shape):
                self.assertTrue(is_valid({"shape": shape}))
                self.assertTrue(is_valid(spec.validate_spec({"shape": shape})))

    def test_number_ranges(self):
        for path, prop in leaf_schemas():
            if prop["type"] not in ("number", "integer"):
                continue
            low, high = prop["minimum"], prop["maximum"]
            step = 1 if prop["type"] == "integer" else 0.001
            with self.subTest(field=".".join(path)):
                if path == ("box", "bevel_cm"):
                    # Its real upper limit is a share of the smallest side (200 cm here).
                    high = 200 * spec.BEVEL_MAX_SHARE
                for good in (low, high):
                    self.assertTrue(is_valid(with_value(path, good)), good)
                for bad in (low - step, prop["maximum"] + step):
                    self.assertFalse(is_valid(with_value(path, bad)), bad)

    def test_choices(self):
        for path, prop in leaf_schemas():
            if "enum" not in prop:
                continue
            with self.subTest(field=".".join(path)):
                for choice in prop["enum"]:
                    self.assertTrue(is_valid(with_value(path, choice)))
                self.assertFalse(is_valid(with_value(path, "not-a-choice")))

    def test_colour_pattern(self):
        for path, prop in leaf_schemas():
            if "pattern" not in prop:
                continue
            pattern = re.compile(prop["pattern"])
            with self.subTest(field=".".join(path)):
                for value in ("#E8A3B5", "#fff", "#ABC", "red", "#12", "E8A3B5", "#GGGGGG"):
                    self.assertEqual(bool(pattern.match(value)), is_valid(with_value(path, value)), value)

    def test_resolution(self):
        prop = spec.json_schema()["properties"]["resolution"]
        low, high = prop["items"]["minimum"], prop["items"]["maximum"]
        self.assertTrue(is_valid(with_value(("resolution",), [low, high])))
        self.assertFalse(is_valid(with_value(("resolution",), [low - 1, high])))
        self.assertFalse(is_valid(with_value(("resolution",), [low])))

    def test_only_the_specs_own_shape(self):
        jar = spec.validate_spec({"shape": "jar", "jar": {"diameter_cm": 7, "height_cm": 5}})
        self.assertEqual([k for k in jar if k in spec.SHAPES], ["jar"])
        self.assertFalse(is_valid({"shape": "jar", "box": {"width_cm": 7}}))
        self.assertFalse(is_valid({"cylinder": {"diameter_cm": 2}}))  # shape left out: a box
        self.assertFalse(is_valid({"shape": "tube"}))
        # A spec from before v2 has no shape: it is a box, as before.
        for path in glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                           "specs", "*.json")):
            with self.subTest(spec=os.path.basename(path)):
                loaded = spec.load_spec(path)
                with open(path, encoding="utf-8") as f:
                    self.assertNotIn("shape", json.load(f))
                self.assertEqual(loaded["shape"], "box")

    def test_a_bottle_is_at_least_as_tall_as_wide(self):
        self.assertTrue(is_valid({"shape": "bottle", "bottle": {"diameter_cm": 6, "height_cm": 6}}))
        self.assertFalse(is_valid({"shape": "bottle", "bottle": {"diameter_cm": 6, "height_cm": 5.9}}))
        # A jar or cylinder may be either way round.
        self.assertTrue(is_valid({"shape": "jar", "jar": {"diameter_cm": 6, "height_cm": 9}}))
        self.assertTrue(is_valid({"shape": "cylinder", "cylinder": {"diameter_cm": 9, "height_cm": 3}}))

    def test_default_cap_colour(self):
        # Black on a light body, silver-grey on a dark one; a given colour is kept.
        cases = {"#F4C2C2": spec.CAP_ON_LIGHT, "#9CAF88": spec.CAP_ON_LIGHT, "#FFFFFF": spec.CAP_ON_LIGHT,
                 "#1A1A1A": spec.CAP_ON_DARK, "#000080": spec.CAP_ON_DARK, "#800020": spec.CAP_ON_DARK}
        for body, cap in cases.items():
            with self.subTest(body=body):
                self.assertEqual(spec.validate_spec({"shape": "bottle", "bottle": {"colour": body}})["bottle"]
                                 ["cap_colour"], cap)
                self.assertEqual(spec.validate_spec({"shape": "jar", "jar": {"colour": body}})["jar"]["lid_colour"],
                                 cap)
        given = spec.validate_spec({"shape": "jar", "jar": {"colour": "#FFFFFF", "lid_colour": "#D4AF37"}})
        self.assertEqual(given["jar"]["lid_colour"], "#D4AF37")
        self.assertEqual(round(spec.lightness("#777777")), 50)  # the split: about mid grey

    def test_bevel_share_of_smallest_side(self):
        box = {"width_cm": 12, "height_cm": 18, "depth_cm": 8}
        self.assertTrue(is_valid({"box": dict(box, bevel_cm=0.8)}))   # exactly 10% of 8 cm
        self.assertFalse(is_valid({"box": dict(box, bevel_cm=0.81)}))
        self.assertFalse(is_valid({"box": dict(box, bevel_cm=1.5)}))  # the "bar of soap" repair

    def test_llm_schema_is_the_spec_schema(self):
        llm_spec = llm_backend.output_schema()["properties"]["spec"]
        self.assertEqual(llm_spec, spec.json_schema(only=llm_backend.LLM_FIELDS, optional=llm_backend.LLM_OPTIONAL))
        self.assertEqual(set(llm_spec["properties"]), set(llm_backend.LLM_FIELDS))
        # The model may leave the backdrop out, and writes only its shape's
        # object (the parser checks that one is there); the rest it must fill in.
        self.assertEqual(set(llm_spec["required"]), {"description", "shape", "camera"})
        self.assertEqual(set(llm_spec["properties"]) & set(spec.SHAPES), set(spec.SHAPES))

    def test_no_real_size_in_the_schema(self):
        # Like the example hex, an example size in a description would be
        # copied. The only numbers allowed are the roughness scale (0 and 1)
        # and the bevel rule (10%).
        def descriptions(node):
            if isinstance(node, dict):
                if isinstance(node.get("description"), str):
                    yield node["description"]
                for value in node.values():
                    yield from descriptions(value)

        numbers = {n for d in descriptions(llm_backend.output_schema()) for n in re.findall(r"\d+(?:\.\d+)?", d)}
        self.assertLessEqual(numbers, {"0", "1", "10"})

    def test_no_real_colour_in_what_the_model_reads(self):
        # An example hex in the schema was copied for a colour the model didn't know.
        prompt = llm_backend.system_prompt()
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", prompt), [])
        self.assertIn("#RRGGBB", prompt)
        problems = []
        spec.Colour("#000000", "").check("pinkish", "box.colour", problems)
        self.assertEqual(re.findall(r"#[0-9A-Fa-f]{6}\b", problems[0]), [])

    def test_system_prompt_contains_schema(self):
        prompt = llm_backend.system_prompt()
        self.assertNotIn("<<SCHEMA>>", prompt)
        self.assertIn('"bevel_cm"', prompt)


if __name__ == "__main__":
    unittest.main()
