"""
The round shapes (cylinder, bottle, jar) as profiles, for render_scene.py.

A profile is the outline of one side of an upright part, as (r, z) points:
r is the distance from the vertical axis, z the height, both in metres. It
starts on the axis at the bottom, goes round the outside and ends on the axis
at the top. render_scene.py spins each profile round the axis into a closed,
smooth-shaded mesh.

Every corner is rounded with a small arc, so smooth shading never smears
across a sharp edge. The spec gives only the diameter and the height; the
proportions of a cylinder's cap, a bottle's shoulder, neck and cap, and a
jar's lid, are fixed shares of those, chosen to look like common cosmetics
packaging.

Plain Python (no Blender), so it can be tested. The box is built by
render_scene.py itself, as before.
"""

import math

# Points on each rounded corner, ends included.
ARC_STEPS = 8

# Edge rounding of every shape: this share of its radius, at most MAX_EDGE.
EDGE_SHARE = 0.12
MAX_EDGE = 0.0025  # 0.25 cm

# Bottle, as shares of its total height (H) or body radius (R).
BOTTLE_CAP_HEIGHT = 0.24       # of H
BOTTLE_CAP_RADIUS = 0.60       # of R
BOTTLE_NECK_HEIGHT = 0.05      # of H: the neck seen between the shoulder and the cap
BOTTLE_NECK_RADIUS = 0.42      # of R
BOTTLE_SHOULDER_HEIGHT = 0.14  # of H, and at most 0.8 R so a squat bottle keeps a wall
# Above 1 the shoulder stays rounded for longer before it turns in to the neck.
SHOULDER_CURVE = 1.5

# Cylinder (a lipstick, a mascara, a balm): a base and a cap. The cap is this
# share of the height, and a little wider than the base, so the seam shows.
CYLINDER_CAP_HEIGHT = 0.42
CYLINDER_CAP_OVERHANG = 1.04

# Jar: the lid is a quarter of the height (at most 0.4 of the diameter), and a
# little wider than the body, so the seam between them shows. (v2 step 1 had
# 0.36 and step 2 0.30; both read as nearly half the jar from the three-quarter
# camera, which also sees the lid's top. Since step 3 that camera is also a
# little lower for a jar: render_scene.CAMERA_PRESETS.)
JAR_LID_HEIGHT = 0.25
JAR_LID_OVERHANG = 1.02


class Part:
    """One mesh of a round shape: its name, its profile, the spec field holding its
    colour, and for a cap or lid the spec field naming its metal."""

    def __init__(self, name, profile, colour, metal=None):
        self.name = name
        self.profile = _dedupe(profile)
        self.colour = colour
        self.metal = metal


class Hero:
    """Where the colour check and the light meter look: the centre of a face of the product.

    centre is (x, y, z) in metres, sides the face's (width, height) for its
    patch, colour the spec field of the part it is on.
    """

    def __init__(self, centre, sides, colour):
        self.centre = centre
        self.sides = sides
        self.colour = colour


def parts(shape, fields):
    """The parts of a round shape, body first, from the spec fields of that shape."""
    return _BUILDERS[shape](fields)[0]


def hero(shape, fields, face):
    """The Hero on the "front" of the body (facing -y, half way up its wall) or on the "top" (topmost part)."""
    return _BUILDERS[shape](fields)[1][face]


# ---------------------------------------------------------------------------
# The shapes
# ---------------------------------------------------------------------------

def _cylinder(fields):
    radius, height = fields["diameter_cm"] / 200, fields["height_cm"] / 100
    cap_height, cap_radius = CYLINDER_CAP_HEIGHT * height, CYLINDER_CAP_OVERHANG * radius
    cap_bottom = height - cap_height
    edge = _edge(radius, cap_bottom)
    # Like a jar's body, the base goes on up a little inside the cap, out of
    # sight, so the two never share a face.
    body = rounded_cylinder(radius, 0.0, cap_bottom + cap_height / 4, edge, 0.03 * radius)
    cap_edge = _edge(cap_radius, cap_height)
    cap = rounded_cylinder(cap_radius, cap_bottom, height, min(0.04 * cap_radius, cap_height / 6), cap_edge)
    heroes = {"front": Hero((0.0, -radius, cap_bottom / 2), (2 * radius, cap_bottom - edge), "colour"),
              "top": Hero((0.0, 0.0, height), (2 * (cap_radius - cap_edge),) * 2, "cap_colour")}
    return [Part("Body", body, "colour"), Part("Cap", cap, "cap_colour", "cap_metal")], heroes


