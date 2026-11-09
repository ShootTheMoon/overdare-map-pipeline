# -*- coding: utf-8 -*-
r"""SGK6 — Sangok terrain + mountain walls re-cut as one 6 x 5 grid of 30 tiles (2026-09-12).
Headless (no blend needed):
  "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe" -b --factory-startup --python _scripts\sgk6_tiles.py
Why: the line the user sees sits exactly on the play-rect edge, where the 12 terrain tiles (40 m, 1024 = 3.9 cm/px)
     meet the 6 wall slabs (130 x 50 m, 2048 textures -> Studio shows them ~1024 = ~13 cm/px, and 3x the bounds).
     Same recipe as Hwaseong TER6/OUT6, which removed the lines there:
  * one grid: x edges -130/-80/-40/0/40/80/130, y edges -110/-60/-20/20/60/110 -> every tile <= 50 m, 1024 texture
  * 0.5 m lattice everywhere (old walls were 1.25 m) -> border vertices identical on both sides, no T-junctions
  * z = sgk_layout.height_at (same function as the live mesh and the COL_TER slabs -> collision / props unchanged)
  * texture = sgk_texbake.bake_rect (world-continuous fields, TEX_PAD from the neighbour's real ground)
  * analytic normals, identical bounds (50 x H x 50 m, 1 mm triangles buried under the ground)
Output: 06_OVERDARE\_rebatch_sgk6\SGK6_TER_ij.fbx, _texwork\T_SGK6_TER_ij.png, place_sgk6.json"""
import bpy, bmesh, os, sys, json, math
from mathutils import Vector
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import sgk_layout as L
import sgk_texbake as TB

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(HERE); OVD = os.path.join(ROOT, "06_OVERDARE")
PREFIX = os.environ.get("SGK_PREFIX", "SGK6")          # SGK7 = same meshes, edge-softened texture (2026-09-12)
DST = os.path.join(OVD, "_rebatch_" + PREFIX.lower()); os.makedirs(DST, exist_ok=True)

# 2026-09-12 (SGK7): the line on the play-rect edge is in the COLOUR, not the mesh — blend_at's litter channel jumps
# 0.55 -> 0.00 within 1 m at |x| = 80 / |y| = 60 (forest/strip masks stop at the rect). Soften the world mask (all
# 4 channels, 3 m gaussian) inside a +-8 m band around the rect edge; everything else stays byte-identical.
_orig_world_mask = TB._world_mask


def _soft_world_mask(res_m=4.0):
    fld = _orig_world_mask(res_m)
    if os.environ.get("SGK_EDGE_SOFT", "1") != "1" or fld.get("soft"):
        return fld
    arr = fld["arr"]; R, C = arr.shape[:2]; res = C / fld["w"]
    X = fld["x0"] + (np.arange(C) + 0.5) / res; Y = fld["y0"] + fld["h"] - (np.arange(R) + 0.5) / res
    d = np.maximum(np.abs(X)[None, :] - L.PLAY_X, np.abs(Y)[:, None] - L.PLAY_Y)       # signed, < 0 inside the rect
    t = np.clip(np.abs(d) / 8.0, 0, 1); w = (1 - t * t * (3 - 2 * t))[:, :, None]
    blur = np.stack([np.asarray(Image.fromarray((arr[:, :, k] * 255).astype("uint8"), "L").filter(ImageFilter.GaussianBlur(3.0 * res)),
                                dtype=np.float32) / 255.0 for k in range(4)], axis=2)
    fld["arr"] = arr * (1 - w) + blur * w; fld["soft"] = True
    return fld


TB._world_mask = _soft_world_mask
XE = [-L.MESH_X, -80.0, -40.0, 0.0, 40.0, 80.0, L.MESH_X]
YE = [-L.MESH_Y, -60.0, -20.0, 20.0, 60.0, L.MESH_Y]
STEP = 0.5; N = 1024; BW = max(b - a for a, b in zip(XE, XE[1:])); BH = max(b - a for a, b in zip(YE, YE[1:]))


