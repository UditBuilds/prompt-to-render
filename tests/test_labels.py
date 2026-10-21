"""
Text labels (v2 step 4): read by code from the sentence's quoted text.

Run all tests with:  python -m unittest discover tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import labels  # noqa: E402
from grounding import load_tables  # noqa: E402
from labels import apply_label, read_label  # noqa: E402
from llm_backend import LLMBackend, Reply  # noqa: E402
from spec import LABEL_ON_DARK, LABEL_ON_LIGHT, METALS, validate_spec  # noqa: E402
from spec_writer import write_spec  # noqa: E402


class Reading(unittest.TestCase):
    def test_the_first_double_quoted_text_exactly(self):
        self.assertEqual(read_label('a black perfume box with "NOIR"').text, "NOIR")
        self.assertEqual(read_label("a white soap box with “Pure Bar”").text, "Pure Bar")  # curly
        self.assertEqual(read_label('a box with "maison Lumière"').text, "maison Lumière")  # case, accent
        self.assertEqual(read_label('a box with "  NO.  5 "').text, "NO. 5")  # ends trimmed, one line
        self.assertEqual(read_label('a box with "TWO\nLINES"').text, "TWO LINES")

    def test_apostrophes_and_single_quotes_never_count(self):
        self.assertEqual(read_label("a charcoal men's grooming box with \"OAK\" for dad's birthday").text, "OAK")
        self.assertIsNone(read_label("a box with 'NOIR'").text)
        self.assertIsNone(read_label("a box with ‘NOIR’").text)
        self.assertIsNone(read_label("men's box for dad's birthday").text)

    def test_no_quotes_no_label(self):
        for sentence in ("a glossy emerald perfume box with a logo", "a white serum bottle with a brand name",
                         "a luxury perfume box from a famous brand", 'a 12" box', 'a box with ""'):
            with self.subTest(sentence=sentence):
                found = read_label(sentence)
                self.assertIsNone(found.text)
                self.assertEqual(found.unsupported, [])

    def test_one_label_per_product(self):
        found = read_label('a black candle box with "EMBER" and "NO. 5"')
        self.assertEqual(found.text, "EMBER")
        self.assertEqual(len(found.unsupported), 1)
        self.assertIn('"NO. 5"', found.unsupported[0])
        self.assertNotIn("EMBER", found.unsupported[0])

    def test_too_long_is_listed_not_drawn_or_cut(self):
        found = read_label('a white gift box with "Happy Birthday Grandma Rose"')
        self.assertIsNone(found.text)
        self.assertEqual(found.unsupported,
                         ['label text over 20 characters, not drawn: "Happy Birthday Grandma Rose" (27 characters)'])
        self.assertEqual(read_label('a box with "' + "x" * 20 + '"').text, "x" * 20)  # exactly 20 is drawn
        # The text that comes second is not drawn in its place.
        found = read_label('a box with "Happy Birthday Grandma Rose" and "ROSE"')
        self.assertIsNone(found.text)
        self.assertEqual(len(found.unsupported), 2)


class Colours(unittest.TestCase):
    def test_a_metal_wins_over_the_colour_of_the_same_name(self):
        for sentence, metal in (('"NOIR" in gold', "gold"), ('"NOIR" in rose gold', "rose gold"),
                                ('"NOIR" in silver', "silver"), ('"NOIR" in golden letters', "gold"),
                                ('"NOIR" in metallic silver', "silver"), ('"NOIR" in copper', "copper")):
            with self.subTest(sentence=sentence):
                found = read_label("a box with " + sentence)
                self.assertEqual((found.metal, found.colour), (metal, None))
        self.assertTrue(all(metal in METALS for metal in ("gold", "rose gold", "silver", "copper")))

    def test_named_colours(self):
        tables = load_tables()["colours"]
        for sentence, colour in (('"LASH" in white', "#FFFFFF"), ('"X" in black', LABEL_ON_LIGHT),
                                 ('"ATLAS" in navy', tables["navy"]["hex"]),
                                 ('"ATLAS" in Navy Blue text', tables["navy"]["hex"]),
                                 ('"X" in sage green', tables["sage"]["hex"]), ('"X" in gray', "#808080"),
                                 ('"SALE" printed in #ff0000', "#FF0000")):
            with self.subTest(sentence=sentence):
                found = read_label("a box with " + sentence)
                self.assertEqual((found.metal, found.colour), (None, colour))
                self.assertEqual(found.unsupported, [])

    def test_an_unknown_colour_is_listed(self):
        found = read_label('a white candle box with "AURA" in cerulean')
        self.assertEqual((found.text, found.metal, found.colour), ("AURA", None, None))
        self.assertEqual(len(found.unsupported), 1)
        self.assertIn('"cerulean"', found.unsupported[0])
        # A place is no colour: nothing listed, nothing named.
        found = read_label('a box with "NOIR" in the centre')
        self.assertEqual((found.colour, found.unsupported), (None, []))

    def test_only_right_after_the_text(self):
        found = read_label('a gold box with "NOIR"')
        self.assertEqual((found.metal, found.colour), (None, None))
        found = read_label('a box with "NOIR" and a lid in gold')
        self.assertEqual((found.metal, found.colour), (None, None))

    def test_label_colours_stay_out_of_the_grounding_tables(self):
        # A plain colour in colours.json would add reference data to every sentence
        # with that word ("a white box") and change the model's request.
        table = {phrase for name, row in load_tables()["colours"].items() for phrase in [name] + row.get("aliases", [])}
        for name, row in labels.load_label_colours().items():
            for phrase in [name] + row.get("aliases", []):
                self.assertNotIn(phrase, table)
            self.assertRegex(row["hex"], r"^#[0-9A-F]{6}$")


class ModelSentence(unittest.TestCase):
    def test_a_sentence_without_quotes_is_unchanged(self):
        for sentence in ("a glossy black perfume bottle with a gold cap", "a  matte   pink box ,",
                         "men's box, for dad's birthday", 'a 12" box', " a box with a logo "):
            with self.subTest(sentence=sentence):
                self.assertIs(read_label(sentence).model_sentence, sentence)

    def test_the_label_and_its_colour_are_left_out(self):
        for sentence, sent in (
                ('a glossy black perfume bottle with a gold cap and "NOIR" in gold',
                 "a glossy black perfume bottle with a gold cap"),
                ('a matte pink box with "GLOW"', "a matte pink box"),
                ('a black mascara with a silver cap and "LASH" in white', "a black mascara with a silver cap"),
                ('a black candle box with "EMBER" and "NO. 5"', "a black candle box"),
                ("a charcoal men's grooming box with \"OAK\" for dad's birthday",
                 "a charcoal men's grooming box for dad's birthday"),
                ('a white candle box with "AURA" in cerulean', "a white candle box"),
                ('a jar with "CALM" and a gold lid', "a jar with a gold lid"),
                ('a box with a "NOIR" label in rose gold', "a box"),
                ('a box with the word "SALE" printed in #ff0000 letters', "a box"),
                ('"NOIR" perfume box, glossy black', "perfume box, glossy black")):
            with self.subTest(sentence=sentence):
                self.assertEqual(read_label(sentence).model_sentence, sent)

    def test_a_quoted_word_means_nothing_else(self):
        for sentence in ('a white serum box with "LUXURY"', 'a white serum bottle with "BOX"',
                         'a white box with "GOLD"', 'a white box with "GLOSS" in navy'):
            with self.subTest(sentence=sentence):
                sent = read_label(sentence).model_sentence
                self.assertNotRegex(sent.lower(), r"luxury|\bbox\b.*\bbox\b|gold|gloss|navy|\"")


class Applying(unittest.TestCase):
    def box(self, colour, camera="three_quarter"):
        return validate_spec({"box": {"colour": colour}, "camera": camera})

    def test_default_black_or_white_for_the_body(self):
        spec = self.box("#111111")
        change, listed = apply_label(read_label('a box with "NOIR"'), spec)
        self.assertEqual(spec["label"], {"text": "NOIR", "colour": LABEL_ON_DARK, "metal": None})
        self.assertEqual((change["colour_from"], listed), ("default", []))
        spec = self.box("#FFFDD0")  # cream
        apply_label(read_label('a box with "NOIR"'), spec)
        self.assertEqual(spec["label"]["colour"], LABEL_ON_LIGHT)
        validate_spec(spec)

    def test_named_and_metal(self):
        spec = self.box("#FFE5B4")  # peach: the default would be black
        change, _ = apply_label(read_label('a box with "SOFT" in white'), spec)
        self.assertEqual((spec["label"]["colour"], change["colour_from"]), ("#FFFFFF", "named"))
        spec = self.box("#000080")
        change, _ = apply_label(read_label('a box with "TRUFFLE" in gold'), spec)
        self.assertEqual(spec["label"], {"text": "TRUFFLE", "colour": METALS["gold"], "metal": "gold"})
        self.assertEqual(change["colour_from"], "metal")
        validate_spec(spec)

    def test_no_label_is_null(self):
        spec = dict(self.box("#111111"), label={"text": "OLD", "colour": "#FFFFFF", "metal": None})
        self.assertEqual(apply_label(read_label("a box"), spec), (None, []))
        self.assertIsNone(spec["label"])  # always set: the model never decides it

    def test_round_shapes_take_the_colour_of_the_part_the_label_is_on(self):
        def bottle(camera, **fields):
            return validate_spec({"shape": "bottle", "camera": camera,
                                  "bottle": dict({"diameter_cm": 4, "height_cm": 12, "colour": "#111111"}, **fields)})

        spec = bottle("three_quarter", cap_colour="#FFFFFF")
        apply_label(read_label('a bottle with "NOIR"'), spec)
        self.assertEqual(spec["label"]["colour"], LABEL_ON_DARK)  # on the black body
        validate_spec(spec)
        # Seen from above, the label is on the cap: white cap, black text.
        spec = bottle("top_down", cap_colour="#FFFFFF")
        apply_label(read_label('a bottle with "NOIR"'), spec)
        self.assertEqual(spec["label"]["colour"], LABEL_ON_LIGHT)
        # A metal cap: its metal's colour (silver is light).
        spec = bottle("top_down", cap_colour="#C0C0C0", cap_metal="silver")
        apply_label(read_label('a bottle with "NOIR"'), spec)
        self.assertEqual(spec["label"]["colour"], LABEL_ON_LIGHT)


class Replies(LLMBackend):
    def __init__(self, reply):
        super().__init__("fake")
        self.reply, self.calls = reply, []

    def generate_spec(self, sentence, previous_errors=None, previous_output=None, reference=None):
        self.calls.append({"sentence": sentence, "reference": reference})
        return Reply(json.dumps(self.reply), 100, 50, 0.1)


WHITE_BOX = {"is_box": True, "shape": "box", "unsupported": [],
             "spec": {"description": "A white box.", "shape": "box",
                      "box": {"width_cm": 6, "height_cm": 12, "depth_cm": 4, "colour": "#FFFFFF",
                              "roughness": 0.5, "bevel_cm": 0.15}, "camera": "three_quarter"}}


class WriteSpec(unittest.TestCase):
    def test_the_model_and_the_tables_never_see_the_quoted_text(self):
        backend = Replies(WHITE_BOX)
        result = write_spec('a white serum box with "LUXURY" in navy', backend)
        self.assertEqual(backend.calls[0]["sentence"], "a white serum box")
        self.assertNotIn("navy", backend.calls[0]["reference"] or "")
        self.assertEqual(result.model_sentence, "a white serum box")
        self.assertEqual(result.style_changes, [])  # "LUXURY" is text, not a style word
        self.assertEqual(result.spec["box"]["colour"], "#FFFFFF")
        self.assertEqual(result.spec["label"]["text"], "LUXURY")
        self.assertEqual(result.label_change["colour_from"], "named")

    def test_code_lists_what_it_doesnt_draw(self):
        reply = dict(WHITE_BOX, unsupported=["ribbon"])
        result = write_spec('a white box with "EMBER" and "NO. 5", with a ribbon', Replies(reply))
        self.assertEqual(result.unsupported[0], "ribbon")  # the model's own items first
        self.assertIn('"NO. 5"', result.unsupported[1])
        self.assertEqual(result.model_unsupported, ["ribbon"])  # the code's items aren't the model's

    def test_without_grounding_the_model_gets_the_whole_sentence_and_no_label_is_drawn(self):
        backend = Replies(WHITE_BOX)
        result = write_spec('a white box with "NOIR"', backend, grounding=False)
        self.assertEqual(backend.calls[0]["sentence"], 'a white box with "NOIR"')
        self.assertIsNone(result.spec["label"])
        self.assertIsNone(result.label_change)


if __name__ == "__main__":
    unittest.main()
