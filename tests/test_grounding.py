"""
The table lookup (grounding.py): which rows a sentence pulls in.

Run all tests with:  python -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grounding import (NEUTRAL_BACKDROP, TABLES, apply_finish, backdrop_colour_words, load_finishes,  # noqa: E402
                       load_tables, lookup, neutral_backdrop)


def names(sentence):
    return [(r["table"], r["name"]) for r in lookup(sentence).rows]


class Lookup(unittest.TestCase):
    def test_longest_phrase_wins(self):
        self.assertEqual(names("a rose gold mascara box"), [("colours", "rose gold"), ("products", "mascara")])
        self.assertEqual(names("an emerald green box")[0], ("colours", "emerald"))

    def test_a_product_word_is_not_also_a_colour(self):
        # "cream" is a colour, but here it is part of the product "face cream".
        self.assertEqual(names("a matte white face cream carton"), [("products", "face cream")])
        self.assertEqual(names("a cream candle box"), [("colours", "cream"), ("products", "candle")])

    def test_whole_words_only(self):
        self.assertEqual(names("a teal tea box"), [("colours", "teal"), ("products", "tea")])
        self.assertEqual(names("a goldfish box"), [])

    def test_aliases_and_hyphens(self):
        self.assertEqual(names("an off-white eco-friendly soap box"),
                         [("colours", "eggshell"), ("styles", "natural"), ("products", "soap")])

    def test_style_words_for_the_backdrop_are_left_out(self):
        self.assertEqual(names("a black box on a playful pink backdrop"), [])
        self.assertEqual(names("a red box on a clean white backdrop"), [])
        self.assertEqual(names("a luxury red box on a pale blush backdrop"),
                         [("styles", "luxury"), ("colours", "blush")])

    def test_common_words_are_not_style_words(self):
        self.assertEqual(names("a simple box"), [])
        self.assertEqual(names("a fun kids box"), [])

    def test_nothing_matched_means_no_block(self):
        found = lookup("a nice box")
        self.assertFalse(found)
        self.assertEqual(found.text, "")

    def test_row_limits(self):
        found = lookup("a crimson, wine, burgundy, coral and teal box")
        self.assertEqual(sum(r["table"] == "colours" for r in found.rows), TABLES["colours"][2])

    def test_text_lists_the_values(self):
        text = lookup("a luxury emerald perfume box").text
        self.assertIn('"emerald" = #009473', text)
        self.assertIn("perfume: typically 7 x 12 x 4.5", text)
        self.assertIn('"luxury": colour becomes deeper and richer (30% darker, 10% less saturated', text)

    def test_style_shift_keeps_hue(self):
        from grounding import apply_style, load_tables
        styles = load_tables()["styles"]
        self.assertEqual(apply_style("#808080", {"lightness": -0.5}), "#404040")
        self.assertEqual(apply_style("#808080", {"lightness": 0.5}), "#C0C0C0")
        deep = apply_style("#D32F2F", styles["luxury"])
        self.assertEqual(deep[1:3] > deep[3:5], True)  # still red
        self.assertNotEqual(deep, "#D32F2F")

    def test_style_skipped_for_an_exact_hex(self):
        from grounding import style_box_colour
        spec = {"box": {"colour": "#123456"}}
        self.assertEqual(style_box_colour("a luxury box in #123456", spec, lookup("a luxury box in #123456")), [])
        self.assertEqual(spec["box"]["colour"], "#123456")
        changes = style_box_colour("a luxury box", spec, lookup("a luxury box"))
        self.assertEqual([c["style"] for c in changes], ["luxury"])
        self.assertNotEqual(spec["box"]["colour"], "#123456")

    def test_tables_are_well_formed(self):
        tables = load_tables()
        self.assertGreaterEqual(len(tables["colours"]), 40)
        self.assertGreaterEqual(len(tables["products"]), 15)
        for name, row in tables["colours"].items():
            self.assertRegex(row["hex"], r"^#[0-9A-F]{6}$", name)
        for name, row in tables["products"].items():
            for axis, value in zip(("width", "height", "depth"), row["typical"]):
                low, high = row[axis]
                self.assertTrue(low <= value <= high, f"{name} {axis}")
        # Every phrase belongs to one row only, finish words included.
        tables["finishes"] = load_finishes()
        phrases = [p for entries in tables.values() for name, row in entries.items()
                   for p in [name] + row.get("aliases", [])]
        self.assertEqual(len(phrases), len(set(phrases)))

    def test_backdrop_colour_words(self):
        # Designed on these dev sentences, not on the eval sentences.
        self.assertEqual(backdrop_colour_words("a white serum box on a mint backdrop"), ["mint"])
        self.assertEqual(backdrop_colour_words("a red box on a clean white backdrop"), ["white"])
        self.assertEqual(backdrop_colour_words("a box in front of a periwinkle backdrop"), ["periwinkle"])
        self.assertEqual(backdrop_colour_words("a navy box on a #F4B6C2 backdrop"), ["#f4b6c2"])
        self.assertEqual(backdrop_colour_words("a cream candle box, background in pale sage"), ["pale", "sage"])
        self.assertEqual(backdrop_colour_words("a lipstick box, background colour lilac"), ["lilac"])
        # A backdrop without a colour, or none at all.
        self.assertEqual(backdrop_colour_words("a nice box on a plain backdrop"), [])
        self.assertEqual(backdrop_colour_words("a teal box against a seamless studio background"), [])
        self.assertEqual(backdrop_colour_words("a luxury teal box"), [])

    def test_neutral_backdrop_unless_one_is_named(self):
        spec = {"background_colour": "#F0E6E6"}
        self.assertEqual(neutral_backdrop("a teal box", spec), {"from": "#F0E6E6", "to": NEUTRAL_BACKDROP})
        self.assertEqual(spec["background_colour"], NEUTRAL_BACKDROP)
        spec = {"background_colour": "#3EB489"}
        self.assertIsNone(neutral_backdrop("a white serum box on a mint backdrop", spec))
        self.assertEqual(spec["background_colour"], "#3EB489")
        spec = {"background_colour": "#f5f5f5"}  # already the neutral one: nothing to report
        self.assertIsNone(neutral_backdrop("a teal box", spec))

    def test_glossy_roughness_is_clamped(self):
        for before, after in ((0.1, 0.05), (0.0, 0.03), (0.15, 0.05)):
            spec = {"box": {"roughness": before}}
            self.assertEqual(apply_finish("a glossy black box", spec),
                             {"finish": "glossy", "from": before, "to": after})
            self.assertEqual(spec["box"]["roughness"], after)
        spec = {"box": {"roughness": 0.04}}  # already in range
        self.assertIsNone(apply_finish("a high-gloss white box", spec))
        self.assertEqual(spec["box"]["roughness"], 0.04)

    def test_other_finishes_are_left_to_the_model(self):
        for sentence in ("a semi-gloss box", "a satin teal tea box", "a matte red lipstick box",
                         "a lip gloss box",                              # a product, not a finish
                         "a matte box on a glossy black backdrop",       # the backdrop's finish
                         "a matte black box with a glossy gold logo"):  # two finishes: unclear
            with self.subTest(sentence=sentence):
                spec = {"box": {"roughness": 0.5}}
                self.assertIsNone(apply_finish(sentence, spec))
                self.assertEqual(spec["box"]["roughness"], 0.5)

    def test_finish_words_never_reach_the_model(self):
        # Code only: no row, so the request the model gets is unchanged.
        self.assertEqual(names("a glossy black box"), [])
        self.assertEqual(names("a matte red lipstick box"), [("products", "lipstick")])


if __name__ == "__main__":
    unittest.main()
