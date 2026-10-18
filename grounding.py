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

Style words are the one place where code, not the model, changes a value:
the model picks the plain colour and the finish, then apply_style() shifts
the box colour by the table's numbers. qwen3:8b couldn't do that hex
arithmetic reliably itself (tested on the dev sentences in
evals/dev_cases.json).

Matching is case-insensitive and by whole words, longest phrase first, across
all tables at once, and each word of the sentence is used once: "rose gold"
is rose gold (not gold), and "face cream" is a product (not the colour
cream). A word that matches nothing is simply left to the model.

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


def lookup(sentence, tables=None):
    tables = tables if tables is not None else load_tables()
    text = sentence.lower()

    # Every phrase that can match, longest first.
    phrases = []
    for table, entries in tables.items():
        for name, row in entries.items():
            for phrase in [name] + row.get("aliases", []):
                phrases.append((phrase.lower(), table, name))
    phrases.sort(key=lambda p: len(p[0]), reverse=True)

    used = [False] * len(text)
    found = {}  # (table, name) -> (position, phrase)
    for phrase, table, name in phrases:
        for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text):
            start, end = match.span()
            if any(used[start:end]):
                continue
            used[start:end] = [True] * (end - start)
            found.setdefault((table, name), (start, phrase))

    rows = []
    for (table, name), (position, phrase) in sorted(found.items(), key=lambda item: item[1][0]):
        limit = TABLES[table][2]
        if sum(r["table"] == table for r in rows) < limit:
            row = {k: v for k, v in tables[table][name].items() if k != "aliases"}
            rows.append(dict(row, table=table, name=name, matched=phrase))
    return Grounding(rows)
