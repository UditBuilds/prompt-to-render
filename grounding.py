"""
Grounding: look up the sentence's words in small reference tables and give
the model only the rows that match. Lightweight retrieval: no embeddings,
just whole-word matching.

    found = lookup("a luxury emerald green perfume box")
    found.rows   [{"table": "colours", "name": "emerald", "matched": "emerald green", ...}, ...]
    found.text   the block added after the sentence in the user message ("" if nothing matched)

The tables live in data/:
    colours.json        specific colour name -> hex
    product_sizes.json  product -> typical box size in cm, and for some its
                        round shape (cylinder, bottle or jar) and size
    style_words.json    style word -> how it shifts colour and finish
    finishes.json       finish word -> roughness range (code only, never shown to the model)

Four values are set by code, not the model, after the model has answered:
- Style words: the model picks the plain colour and the finish, then
  apply_style() shifts the box colour by the table's numbers. qwen3:8b
  couldn't do that hex arithmetic reliably itself (tested on the dev
  sentences in evals/dev_cases.json).
- Glossy: apply_finish() clamps the roughness into 0.03-0.05. The model's
  own "glossy" (0.1) rendered satin.
- The backdrop: neutral_backdrop() makes it a neutral light grey unless the
  sentence gives the backdrop a colour. The model's tinted backdrops could
  clash with the box.
- The cap or lid of a bottle or jar: default_cap() makes it black on a light
  body and silver-grey on a dark one, unless the sentence gives it a colour.
The last three add nothing to the request.

A sentence that names a box (box, carton, case, package) gets the box size
of a product, in exactly the words of v1.3. Any other sentence gets the
product's round shape and size where the table has one.

Matching is case-insensitive and by whole words, longest phrase first, across
all tables at once, and each word of the sentence is used once: "rose gold"
is rose gold (not gold), and "face cream" is a product (not the colour
cream). A style word inside a backdrop phrase ("on a playful pink backdrop")
describes the backdrop, not the box, so it is left out. A word that matches
nothing is simply left to the model.

Standard library only.
"""

import colorsys
import json
import os
import re

from spec import CAP_FIELDS, default_cap_colour

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")

# table name -> (file, key inside it, most rows to inject)
TABLES = {
    "colours": ("colours.json", "colours", 4),
    "products": ("product_sizes.json", "products", 2),
    "styles": ("style_words.json", "styles", 2),
}


def load_tables():
    tables = {}
    for table, (filename, key, _) in TABLES.items():
        with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
            tables[table] = json.load(f)[key]
    return tables


# A sentence with one of these words is about a box, whatever the product.
BOX_WORDS = {"box", "boxes", "carton", "cartons", "case", "cases", "package", "packages", "packaging"}
# The round shapes a product row may give a size for.
ROUND_SHAPES = ("cylinder", "bottle", "jar")


def names_a_box(sentence):
    return any(word in BOX_WORDS for word in re.findall(r"[a-z]+", sentence.lower()))


