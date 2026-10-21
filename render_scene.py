"""
Builds a studio product shot of a product (a box, cylinder, bottle or jar)
from a JSON spec and renders it to PNG.

This script runs INSIDE Blender. You normally don't call it yourself; run.py
does, roughly like this:

    blender --background --factory-startup --python render_scene.py -- \
            --spec specs/pink_three_quarter.json --output renders/out.png

Everything is built from scratch on every run (product, backdrop, lights,
camera), so the result depends only on the spec file, never on Blender's
saved settings.

Conventions:
  * 1 Blender unit = 1 metre. The spec is in cm, so sizes are divided by 100.
  * The product stands on the floor (z = 0), centred on the origin.
  * The FRONT of the product faces -Y (towards the "front" camera).
  * The round shapes come from shapes.py as profiles, spun round the
    vertical axis here.
"""

import argparse
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shapes  # noqa: E402
from check_colour import delta_e76, describe_delta_e, measure_patch  # noqa: E402
from spec import METAL_ROUGHNESS, METALS, SpecError, has_shine, hex_to_linear_rgb, load_spec  # noqa: E402

# ---------------------------------------------------------------------------
# Presets. Distances and sizes are multiples of the product's "radius" (half
# the diagonal of a box, the farthest point from the centre of any shape), so
# a tiny lipstick box and a big gift box get the same framing and the same
# exposure.
# ---------------------------------------------------------------------------

# azimuth: degrees around the box (0 = straight in front, + = towards the right)
# elevation: degrees above the floor (90 = looking straight down)
# hero_face: the face the key light hits; used by the light meter and the
#            colour check. "front" on a round shape: the front of its body.
# light_overrides: per-camera changes to the lighting preset (see below).
# shape_overrides: per-shape changes to the camera itself. A jar seen from
# three-quarter is looked at a little lower (v2 step 3), so the top of its lid
# takes less of the picture; every other shape and camera is as before.
CAMERA_PRESETS = {
    "front":         {"azimuth": 0,  "elevation": 8,  "lens_mm": 85, "hero_face": "front"},
    "three_quarter": {"azimuth": 35, "elevation": 22, "lens_mm": 85, "hero_face": "front",
                      "shape_overrides": {"jar": {"elevation": 15}}},
    "top_down":      {
        "azimuth": 0, "elevation": 90, "lens_mm": 85, "hero_face": "top",
        # Seen from straight above, a rim light only adds a second shadow that
        # crosses the key's shadow, and the backdrop light's edge would fall
        # inside the frame. Instead: a higher, bigger (softer) key and a fill
        # from overhead that lifts the shadow.
        "light_overrides": {
            "Key":      {"elevation": 70, "size": 1.5},
            "Fill":     {"elevation": 88, "size": 2.0, "strength": 0.8},
            "Rim":      {"strength": 0},
            "Backdrop": {"strength": 0},
        },
    },
}

# The box fills this fraction of the frame along its tightest axis.
FRAME_FILL = 0.62

# Lights are placed relative to the camera, so every camera angle gets the
# same look. azimuth is an offset from the camera's azimuth.
#   distance: multiple of the box radius
#   size:     softbox size as a fraction of its distance (bigger = softer)
#   strength: brightness at the box, relative to BASE_IRRADIANCE (0 = off)
LIGHTING_PRESETS = {
    "studio_soft": [
        # Key: main light, front-left and above. Sets the shadow direction.
        {"name": "Key",  "azimuth": -55, "elevation": 40, "distance": 6, "size": 0.3, "strength": 1.0},
        # Fill: low and straight in front, softens the shadows. On glossy boxes
        # it also shows up as a softbox reflection on the front face.
        {"name": "Fill", "azimuth": 0,   "elevation": 0,  "distance": 7, "size": 0.6, "strength": 0.2},
        # Rim: behind the box, on the opposite side to the key, high up. Lights
        # the top and back edges so the box separates from the backdrop.
        {"name": "Rim",  "azimuth": 200, "elevation": 50, "distance": 5, "size": 0.5, "strength": 1.0},
        # Backdrop: a big softbox behind the box, aimed away from it at the
        # sweep. Lights the far backdrop evenly so it doesn't fall off into
        # dark corners. Being aimed away, it barely touches the box itself.
        {"name": "Backdrop", "azimuth": 180, "elevation": 50, "distance": 3, "size": 1.5,
         "strength": 1.5, "aim_behind": 8},
    ],
}

# Irradiance (W/m^2) the key light delivers at the box. Light power is scaled
# by distance^2 so this stays the same for every box size.
BASE_IRRADIANCE = 3.5

