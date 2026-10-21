"""
Text labels (v2 step 4): read from the sentence's quoted text by code, never
by the model.

    found = read_label('a glossy black perfume bottle with a gold cap and "NOIR" in gold')
    found.text            "NOIR"
    found.metal           "gold"   a metal named right after the text: drawn as that metal
    found.colour          None     a colour named right after the text, as a hex
    found.unsupported     []       what code lists as unsupported: a second quoted
                                   text, a text too long to draw, a colour name code
                                   doesn't know
    found.model_sentence  "a glossy black perfume bottle with a gold cap"

The rules:
- The label is the first text in double quotes, straight ("NOIR") or curly
  (“NOIR”). Apostrophes and single quotes never count ("men's", "dad's").
  Spaces at its ends are dropped and a line break becomes a space (one
  line); otherwise it is kept exactly as typed, case and accents too. Empty
  quotes are no label.
- One label per product: every quoted text after the first is listed as
  unsupported. So is a text over spec.MAX_LABEL_CHARS characters, which is
  not drawn at all: cutting it would change what the user typed.
- Its colour, decided by code: a metal or a colour named right after it
  ("in gold", "in white", "in navy blue", "in #FFFFFF"). A metal
  (spec.METALS) is drawn as that metal; colour names come from
  data/label_colours.json and data/colours.json. A name code doesn't know
  is listed as unsupported. Otherwise (and then too) the label is black on
  a light surface and white on a dark one (spec.default_label_colour).
- The model and the tables never see a quoted text or its colour:
  model_sentence leaves them out, with the word that joined them on
  ("with", "and"). So a quoted word means nothing else: "LUXURY" is no
  style, "BOX" no box, "GOLD" no colour. A sentence without quotes comes
  back unchanged, character for character, so its spec is the same as
  before labels existed.

Standard library only.
"""

import json
import os
import re

from grounding import DATA_DIR, load_tables
from spec import CAP_FIELDS, MAX_LABEL_CHARS, METAL_FIELDS, METALS, default_label_colour

LABEL_COLOURS_FILE = "label_colours.json"

# A quoted text: straight or curly double quotes, either way round.
QUOTED = re.compile(r'["“]([^"“”]*)["”]')
# The words just before a quoted text that join it to the sentence: "with",
# "and a", "with the word". Left out of model_sentence with it.
_LEAD_IN = re.compile(r"\s*(?:,\s*)?(?:\b(?P<join>with|and|plus|saying|reading|that\s+(?:says|reads))\b"
                      r"(?:\s+(?:a|an|the))?(?:\s+(?:words?|text|name|brand\s+name|label|logo|lettering))?\s*)?$",
                      re.IGNORECASE)
# "and" right after a label that "with" led in: 'a jar with "CALM" and a gold lid'
# becomes "a jar with a gold lid", not "a jar and a gold lid".
_AND_AFTER = re.compile(r"\s*,?\s+and\b(?!\s*[\"“])", re.IGNORECASE)
# The start of a colour phrase right after a quoted text: "in", "printed in".
_COLOUR_LEAD = re.compile(r"\s*,?\s*(?:(?:printed|written|lettered)\s+)?in\s+", re.IGNORECASE)
# A word after the colour, or after the text, that names the text itself: "in gold letters".
_TEXT_WORD = re.compile(r"\s+(?:text|lettering|letters|label|logo|font|ink)\b", re.IGNORECASE)
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])")
_WORD = re.compile(r"[A-Za-z][A-Za-z-]*")
# After "in", these start a place, not a colour: "in the centre".
_NOT_A_COLOUR = {"a", "an", "the", "its", "it", "their", "this", "that"}


def load_label_colours():
    with open(os.path.join(DATA_DIR, LABEL_COLOURS_FILE), encoding="utf-8") as f:
        return json.load(f)["colours"]


def colour_names(tables=None, label_colours=None):
    """Every colour a label may be named in: [(phrase, metal, hex)], longest phrase first.

    A metal (metal set, hex None) wins over a colour of the same name, so "in
    gold" is gold metal, and so are the colour table's aliases of a metal
    ("golden", "metallic gold").
    """
    colours = (tables if tables is not None else load_tables())["colours"]
    label_colours = label_colours if label_colours is not None else load_label_colours()
    names = {metal: (metal, None) for metal in METALS}
    for rows in (label_colours, colours):
        for name, row in rows.items():
            for phrase in [name] + row.get("aliases", []):
                names.setdefault(phrase.lower(), (name, None) if name in METALS else (None, row["hex"].upper()))
    return sorted(((phrase, metal, hex_colour) for phrase, (metal, hex_colour) in names.items()),
                  key=lambda n: len(n[0]), reverse=True)


class FoundLabel:
    """What read_label found in a sentence. text is None when there is no label to draw."""

    def __init__(self, text=None, metal=None, colour=None, colour_word=None, unsupported=None,
                 model_sentence=""):
        self.text = text                  # the label, exactly as typed, or None
        self.metal = metal                # the metal named after it, or None
        self.colour = colour              # the colour named after it, as a hex, or None
        self.colour_word = colour_word    # the words naming its colour or metal, e.g. "navy blue"
        self.unsupported = unsupported or []
        self.model_sentence = model_sentence


