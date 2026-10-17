"""
Builds a studio product shot of a box from a JSON spec and renders it to PNG.

This script runs INSIDE Blender. You normally don't call it yourself; run.py
does, roughly like this:

    blender --background --factory-startup --python render_scene.py -- \
            --spec specs/pink_three_quarter.json --output renders/out.png

Everything is built from scratch on every run (box, backdrop, lights, camera),
so the result depends only on the spec file, never on Blender's saved settings.

Conventions:
  * 1 Blender unit = 1 metre. The spec is in cm, so sizes are divided by 100.
  * The box stands on the floor (z = 0), centred on the origin.
  * The FRONT of the box faces -Y (towards the "front" camera).
"""

import argparse
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec import SpecError, hex_to_linear_rgb, load_spec  # noqa: E402

# ---------------------------------------------------------------------------
# Presets. Distances and sizes are multiples of the box's "radius" (half its
# diagonal), so a tiny lipstick box and a big gift box get the same framing
# and the same exposure.
# ---------------------------------------------------------------------------

# azimuth: degrees around the box (0 = straight in front, + = towards the right)
# elevation: degrees above the floor (90 = looking straight down)
CAMERA_PRESETS = {
    "front":         {"azimuth": 0,  "elevation": 8,  "lens_mm": 85},
    "three_quarter": {"azimuth": 35, "elevation": 22, "lens_mm": 85},
    "top_down":      {"azimuth": 0,  "elevation": 90, "lens_mm": 85},
}

# The box fills this fraction of the frame along its tightest axis.
FRAME_FILL = 0.62

# Lights are placed relative to the camera, so every camera angle gets the
# same look. azimuth is an offset from the camera's azimuth.
#   distance: multiple of the box radius
#   size:     softbox size as a fraction of its distance (bigger = softer)
#   strength: brightness at the box, relative to BASE_IRRADIANCE
LIGHTING_PRESETS = {
    "studio_soft": [
        # Key: main light, front-left and above. Sets the shadow direction.
        {"name": "Key",  "azimuth": -55, "elevation": 40, "distance": 6, "size": 0.3, "strength": 1.0},
        # Fill: low and straight in front, softens the shadows. On glossy boxes
        # it also shows up as a softbox reflection on the front face.
        {"name": "Fill", "azimuth": 0,   "elevation": 0,  "distance": 7, "size": 0.6, "strength": 0.2},
        # Rim: behind the box, on the opposite side to the key. Lights the top
        # and back edges so the box separates from the backdrop.
        {"name": "Rim",  "azimuth": 200, "elevation": 50, "distance": 5, "size": 0.5, "strength": 1.0},
    ],
}

# Irradiance (W/m^2) the key light delivers at the box. Light power is scaled
# by distance^2 so this stays the same for every box size.
BASE_IRRADIANCE = 3.5

# The environment around the set: the background colour, dimmed.
WORLD_STRENGTH = 0.2

BACKDROP_ROUGHNESS = 0.7
# Behind the box the floor curves up into a wall (multiples of the box radius).
BACKDROP_CURVE_START = 3
BACKDROP_CURVE_RADIUS = 6
BEVEL_SEGMENTS = 6

# AgX "look" (contrast curve) applied on top of the AgX view transform.
# A little extra contrast keeps pastel colours from looking washed out.
AGX_LOOK = "AgX - Medium High Contrast"


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

    scene.render.resolution_x, scene.render.resolution_y = spec["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False

    scene.display_settings.display_device = "sRGB"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = AGX_LOOK
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = output_path
    return device


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


def new_principled_material(name, hex_colour, roughness):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True  # older Blender versions start without nodes
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*hex_to_linear_rgb(hex_colour), 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def add_object(scene, name, data):
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    return obj


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


def build_backdrop(scene, hex_colour, radius):
    """A seamless studio sweep: floor that curves smoothly up into a back wall.

    Built as a profile (side view) that is extruded left-to-right. The curve
    meets the floor and the wall tangentially, so there is no horizon line.
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
    return add_object(scene, "Backdrop", mesh)


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


def build_lights(scene, target, radius, preset_name, camera_azimuth):
    """Three soft area lights (key, fill, rim) aimed at the box."""
    for setup in LIGHTING_PRESETS[preset_name]:
        distance = setup["distance"] * radius
        position = target + distance * direction_from_angles(
            camera_azimuth + setup["azimuth"], setup["elevation"])

        light = bpy.data.lights.new(setup["name"], "AREA")
        light.shape = "RECTANGLE"
        light.size = setup["size"] * distance
        light.size_y = light.size * 0.75
        # Power falls off with distance^2, so scale it up to compensate.
        light.energy = setup["strength"] * BASE_IRRADIANCE * math.pi * distance ** 2

        obj = add_object(scene, setup["name"], light)
        obj.location = position
        # Area lights shine along their local -Z axis: point that at the box.
        obj.rotation_euler = (target - position).to_track_quat("-Z", "Y").to_euler()
        # The softbox itself is never seen by the camera, only its light and
        # its reflection in glossy surfaces.
        obj.visible_camera = False


def build_camera(scene, box_obj, preset_name, resolution):
    """Place the camera for a preset and auto-frame it tightly on the box."""
    preset = CAMERA_PRESETS[preset_name]
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = preset["lens_mm"]
    cam_data.sensor_width = 36
    cam_data.sensor_fit = "AUTO"
    cam = add_object(scene, "Camera", cam_data)
    scene.camera = cam

    # The 8 corners of the (un-bevelled) box; the bevel only ever cuts inwards.
    corners = [box_obj.matrix_world @ v.co for v in box_obj.data.vertices]
    target = sum(corners, Vector()) / 8
    radius = max((c - target).length for c in corners)

    # Camera axes: forward (looking at the box), right, and up in the image.
    to_camera = direction_from_angles(preset["azimuth"], preset["elevation"])
    forward = -to_camera
    # Looking straight down, "up" is ambiguous: use the back of the box (+Y),
    # so the front of the box is at the bottom of the frame.
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
        """Box corners as seen from a camera this far away: (min_x, max_x, min_y, max_y)."""
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

    # Binary search for the closest distance where the box still fits.
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

    # Perspective makes the box sit slightly off-centre; shift the lens to recentre it.
    x0, x1, y0, y1 = projected_extent(distance)
    cam_data.shift_x = ((x0 + x1) / 2) / (2 * half_long)
    cam_data.shift_y = ((y0 + y1) / 2) / (2 * half_long)

    cam_data.clip_start = distance * 0.01
    cam_data.clip_end = distance * 100
    return cam, target, radius, preset["azimuth"]


def build_scene(spec):
    """Build the whole set from the spec. Returns the scene, ready to render."""
    scene = clear_scene()
    box = build_box(scene, spec["box"])
    _, target, radius, camera_azimuth = build_camera(scene, box, spec["camera"], spec["resolution"])
    build_backdrop(scene, spec["background_colour"], radius)
    build_world(scene, spec["background_colour"])
    build_lights(scene, target, radius, spec["lighting"], camera_azimuth)
    return scene


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
    log(f"camera: {spec['camera']}, lighting: {spec['lighting']}, "
        f"{spec['resolution'][0]}x{spec['resolution'][1]}, {spec['samples']} samples")

    start = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    seconds = time.perf_counter() - start

    log(f"render time: {seconds:.1f} s")
    log(f"saved: {output_path}")


if __name__ == "__main__":
    main()