# Strip lights: tall, bright softboxes that give glossy and metal surfaces
# sharp highlights. Added only when something in the scene is glossy or metal
# (spec.has_shine), so a matte render is exactly as before. They light nothing
# diffusely, so the light meter, matte colours and shadows don't change; they
# light only the product (light linking), and the camera never sees them:
# they only show up in its reflections.
# Seen from 22 degrees above, an upright face reflects what is below its own
# height, so the strips stand close and reach down to the floor; the upper
# part of each upright face or wall shows them. A thin strip on the left
# draws a line on round shapes; a wider card on the right, where the camera
# sees a box's side face mirrored, puts a broad reflection on it.
#   azimuth, elevation, distance: as for the lights above, aimed at the product
#   width, height: the strip's size as a fraction of its distance
#   radiance: its brightness, as a multiple of a white card's under the key light
STRIP_LIGHTS = [
    {"name": "StripLeft", "azimuth": -100, "elevation": 0, "distance": 1.4, "width": 0.12, "height": 2.0,
     "radiance": 20},
    {"name": "CardRight", "azimuth": 110, "elevation": 0, "distance": 1.4, "width": 0.6, "height": 2.0,
     "radiance": 8},
]

# The environment around the set: the background colour, dimmed.
WORLD_STRENGTH = 0.3

BACKDROP_ROUGHNESS = 0.7
# Behind the box the floor curves up into a wall (multiples of the box radius).
BACKDROP_CURVE_START = 3
BACKDROP_CURVE_RADIUS = 6
BEVEL_SEGMENTS = 6
# Faces round the axis of a round shape: enough for a smooth outline.
ROUND_SEGMENTS = 128
# Framing a round shape looks at every FRAMING_STEP-th vertex: plenty for its outline.
FRAMING_STEP = 4

# How each colour_mode turns rendered light into image colours.
COLOUR_MODES = {
    # Khronos PBR Neutral is made for product shots: colours below ~80%
    # brightness come out nearly unchanged (it subtracts a little to cancel
    # surface sheen), and only brighter highlights are gently compressed
    # instead of clipping to flat white. Exposure is set by the light meter,
    # see meter_exposure().
    "accurate":  {"view_transform": "Khronos PBR Neutral", "look": "None"},
    # AgX with extra contrast: a filmic look, but it shifts colours (pastels
    # come out paler than their hex).
    "realistic": {"view_transform": "AgX", "look": "AgX - Medium High Contrast"},
}

# The light meter's patch covers this fraction of the hero face's shorter side.
PATCH_FRACTION = 0.2
METER_SAMPLES = 64

# A text label (v2 step 4), in Blender's built-in font, centred on the face
# the camera sees (the hero face): this share of the face's width, and never
# taller than LABEL_MAX_HEIGHT of the face's height (a flat scarf box's front
# is wide but low).
LABEL_WIDTH = 0.6
LABEL_MAX_HEIGHT = 0.5
# Printed, a hair raised: its thickness is this share of its height, and
# LABEL_INSET of that thickness sits inside the surface, so it never floats
# and is never sunk in.
LABEL_THICKNESS = 0.03
LABEL_INSET = 1 / 3
# Wrapped round a round body, the letters are cut into upright strips this
# many degrees of the curve wide, so no straight edge cuts into the body.
LABEL_SLICE_DEGREES = 1.5


def log(message):
    """Print a line that run.py will show to the user."""
    print(f"[render] {message}", flush=True)


# ---------------------------------------------------------------------------
# Render device
# ---------------------------------------------------------------------------

def use_gpu_if_available(scene):
    """Force Cycles onto the NVIDIA GPU via OptiX, or fall back to the CPU.

    Headless Blender doesn't reliably pick up the GPU setting saved in the UI
    (and --factory-startup ignores it on purpose), so it is set here explicitly.
    Returns a short description of the device that will render.
    """
    prefs = bpy.context.preferences.addons["cycles"].preferences
    gpus = []
    try:
        prefs.compute_device_type = "OPTIX"
        prefs.refresh_devices()
        gpus = [d for d in prefs.devices if d.type == "OPTIX"]
    except (TypeError, ValueError) as e:
        log(f"OptiX could not be selected: {e}")

    # Enable only the OptiX GPU. Leaving the CPU ticked as well would make a
    # slower "hybrid" render.
    for device in prefs.devices:
        device.use = device.type == "OPTIX"

    if gpus:
        scene.cycles.device = "GPU"
        scene.cycles.denoiser = "OPTIX"
        return "GPU (OptiX) - " + ", ".join(d.name for d in gpus)

    for line in (
        "!" * 70,
        "WARNING: NO OPTIX GPU FOUND - RENDERING ON THE CPU INSTEAD.",
        "WARNING: This will be much slower. Check the NVIDIA driver, and that",
        "WARNING: Blender > Preferences > System > Cycles shows the RTX GPU under OptiX.",
        "!" * 70,
    ):
        log(line)
    scene.cycles.device = "CPU"
    scene.cycles.denoiser = "OPENIMAGEDENOISE"  # the OptiX denoiser needs the GPU
    return "CPU (WARNING: GPU not available)"