def _bottle(fields):
    radius, height = fields["diameter_cm"] / 200, fields["height_cm"] / 100
    cap_height, cap_radius = BOTTLE_CAP_HEIGHT * height, BOTTLE_CAP_RADIUS * radius
    neck_height, neck_radius = BOTTLE_NECK_HEIGHT * height, BOTTLE_NECK_RADIUS * radius
    shoulder = min(BOTTLE_SHOULDER_HEIGHT * height, 0.8 * radius)
    wall = height - cap_height - neck_height - shoulder  # straight side of the body
    edge = _edge(radius, wall)
    cap_bottom = height - cap_height

    body = [(0.0, 0.0)]
    body += _arc(radius - edge, edge, edge, -90, 0)
    # Shoulder: one S-curve from the top of the wall in to the neck, upright
    # at both ends, so it meets each without a ledge. It is rounded (convex)
    # most of the way and turns concave just below the neck.
    steps = 3 * ARC_STEPS
    body += [(neck_radius + (radius - neck_radius) * (1 + math.cos(math.pi * t ** SHOULDER_CURVE)) / 2,
              wall + shoulder * t)
             for t in (i / steps for i in range(steps + 1))]
    # The neck goes on up inside the cap, out of sight.
    neck_top = cap_bottom + cap_height / 2
    body += [(neck_radius, neck_top), (0.0, neck_top)]

    cap_edge = min(0.18 * cap_radius, cap_height / 3)
    cap = rounded_cylinder(cap_radius, cap_bottom, height, min(0.05 * cap_radius, cap_height / 6), cap_edge)
    heroes = {"front": Hero((0.0, -radius, wall / 2), (2 * radius, wall - edge), "colour"),
              "top": Hero((0.0, 0.0, height), (2 * (cap_radius - cap_edge),) * 2, "cap_colour")}
    return [Part("Body", body, "colour"), Part("Cap", cap, "cap_colour", "cap_metal")], heroes


def _jar(fields):
    radius, height = fields["diameter_cm"] / 200, fields["height_cm"] / 100
    lid_height = min(JAR_LID_HEIGHT * height, 0.4 * 2 * radius)
    lid_radius = JAR_LID_OVERHANG * radius
    lid_bottom = height - lid_height
    edge = _edge(radius, lid_bottom)
    # The body goes on up a little inside the lid, out of sight, so the two
    # never share a face.
    body = rounded_cylinder(radius, 0.0, lid_bottom + lid_height / 4, edge, 0.03 * radius)
    lid_edge = min(EDGE_SHARE * lid_radius, MAX_EDGE * 1.5, lid_height / 3)
    lid = rounded_cylinder(lid_radius, lid_bottom, height, min(0.04 * lid_radius, lid_height / 6), lid_edge)
    heroes = {"front": Hero((0.0, -radius, lid_bottom / 2), (2 * radius, lid_bottom - edge), "colour"),
              "top": Hero((0.0, 0.0, height), (2 * (lid_radius - lid_edge),) * 2, "lid_colour")}
    return [Part("Body", body, "colour"), Part("Lid", lid, "lid_colour", "lid_metal")], heroes


_BUILDERS = {"cylinder": _cylinder, "bottle": _bottle, "jar": _jar}


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def rounded_cylinder(radius, z_bottom, z_top, bottom_edge, top_edge):
    """Profile of an upright cylinder from z_bottom to z_top, its two rims rounded."""
    points = [(0.0, z_bottom)]
    points += _arc(radius - bottom_edge, z_bottom + bottom_edge, bottom_edge, -90, 0)
    points += _arc(radius - top_edge, z_top - top_edge, top_edge, 0, 90)
    points.append((0.0, z_top))
    return points


def _edge(radius, height):
    return min(EDGE_SHARE * radius, MAX_EDGE, height / 4)


def _arc(centre_r, centre_z, radius, start_deg, end_deg, steps=ARC_STEPS):
    """Points on a circular arc from start_deg to end_deg (either way round), both ends included."""
    return [(centre_r + radius * math.cos(math.radians(a)), centre_z + radius * math.sin(math.radians(a)))
            for a in (start_deg + (end_deg - start_deg) * i / steps for i in range(steps + 1))]


def _dedupe(points):
    """Drop a point that repeats the one before it: it would make a face of zero size."""
    kept = [points[0]]
    for r, z in points[1:]:
        if math.hypot(r - kept[-1][0], z - kept[-1][1]) > 1e-9:
            kept.append((r, z))
    return kept
