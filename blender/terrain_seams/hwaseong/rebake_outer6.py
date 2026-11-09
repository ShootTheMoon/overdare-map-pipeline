# -*- coding: utf-8 -*-
r"""OUT6 — the 10 outer 100 m ring tiles, same treatment as TER6 (user 2026-09-12: "밖부분도 똑같이"):
berm + terrain6.bump_outer (+-15 cm, fades to 0 at the inner terrain), 1 m lattice (was 4 m) with the inner hole
cut per cell, identical bounds (100 x H x 100 m, buried 1 mm markers), 1024 world-continuous PAD bake, analytic
normals, litter under the outer pines, weak mottling.
Headless:  blender.exe -b hwaseong_v25.blend --python rebake_outer6.py
Output:    ovdr_export\hwaseong_v25\_rebatch_out6\HWS_OUT6_ij.fbx + place_out6.json + deltas_out6.json"""
import bpy, bmesh, os, sys, json, io, shutil
import numpy as np
V25 = r"C:\Work\blender\hwaseong_rebuild\v25"
sys.path.insert(0, V25)
import hws_stage3 as S3, hws_export as HX
import rebake_tiles3 as R3, rebake_tiles5 as R5
import terrain6 as T6
from rebake_tiles6 import walk, PROJ

tv = S3.tv; ox, oy, _ = tv['OUTER']; CY = tv['CY']
OX0, OX1, OY0, OY1 = -ox / 2, ox / 2, CY - oy / 2, CY + oy / 2
HOLE = (T6.GX0, T6.GX1, T6.GY0, T6.GY1)
DST = os.path.join(HX.OUT, "_rebatch_out6"); os.makedirs(DST, exist_ok=True)
R5.N = 1024; R5.relief = T6.relief6_outer; R5.DST = DST; R5.BW = 100.0; R5.BH = 100.0
R5.GX0, R5.GX1, R5.GY0, R5.GY1 = OX0, OX1, OY0, OY1          # litter + mottling field cover the ring


def cells(x0, x1, y0, y1):
    return [(i, j) for i in range(round(x1 - x0)) for j in range(round(y1 - y0))
            if not (HOLE[0] < x0 + i + 0.5 < HOLE[1] and HOLE[2] < y0 + j + 0.5 < HOLE[3])]


def build(name, x0, x1, y0, y1, cl, path, rect, zhi):
    hf = R5.relief; bm = bmesh.new(); G = {}
    def V(i, j):
        if (i, j) not in G:
            x, y = x0 + i, y0 + j; G[(i, j)] = bm.verts.new((x, y, hf(x, y)))
        return G[(i, j)]
    for i, j in cl:
        bm.faces.new((V(i, j), V(i + 1, j), V(i + 1, j + 1), V(i, j + 1)))
    top = max(G.values(), key=lambda v: v.co.z)
    R5.micro(bm, x0, y0, R5.ZLO); R5.micro(bm, x0 + R5.BW, y0 + R5.BH, R5.ZLO); R5.micro(bm, top.co.x, top.co.y, zhi)
    bm.loops.layers.uv.new("UVMap")
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    R3.set_uv(o, *rect); R3.analytic_normals(o, hf)
    m = bpy.data.materials.new("M_" + name); m.use_nodes = True
    bs = m.node_tree.nodes["Principled BSDF"]; bs.inputs['Roughness'].default_value = 0.95
    ti = m.node_tree.nodes.new('ShaderNodeTexImage'); ti.image = bpy.data.images.load(path)
    m.node_tree.links.new(ti.outputs['Color'], bs.inputs['Base Color']); me.materials.append(m)
    p = HX.export_one(o, "03_TERRAIN", name, world=True)
    shutil.move(p, os.path.join(DST, os.path.basename(p)))
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    rec = {"tris": sum(len(q.vertices) - 2 for q in me.polygons),
           "position": [round(c[0] * 100 + S3.X0, 1), round(c[2] * 100, 1), round(-c[1] * 100, 1)],
           "size": [round((max(xs) - min(xs)) * 100, 1), round((max(zs) - min(zs)) * 100, 1), round((max(ys) - min(ys)) * 100, 1)]}
    bpy.data.meshes.remove(me)
    return rec


def deltas():
    root = json.loads(io.open(PROJ, "rb").read().decode("utf-16")); out = {}
    for o in walk(root):
        n = o.get("Name", "")
        if not (n.startswith("HWS_지면소품_") or n.startswith("HWS_수목_") or (n.startswith("HWS_") and " " in n)):
            continue
        p = o["CFrame"]["Position"]; d = T6.bump_outer((p["X"] - S3.X0) / 100, -p["Z"] / 100) * 100
        if abs(d) >= 0.5:
            out[o["ActorGuid"]] = round(d, 1)
    json.dump(out, io.open(os.path.join(DST, "deltas_out6.json"), "w", encoding="utf-8"))
    print("@@DELTAS", len(out), "max %.1f min %.1f cm" % (max(out.values(), default=0), min(out.values(), default=0)), flush=True)


def main():
    HX.ensure_dirs(); R5.fill_trees(); fld = R5.build_field(res=1.0)
    zhi = max(T6.relief6_outer(x, y) for x in np.arange(OX0, OX1 + 0.5, 2.0) for y in np.arange(OY0, OY1 + 0.5, 2.0)) + 0.01
    place = {}
    for i in range(round(ox / 100)):
        for j in range(round(oy / 100)):
            x0, y0 = OX0 + 100.0 * i, OY0 + 100.0 * j; x1, y1 = x0 + 100.0, y0 + 100.0
            cl = cells(x0, x1, y0, y1)
            if not cl:
                continue
            name = "HWS_OUT6_%d%d" % (i, j)
            path, rect = R5.bake(name, x0, x1, y0, y1, fld)
            place[name] = build(name, x0, x1, y0, y1, cl, path, rect, zhi)
            print("@@TILE", name, place[name]["tris"], place[name]["size"], flush=True)
    json.dump(place, open(os.path.join(DST, "place_out6.json"), "w"), indent=1)
    deltas()
    print("@@OUTER6 done", DST)

if __name__ == "__main__":
    main()