def setup_render(scene, spec, output_path):
    """Cycles, samples, denoising, colour management and PNG output."""
    scene.render.engine = "CYCLES"
    device = use_gpu_if_available(scene)

    scene.cycles.samples = spec["samples"]
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    scene.render.film_transparent = False

    mode = COLOUR_MODES[spec["colour_mode"]]
    scene.display_settings.display_device = "sRGB"
    scene.view_settings.view_transform = mode["view_transform"]
    scene.view_settings.look = mode["look"]
    scene.view_settings.exposure = 0.0  # accurate mode: replaced by the light meter
    scene.view_settings.gamma = 1.0

    set_png_output(scene, output_path)
    return device


def set_png_output(scene, output_path):
    settings = scene.render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "RGB"
    settings.color_depth = "8"
    scene.render.filepath = output_path


# ---------------------------------------------------------------------------
# Scene building
# ---------------------------------------------------------------------------

def clear_scene():
    """Delete everything in the default scene (cube, light, camera...)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                       bpy.data.cameras, bpy.data.worlds):
        for block in list(collection):
            collection.remove(block)
    return bpy.context.scene


def new_principled_material(name, hex_colour, roughness, metallic=0.0):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True  # older Blender versions start without nodes
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*hex_to_linear_rgb(hex_colour), 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    if metallic:
        bsdf.inputs["Metallic"].default_value = metallic
    return mat


def new_metal_material(name, metal):
    """Polished metal: the metal's own reflected colour (spec.METALS), fully metallic."""
    return new_principled_material(name, METALS[metal], METAL_ROUGHNESS, metallic=1.0)


def add_object(scene, name, data):
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    return obj


def build_product(scene, spec):
    """The product, standing on the floor. Returns its objects, the body first.

    A box is one object. A round shape is a body plus a cap or lid, each
    with its own colour and the shape's roughness; a cap or lid the spec
    names a metal for is drawn in that metal instead. Every part is tagged
    "product_part" for the light meter.
    """
    shape = spec["shape"]
    fields = spec[shape]
    if shape == "box":
        objects = [build_box(scene, fields)]
    else:
        objects = []
        for part in shapes.parts(shape, fields):
            obj = add_object(scene, part.name, lathe(part.name, part.profile))
            metal = fields.get(part.metal) if part.metal else None
            name = f"{part.name}Material"
            obj.data.materials.append(new_metal_material(name, metal) if metal else
                                      new_principled_material(name, fields[part.colour], fields["roughness"]))
            objects.append(obj)
    for obj in objects:
        obj["product_part"] = True
    return objects


def product_parts():
    return [obj for obj in bpy.data.objects if obj.get("product_part")]


