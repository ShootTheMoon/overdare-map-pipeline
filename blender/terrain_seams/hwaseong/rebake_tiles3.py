# -*- coding: utf-8 -*-
"""Terrain tiles, round 3 — port of the Sangok seam fixes (sgk_texbake / sgk_export.export_terrain).
Headless:  blender.exe -b hwaseong_v25.blend --python rebake_tiles3.py
Output:    ovdr_export\hwaseong_v25\_rebatch_tiles3\HWS_TER3_ij.fbx / HWS_OUT3_ij.fbx (+ _tex\T_HWS_*3_ij.png)
Why:       TER2 (wider pad) is live and the tile lines are still there. Two causes remained:
           1) bake margin EXTEND smears the edge texel, it is not the neighbour's ground -> bake an extended rect
              (M_HWS_Terrain samples Object coords + world vertex fields, object at origin = world-continuous),
              so the PAD texels outside the tile are the real neighbouring ground;
           2) normals came from each tile's own faces, border vertices see half their neighbours -> shading step.
              Use the analytic slope of relief()/berm() so both tiles agree to the bit."""
import bpy, os, sys, json, shutil
import numpy as np
V25 = r"C:\Work\blender\hwaseong_rebuild\v25"
sys.path.insert(0, V25)
import hws_stage3 as S3, hws_export as HX, rebuild

N = 1024
PAD = 24                                   # texels of real neighbour ground on each side
DST = os.path.join(HX.OUT, "_rebatch_tiles3"); os.makedirs(DST, exist_ok=True)


def ext(w):
    return PAD * w / (N - 2 * PAD)         # metres of world outside the tile that land in the PAD texels


def set_uv(o, rx0, rx1, ry0, ry1):
    me = o.data; uv = me.uv_layers["UVMap"]
    for poly in me.polygons:
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x - rx0) / (rx1 - rx0), (v.y - ry0) / (ry1 - ry0))


def analytic_normals(o, hf, e=0.25):
    from mathutils import Vector
    me = o.data; vn = []
    for v in me.vertices:
        x, y = v.co.x, v.co.y
        hx = (hf(x + e, y) - hf(x - e, y)) / (2 * e); hy = (hf(x, y + e) - hf(x, y - e)) / (2 * e)
        vn.append(Vector((-hx, -hy, 1.0)).normalized())
    for p in me.polygons:
        p.use_smooth = True
    me.normals_split_custom_set_from_vertices(vn)


def bake(name, x0, x1, y0, y1, cell, hf, hole):
    ex, ey = ext(x1 - x0), ext(y1 - y0)
    rx0, rx1, ry0, ry1 = x0 - ex, x1 + ex, y0 - ey, y1 + ey
    cx = (rx1 - rx0) / max(1, round((rx1 - rx0) / cell))       # grid that ends exactly on the extended rect
    bo = S3.tile_mesh(name + "_BK", rx0, rx1, ry0, ry1, cx, hf, hole)
    set_uv(bo, rx0, rx1, ry0, ry1)
    sc = bpy.context.scene; sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 1
    mat = bpy.data.materials["M_HWS_Terrain"].copy(); mat.name = "BAKE_" + name
    bo.data.materials.append(mat); nt = mat.node_tree
    img = bpy.data.images.new("_bake_" + name, N, N, alpha=False)
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = img; nt.nodes.active = t
    for n in nt.nodes:
        n.select = (n == t)
    sc.render.bake.margin_type = 'EXTEND'
    with bpy.context.temp_override(**rebuild._sel([bo], bo)):
        bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, margin=4, use_clear=True)
    path = os.path.join(HX.TEXOUT, "T_" + name + ".png"); img.filepath_raw = path; img.file_format = 'PNG'; img.save()
    bpy.data.images.remove(img); bpy.data.materials.remove(mat); bpy.data.meshes.remove(bo.data)
    return path, (rx0, rx1, ry0, ry1)


