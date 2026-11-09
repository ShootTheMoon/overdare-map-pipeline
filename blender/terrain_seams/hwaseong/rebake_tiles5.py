# -*- coding: utf-8 -*-
r"""Inner terrain, round 5 — 4 tiles, seams hidden on road edges, identical bounds, litter + mottling, seam scatter.
Headless:  blender.exe -b hwaseong_v25.blend --python rebake_tiles5.py
Output:    ovdr_export\hwaseong_v25\_rebatch_tiles5\HWS_TER5_{A,B,C,D}.fbx (+ _tex\T_HWS_TER5_*.png, 2048²)
           place5.json (tile position/size), seam_props5.json (ready-to-create clutter items on exposed seams)
Why (2026-09-12): TER3 files are continuous but Studio shades each mesh a little differently (per-mesh sky light),
           so every border reads as a line; TER4's jigsaw border just made the line jagged. Sangok never fixed it —
           its borders are masked by contrasty ground and all its tiles share tall bounds (4–12 m) while ours
           ranged 1 cm..1.1 m. So, all at once:
  1. identical bounds: every tile 104 x (ZHI-ZLO) x 86 m, via 1 mm triangles buried 4.5 m under the ground;
  2. only 2 borders, on the road edges (x = 4 beside the N-S road, y = 16 beside the E-W road) where the ground
     already changes from dirt to grass -> 1,200 m of tile border becomes ~74 m exposed;
  3. seam_props5.json: Sangok fern/grass masters scattered along the exposed ~74 m;
  4. weak world-continuous mottling (+-7 % brightness, 10 % dry tint) + pine-needle litter under the real trees
     (earlier headless bakes had an empty _TREES list, so litter was 0)."""
import bpy, bmesh, os, sys, json, shutil, math, random, io
import numpy as np
from mathutils import Vector, noise
V25 = r"C:\Work\blender\hwaseong_rebuild\v25"
sys.path.insert(0, V25)
import hws_stage3 as S3, hws_export as HX, rebuild
import rebake_tiles3 as R3

tv = S3.tv; relief = S3.relief
DST = os.path.join(HX.OUT, "_rebatch_tiles5"); os.makedirs(DST, exist_ok=True)
N = 2048; PAD = 24; ZLO = -4.5
GX0, GX1 = -tv['SX'] / 2, tv['SX'] / 2; GY0, GY1 = tv['CY'] - tv['SY'] / 2, tv['CY'] + tv['SY'] / 2
XB, YB = 4.0, 16.0                                      # road-edge borders
TILES = [("HWS_TER5_A", GX0, XB, GY0, YB), ("HWS_TER5_B", XB, GX1, GY0, YB),
         ("HWS_TER5_C", GX0, XB, YB, GY1), ("HWS_TER5_D", XB, GX1, YB, GY1)]
BW = max(t[2] - t[1] for t in TILES); BH = max(t[4] - t[3] for t in TILES)
EXPOSED = [((GX0, YB), (-70.0, YB)), ((70.0, YB), (GX1, YB)), ((XB, 66.0), (XB, GY1))]


# ------------------------------------------------------------------ litter from the real trees
def fill_trees():
    tv['_TREES'].clear(); tv['_FERNS'].clear()
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        x, y = o.matrix_world.translation.x, o.matrix_world.translation.y
        if not (GX0 - 8 < x < GX1 + 8 and GY0 - 8 < y < GY1 + 8):
            continue
        if o.name.startswith("수목_"):
            tv['_TREES'].append((x, y, 1.0))
        elif o.name.startswith("지면소품_") and "FERN" in o.data.name.upper():
            tv['_FERNS'].append((x, y))
    print("@@LITTER trees", len(tv['_TREES']), "ferns", len(tv['_FERNS']), flush=True)


# ------------------------------------------------------------------ world mottling field (0.5 m grid, bilinear)
def build_field(res=0.5):
    xs = np.arange(GX0 - 10, GX1 + 10 + res, res); ys = np.arange(GY0 - 10, GY1 + 10 + res, res)
    F = np.empty((len(ys), len(xs), 2), np.float32); fbm, sm = tv['fbm'], tv['smooth']
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            F[j, i, 0] = 0.07 * fbm(x, y, 1 / 20.0, 3, 41.0) + 0.035 * noise.noise(Vector((x / 6.0, y / 6.0, 43.0)))
            F[j, i, 1] = 0.10 * sm((fbm(x, y, 1 / 30.0, 3, 47.0) - 0.1) / 0.3)
    return xs, ys, F, res


