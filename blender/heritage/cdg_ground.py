# -*- coding: utf-8 -*-
"""
CDG - stage 5: terrain, bakseok courtyard paving, eodo and the palace wall.

Design notes
------------
* Terrain height is NOT a hand-authored guess. Every placed building already knows
  the height its base sits at, so the ground is an inverse-distance-weighted field
  through those measured base heights. The terrain therefore meets each building
  exactly, and Changdeokgung's real south-to-north rise falls out of the data
  (Injeongmun court 0.0 m -> Injeongjeon 1.2 -> Seonwonjeon compound 2.6 ->
  Uipunggak 4.0).
* The courtyard paving is fitted to ACTUAL FREE SPACE, not to an assumed rectangle.
  The corridor assets are L-shaped (haenggak + wollang), so a rectangle guessed from
  their bounding boxes would have run paving straight through the buildings. Instead
  every building footprint is rasterized and slabs are emitted only on empty cells.
* All materials reuse textures from the shared KHS _TexLib, so the built kit has the
  same surface identity as the scanned buildings - the single biggest quality lever
  on a mixed scanned/authored map.

blender.exe --background --factory-startup --python cdg_ground.py
"""
import json
import math
import os
import random

import bpy
from mathutils import Vector

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
MASTER = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master.blend")
OUT = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master.blend")
TEXLIB = os.path.join(ROOT, "_extracted", "_TexLib")
REPORT = os.path.join(ROOT, "_extracted", "GROUND_REPORT.json")

random.seed(20260811)          # deterministic: reruns must not reshuffle the paving

CELL = 0.75                    # occupancy raster for free-space detection
TERRAIN_STEP = 4.0
MARGIN = 18.0
YCUT = 52.0          # north spur begins here (Seonwonjeon / Uipunggak compounds)
SLAB = 1.55                    # bakseok slab pitch
SLAB_GAP = 0.085

# courtyards to pave: (name, x0, x1, y0, y1, material)
COURTS = [
    ("Jojeong",     -30.0,  40.0, -60.0, -22.0, "bakseok"),   # Injeongjeon main court
    ("Injeongmun",  -52.0,  52.0, -106.0, -66.0, "bakseok"),  # Jinseonmun forecourt
    ("Seonwonjeon", -92.0, -50.0,  -3.0,  30.0, "bakseok"),   # Seonwonjeon compound
]

# eodo: the raised royal road up the middle of the Jojeong
EODO = dict(x=3.0, y0=-59.0, y1=-24.0, width=4.6, rise=0.14, border=0.55)


def tex(name):
    p = os.path.join(TEXLIB, name)
    return p if os.path.exists(p) else None