def build(name, x0, x1, y0, y1, cell, hf, hole, path, rect):
    o = S3.tile_mesh(name, x0, x1, y0, y1, cell, hf, hole)
    set_uv(o, *rect)
    analytic_normals(o, hf)
    m = bpy.data.materials.new("M_" + name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs['Roughness'].default_value = 0.95
    ti = m.node_tree.nodes.new('ShaderNodeTexImage'); ti.image = bpy.data.images.load(path)
    m.node_tree.links.new(ti.outputs['Color'], b.inputs['Base Color'])
    o.data.materials.clear(); o.data.materials.append(m)
    p = HX.export_one(o, "03_TERRAIN", name, world=True)
    shutil.move(p, os.path.join(DST, os.path.basename(p)))
    bpy.data.meshes.remove(o.data)


def seam_check(names_ij):
    """Mean |dRGB| (0-255) across every inner vertical/horizontal tile border, sampled at the border world line."""
    def load(k):
        im = bpy.data.images.load(os.path.join(HX.TEXOUT, "T_%s.png" % k)); a = np.empty(N * N * 4, np.float32)
        im.pixels.foreach_get(a); bpy.data.images.remove(im); return a.reshape(N, N, 4)[:, :, :3]
    out = []
    for (i, j) in names_ij:
        a = load("HWS_TER3_%d%d" % (i, j))
        for di, dj in ((1, 0), (0, 1)):
            if (i + di, j + dj) not in names_ij:
                continue
            b = load("HWS_TER3_%d%d" % (i + di, j + dj))
            e = N - PAD                                  # border line = texel N-PAD in a, texel PAD in b
            d = np.abs(a[:, e - 1] - b[:, PAD - 1]).mean() if di else np.abs(a[e - 1, :] - b[PAD - 1, :]).mean()
            out.append(round(float(d) * 255, 2))
    return out


def main():
    tv = S3.tv; SX, SY, CY = tv['SX'], tv['SY'], tv['CY']; ox, oy, _ = tv['OUTER']
    tiles = []
    xs = [-SX / 2 + 40.0 * i for i in range(5)]; ys = [CY - SY / 2 + 40.0 * j for j in range(4)]
    for i, x0 in enumerate(xs):
        for j, y0 in enumerate(ys):
            tiles.append(("HWS_TER3_%d%d" % (i, j), x0, min(x0 + 40.0, SX / 2), y0, min(y0 + 40.0, CY + SY / 2), 1.0, S3.relief, None))
    hole = (-SX / 2 - 0.01, SX / 2 + 0.01, CY - SY / 2 - 0.01, CY + SY / 2 + 0.01)
    oxs = [-ox / 2 + 100.0 * i for i in range(4)]; oys = [CY - oy / 2 + 100.0 * j for j in range(3)]
    for i, x0 in enumerate(oxs):
        for j, y0 in enumerate(oys):
            tiles.append(("HWS_OUT3_%d%d" % (i, j), x0, x0 + 100.0, y0, y0 + 100.0, 4.0, S3.berm, hole))
    HX.ensure_dirs(); done = []
    for name, x0, x1, y0, y1, cell, hf, hl in tiles:
        probe = S3.tile_mesh(name + "_P", x0, x1, y0, y1, cell, hf, hl)     # outer tiles fully inside the hole -> skip
        if not probe:
            continue
        bpy.data.meshes.remove(probe.data)
        path, rect = bake(name, x0, x1, y0, y1, cell, hf, hl)
        build(name, x0, x1, y0, y1, cell, hf, hl, path, rect)
        done.append(name); print("@@TILE", name, flush=True)
    json.dump(done, open(os.path.join(DST, "tiles.json"), "w"))
    ij = {(int(n[-2]), int(n[-1])) for n in done if n.startswith("HWS_TER3_")}
    print("@@SEAM dRGB", seam_check(ij))
    print("@@REBAKE3 done", len(done), DST)

if __name__ == "__main__":
    main()
