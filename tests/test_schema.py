"""
The JSON schema the LLM is held to and the validator must agree.

Both are built from spec.FIELDS. These tests check that the result really
agrees: every value at the edge of the schema's ranges passes the validator,
and every value just outside fails it.

Run all tests with:  python -m unittest discover tests
"""

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
    raw = spec.validate_spec({})  # all defaults
    if len(path) == 2:
        raw[path[0]][path[1]] = value
    else:
        raw[path[0]] = value
    # A big box, so the bevel rule doesn't get in the way of bevel range tests.
    if path != ("box", "width_cm") and path != ("box", "height_cm") and path != ("box", "depth_cm"):
        raw["box"].update(width_cm=200, height_cm=200, depth_cm=200)
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
        self.assertEqual(list(full["properties"]["box"]["properties"]), list(spec.DEFAULTS["box"]))
        self.assertEqual(full["required"], list(spec.DEFAULTS))
        self.assertFalse(full["additionalProperties"])

    def test_defaults_are_valid(self):
        self.assertTrue(is_valid({}))
        self.assertTrue(is_valid(spec.DEFAULTS))

    def test_number_ranges(self):
        for path, prop in leaf_schemas():
            if prop["type"] not in ("number", "integer"):
                continue
            low, high = prop["minimum"], prop["maximum"]
            step = 1 if prop["type"] == "integer" else 0.001
            with self.subTest(field=".".join(path)):
                if path == ("box", "bevel_cm"):
                    high = 99.9  # its real upper limit is half the smallest side
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

    def test_llm_schema_is_the_spec_schema(self):
        llm_spec = llm_backend.output_schema()["properties"]["spec"]
        self.assertEqual(llm_spec, spec.json_schema(only=llm_backend.LLM_FIELDS))
        self.assertEqual(set(llm_spec["properties"]), set(llm_backend.LLM_FIELDS))

    def test_system_prompt_contains_schema(self):
        prompt = llm_backend.system_prompt()
        self.assertNotIn("<<SCHEMA>>", prompt)
        self.assertIn('"bevel_cm"', prompt)


if __name__ == "__main__":
    unittest.main()