def sample(fld, wx, wy):
    xs, ys, F, res = fld
    fx = (wx - xs[0]) / res; fy = (wy - ys[0]) / res
    i0 = np.clip(np.floor(fx).astype(int), 0, len(xs) - 2); j0 = np.clip(np.floor(fy).astype(int), 0, len(ys) - 2)
    tx = (fx - i0)[..., None]; ty = (fy - j0)[..., None]
    return (F[j0, i0] * (1 - tx) * (1 - ty) + F[j0, i0 + 1] * tx * (1 - ty) + F[j0 + 1, i0] * (1 - tx) * ty + F[j0 + 1, i0 + 1] * tx * ty)


# ------------------------------------------------------------------ bake (extended rect so PAD texels = real neighbour ground)
def bake_grid(name, rx0, rx1, ry0, ry1, step=1.0):
    nx, ny = max(1, round((rx1 - rx0) / step)), max(1, round((ry1 - ry0) / step))
    bm = bmesh.new()
    G = [[bm.verts.new((rx0 + (rx1 - rx0) * i / nx, ry0 + (ry1 - ry0) * j / ny, 0.0)) for j in range(ny + 1)] for i in range(nx + 1)]
    for row in G:
        for v in row:
            v.co.z = relief(v.co.x, v.co.y)
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((G[i][j], G[i + 1][j], G[i + 1][j + 1], G[i][j + 1]))
    bm.loops.layers.uv.new("UVMap")
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ca = me.color_attributes.new("Blend", 'FLOAT_COLOR', 'POINT'); cols = []
    for v in me.vertices:
        x, y, z = v.co
        cols += [tv['dirt'](x, y), tv['rock'](x, y, z), tv['wet'](x, y, z), tv['litter'](x, y)]
    ca.data.foreach_set("color", cols)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    R3.set_uv(o, rx0, rx1, ry0, ry1)
    return o


def bake(name, x0, x1, y0, y1, fld):
    ex, ey = PAD * (x1 - x0) / (N - 2 * PAD), PAD * (y1 - y0) / (N - 2 * PAD)
    rx0, rx1, ry0, ry1 = x0 - ex, x1 + ex, y0 - ey, y1 + ey
    bo = bake_grid(name + "_BK", rx0, rx1, ry0, ry1)
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
    px = np.empty(N * N * 4, np.float32); img.pixels.foreach_get(px); px = px.reshape(N, N, 4)
    wx = rx0 + (np.arange(N) + 0.5) / N * (rx1 - rx0); wy = ry0 + (np.arange(N) + 0.5) / N * (ry1 - ry0)
    WX, WY = np.meshgrid(wx, wy)                                    # rows = v = y
    m = sample(fld, WX, WY); b, tt = m[..., 0:1], m[..., 1:2]
    rgb = px[..., :3] * (1 + b); rgb = rgb * (1 + tt * (np.array([1.10, 1.02, 0.80], np.float32) - 1))
    px[..., :3] = np.clip(rgb, 0, 1); img.pixels.foreach_set(px.ravel())
    path = os.path.join(HX.TEXOUT, "T_" + name + ".png"); img.filepath_raw = path; img.file_format = 'PNG'; img.save()
    bpy.data.images.remove(img); bpy.data.materials.remove(mat); bpy.data.meshes.remove(bo.data)
    return path, (rx0, rx1, ry0, ry1)


# ------------------------------------------------------------------ export mesh: 1 m lattice cells + buried bound markers
def micro(bm, x, y, z):
    a = bm.verts.new((x, y, z)); b = bm.verts.new((x + 0.001, y, z)); c = bm.verts.new((x, y + 0.001, z)); bm.faces.new((a, b, c))


def build(name, x0, x1, y0, y1, path, rect, zhi):
    nx, ny = round(x1 - x0), round(y1 - y0); cx, cy = (x1 - x0) / nx, (y1 - y0) / ny
    bm = bmesh.new(); G = {}
    def V(i, j):
        if (i, j) not in G:
            x, y = x0 + i * cx, y0 + j * cy; G[(i, j)] = bm.verts.new((x, y, relief(x, y)))
        return G[(i, j)]
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((V(i, j), V(i + 1, j), V(i + 1, j + 1), V(i, j + 1)))
    top = max(G.values(), key=lambda v: v.co.z)
    micro(bm, x0, y0, ZLO); micro(bm, x0 + BW, y0 + BH, ZLO); micro(bm, top.co.x, top.co.y, zhi)
    bm.loops.layers.uv.new("UVMap")
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    R3.set_uv(o, *rect); R3.analytic_normals(o, relief)
    m = bpy.data.materials.new("M_" + name); m.use_nodes = True
    bs = m.node_tree.nodes["Principled BSDF"]; bs.inputs['Roughness'].default_value = 0.95
    ti = m.node_tree.nodes.new('ShaderNodeTexImage'); ti.image = bpy.data.images.load(path)
    m.node_tree.links.new(ti.outputs['Color'], bs.inputs['Base Color']); me.materials.append(m)
    p = HX.export_one(o, "03_TERRAIN", name, world=True)
    shutil.move(p, os.path.join(DST, os.path.basename(p)))
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    rec = {"tris": sum(len(p.vertices) - 2 for p in me.polygons),
           "position": [round(c[0] * 100 + S3.X0, 1), round(c[2] * 100, 1), round(-c[1] * 100, 1)],
           "size": [round((max(xs) - min(xs)) * 100, 1), round((max(zs) - min(zs)) * 100, 1), round((max(ys) - min(ys)) * 100, 1)]}
    bpy.data.meshes.remove(me)
    return rec


