"""
The round shapes' profiles (shapes.py), checked without Blender.

Run all tests with:  python -m unittest discover tests
"""

import ast
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import shapes  # noqa: E402
from spec import validate_spec  # noqa: E402

SIZES = {  # cm: a lipstick, a mascara, a perfume and a serum bottle, a cream jar, and extremes
    "cylinder": [(2, 8), (1.7, 13.5), (10, 3), (0.5, 200)],
    "bottle": [(5.5, 11.5), (3.2, 10), (6, 6), (0.5, 200)],
    "jar": [(6.5, 4.5), (8, 10), (12, 2), (0.5, 0.5)],
}


def fields(shape, diameter, height):
    return validate_spec({"shape": shape, shape: {"diameter_cm": diameter, "height_cm": height}})[shape]


def every_shape():
    for shape, sizes in SIZES.items():
        for diameter, height in sizes:
            yield shape, diameter, height, fields(shape, diameter, height)


class Profiles(unittest.TestCase):
    def test_parts_are_closed_and_fit_the_spec(self):
        for shape, diameter, height, f in every_shape():
            with self.subTest(shape=shape, size=(diameter, height)):
                parts = shapes.parts(shape, f)
                self.assertEqual(parts[0].name, "Body")
                self.assertEqual(parts[0].colour, "colour")
                for part in parts:
                    first, last = part.profile[0], part.profile[-1]
                    # Starts and ends on the axis, bottom to top, so the spun mesh is closed.
                    self.assertEqual((first[0], last[0]), (0.0, 0.0))
                    self.assertLess(first[1], last[1])
                    self.assertTrue(all(r >= 0 for r, _ in part.profile))
                    # No repeated points: they would make faces of zero size.
                    for (r0, z0), (r1, z1) in zip(part.profile, part.profile[1:]):
                        self.assertGreater(math.hypot(r1 - r0, z1 - z0), 1e-9)
                points = [p for part in parts for p in part.profile]
                # The body is the spec's diameter (a cylinder's cap and a jar's lid
                # overhang it a little), and the whole product the spec's height,
                # standing on the floor.
                self.assertAlmostEqual(max(r for r, _ in parts[0].profile), diameter / 200)
                overhang = max(shapes.CYLINDER_CAP_OVERHANG, shapes.JAR_LID_OVERHANG)
                self.assertLessEqual(max(r for r, _ in points), diameter / 200 * overhang + 1e-12)
                self.assertAlmostEqual(min(z for _, z in points), 0.0)
                self.assertAlmostEqual(max(z for _, z in points), height / 100)

    def test_caps_and_lids(self):
        bottle = shapes.parts("bottle", fields("bottle", 5.5, 11.5))
        self.assertEqual([(p.name, p.colour, p.metal) for p in bottle],
                         [("Body", "colour", None), ("Cap", "cap_colour", "cap_metal")])
        cap_radius = max(r for r, _ in bottle[1].profile)
        self.assertLess(cap_radius, 5.5 / 200)  # narrower than the body
        jar = shapes.parts("jar", fields("jar", 6.5, 4.5))
        self.assertEqual([(p.name, p.colour, p.metal) for p in jar],
                         [("Body", "colour", None), ("Lid", "lid_colour", "lid_metal")])
        self.assertGreater(max(r for r, _ in jar[1].profile), 6.5 / 200)  # a little wider: the seam shows
        # v2 step 2: a cylinder is a base and a cap, the cap a little wider so the seam shows.
        cylinder = shapes.parts("cylinder", fields("cylinder", 2, 8))
        self.assertEqual([(p.name, p.colour, p.metal) for p in cylinder],
                         [("Body", "colour", None), ("Cap", "cap_colour", "cap_metal")])
        self.assertGreater(max(r for r, _ in cylinder[1].profile), 2 / 200)

    def test_cap_and_lid_heights(self):
        def span(part):
            heights = [z for _, z in part.profile]
            return max(heights) - min(heights)

        # A jar's lid is a quarter of its height (v2 step 3; the evals want 20-30%, and step 2's 25-35%).
        for diameter, height in SIZES["jar"][:3]:
            with self.subTest(jar=(diameter, height)):
                lid = shapes.parts("jar", fields("jar", diameter, height))[1]
                self.assertAlmostEqual(span(lid) / (height / 100), shapes.JAR_LID_HEIGHT)
                self.assertTrue(0.25 <= shapes.JAR_LID_HEIGHT <= 0.30)
        cap = shapes.parts("cylinder", fields("cylinder", 2, 8))[1]
        self.assertAlmostEqual(span(cap) / 0.08, shapes.CYLINDER_CAP_HEIGHT)
        # The base runs on up inside the cap, out of sight, so there is no gap.
        base = shapes.parts("cylinder", fields("cylinder", 2, 8))[0]
        self.assertGreater(max(z for _, z in base.profile), min(z for _, z in cap.profile))

    def test_a_bottle_has_a_neck(self):
        body, cap = (p.profile for p in shapes.parts("bottle", fields("bottle", 5.5, 11.5)))
        cap_bottom = min(z for _, z in cap)
        # The body runs on up into the cap as the neck, much narrower than the body.
        neck = [r for r, z in body if z >= cap_bottom and r > 0]
        self.assertEqual(neck, [shapes.BOTTLE_NECK_RADIUS * 5.5 / 200])

    def test_hero_faces(self):
        for shape, diameter, height, f in every_shape():
            with self.subTest(shape=shape, size=(diameter, height)):
                front = shapes.hero(shape, f, "front")
                # On the front of the body, half way up its straight wall, below any cap or lid.
                self.assertEqual(front.colour, "colour")
                self.assertAlmostEqual(front.centre[1], -diameter / 200)
                self.assertGreater(front.centre[2], 0)
                self.assertTrue(all(side > 0 for side in front.sides))
                cap_bottom = min(z for _, z in shapes.parts(shape, f)[1].profile)
                self.assertLessEqual(front.centre[2] + front.sides[1] / 2, cap_bottom + 1e-12)
                top = shapes.hero(shape, f, "top")
                # From above: the top of the topmost part, the cap or lid.
                self.assertAlmostEqual(top.centre[2], height / 100)
                self.assertEqual(top.colour, "lid_colour" if shape == "jar" else "cap_colour")
                self.assertTrue(all(side > 0 for side in top.sides))


class Cameras(unittest.TestCase):
    """render_scene.py runs inside Blender (it imports bpy), so its camera presets are read from its source."""

    def test_only_a_jar_seen_from_three_quarter_is_lower(self):
        with open(os.path.join(ROOT, "render_scene.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", None) == "CAMERA_PRESETS" for t in n.targets))
        presets = ast.literal_eval(node.value)
        # v2 step 3: a jar from three-quarter is seen from 15 degrees up, not 22.
        self.assertEqual({name: preset.get("shape_overrides") for name, preset in presets.items()},
                         {"front": None, "three_quarter": {"jar": {"elevation": 15}}, "top_down": None})
        # Every other shape keeps step 2's cameras.
        self.assertEqual([(p["azimuth"], p["elevation"], p["lens_mm"]) for p in presets.values()],
                         [(0, 8, 85), (35, 22, 85), (0, 90, 85)])


if __name__ == "__main__":
    unittest.main()
