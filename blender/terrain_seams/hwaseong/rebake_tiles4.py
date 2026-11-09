# -*- coding: utf-8 -*-
r"""Inner terrain tiles, round 4 — tangled (jigsaw) borders.
Headless:  blender.exe -b hwaseong_v25.blend --python rebake_tiles4.py
Output:    ovdr_export\hwaseong_v25\_rebatch_tiles4\HWS_TER4_ij.fbx (+ _tex\T_HWS_TER4_ij.png) + place4.json
Why:       TER3 made the files continuous (texture + analytic normals) and the line is still visible: Studio shades
           each mesh a little differently (per-mesh sky light), so a STRAIGHT 40 m border always reads as a line.
           Here every 1 m cell picks its tile through a noise-warped + per-cell-jittered lookup, so the border is a
           ragged, interleaved band (up to ~7 m wide) instead of a line. Shared vertices keep identical position/height/
           normal -> no cracks. Tiles grow past 40 m, so position/size change -> place4.json."""
import bpy, bmesh, os, sys, json, shutil, math, random
from mathutils import Vector, noise
V25 = r"C:\Work\blender\hwaseong_rebuild\v25"
sys.path.insert(0, V25)
import hws_stage3 as S3, hws_export as HX
import rebake_tiles3 as R3          # bake() / analytic_normals() / set_uv(); its main() runs only under __main__ guard below

DST = os.path.join(HX.OUT, "_rebatch_tiles4"); os.makedirs(DST, exist_ok=True)
T = 40.0
A1, F1, A2, F2, JIT = 4.0, 12.0, 1.5, 4.0, 1.5      # meander amp/period, detail amp/period, per-cell jitter (m)


def owner(cx, cy, k, gx0, gy0, NI, NJ):
    dx = noise.noise(Vector((cx / F1, cy / F1, 0.37))) * A1 + noise.noise(Vector((cx / F2, cy / F2, 5.1))) * A2
    dy = noise.noise(Vector((cx / F1, cy / F1, 9.73))) * A1 + noise.noise(Vector((cx / F2, cy / F2, 13.3))) * A2
    r = random.Random(k * 7919 + 13)
    wx = cx + dx + (r.random() * 2 - 1) * JIT; wy = cy + dy + (r.random() * 2 - 1) * JIT
    return min(NI - 1, max(0, int(math.floor((wx - gx0) / T)))), min(NJ - 1, max(0, int(math.floor((wy - gy0) / T))))


def main():
    tv = S3.tv; SX, SY, CY = tv['SX'], tv['SY'], tv['CY']
    gx0, gy0 = -SX / 2, CY - SY / 2
    nx, ny = int(round(SX)), int(round(SY)); cx_, cy_ = SX / nx, SY / ny
    NI, NJ = int(math.ceil(SX / T - 1e-6)), int(math.ceil(SY / T - 1e-6))
    cells = {}
    for a in range(nx):
        for b in range(ny):
            cx, cy = gx0 + (a + 0.5) * cx_, gy0 + (b + 0.5) * cy_
            cells.setdefault(owner(cx, cy, a * 100003 + b, gx0, gy0, NI, NJ), []).append((a, b))
    HX.ensure_dirs(); place = {}
    for (i, j), cl in sorted(cells.items()):
        name = "HWS_TER4_%d%d" % (i, j)
        bm = bmesh.new(); vm = {}
        def V(a, b):
            if (a, b) not in vm:
                x, y = gx0 + a * cx_, gy0 + b * cy_; vm[(a, b)] = bm.verts.new((x, y, S3.relief(x, y)))
            return vm[(a, b)]
        for a, b in cl:
            bm.faces.new((V(a, b), V(a + 1, b), V(a + 1, b + 1), V(a, b + 1)))
        bm.loops.layers.uv.new("UVMap")
        me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
        o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
        xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        path, rect = R3.bake(name, x0, x1, y0, y1, 1.0, S3.relief, None)
        R3.set_uv(o, *rect); R3.analytic_normals(o, S3.relief)
        m = bpy.data.materials.new("M_" + name); m.use_nodes = True
        bs = m.node_tree.nodes["Principled BSDF"]; bs.inputs['Roughness'].default_value = 0.95
        ti = m.node_tree.nodes.new('ShaderNodeTexImage'); ti.image = bpy.data.images.load(path)
        m.node_tree.links.new(ti.outputs['Color'], bs.inputs['Base Color']); me.materials.append(m)
        p = HX.export_one(o, "03_TERRAIN", name, world=True)
        shutil.move(p, os.path.join(DST, os.path.basename(p)))
        c = ((x0 + x1) / 2, (y0 + y1) / 2, (min(zs) + max(zs)) / 2)
        place[name] = {"old": "HWS_TER_%d%d" % (i, j), "cells": len(cl),
                       "position": [round(c[0] * 100 + S3.X0, 1), round(c[2] * 100, 1), round(-c[1] * 100, 1)],
                       "size": [round((x1 - x0) * 100, 1), round((max(zs) - min(zs)) * 100, 1), round((y1 - y0) * 100, 1)]}
        bpy.data.meshes.remove(me); print("@@TILE", name, len(cl), place[name]["size"], flush=True)
    json.dump(place, open(os.path.join(DST, "place4.json"), "w"), indent=1)
    print("@@REBAKE4 done", len(place), DST)

main()