class Grounding:
    def __init__(self, rows, boxed=True):
        self.rows = rows  # in sentence order, at most TABLES[...][2] per table
        self.boxed = boxed  # the sentence names a box: products get their box size

    def __bool__(self):
        return bool(self.rows)

    def summary(self):
        """One line for the terminal, e.g. 'colour emerald #50C878, product perfume'."""
        parts = []
        for row in self.rows:
            if row["table"] == "colours":
                parts.append(f"colour {row['name']} {row['hex']}")
            elif row["table"] == "products":
                parts.append(f"product {row['name']}")
            else:
                parts.append(f"style {row['name']}")
        return ", ".join(parts)

    @property
    def text(self):
        if not self.rows:
            return ""
        lines = ["Reference data for words in this sentence (from Prompt-to-Render's tables):"]
        colours = [r for r in self.rows if r["table"] == "colours"]
        products = [r for r in self.rows if r["table"] == "products"]
        styles = [r for r in self.rows if r["table"] == "styles"]
        # A sentence that names a box reads exactly as in v1.3.
        product = "box" if self.boxed else "product"
        if colours:
            uses = "the box" if self.boxed else "the product, its cap or lid"
            lines.append("Colour names: what each name means. Use it for whatever the sentence uses that "
                         f"name for: {uses}, the backdrop, or a detail the renderer can't draw.")
            lines += [f'- "{r["matched"]}" = {r["hex"]}' for r in colours]
        round_rows = [r for r in products if not self.boxed and _round_shape(r)]
        box_rows = [r for r in products if r not in round_rows]
        if box_rows:
            lines.append("Product sizes: the usual box for that product, width x height x depth in cm.")
            for r in box_rows:
                (w, h, d), note = r["typical"], f" ({r['note']})" if r.get("note") else ""
                lines.append(f"- {r['name']}: typically {w:g} x {h:g} x {d:g}; width {_span(r['width'])}, "
                             f"height {_span(r['height'])}, depth {_span(r['depth'])}{note}")
        if round_rows:
            lines.append("Product sizes: the usual shape and size of that product, diameter x height in cm, "
                         "with any cap or lid on.")
            for r in round_rows:
                shape = _round_shape(r)
                size = r[shape]
                (d, h) = size["typical"]
                lines.append(f"- {r['name']}: a {shape}, typically {d:g} x {h:g}; diameter {_span(size['diameter'])}, "
                             f"height {_span(size['height'])}")
        if styles:
            lines.append(f"Style words: choose the plain {product} colour as usual (don't shift it yourself); the "
                         "colour shift is applied to it automatically afterwards. Do apply the finish.")
            lines += [f'- "{r["matched"]}": colour becomes {r["colour"]} ({_describe_shift(r)}, applied for you). '
                      f'Finish: {r["finish"]}.' for r in styles]
        lines.append("Use these values. Anything not listed here is up to you.")
        return "\n".join(lines)


def _span(pair):
    return f"{pair[0]:g}-{pair[1]:g}"


def _product(spec):
    """The fields of the spec's own shape. A spec without a shape is a box, the default."""
    return spec[spec.get("shape", "box")]


def _round_shape(row):
    """The round shape a product row gives a size for, or None."""
    return next((shape for shape in ROUND_SHAPES if shape in row), None)


def _describes_backdrop(text, start):
    """True if the word at `start` is part of a backdrop phrase.

    Looks at the rest of the clause: "playful pink backdrop" is about the
    backdrop, "luxury red box on a pale backdrop" is about the box.
    """
    clause = re.split(r"[,;]", text[start:], maxsplit=1)[0]
    backdrop = re.search(r"\b(?:backdrop|background)\b", clause)
    return bool(backdrop) and not re.search(r"\b(?:box|carton|case|package)\b", clause[:backdrop.start()])


def _describe_shift(row):
    parts = []
    for key, less, more in (("lightness", "darker", "lighter"), ("saturation", "less saturated", "more saturated")):
        value = row.get(key, 0)
        if value:
            parts.append(f"{abs(value):.0%} {less if value < 0 else more}")
    return ", ".join(parts) or "no colour change"


def _shift(value, amount):
    """Negative: scale towards 0 by that share. Positive: move that share of the way to 1."""
    return value * (1 + amount) if amount < 0 else value + (1 - value) * amount