def lathe(name, profile):
    """A closed, smooth-shaded mesh: an (r, z) profile spun round the vertical axis.

    The profile starts and ends on the axis (r = 0); every point off the axis
    becomes a ring of ROUND_SEGMENTS vertices. Like the box, it is lifted a
    hair above the floor so the two don't overlap.
    """
    angles = [2 * math.pi * i / ROUND_SEGMENTS for i in range(ROUND_SEGMENTS)]
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        z += 0.00001
        if r <= 1e-9:
            rings.append([bm.verts.new((0.0, 0.0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for a in angles])
    for lower, upper in zip(rings, rings[1:]):
        for i in range(ROUND_SEGMENTS):
            j = (i + 1) % ROUND_SEGMENTS
            if len(lower) == 1:
                bm.faces.new((lower[0], upper[j], upper[i]))
            elif len(upper) == 1:
                bm.faces.new((lower[i], lower[j], upper[0]))
            else:
                bm.faces.new((lower[i], lower[j], upper[j], upper[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    # Every corner of the profile is rounded, so smooth shading is right everywhere.
    for poly in mesh.polygons:
        poly.use_smooth = True
    return mesh


def build_box(scene, box):
    """A bevelled box standing on the floor, with a Principled BSDF material."""
    w, h, d = box["width_cm"] / 100, box["height_cm"] / 100, box["depth_cm"] / 100
    bevel = box["bevel_cm"] / 100

    mesh = bpy.data.meshes.new("Box")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
    # Lift it a hair above the floor so the two bottom faces don't overlap.
    bmesh.ops.translate(bm, vec=(0, 0, h / 2 + 0.00001), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()

    obj = add_object(scene, "Box", mesh)
    if bevel > 0:
        # Smooth shading for the rounded edges; "harden normals" keeps the big
        # flat faces perfectly flat so reflections don't smear.
        for poly in mesh.polygons:
            poly.use_smooth = True
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = BEVEL_SEGMENTS
        mod.limit_method = "NONE"
        mod.harden_normals = True

    mesh.materials.append(new_principled_material("BoxMaterial", box["colour"], box["roughness"]))
    return obj


def build_backdrop(scene, hex_colour, radius, camera_azimuth):
    """A seamless studio sweep: floor that curves smoothly up into a back wall.

    Built as a profile (side view) that is extruded left-to-right. The curve
    meets the floor and the wall tangentially, so there is no horizon line.
    Like in a real studio, the sweep is turned to face the camera.
    """
    floor_front = -30 * radius   # floor reaches far past the camera
    curve_start = BACKDROP_CURVE_START * radius  # where the floor starts bending upwards
    curve_radius = BACKDROP_CURVE_RADIUS * radius
    wall_top = 30 * radius
    half_width = 30 * radius
    curve_segments = 64

    # (y, z) points of the side profile, from front to top of the wall.
    profile = [(floor_front, 0.0), (0.0, 0.0)]
    for i in range(curve_segments + 1):
        t = (math.pi / 2) * i / curve_segments
        profile.append((curve_start + curve_radius * math.sin(t),
                        curve_radius * (1 - math.cos(t))))
    profile.append((curve_start + curve_radius, wall_top))

    mesh = bpy.data.meshes.new("Backdrop")
    bm = bmesh.new()
    left = [bm.verts.new((-half_width, y, z)) for y, z in profile]
    right = [bm.verts.new((half_width, y, z)) for y, z in profile]
    for i in range(len(profile) - 1):
        # Vertex order chosen so the surface faces up/towards the camera.
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True

    mesh.materials.append(new_principled_material("BackdropMaterial", hex_colour, BACKDROP_ROUGHNESS))
    obj = add_object(scene, "Backdrop", mesh)
    obj.rotation_euler.z = math.radians(camera_azimuth)
    return obj


def build_world(scene, hex_colour):
    """A dim environment in the background colour, for soft ambient light."""
    world = bpy.data.worlds.new("World")
    if world.node_tree is None:
        world.use_nodes = True
    scene.world = world
    background = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    background.inputs["Color"].default_value = (*hex_to_linear_rgb(hex_colour), 1.0)
    background.inputs["Strength"].default_value = WORLD_STRENGTH


def direction_from_angles(azimuth_deg, elevation_deg):
    """Unit vector pointing from the box towards a point at these angles."""
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def build_lights(scene, target, radius, preset_name, camera_preset):
    """Soft area lights (key, fill, rim) aimed at the box."""
    overrides = camera_preset.get("light_overrides", {})
    for setup in LIGHTING_PRESETS[preset_name]:
        setup = {**setup, **overrides.get(setup["name"], {})}
        if setup["strength"] <= 0:
            continue
        distance = setup["distance"] * radius
        position = target + distance * direction_from_angles(
            camera_preset["azimuth"] + setup["azimuth"], setup["elevation"])

        # Most lights aim at the box. A light with "aim_behind" aims at the
        # backdrop instead: at the floor, that many box-radii behind the box
        # (as seen from the camera).
        if "aim_behind" in setup:
            away_from_camera = direction_from_angles(camera_preset["azimuth"] + 180, 0)
            aim = Vector((target.x, target.y, 0)) + setup["aim_behind"] * radius * away_from_camera
        else:
            aim = target

        light = bpy.data.lights.new(setup["name"], "AREA")
        light.shape = "RECTANGLE"
        light.size = setup["size"] * distance
        light.size_y = light.size * 0.75
        # Power falls off with distance^2, so scale it up to compensate.
        light.energy = setup["strength"] * BASE_IRRADIANCE * math.pi * (aim - position).length ** 2

        obj = add_object(scene, setup["name"], light)
        obj.location = position
        # Area lights shine along their local -Z axis: point that at the aim.
        obj.rotation_euler = (aim - position).to_track_quat("-Z", "Y").to_euler()
        # The softbox itself is never seen by the camera, only its light and
        # its reflection in glossy surfaces.
        obj.visible_camera = False


def build_strip_lights(scene, target, radius, camera_preset):
    """STRIP_LIGHTS: upright softboxes beside the product, seen only in its reflections."""
    # Light linking: only the product receives their light. The backdrop's
    # faint sheen would otherwise show a glow on the floor beside them.
    receivers = bpy.data.collections.new("StripLightReceivers")
    for obj in product_parts():
        receivers.objects.link(obj)
    for setup in STRIP_LIGHTS:
        distance = setup["distance"] * radius
        position = target + distance * direction_from_angles(
            camera_preset["azimuth"] + setup["azimuth"], setup["elevation"])

        light = bpy.data.lights.new(setup["name"], "AREA")
        light.shape = "RECTANGLE"
        light.size = setup["width"] * distance
        light.size_y = setup["height"] * distance
        # An area light's radiance is power / (pi * area), and a white card
        # under the key reads BASE_IRRADIANCE / pi.
        light.energy = setup["radiance"] * BASE_IRRADIANCE * light.size * light.size_y

        obj = add_object(scene, setup["name"], light)
        obj.location = position
        # Shine along local -Z at the product, local Y (the strip's length) upright.
        obj.rotation_euler = (target - position).to_track_quat("-Z", "Y").to_euler()
        obj.visible_camera = False
        obj.visible_diffuse = False
        obj.visible_transmission = False
        obj.visible_volume_scatter = False
        obj.light_linking.receiver_collection = receivers


def camera_preset(preset_name, shape):
    """The camera preset, with its changes for this shape (shape_overrides) applied."""
    preset = CAMERA_PRESETS[preset_name]
    return dict(preset, **preset.get("shape_overrides", {}).get(shape, {}))


def build_camera(scene, objects, shape, preset_name, resolution):
    """Place the camera for a preset and auto-frame it tightly on the product."""
    preset = camera_preset(preset_name, shape)
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = preset["lens_mm"]
    cam_data.sensor_width = 36
    cam_data.sensor_fit = "AUTO"
    cam = add_object(scene, "Camera", cam_data)
    scene.camera = cam

    if shape == "box":
        # The 8 corners of the (un-bevelled) box; the bevel only ever cuts inwards.
        corners = [objects[0].matrix_world @ v.co for v in objects[0].data.vertices]
        target = sum(corners, Vector()) / 8
    else:
        # A round shape's own vertices: there is no modifier, so they are its surface.
        corners = [obj.matrix_world @ v.co for obj in objects
                   for i, v in enumerate(obj.data.vertices) if i % FRAMING_STEP == 0]
        target = (Vector([min(c[k] for c in corners) for k in range(3)])
                  + Vector([max(c[k] for c in corners) for k in range(3)])) / 2
    radius = max((c - target).length for c in corners)

    # Camera axes: forward (looking at the box), right, and up in the image.
    to_camera = direction_from_angles(preset["azimuth"], preset["elevation"])
    forward = -to_camera
    # Looking straight down, "up" is ambiguous: use the back of the product
    # (+Y), so its front is at the bottom of the frame.
    world_up = Vector((0, 1, 0)) if preset["elevation"] >= 89.9 else Vector((0, 0, 1))
    right = forward.cross(world_up).normalized()
    up = right.cross(forward).normalized()

    # Half the field of view, as a slope, for each image axis.
    res_x, res_y = resolution
    half_long = (cam_data.sensor_width / 2) / cam_data.lens
    if res_x >= res_y:
        half_x, half_y = half_long, half_long * res_y / res_x
    else:
        half_x, half_y = half_long * res_x / res_y, half_long

    def projected_extent(distance):
        """The corners as seen from a camera this far away: (min_x, max_x, min_y, max_y)."""
        position = target + distance * to_camera
        xs, ys = [], []
        for c in corners:
            v = c - position
            depth = v.dot(forward)
            xs.append(v.dot(right) / depth)
            ys.append(v.dot(up) / depth)
        return min(xs), max(xs), min(ys), max(ys)

    def fits(distance):
        x0, x1, y0, y1 = projected_extent(distance)
        return (x1 - x0) / 2 <= FRAME_FILL * half_x and (y1 - y0) / 2 <= FRAME_FILL * half_y

    # Binary search for the closest distance where the product still fits.
    near, far = radius * 1.01, radius * 1000
    for _ in range(60):
        mid = (near + far) / 2
        if fits(mid):
            far = mid
        else:
            near = mid
    distance = far

    cam.matrix_world = Matrix.Translation(target + distance * to_camera) @ \
        Matrix((right, up, to_camera)).transposed().to_4x4()

    # Perspective makes the product sit slightly off-centre; shift the lens to recentre it.
    x0, x1, y0, y1 = projected_extent(distance)
    cam_data.shift_x = ((x0 + x1) / 2) / (2 * half_long)
    cam_data.shift_y = ((y0 + y1) / 2) / (2 * half_long)

    cam_data.clip_start = distance * 0.01
    cam_data.clip_end = distance * 100
    return cam, target, radius


def text_mesh(scene, text):
    """The text as a flat mesh in Blender's built-in font, in font units: (mesh, bounds).

    Reads left to right along +x, up along +y, facing +z. bounds is
    (min_x, max_x, min_y, max_y) of the letters themselves.
    """
    curve = bpy.data.curves.new("LabelText", "FONT")
    curve.body = text
    obj = add_object(scene, "LabelText", curve)
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.curves.remove(curve)
    xs, ys = [v.co.x for v in mesh.vertices], [v.co.y for v in mesh.vertices]
    return mesh, (min(xs), max(xs), min(ys), max(ys))


def build_label(scene, spec):
    """The spec's label, printed on the face the camera sees (hero_face), or None if it has none.

    Centred on the face, LABEL_WIDTH of its width (at most LABEL_MAX_HEIGHT
    of its height), reading left to right and upright as the camera sees it:
    the face's u runs to the camera's right and v upwards (from straight
    above, towards the back of the product). On the side of a round body it
    is wrapped round the curve, centred where the camera looks from. Tagged
    "product_part", so the strip lights reach it (the light meter hides
    it). Its height on the face is kept in obj["label_height"], for the
    colour check (colour_check_patch).
    """
    label = spec.get("label")
    if not label:
        return None
    centre, u, v, (face_w, face_h), _ = hero_face(spec)
    # The side of a round body (not its top) is curved: the label is wrapped
    # round it, centred where the camera looks from, and its width is measured
    # along the curve: the arc whose chord is LABEL_WIDTH of the diameter.
    wrapped = spec["shape"] != "box" and CAMERA_PRESETS[spec["camera"]]["hero_face"] == "front"
    radius = face_w / 2
    width = 2 * radius * math.asin(LABEL_WIDTH) if wrapped else LABEL_WIDTH * face_w
    flat, (x0, x1, y0, y1) = text_mesh(scene, label["text"])
    scale = min(width / (x1 - x0), LABEL_MAX_HEIGHT * face_h / (y1 - y0))
    width, height = scale * (x1 - x0), scale * (y1 - y0)
    thickness = LABEL_THICKNESS * height
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    bm = bmesh.new()
    bm.from_mesh(flat)
    bpy.data.meshes.remove(flat)
    if wrapped:
        # Cut the letters into thin upright strips first, so no straight edge
        # spans enough of the curve to cut into the body once wrapped.
        step = radius * math.radians(LABEL_SLICE_DEGREES) / scale
        for i in range(1, math.ceil((x1 - x0) / step)):
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                                   plane_co=(x0 + i * step, 0, 0), plane_no=(1, 0, 0))
    # Thicken the flat letters outwards (+z).
    faces = list(bm.faces)
    grown = bmesh.ops.extrude_face_region(bm, geom=faces, use_keep_orig=True)
    lifted = [g for g in grown["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, thickness / scale), verts=lifted)

    # Then onto the face: x along u (the camera's right), y along v (up), z out of it.
    normal = u.cross(v)
    azimuth = math.radians(CAMERA_PRESETS[spec["camera"]]["azimuth"])
    for vert in bm.verts:
        x, y, z = scale * (vert.co.x - cx), scale * (vert.co.y - cy), scale * vert.co.z - LABEL_INSET * thickness
        if wrapped:
            # x runs along the curve: round the axis from the camera's side, to its right.
            angle, r = azimuth + x / radius, radius + z
            vert.co = Vector((r * math.sin(angle), -r * math.cos(angle), centre.z + y))
        else:
            vert.co = centre + x * u + y * v + z * normal
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("Label")
    bm.to_mesh(mesh)
    bm.free()

    obj = add_object(scene, "Label", mesh)
    metal = label["metal"]
    roughness = spec[spec["shape"]]["roughness"]
    mesh.materials.append(new_metal_material("LabelMaterial", metal) if metal else
                          new_principled_material("LabelMaterial", label["colour"], roughness))
    obj["product_part"] = True
    obj["label_height"] = height

    if wrapped:
        half = width / 2 / radius
        ends = [Vector((radius * math.sin(azimuth + a), -radius * math.cos(azimuth + a), centre.z))
                for a in (-half, half)]
        middle = Vector((radius * math.sin(azimuth), -radius * math.cos(azimuth), centre.z))
        normal = Vector((math.sin(azimuth), -math.cos(azimuth), 0))
    else:
        ends = [centre - width / 2 * u, centre + width / 2 * u]
        middle = centre
    check_label_reads(scene, label["text"], ends, middle, v, normal, width, height)
    return obj


def check_label_reads(scene, text, ends, middle, up, normal, width, height):
    """Stop the render if the camera would see the label mirrored, upside down or from behind.

    ends: the label's left and right ends, middle its centre, up its upward
    direction and normal the way its middle faces, all in world space.
    """
    camera = scene.camera
    left, right = (world_to_camera_view(scene, camera, end) for end in ends)
    bottom, top = (world_to_camera_view(scene, camera, middle + side * height / 2 * up) for side in (-1, 1))
    facing = normal.dot(camera.matrix_world.translation - middle) > 0
    if not (left.x < right.x and bottom.y < top.y and facing):
        raise RuntimeError(f'label "{text}" would not read correctly from the camera: left-right '
                           f"{left.x:.2f} -> {right.x:.2f}, bottom-top {bottom.y:.2f} -> {top.y:.2f}, "
                           f"facing the camera: {facing}")
    log(f'label: "{text}", {width * 100:.1f} x {height * 100:.1f} cm, reads left to right and upright '
        f"from the camera")


def build_scene(spec):
    """Build the whole set from the spec. Returns the scene, ready to render."""
    scene = clear_scene()
    objects = build_product(scene, spec)
    _, target, radius = build_camera(scene, objects, spec["shape"], spec["camera"], spec["resolution"])
    # After the camera, so a label never changes the framing.
    build_label(scene, spec)
    build_backdrop(scene, spec["background_colour"], radius, CAMERA_PRESETS[spec["camera"]]["azimuth"])
    build_world(scene, spec["background_colour"])
    build_lights(scene, target, radius, spec["lighting"], CAMERA_PRESETS[spec["camera"]])
    if has_shine(spec):
        build_strip_lights(scene, target, radius, CAMERA_PRESETS[spec["camera"]])
    return scene


# ---------------------------------------------------------------------------
# Colour accuracy: hero patch and light meter
# ---------------------------------------------------------------------------

def hero_face(spec):
    """The product's main lit face: (centre, u, v, face_sides, colour).

    u and v are the face's directions, face_sides its size along them (m),
    colour the spec colour of the part the face is on. From above, a bottle
    or jar shows its cap or lid; from the front, every shape shows its body.
    """
    shape = spec["shape"]
    fields = spec[shape]
    face = CAMERA_PRESETS[spec["camera"]]["hero_face"]
    if shape == "box":
        w, h, d = fields["width_cm"] / 100, fields["height_cm"] / 100, fields["depth_cm"] / 100
        if face == "top":
            return Vector((0, 0, h)), Vector((1, 0, 0)), Vector((0, 1, 0)), (w, d), fields["colour"]
        return Vector((0, -d / 2, h / 2)), Vector((1, 0, 0)), Vector((0, 0, 1)), (w, h), fields["colour"]
    hero = shapes.hero(shape, fields, face)
    v = Vector((0, 1, 0)) if face == "top" else Vector((0, 0, 1))
    return Vector(hero.centre), Vector((1, 0, 0)), v, hero.sides, fields[hero.colour]


def hero_patch(scene, spec, below=None):
    """Where the centre of the product's main lit face lands in the image.

    Returns (min_x, max_x, min_y, max_y) in 0-1 image coordinates, origin at
    the bottom-left. The patch is a square on the face, PATCH_FRACTION of the
    face's shorter side. With `below` (the height of a label centred on the
    face), it is moved off the label: half way between the label's lower edge
    and the face's, and made smaller if it wouldn't fit there.
    """
    centre, u, v, face_sides, _ = hero_face(spec)

    half = PATCH_FRACTION * min(face_sides) / 2
    if below:
        room = (face_sides[1] - below) / 2  # the face below the label
        centre = centre - (below + room) / 2 * v
        half = min(half, 0.3 * room)
    points = [world_to_camera_view(scene, scene.camera, centre + su * half * u + sv * half * v)
              for su in (-1, 1) for sv in (-1, 1)]
    return (min(p.x for p in points), max(p.x for p in points),
            min(p.y for p in points), max(p.y for p in points))


def colour_check_patch(scene, spec):
    """The colour check's patch: the hero patch, or below the label if there is one.

    The light meter keeps the hero patch, and hides the label while it
    meters, so a label changes neither the exposure nor the white balance.
    """
    label = bpy.data.objects.get("Label")
    return hero_patch(scene, spec, below=label["label_height"] if label else None)


def white_card_material():
    """Pure white, perfectly matte material (no shine) for the light meter."""
    mat = bpy.data.materials.new("LightMeterCard")
    if mat.node_tree is None:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for node in list(nodes):
        if node.type != "OUTPUT_MATERIAL":
            nodes.remove(node)
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    output = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    mat.node_tree.links.new(diffuse.outputs["BSDF"], output.inputs["Surface"])
    return mat


def meter_exposure(scene, spec):
    """Accurate mode's light meter. Sets the exposure; returns it in stops.

    Like a photographer holding a white card where the product is: the
    product (every part of it) is briefly made pure matte white, and only a
    small patch at the centre of its main lit face is rendered, to a linear
    EXR file. The brightness of a white matte card measures how much light
    falls on it. Exposure is then set so that this brightness maps to exactly
    1.0, which makes a matte product show (very nearly) its own colour. The
    card also sets the white balance.
    """
    render = scene.render
    # A label is hidden while metering, so the exposure is exactly the one
    # without it: a hair raised, its letter edges would shade the card.
    label = bpy.data.objects.get("Label")
    parts = [obj for obj in product_parts() if obj is not label]
    real_materials = [obj.data.materials[0] for obj in parts]
    if label:
        label.hide_render = True
    saved = {name: getattr(render, name) for name in (
        "use_border", "use_crop_to_border", "border_min_x", "border_max_x",
        "border_min_y", "border_max_y", "filepath")}
    saved_samples = scene.cycles.samples
    meter_path = render.filepath + ".meter.exr"

    white = white_card_material()
    for obj in parts:
        obj.data.materials[0] = white
    render.use_border = render.use_crop_to_border = True
    (render.border_min_x, render.border_max_x,
     render.border_min_y, render.border_max_y) = hero_patch(scene, spec)
    render.image_settings.file_format = "OPEN_EXR"  # linear: the true amount of light
    render.image_settings.color_depth = "32"
    render.filepath = meter_path
    scene.cycles.samples = METER_SAMPLES
    try:
        bpy.ops.render.render(write_still=True)
        card = bpy.data.images.load(meter_path)
        pixels = np.array(card.pixels[:]).reshape(-1, card.channels)[:, :3]
        bpy.data.images.remove(card)
    finally:
        if os.path.exists(meter_path):
            os.remove(meter_path)
        for name, value in saved.items():
            setattr(render, name, value)
        scene.cycles.samples = saved_samples
        set_png_output(scene, saved["filepath"])
        for obj, material in zip(parts, real_materials):
            obj.data.materials[0] = material
        if label:
            label.hide_render = False

    card = pixels.mean(axis=0)
    brightness = 0.2126 * card[0] + 0.7152 * card[1] + 0.0722 * card[2]
    if brightness <= 1e-6 or min(card) <= 1e-6:
        log("WARNING: light meter saw no light on the product; exposure left at 0")
        return 0.0

    # White balance: light bouncing off a coloured backdrop tints the product (a
    # pink floor makes everything near it pinker). Tint every light source by
    # the opposite amount so the white card reads neutral again. This is
    # exactly what a camera's white balance does.
    balance = brightness / card
    strongest = balance.max()
    balance = balance / strongest  # keep every colour value <= 1
    for light in bpy.data.lights:
        light.color = tuple(balance)
    background = next(n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND")
    world_colour = np.array(background.inputs["Color"].default_value[:3])
    background.inputs["Color"].default_value = (*(world_colour * balance), 1.0)

    # After white balance the card reads brightness / strongest in every
    # channel. Expose so that becomes exactly 1.0.
    stops = max(-4.0, min(4.0, math.log2(strongest / brightness)))
    scene.view_settings.exposure = stops
    return stops


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    # Blender's own arguments come before "--"; ours come after it.
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="render_scene.py")
    parser.add_argument("--spec", required=True, help="path to a JSON scene spec")
    parser.add_argument("--output", required=True, help="where to save the PNG")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    try:
        spec = load_spec(args.spec)
    except SpecError as e:
        log(f"Invalid spec: {args.spec}")
        for problem in e.problems:
            log(f"  - {problem}")
        sys.exit(2)

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    scene = build_scene(spec)
    device = setup_render(scene, spec, output_path)
    log(f"device: {device}")
    log(f"shape: {spec['shape']}, camera: {spec['camera']}, lighting: {spec['lighting']}"
        f"{' + strip lights (glossy or metal)' if has_shine(spec) else ''}, colour mode: {spec['colour_mode']}, "
        f"{spec['resolution'][0]}x{spec['resolution'][1]}, {spec['samples']} samples")

    if spec["colour_mode"] == "accurate":
        start = time.perf_counter()
        stops = meter_exposure(scene, spec)
        log(f"light meter: exposure {stops:+.2f} stops ({time.perf_counter() - start:.1f} s)")

    start = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    seconds = time.perf_counter() - start
    log(f"render time: {seconds:.1f} s")
    log(f"saved: {output_path}")

    measured, _ = measure_patch(output_path, colour_check_patch(scene, spec))
    target = hero_face(spec)[4].upper()
    delta_e = delta_e76(target, measured)
    log(f"colour check: spec {target}, measured {measured}, "
        f"Delta E {delta_e:.1f} ({describe_delta_e(delta_e)})")


if __name__ == "__main__":
    main()
