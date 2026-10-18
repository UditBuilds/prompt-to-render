"""
The table lookup (grounding.py): which rows a sentence pulls in.

Run all tests with:  python -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grounding import TABLES, load_tables, lookup  # noqa: E402


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

    def test_nothing_matched_means_no_block(self):
        found = lookup("a nice box")
        self.assertFalse(found)
        self.assertEqual(found.text, "")

    def test_row_limits(self):
        found = lookup("a crimson, wine, burgundy, coral and teal box")
        self.assertEqual(sum(r["table"] == "colours" for r in found.rows), TABLES["colours"][2])

    def test_text_lists_the_values(self):
        text = lookup("a luxury emerald perfume box").text
        self.assertIn('"emerald" = #50C878', text)
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
        # Every phrase belongs to one row only.
        phrases = [p for entries in tables.values() for name, row in entries.items()
                   for p in [name] + row.get("aliases", [])]
        self.assertEqual(len(phrases), len(set(phrases)))


if __name__ == "__main__":
    unittest.main()