def read_label(sentence, names=None):
    """The label in a sentence: its first quoted text, and the colour named right after it.

    See the module docstring for the rules. Returns a FoundLabel.
    """
    names = names if names is not None else colour_names()
    found = FoundLabel()
    cuts = []
    seen_first = False
    for match in QUOTED.finditer(sentence):
        text = " ".join(match.group(1).split())
        lead = _LEAD_IN.search(sentence[:match.start()])
        colour, end = _colour_after(sentence, match.end(), names)
        and_after = _AND_AFTER.match(sentence, end)
        if (lead.group("join") or "").lower() == "with" and and_after:
            cuts.append((lead.end("join"), and_after.end()))
        else:
            cuts.append((lead.start(), end))
        if not text:
            continue
        if seen_first:
            found.unsupported.append(f'label text "{text}": one label per product, only the first quoted '
                                     f"text is drawn")
            continue
        seen_first = True
        if len(text) > MAX_LABEL_CHARS:
            found.unsupported.append(f'label text over {MAX_LABEL_CHARS} characters, not drawn: "{text}" '
                                     f"({len(text)} characters)")
            continue
        found.text = text
        if colour:
            phrase, metal, hex_colour = colour
            found.colour_word, found.metal, found.colour = phrase, metal, hex_colour
            if metal is None and hex_colour is None:
                found.unsupported.append(f'label colour "{phrase}": not a colour code knows, so the label is '
                                         f"black or white for the colour it is on")
    found.model_sentence = _without(sentence, cuts)
    return found


def _colour_after(sentence, at, names):
    """The colour phrase right after a quoted text that ends at `at`, and where the label's words end.

    Returns ((phrase, metal, hex) or None, end). For a name code doesn't
    know, metal and hex are both None. A word naming the text itself, before
    or after the colour ('"NOIR" label in gold', '"NOIR" in gold letters'),
    is part of the label's words too.
    """
    text_word = _TEXT_WORD.match(sentence, at)
    end = text_word.end() if text_word else at
    colour = None
    lead = _COLOUR_LEAD.match(sentence, end)
    if lead:
        rest = sentence[lead.end():]
        lower = rest.lower()
        for phrase, metal, hex_colour in names:
            if lower.startswith(phrase) and not re.match(r"\w", lower[len(phrase):len(phrase) + 1]):
                colour, end = (phrase, metal, hex_colour), lead.end() + len(phrase)
                break
        else:
            hex_match, word = _HEX.match(rest), _WORD.match(rest)
            if hex_match:
                colour, end = (hex_match.group(0), None, hex_match.group(0).upper()), lead.end() + hex_match.end()
            elif word and word.group(0).lower() not in _NOT_A_COLOUR:
                colour, end = (word.group(0).lower(), None, None), lead.end() + word.end()
    text_word = _TEXT_WORD.match(sentence, end)
    if text_word:
        end = text_word.end()
    return colour, end


def _without(sentence, cuts):
    """The sentence with the label's words cut out, tidied. With nothing to cut, the sentence itself."""
    if not cuts:
        return sentence
    pieces, at = [], 0
    for start, end in sorted(cuts):
        pieces.append(sentence[at:max(start, at)])
        at = max(at, end)
    pieces.append(sentence[at:])
    text = re.sub(r"\s+", " ", "".join(pieces))
    text = re.sub(r"\s+([,;.:!?])", r"\1", text).strip()
    text = re.sub(r"^[,;\s]+|[,;\s]+$", "", text)
    return re.sub(r"\s+\b(?:with|and|plus)$", "", text, flags=re.IGNORECASE)


def surface_colour(spec):
    """The colour a label is printed on: the product's, or seen from above (top_down) a round
    shape's cap or lid, in its metal's colour if it is metal."""
    shape = spec["shape"]
    fields = spec[shape]
    if spec["camera"] == "top_down" and shape in CAP_FIELDS:
        metal = fields.get(METAL_FIELDS[shape])
        return METALS[metal] if metal else fields[CAP_FIELDS[shape]]
    return fields["colour"]


def apply_label(found, spec):
    """Set spec["label"] from read_label's result, in place. The field is always set, so
    the model never decides it.

    Run last, after every other rule: the default colour depends on the
    product's final colour. Returns (change, unsupported): change is
    {"text", "colour", "metal", "colour_from"} ("named", "metal" or
    "default") or None when no label is drawn; unsupported is what code
    lists (found.unsupported).
    """
    unsupported = list(found.unsupported)
    spec["label"] = None
    if found.text is None:
        return None, unsupported
    if found.metal:
        colour, how = METALS[found.metal], "metal"
    elif found.colour:
        colour, how = found.colour, "named"
    else:
        colour, how = default_label_colour(surface_colour(spec)), "default"
    spec["label"] = {"text": found.text, "colour": colour, "metal": found.metal}
    return dict(spec["label"], colour_from=how), unsupported