def normal(x, y, e=0.25):
    hx = (L.height_at(x + e, y) - L.height_at(x - e, y)) / (2 * e)
    hy = (L.height_at(x, y + e) - L.height_at(x, y - e)) / (2 * e)
    return Vector((-hx, -hy, 1.0)).normalized()


def micro(bm, x, y, z):
    a = bm.verts.new((x, y, z)); b = bm.verts.new((x + 0.001, y, z)); c = bm.verts.new((x, y + 0.001, z)); bm.faces.new((a, b, c))


def material(name, png):
    m = bpy.data.materials.new("M_" + name); m.use_nodes = True; nt = m.node_tree
    b = nt.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = 0.85
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(png); nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    return m


def build(name, x0, x1, y0, y1, zlo, zhi, png):
    nx, ny = round((x1 - x0) / STEP), round((y1 - y0) / STEP)
    bm = bmesh.new(); G = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            x, y = x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny; G[(i, j)] = bm.verts.new((x, y, L.height_at(x, y)))
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((G[(i, j)], G[(i + 1, j)], G[(i + 1, j + 1)], G[(i, j + 1)]))
    top = max(G.values(), key=lambda v: v.co.z)
    micro(bm, x0, y0, zlo); micro(bm, x0 + BW, y0 + BH, zlo); micro(bm, top.co.x, top.co.y, zhi)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (L.uv_pad((l.vert.co.x - x0) / (x1 - x0), N), L.uv_pad((l.vert.co.y - y0) / (y1 - y0), N))
    bm.verts.index_update()
    vn = [normal(v.co.x, v.co.y) for v in bm.verts]
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.normals_split_custom_set_from_vertices(vn)
    me.materials.append(material(name, png))
    ob = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(ob)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.fbx(filepath=os.path.join(DST, name + ".fbx"), use_selection=True, object_types={"MESH"}, axis_up="Y", axis_forward="-Z",
                             apply_scale_options="FBX_SCALE_NONE", global_scale=1.0, apply_unit_scale=True, path_mode="COPY", embed_textures=True,
                             mesh_smooth_type="FACE", use_mesh_modifiers=True, add_leaf_bones=False, bake_anim=False, use_custom_props=False)
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    rec = {"tris": sum(len(p.vertices) - 2 for p in me.polygons),
           "position": [round(c[0] * 100 + L.ENGINE_X0, 1), round(c[2] * 100, 1), round(-c[1] * 100 + L.ENGINE_Z0, 1)],
           "size": [round((max(xs) - min(xs)) * 100, 1), round((max(zs) - min(zs)) * 100, 1), round((max(ys) - min(ys)) * 100, 1)]}
    bpy.data.objects.remove(ob); bpy.data.meshes.remove(me)
    return rec


def main():
    hs = [L.height_at(x, y) for x in range(int(XE[0]), int(XE[-1]) + 1) for y in range(int(YE[0]), int(YE[-1]) + 1)]
    zlo, zhi = min(hs) - 1.0, max(hs) + 0.3
    print("@@Z range %.2f .. %.2f  bounds %.0f x %.0f" % (zlo, zhi, BW, BH), flush=True)
    src = TB._load_sources(); place = {}
    for i, (x0, x1) in enumerate(zip(XE, XE[1:])):
        for j, (y0, y1) in enumerate(zip(YE, YE[1:])):
            name = PREFIX + "_TER_%d%d" % (i, j)
            TB.bake_rect("T_" + name, x0, y0, x1 - x0, y1 - y0, N, N, src)
            place[name] = build(name, x0, x1, y0, y1, zlo, zhi, os.path.join(TB.OUT, "T_" + name + ".png"))
            print("@@TILE", name, place[name]["tris"], place[name]["size"], flush=True)
    json.dump(place, open(os.path.join(DST, "place_" + PREFIX.lower() + ".json"), "w"), indent=1)
    print("@@" + PREFIX + " done", len(place), DST)

if __name__ == "__main__":
    main()