def make_mat(name, image, tile=4.0, rough=0.85):
    """Plain TEX_IMAGE -> Principled.Base Color -> Output. Nothing else: FBX exports
    only an image wired DIRECTLY to Base Color, and any Mix/HueSaturation chain in
    between silently exports untextured."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (200, 0)
    bsdf.inputs["Roughness"].default_value = rough
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    p = tex(image)
    if p:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.location = (-150, 0)
        t.image = bpy.data.images.load(p, check_existing=True)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (0.55, 0.53, 0.5, 1.0)
    m["uv_tile"] = tile
    return m


def new_obj(name, verts, faces, uvs, mat, coll):
    me = bpy.data.meshes.new("ME_" + name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.materials.append(mat)
    lay = me.uv_layers.new(name="UVMap")
    flat = []
    for uv in uvs:
        flat += [uv[0], uv[1]]
    if len(flat) == len(me.loops) * 2:
        lay.uv.foreach_set("vector", flat)
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    me.shade_flat()
    return o


# ------------------------------------------------------------------ measurement
def building_objects():
    return [o for o in bpy.data.objects
            if o.type == "MESH" and o.name.startswith("SM_CDG_")]


def anchors():
    """(x, y, base_z) per asset, from the placed geometry."""
    agg = {}
    for o in building_objects():
        key = o.name.split("_")[2]
        b = agg.setdefault(key, [1e18, 1e18, 1e18, -1e18, -1e18])
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            b[0] = min(b[0], w.x)
            b[1] = min(b[1], w.y)
            b[2] = min(b[2], w.z)
            b[3] = max(b[3], w.x)
            b[4] = max(b[4], w.y)
    return [((b[0] + b[3]) * 0.5, (b[1] + b[4]) * 0.5, b[2]) for b in agg.values()]


def occupancy():
    """Set of occupied XY cells, from every building vertex."""
    occ = set()
    for o in building_objects():
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            occ.add((int(math.floor(w.x / CELL)), int(math.floor(w.y / CELL))))
    return occ


def dilate(occ, r=2):
    out = set()
    for (x, y) in occ:
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                out.add((x + dx, y + dy))
    return out


def _smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def height_fn(pts, power=2.2, smooth=9.0, hills=True):
    """Inverse-distance weighting through the measured building base heights, plus
    terrain relief OUTSIDE the built area.

    Changdeokgung is a valley palace backed by Eungbong to the north, so a flat plate
    reads wrong and, for an FPS, gives no sightline blocking at all. The rise is keyed
    to distance from the nearest building so it is exactly zero under every structure
    and the courtyards stay dead flat."""
    def h(x, y):
        num = den = 0.0
        dmin = 1e18
        for (px, py, pz) in pts:
            dx, dy = x - px, y - py
            d2 = dx * dx + dy * dy
            if d2 < dmin:
                dmin = d2
            w = 1.0 / (d2 + smooth ** 2) ** (power * 0.5)
            num += w * pz
            den += w
        z = num / den
        if hills:
            d = dmin ** 0.5
            z += _smooth((d - 88.0) / 105.0) * 11.0             # ridge, kept well beyond the wall
            z += _smooth((y - 95.0) / 110.0) * _smooth((d - 55.0) / 70.0) * 14.0  # north hill (Eungbong)
        return z
    return h


# ---------------------------------------------------------------------- builders
def build_terrain(h, x0, x1, y0, y1, mat, coll):
    nx = int((x1 - x0) / TERRAIN_STEP) + 1
    ny = int((y1 - y0) / TERRAIN_STEP) + 1
    verts = []
    for j in range(ny):
        for i in range(nx):
            x = x0 + i * TERRAIN_STEP
            y = y0 + j * TERRAIN_STEP
            verts.append((x, y, h(x, y) - 0.06))
    faces, uvs = [], []
    tile = mat["uv_tile"]
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            f = (a, a + 1, a + nx + 1, a + nx)
            faces.append(f)
            for vi in f:
                vx, vy = verts[vi][0], verts[vi][1]
                uvs.append((vx / tile, vy / tile))
    return new_obj("MOD_Terrain", verts, faces, uvs, mat, coll)


def build_paving(name, h, occ, x0, x1, y0, y1, mat, coll):
    """Jittered granite slabs on free cells only."""
    tile = mat["uv_tile"]
    verts, faces, uvs = [], [], []
    n = 0
    pitch = SLAB
    ny = int((y1 - y0) / pitch)
    nx = int((x1 - x0) / pitch)
    for j in range(ny):
        for i in range(nx):
            cx = x0 + (i + 0.5) * pitch
            cy = y0 + (j + 0.5) * pitch
            cell = (int(math.floor(cx / CELL)), int(math.floor(cy / CELL)))
            if cell in occ:
                continue
            hw = (pitch - SLAB_GAP) * 0.5 * random.uniform(0.88, 1.0)
            hh = (pitch - SLAB_GAP) * 0.5 * random.uniform(0.88, 1.0)
            a = random.uniform(-0.13, 0.13)
            ca, sa = math.cos(a), math.sin(a)
            z = h(cx, cy) + random.uniform(-0.012, 0.022)
            base = len(verts)
            corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
            for (lx, ly) in corners:
                verts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca, z))
            faces.append((base, base + 1, base + 2, base + 3))
            u0 = random.random()
            v0 = random.random()
            s = pitch / tile
            for (uu, vv) in ((0, 0), (1, 0), (1, 1), (0, 1)):
                uvs.append((u0 + uu * s, v0 + vv * s))
            n += 1
    if not n:
        return None, 0
    o = new_obj("MOD_Paving_Bakseok_" + name, verts, faces, uvs, mat, coll)
    return o, n


def build_eodo(h, mat, coll):
    """Raised three-lane royal road, Injeongmun -> Injeongjeon woldae."""
    tile = mat["uv_tile"]
    verts, faces, uvs = [], [], []
    lanes = [(-EODO["width"] * 0.5 - EODO["border"], -EODO["width"] * 0.5),
             (-EODO["width"] * 0.5, EODO["width"] * 0.5),
             (EODO["width"] * 0.5, EODO["width"] * 0.5 + EODO["border"])]
    steps = 26
    for (la, lb) in lanes:
        for s in range(steps):
            ya = EODO["y0"] + (EODO["y1"] - EODO["y0"]) * s / steps
            yb = EODO["y0"] + (EODO["y1"] - EODO["y0"]) * (s + 1) / steps
            base = len(verts)
            for (xx, yy) in ((EODO["x"] + la, ya), (EODO["x"] + lb, ya),
                             (EODO["x"] + lb, yb), (EODO["x"] + la, yb)):
                verts.append((xx, yy, h(xx, yy) + EODO["rise"]))
            faces.append((base, base + 1, base + 2, base + 3))
            for vi in range(base, base + 4):
                uvs.append((verts[vi][0] / tile, verts[vi][1] / tile))
    return new_obj("MOD_Eodo", verts, faces, uvs, mat, coll)


def build_wall(h, loop, mat_body, mat_cap, coll, height=3.1, thick=0.95):
    """Palace wall (gungjang) along a polyline: stone body + tile coping."""
    def strip(mat, z0f, z1f, tag):
        tile = mat["uv_tile"]
        verts, faces, uvs = [], [], []
        run = 0.0
        for i in range(len(loop) - 1):
            x1, y1 = loop[i]
            x2, y2 = loop[i + 1]
            seg = math.hypot(x2 - x1, y2 - y1)
            n = max(1, int(seg / 3.0))
            for s in range(n):
                ax = x1 + (x2 - x1) * s / n
                ay = y1 + (y2 - y1) * s / n
                bx = x1 + (x2 - x1) * (s + 1) / n
                by = y1 + (y2 - y1) * (s + 1) / n
                dx, dy = bx - ax, by - ay
                L = math.hypot(dx, dy) or 1.0
                px, py = -dy / L * thick * 0.5, dx / L * thick * 0.5
                ha, hb = h(ax, ay), h(bx, by)
                for sgn in (1, -1):
                    base = len(verts)
                    verts.append((ax + px * sgn, ay + py * sgn, ha + z0f))
                    verts.append((bx + px * sgn, by + py * sgn, hb + z0f))
                    verts.append((bx + px * sgn, by + py * sgn, hb + z1f))
                    verts.append((ax + px * sgn, ay + py * sgn, ha + z1f))
                    faces.append((base, base + 1, base + 2, base + 3))
                    for (uu, vv) in ((0, 0), (L / tile, 0),
                                     (L / tile, (z1f - z0f) / tile), (0, (z1f - z0f) / tile)):
                        uvs.append((run / tile + uu, vv))
                # cap the top
                base = len(verts)
                verts.append((ax + px, ay + py, ha + z1f))
                verts.append((bx + px, by + py, hb + z1f))
                verts.append((bx - px, by - py, hb + z1f))
                verts.append((ax - px, ay - py, ha + z1f))
                faces.append((base, base + 1, base + 2, base + 3))
                for (uu, vv) in ((0, 0), (L / tile, 0), (L / tile, thick / tile), (0, thick / tile)):
                    uvs.append((run / tile + uu, vv))
                run += L
        return new_obj("MOD_PalaceWall_" + tag, verts, faces, uvs, mat, coll)

    body = strip(mat_body, -0.25, height, "Body")
    cap = strip(mat_cap, height, height + 0.55, "Coping")
    return [body, cap]



# ------------------------------------------------------------------------ trees
TREE_BLEND = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_TreeAssets.blend")


def load_tree_masters():
    """Append the Sketchfab pine once; every placed tree is a LINKED DUPLICATE of it.

    The model is 2,640 tris (72-tri trunk + 2,568-tri alpha-carded foliage). Placing
    2,000 of them as real geometry would be 5.3 M triangles on a map that is already
    6.6 M. As linked duplicates the scene carries ONE copy of the mesh, and that is
    also exactly how it ships: OVERDARE imports one tree MeshPart and clones it, so
    the export cost is 2,640 triangles no matter how many trees stand in the map.

    Replaces the procedural cones-on-a-stick I wrote first, which the user correctly
    called too low quality.
    "Pine Tree - Low Poly Stylized Tree" by Jimmy_Johansson, CC BY 4.0 - see
    OfficialSource/04_Attribution/ATTRIBUTION.txt
    """
    names = ["TREE_Pine_Trunk", "TREE_Pine_Foliage"]
    have = [n for n in names if n in bpy.data.objects]
    if len(have) == len(names):
        return [bpy.data.objects[n] for n in names]
    with bpy.data.libraries.load(TREE_BLEND, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n in names]
    out = []
    for o in bpy.data.objects:
        if o.name in names and o.name not in [x.name for x in out]:
            out.append(o)
    for o in out:
        if o.name not in bpy.context.scene.collection.objects:
            try:
                bpy.context.scene.collection.objects.link(o)
            except RuntimeError:
                pass
    return out


def build_trees(h, occ, x0, x1, y0, y1, coll, anchors_xy):
    """Scatter linked instances of the pine master. Density rises with distance from
    the buildings and the courtyards stay clear - the Jojeong is historically bare
    bakseok, so trees there would be wrong as well as bad for the sightlines."""
    random.seed(414)
    masters = load_tree_masters()
    if not masters:
        print("  !! tree masters not found in", TREE_BLEND)
        return [], 0, []
    for m in masters:
        m.hide_render = True
        m.hide_viewport = True

    step = 7.5
    placed = []
    ny = int((y1 - y0) / step)
    nx = int((x1 - x0) / step)
    for j in range(ny):
        for i in range(nx):
            cx = x0 + (i + 0.5) * step + random.uniform(-3.4, 3.4)
            cy = y0 + (j + 0.5) * step + random.uniform(-3.4, 3.4)
            if (int(math.floor(cx / CELL)), int(math.floor(cy / CELL))) in occ:
                continue
            skip = False
            for (_n, ax0, ax1, ay0, ay1, _m) in COURTS:
                if ax0 - 4 < cx < ax1 + 4 and ay0 - 4 < cy < ay1 + 4:
                    skip = True
                    break
            if skip:
                continue
            d = min(math.hypot(cx - px, cy - py) for (px, py) in anchors_xy)
            if d < 14.0:
                continue
            clump = 0.5 + 0.5 * math.sin(cx * 0.055) * math.cos(cy * 0.047)
            p = (0.07 + 0.55 * _smooth((d - 16.0) / 60.0)) * (0.45 + 0.9 * clump)
            if random.random() > p:
                continue
            placed.append((cx, cy, h(cx, cy),
                           random.uniform(0.62, 1.28),
                           random.uniform(0, math.tau)))

    objs = []
    for (cx, cy, cz, sc, rot) in placed:
        for m in masters:
            o = bpy.data.objects.new(m.name.replace("TREE_", "SM_CDG_Tree_"), m.data)
            coll.objects.link(o)
            o.location = (cx, cy, cz - 0.15)
            o.rotation_euler = (0.0, 0.0, rot)
            o.scale = (sc, sc, sc)
            objs.append(o)
    return objs, len(placed), placed

def main():
    bpy.ops.wm.open_mainfile(filepath=MASTER)

    # wipe any previous ground pass so reruns are idempotent
    old = bpy.data.collections.get("30_GROUND")
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new("30_GROUND")
    bpy.context.scene.collection.children.link(coll)

    pts = anchors()
    h = height_fn(pts)
    occ = dilate(occupancy(), r=2)
    print("  anchors %d   occupied cells %d" % (len(pts), len(occ)))

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    # terrain must extend well past the wall so the hills have room to rise
    x0, x1 = min(xs) - 155, max(xs) + 155
    y0, y1 = min(ys) - 155, max(ys) + 155

    # T_Ground02A is moss/grass (avg RGB 122,129,52) and made the palace read as a golf
    # course. T_Ground01A (190,152,120) is the packed-earth/masato tone the courtyards
    # actually have.
    m_ground = make_mat("MAT_CDG_Ground", "T_Ground01A_BC.png", tile=5.0)
    m_slab = make_mat("MAT_CDG_Bakseok", "T_Stone01A_BC.png", tile=3.0)
    m_eodo = make_mat("MAT_CDG_Eodo", "T_Stone01B_BC.png", tile=3.0)
    m_wallb = make_mat("MAT_CDG_WallBody", "T_StoneWall01A_BC.png", tile=3.0)
    m_wallc = make_mat("MAT_CDG_WallCap", "T_Giwa_BC.png", tile=2.0)

    made = {}
    t = build_terrain(h, x0, x1, y0, y1, m_ground, coll)
    made["terrain"] = len(t.data.polygons)

    total_slabs = 0
    for (nm, cx0, cx1, cy0, cy1, _) in COURTS:
        o, n = build_paving(nm, h, occ, cx0, cx1, cy0, cy1, m_slab, coll)
        total_slabs += n
        made["paving_" + nm] = n
        print("  paving %-12s %5d slabs" % (nm, n))

    e = build_eodo(h, m_eodo, coll)
    made["eodo"] = len(e.data.polygons)

    # Fit the palace wall to the ACTUAL built area instead of a hand-typed rectangle.
    # The old loop left 60-80 m of bare ground on every side and pushed the map to
    # 225 x 288 m, far past a 5v5 footprint - and it left Eochago (x=+81) outside.
    bx0 = bx1 = by0 = by1 = None
    nx1 = None
    for o in building_objects():
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            bx0 = w.x if bx0 is None else min(bx0, w.x)
            bx1 = w.x if bx1 is None else max(bx1, w.x)
            by0 = w.y if by0 is None else min(by0, w.y)
            by1 = w.y if by1 is None else max(by1, w.y)
            if w.y > YCUT:
                nx1 = w.x if nx1 is None else max(nx1, w.x)
    M = 13.0
    x0w, x1w = bx0 - M, bx1 + M
    y0w, y1w = by0 - M, by1 + M
    xnw = (nx1 + M) if nx1 is not None else (x0w + 40.0)
    loop = [(x0w, y0w), (x1w, y0w), (x1w, YCUT), (xnw, YCUT),
            (xnw, y1w), (x0w, y1w), (x0w, y0w)]
    made["wall_extent"] = [round(x1w - x0w, 1), round(y1w - y0w, 1)]
    print("  wall fitted: main %.0f x %.0f m, north spur to y=%.0f" % (
        x1w - x0w, YCUT - y0w, y1w))
    walls = build_wall(h, loop, m_wallb, m_wallc, coll)
    made["wall"] = sum(len(w.data.polygons) for w in walls)

    tobjs, ntree, tplaced = build_trees(h, occ, x0 + 20, x1 - 20, y0 + 20, y1 - 20,
                                        coll, [(p[0], p[1]) for p in pts])
    made["trees"] = ntree
    uniq = set()
    for t in tobjs:
        uniq.add(t.data.name)
    made["tree_unique_tris"] = sum(len(bpy.data.meshes[n].polygons) for n in uniq)
    with open(os.path.join(ROOT, "_extracted", "TREE_PLACEMENTS.csv"), "w",
              encoding="utf-8") as f:
        f.write("x,y,z,scale,yaw_rad\n")
        for (cx, cy, cz, sc, rot) in tplaced:
            f.write("%.3f,%.3f,%.3f,%.4f,%.5f\n" % (cx, cy, cz, sc, rot))
    print("  trees placed %d (linked instances of %d unique tris)"
          % (ntree, made["tree_unique_tris"]))

    tris = 0
    for o in coll.objects:
        o.data.calc_loop_triangles()
        tris += len(o.data.loop_triangles)
    print("\n  30_GROUND objects %d   tris %,d".replace(",d", "d")
          % (len(coll.objects), tris))
    made["ground_tris"] = tris

    allt = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and not o.name.startswith("GUIDE_"):
            o.data.calc_loop_triangles()
            allt += len(o.data.loop_triangles)
    made["map_tris"] = allt
    print("  map total tris %d" % allt)

    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(made, f, ensure_ascii=False, indent=1)
    print("  saved", OUT)


main()
