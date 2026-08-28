# -*- coding: utf-8 -*-
"""
CDG - render an asset for visual QA, with textures resolved from the shared
_TexLib.

Two modes:
  --render  <Key>   render the reduced .blend
  --compare <Key>   render source FBX and reduced side by side, same camera

The A/B is the only honest check that the decimation ratios are survivable.
Trap F says collapse-decimating a scan shatters it; these are authored meshes so
it should hold, but "should" is not evidence.

Usage:
  blender.exe --background --factory-startup --python cdg_render.py -- compare BukJinseolcheong
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
TEXLIB = os.path.join(ROOT, "_extracted", "_TexLib")
FBX_DIR = os.path.join(ROOT, "_extracted", "FBX")
OUT = os.path.join(ROOT, "_renders")
RES = (1280, 800)
SAMPLES = 24


def relink_images():
    """FBX was imported with use_image_search=False, so images have a name but no
    pixels. Point every one at the de-duplicated library and load it."""
    ok = miss = 0
    for img in bpy.data.images:
        if img.name in ("Render Result", "Viewer Node"):
            continue
        base = os.path.basename(img.filepath_from_user() or img.name)
        if not base.lower().endswith((".png", ".jpg", ".tga")):
            base += ".png"
        cand = os.path.join(TEXLIB, base)
        if not os.path.exists(cand):
            hit = next((f for f in os.listdir(TEXLIB)
                        if f.lower() == base.lower()), None)
            cand = os.path.join(TEXLIB, hit) if hit else None
        if cand and os.path.exists(cand):
            img.filepath = cand
            try:
                img.reload()
                ok += 1
            except Exception:
                miss += 1
        else:
            miss += 1
    return ok, miss


def scene_bounds():
    lo = Vector((1e18,) * 3)
    hi = Vector((-1e18,) * 3)
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def setup_world():
    w = bpy.data.worlds.new("W") if not bpy.data.worlds else bpy.data.worlds[0]
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.62, 0.70, 0.82, 1.0)
        bg.inputs[1].default_value = 1.4


def add_sun():
    d = bpy.data.lights.new("Sun", "SUN")
    d.energy = 4.0
    d.angle = math.radians(2.0)
    o = bpy.data.objects.new("Sun", d)
    bpy.context.scene.collection.objects.link(o)
    o.rotation_euler = (math.radians(52), 0, math.radians(35))


def place_camera(lo, hi, azim_deg, elev_deg, pad=1.35):
    ctr = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 1.0)
    cam_d = bpy.data.cameras.new("Cam")
    cam_d.lens = 50
    cam = bpy.data.objects.new("Cam", cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    a = math.radians(azim_deg)
    e = math.radians(elev_deg)
    dist = radius * pad / math.tan(math.radians(20))
    cam.location = ctr + Vector((math.cos(a) * math.cos(e),
                                 math.sin(a) * math.cos(e),
                                 math.sin(e))) * dist
    direction = ctr - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam


def render_to(path):
    sc = bpy.context.scene
    avail = sc.render.bl_rna.properties["engine"].enum_items.keys()
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        if eng in avail:
            sc.render.engine = eng
            break
    try:
        sc.eevee.taa_render_samples = SAMPLES
    except Exception:
        pass
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def shoot(tag, views):
    os.makedirs(OUT, exist_ok=True)
    lo, hi = scene_bounds()
    setup_world()
    add_sun()
    for name, az, el in views:
        for c in [o for o in bpy.data.objects if o.type == "CAMERA"]:
            bpy.data.objects.remove(c, do_unlink=True)
        place_camera(lo, hi, az, el)
        p = os.path.join(OUT, "%s_%s.png" % (tag, name))
        render_to(p)
        print("   rendered", p)


VIEWS = [("3q", 35, 22), ("front", -90, 8), ("closeup_eave", 20, 5)]


def do_reduced(key):
    blend = None
    arch = os.path.join(ROOT, "20_ARCHITECTURE")
    for zone in os.listdir(arch):
        c = os.path.join(arch, zone, "CDG_%s_reduced.blend" % key)
        if os.path.exists(c):
            blend = c
            break
    if not blend:
        print("no reduced blend for", key)
        return
    bpy.ops.wm.open_mainfile(filepath=blend)
    ok, miss = relink_images()
    print("   textures linked %d, missing %d" % (ok, miss))
    shoot(key + "_REDUCED", VIEWS)


def do_source(key):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=os.path.join(FBX_DIR, key + ".fbx"),
                             use_image_search=False, use_anim=False,
                             use_custom_normals=False)
    ok, miss = relink_images()
    print("   textures linked %d, missing %d" % (ok, miss))
    shoot(key + "_SOURCE", VIEWS)


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not args:
        print("usage: -- [render|compare] <Key> ...")
        return
    mode, keys = args[0], args[1:]
    for k in keys:
        print("===", mode, k)
        if mode == "compare":
            do_source(k)
            do_reduced(k)
        else:
            do_reduced(k)


main()
