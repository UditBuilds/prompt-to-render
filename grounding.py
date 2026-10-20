"""
Grounding: look up the sentence's words in small reference tables and give
the model only the rows that match. Lightweight retrieval: no embeddings,
just whole-word matching.

    found = lookup("a luxury emerald green perfume box")
    found.rows   [{"table": "colours", "name": "emerald", "matched": "emerald green", ...}, ...]
    found.text   the block added after the sentence in the user message ("" if nothing matched)

The tables live in data/:
    colours.json        specific colour name -> hex
    product_sizes.json  product -> typical box size in cm
    style_words.json    style word -> how it shifts colour and finish
    finishes.json       finish word -> roughness range (code only, never shown to the model)

Three values are set by code, not the model, after the model has answered:
- Style words: the model picks the plain colour and the finish, then
  apply_style() shifts the box colour by the table's numbers. qwen3:8b
  couldn't do that hex arithmetic reliably itself (tested on the dev
  sentences in evals/dev_cases.json).
- Glossy: apply_finish() clamps the roughness into 0.03-0.05. The model's
  own "glossy" (0.1) rendered satin.
- The backdrop: neutral_backdrop() makes it a neutral light grey unless the
  sentence gives the backdrop a colour. The model's tinted backdrops could
  clash with the box.
The last two add nothing to the request, so the model sees exactly what it
saw before they existed.

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


class Grounding:
    def __init__(self, rows):
        self.rows = rows  # in sentence order, at most TABLES[...][2] per table

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
        if colours:
            lines.append("Colour names: what each name means. Use it for whatever the sentence uses that "
                         "name for: the box, the backdrop, or a detail the renderer can't draw.")
            lines += [f'- "{r["matched"]}" = {r["hex"]}' for r in colours]
        if products:
            lines.append("Product sizes: the usual box for that product, width x height x depth in cm.")
            for r in products:
                (w, h, d), note = r["typical"], f" ({r['note']})" if r.get("note") else ""
                lines.append(f"- {r['name']}: typically {w:g} x {h:g} x {d:g}; width {_span(r['width'])}, "
                             f"height {_span(r['height'])}, depth {_span(r['depth'])}{note}")
        if styles:
            lines.append("Style words: choose the plain box colour as usual (don't shift it yourself); the colour "
                         "shift is applied to it automatically afterwards. Do apply the finish.")
            lines += [f'- "{r["matched"]}": colour becomes {r["colour"]} ({_describe_shift(r)}, applied for you). '
                      f'Finish: {r["finish"]}.' for r in styles]
        lines.append("Use these values. Anything not listed here is up to you.")
        return "\n".join(lines)


def _span(pair):
    return f"{pair[0]:g}-{pair[1]:g}"


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
    """Apply every matched style word to the spec's box colour, in sentence order.

    Skipped when the sentence gives an exact hex: the user's colour wins.
    Returns a list of {"style", "from", "to"} (empty if nothing changed).
    """
    styles = [r for r in grounding.rows if r["table"] == "styles"]
    if not styles or re.search(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b", sentence):
        return []
    changes = []
    for row in styles:
        before = spec["box"]["colour"]
        after = apply_style(before, row)
        spec["box"]["colour"] = after
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
    return Grounding(rows)


# ---------------------------------------------------------------------------
# Rules applied by code after the model, never shown to it: the finish of a
# glossy box and the backdrop when the sentence gives it no colour.
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


def load_finishes():
    with open(os.path.join(DATA_DIR, FINISHES_FILE), encoding="utf-8") as f:
        return json.load(f)["finishes"]


def finish_words(sentence, tables=None, finishes=None):
    """The finish rows the sentence names for the box, in sentence order.

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
    """Clamp the box roughness into the range of the sentence's finish, if that finish has one.

    Only when the sentence names exactly one finish: with two ("a matte box
    with a glossy logo") the model's choice stands. Returns
    {"finish", "from", "to"}, or None if the roughness didn't change.
    """
    rows = finish_words(sentence, tables, finishes)
    if len({r["name"] for r in rows}) != 1 or "roughness" not in rows[0]:
        return None
    low, high = rows[0]["roughness"]
    before = spec["box"]["roughness"]
    after = min(max(before, low), high)
    if after == before:
        return None
    spec["box"]["roughness"] = after
    return {"finish": rows[0]["name"], "from": before, "to": after}


def backdrop_colour_words(sentence):
    """The words that give the backdrop a colour, e.g. ["pale", "blush"]; [] if there are none.

    Looks just before each "backdrop"/"background" ("on a pale blush
    backdrop") and after it ("a backdrop of pale pink"). Any word that isn't
    a plain description ("clean", "studio") counts, so a colour name the
    code has never heard of still keeps the backdrop the model chose.
    """
    words = []
    for clause in re.split(r"[,;.:]", sentence.lower()):
        tokens = re.findall(r"#?[\w'-]+", clause)
        for i, token in enumerate(tokens):
            if token not in _BACKDROP_WORDS:
                continue
            before = []
            for word in reversed(tokens[:i]):
                if word in _PHRASE_BREAKS:
                    break
                before.insert(0, word)
            words += before
            if i + 1 < len(tokens) and tokens[i + 1] in _LEADS_ON:
                for word in tokens[i + 2:]:
                    if word in _LEADS_ON or word in ("a", "an", "the"):
                        continue
                    if word in _PHRASE_BREAKS:
                        break
                    words.append(word)
    return [w for w in words if w not in _PLAIN_BACKDROP]


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