# ------------------------------------------------------------------ seam clutter (Sangok small-plant masters, existing asset ids)
def seam_props():
    import glob
    items = [i for f in glob.glob(os.path.join(HX.OUT, "_place", "place_*.json")) for i in json.load(io.open(f, encoding="utf-8"))]
    tm = {}
    for it in items:
        if not it["name"].startswith(("HWS_지면소품_FERN", "HWS_지면소품_EULALIA", "HWS_지면소품_ARTEMISIA")):
            continue                                                 # small plants only (no boulders / stumps / trunks)
        p = it["props"]
        X, Y, Z = p["position"]; x, y = (X - S3.X0) / 100, -Z / 100
        tm.setdefault(p["meshId"], []).append((Y - relief(x, y) * 100, p))
    tpl = []
    for mid, v in tm.items():
        offs = sorted(o for o, _ in v); tpl.append((offs[len(offs) // 2], v[0][1], len(v)))
    print("@@SEAM templates", [(t[1]["meshId"][-8:], round(t[0], 1), t[1]["size"], t[2]) for t in tpl], flush=True)
    rnd = random.Random(2512); out = []
    wts = [t[2] for t in tpl]
    for (ax, ay), (bx, by) in EXPOSED:
        L = math.hypot(bx - ax, by - ay); ux, uy = (bx - ax) / L, (by - ay) / L
        k = 0.0
        while k < L:
            for side in (-1, 1):
                d = side * rnd.uniform(0.1, 1.1); s = rnd.uniform(0.85, 1.3)
                x = ax + ux * (k + rnd.uniform(-0.4, 0.4)) - uy * d; y = ay + uy * (k + rnd.uniform(-0.4, 0.4)) + ux * d
                off, p, _ = rnd.choices(tpl, weights=wts)[0]
                q = json.loads(json.dumps(p))
                q["size"] = [round(v * s, 1) for v in p["size"]]
                q["position"] = [round(x * 100 + S3.X0, 1), round(relief(x, y) * 100 + off * s, 1), round(-y * 100, 1)]
                o = p.get("orientation", [0, 0, 0]); q["orientation"] = [o[0], round(rnd.uniform(-180, 180), 1), o[2]]
                out.append({"className": "MeshPart", "name": "HWS_지면소품_seam_%03d" % len(out), "props": q})
            k += 1.1
    json.dump(out, io.open(os.path.join(DST, "seam_props5.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("@@SEAM props", len(out), flush=True)


def seam_check():
    def load(k):
        im = bpy.data.images.load(os.path.join(HX.TEXOUT, "T_%s.png" % k)); a = np.empty(N * N * 4, np.float32)
        im.pixels.foreach_get(a); bpy.data.images.remove(im); return a.reshape(N, N, 4)[:, :, :3]
    A, B, C = load("HWS_TER5_A"), load("HWS_TER5_B"), load("HWS_TER5_C")
    e = N - PAD
    print("@@SEAM dRGB A|B (x=4) %.2f   A|C (y=16) %.2f" % (np.abs(A[:, e - 1] - B[:, PAD - 1]).mean() * 255, np.abs(A[e - 1, :] - C[PAD - 1, :]).mean() * 255))


def main():
    HX.ensure_dirs(); fill_trees(); fld = build_field()
    zhi = max(relief(x, y) for x in np.arange(GX0, GX1 + 0.5, 1.0) for y in np.arange(GY0, GY1 + 0.5, 1.0)) + 0.01
    place = {}
    for name, x0, x1, y0, y1 in TILES:
        path, rect = bake(name, x0, x1, y0, y1, fld)
        place[name] = build(name, x0, x1, y0, y1, path, rect, zhi)
        print("@@TILE", name, place[name], flush=True)
    json.dump(place, open(os.path.join(DST, "place5.json"), "w"), indent=1)
    seam_check(); seam_props()
    print("@@REBAKE5 done", DST)

if __name__ == "__main__":
    main()