def apply_style(hex_colour, row):
    """Shift a "#RRGGBB" colour by a style row's lightness and saturation (in HLS)."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    lightness = _shift(lightness, row.get("lightness", 0))
    saturation = _shift(saturation, row.get("saturation", 0))
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#" + "".join(f"{round(c * 255):02X}" for c in (r, g, b))


def style_box_colour(sentence, spec, grounding):
    """Apply every matched style word to the product's colour (any shape), in sentence order.

    Skipped when the sentence gives an exact hex: the user's colour wins.
    Returns a list of {"style", "from", "to"} (empty if nothing changed).
    """
    styles = [r for r in grounding.rows if r["table"] == "styles"]
    if not styles or re.search(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b", sentence):
        return []
    changes = []
    product = _product(spec)
    for row in styles:
        before = product["colour"]
        after = apply_style(before, row)
        product["colour"] = after
        changes.append({"style": row["name"], "from": before.upper(), "to": after})
    return changes


def _match(text, tables):
    """Whole-word matches of every name and alias, longest phrase first, each word used once.

    Returns {(table, name): (position, phrase)}, for where each row first matched.
    """
    phrases = []
    for table, entries in tables.items():
        for name, row in entries.items():
            for phrase in [name] + row.get("aliases", []):
                phrases.append((phrase.lower(), table, name))
    phrases.sort(key=lambda p: len(p[0]), reverse=True)

    used = [False] * len(text)
    found = {}
    for phrase, table, name in phrases:
        for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text):
            start, end = match.span()
            if any(used[start:end]):
                continue
            used[start:end] = [True] * (end - start)
            found.setdefault((table, name), (start, phrase))
    return found


def lookup(sentence, tables=None):
    tables = tables if tables is not None else load_tables()
    text = sentence.lower()
    found = _match(text, tables)

    rows = []
    for (table, name), (position, phrase) in sorted(found.items(), key=lambda item: item[1][0]):
        if table == "styles" and _describes_backdrop(text, position):
            continue
        limit = TABLES[table][2]
        if sum(r["table"] == table for r in rows) < limit:
            row = {k: v for k, v in tables[table][name].items() if k != "aliases"}
            rows.append(dict(row, table=table, name=name, matched=phrase))
    return Grounding(rows, names_a_box(sentence))


# ---------------------------------------------------------------------------
# Rules applied by code after the model, never shown to it: the finish of a
# glossy product, the backdrop when the sentence gives it no colour, and the
# cap or lid when the sentence gives it no colour.
# ---------------------------------------------------------------------------

FINISHES_FILE = "finishes.json"

# The backdrop when the sentence gives it no colour: a neutral light grey. It
# is the backdrop qwen3:8b picked most often in v1.1 (73 of 90 eval runs),
# including the v1.1 lipstick render.
NEUTRAL_BACKDROP = "#F5F5F5"

_BACKDROP_WORDS = {"backdrop", "backdrops", "background", "backgrounds"}
# Words that describe a backdrop without giving it a colour.
_PLAIN_BACKDROP = {"plain", "simple", "clean", "neutral", "seamless", "studio", "soft", "smooth", "blank",
                   "solid", "empty", "infinity", "photo"}
# Words that end a backdrop phrase: "a white box on a pink background" -> "pink".
_PHRASE_BREAKS = {"a", "an", "the", "its", "their", "on", "onto", "against", "over", "in", "of", "with",
                  "and", "or", "for", "box", "carton", "case", "package", "set"}
# Words after "backdrop" that lead on to its colour: "a backdrop of pale pink", "background colour lilac".
_LEADS_ON = {"of", "in", "colour", "color", "coloured", "colored"}

_CAP_WORDS = {"cap", "caps", "lid", "lids"}
# Words that describe a cap or lid without giving it a colour.
_PLAIN_CAP = {"matching", "screw", "flip", "twist", "round", "flat", "domed", "simple", "plain", "big", "large",
              "small", "tall", "short", "wide", "thin", "thick", "dropper", "pump", "spray",
              "glossy", "gloss", "shiny", "matte", "matt", "satin", "metallic", "polished"}
# A cap phrase also ends at the container: "a gold bottle cap" names the bottle's colour, not the cap's.
_CAP_BREAKS = _PHRASE_BREAKS | {"bottle", "bottles", "jar", "jars", "tube", "tubes", "cylinder"}


def load_finishes():
    with open(os.path.join(DATA_DIR, FINISHES_FILE), encoding="utf-8") as f:
        return json.load(f)["finishes"]


def finish_words(sentence, tables=None, finishes=None):
    """The finish rows the sentence names for the product, in sentence order.

    Matched together with the other tables, so a product name ("lip gloss")
    keeps its words, and a finish inside a backdrop phrase is left out.
    """
    tables = tables if tables is not None else load_tables()
    finishes = finishes if finishes is not None else load_finishes()
    text = sentence.lower()
    found = _match(text, dict(tables, finishes=finishes))
    rows = []
    for (table, name), (position, phrase) in sorted(found.items(), key=lambda item: item[1][0]):
        if table == "finishes" and not _describes_backdrop(text, position):
            rows.append(dict(finishes[name], name=name, matched=phrase))
    return rows


def apply_finish(sentence, spec, tables=None, finishes=None):
    """Clamp the product's roughness into the range of the sentence's finish, if that finish has one.

    Only when the sentence names exactly one finish: with two ("a matte box
    with a glossy logo") the model's choice stands. Returns
    {"finish", "from", "to"}, or None if the roughness didn't change.
    """
    rows = finish_words(sentence, tables, finishes)
    if len({r["name"] for r in rows}) != 1 or "roughness" not in rows[0]:
        return None
    low, high = rows[0]["roughness"]
    product = _product(spec)
    before = product["roughness"]
    after = min(max(before, low), high)
    if after == before:
        return None
    product["roughness"] = after
    return {"finish": rows[0]["name"], "from": before, "to": after}


def backdrop_colour_words(sentence):
    """The words that give the backdrop a colour, e.g. ["pale", "blush"]; [] if there are none.

    Looks just before each "backdrop"/"background" ("on a pale blush
    backdrop") and after it ("a backdrop of pale pink"). Any word that isn't
    a plain description ("clean", "studio") counts, so a colour name the
    code has never heard of still keeps the backdrop the model chose.
    """
    return _colour_words(sentence, _BACKDROP_WORDS, _PHRASE_BREAKS, _PLAIN_BACKDROP)


def cap_colour_words(sentence):
    """The words that give a cap or lid a colour, e.g. ["gold"] in "with a gold cap"; [] if none do.

    Found the same way as the backdrop's colour words.
    """
    return _colour_words(sentence, _CAP_WORDS, _CAP_BREAKS, _PLAIN_CAP)


def _colour_words(sentence, targets, breaks, plain):
    """The words just before each target word, and after it ("a lid in gold"), that aren't plain."""
    words = []
    for clause in re.split(r"[,;.:]", sentence.lower()):
        tokens = re.findall(r"#?[\w'-]+", clause)
        for i, token in enumerate(tokens):
            if token not in targets:
                continue
            before = []
            for word in reversed(tokens[:i]):
                if word in breaks:
                    break
                before.insert(0, word)
            words += before
            if i + 1 < len(tokens) and tokens[i + 1] in _LEADS_ON:
                for word in tokens[i + 2:]:
                    if word in _LEADS_ON or word in ("a", "an", "the"):
                        continue
                    if word in breaks:
                        break
                    words.append(word)
    return [w for w in words if w not in plain]


def neutral_backdrop(sentence, spec, given=True):
    """Unless the sentence gives the backdrop a colour, make it NEUTRAL_BACKDROP.

    `given` is False when the model left the backdrop out. Returns
    {"from", "to"} ("from" is None if it was left out), or None if the
    backdrop is the sentence's (or already the neutral one).
    """
    if backdrop_colour_words(sentence):
        return None
    before = spec["background_colour"].upper() if given else None
    spec["background_colour"] = NEUTRAL_BACKDROP
    return {"from": before, "to": NEUTRAL_BACKDROP} if before != NEUTRAL_BACKDROP else None


def default_cap(sentence, spec, given=True):
    """Unless the sentence gives the cap or lid a colour, set the default one for the body colour.

    Only for a bottle or jar. The default (spec.default_cap_colour) is black
    on a light body and silver-grey on a dark one. Run after the style
    shift, which may change the body colour. `given` is False when the model
    left the cap colour out. Returns {"field", "from", "to"} ("from" is None
    if it was left out), or None if nothing changed.
    """
    field = CAP_FIELDS.get(spec["shape"])
    if field is None or cap_colour_words(sentence):
        return None
    product = spec[spec["shape"]]
    before = product[field].upper() if given else None
    after = default_cap_colour(product["colour"])
    product[field] = after
    return {"field": field, "from": before, "to": after} if before != after else None
