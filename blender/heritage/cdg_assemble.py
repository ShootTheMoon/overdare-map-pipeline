# -*- coding: utf-8 -*-
"""
CDG - stage 4: assemble the reduced buildings into one world-scale master scene.

The KHS assets are NOT co-registered - verified by comparing inter-asset bbox
centre distances (3-24 m) against the real OSM distances (15-212 m).  Each
building is modelled around its own local origin with an arbitrary ground level
(-11.6 m for Injeongjeon, +0.65 m for Naejaesil).  So placement is solved here.

Method: for each asset compute the minimum-area rectangle of its FOOTPRINT
(vertices projected to XY), then solve the rigid transform that carries that
rectangle onto the corresponding OpenStreetMap building footprint rectangle.
Rotation is taken from the rectangle angles, translation from the centres, and Z
from the measured ground so every building's base lands on its zone's terrain
height.

Rectangle matching has a 180-degree ambiguity that geometry alone cannot resolve
(a hall and its mirror have the same footprint).  Long-axis-to-long-axis is
chosen automatically; anything that comes out backwards is corrected by the
`yaw_fix` override in cdg_placement.json after looking at the aerial render.

Usage:
  blender.exe --background --factory-startup --python cdg_assemble.py
"""
import json
import math
import os

import bpy
from mathutils import Matrix, Vector

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
ARCH = os.path.join(ROOT, "20_ARCHITECTURE")
LAYOUT = os.path.join(ROOT, "_scripts", "cdg_layout.json")
OSM = os.path.join(ROOT, "_scripts", "cdg_osm_footprints.json")
OVERRIDE = os.path.join(ROOT, "_scripts", "cdg_placement.json")
MASTER = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master.blend")
RAW_OSM = os.path.join(ROOT, "_scripts", "cdg_osm_raw.json")

# asset key -> OSM way ids whose pooled outline is the placement target.
# Several KHS assets span more than one OSM way (a corridor plus its wollang).
TARGETS = {
    "Injeongjeon":      ["380863259"],
    "Injeongmun":       ["894448260"],
    "Jinseonmun":       ["894448271"],
    "Sukjangmun":       ["894448269"],
    "JinseonmunL":      ["894476991"],
    "CorridorE":        ["894611029", "894611028"],
    "CorridorW":        ["894611017", "894611016"],
    "Seonwonjeon":      ["170199421"],
    "SeonwonjeonS":     ["894962185"],
    "Yangjidang":       ["612979882"],
    "SeoJinseolcheong": ["787949776"],
    "BukJinseolcheong": ["894940677"],
    "Uipunggak":        ["170199482"],
    "Gyujanggak":        ["432721335"],
    "GyujanggakGate":    ["895115683"],
    "Bongmodang":        ["612929598"],
    "Chaekgo1":          ["787949782"],
    "Chaekgo2":          ["787949781"],
    "Chaekgo3":          ["787954254"],
    "Unhanmun":          ["787949792"],
    "Naegak":            ["170403815"],
    "Geomseocheong":     ["432721336"],
    "GeomseocheongX":    ["895115681"],
    "Manumun":           ["301282715"],
    "Yeonguisa":         ["922226671"],
    "Okdang":            ["612929603"],
    "OkdangS":           ["894962174"],
    "Yakbang":           ["895432665"],
    "YakbangE":          ["787949785"],
    "JeongcheongX":      ["787949784"],
    "Hyangsil":          ["894940648"],
    "Yemungwan":         ["894448285"],
    "Eochago":           ["612979887"],
}

# assets with no OSM way of their own - placed by hand, refined against renders
MANUAL = {
    "CorridorOuter":  {"x":  -2.0, "y": -86.0, "yaw":   6.4},
    "YangjidangGak":  {"x": -55.8, "y":  13.5, "yaw":   5.2},
    "Naejaesil":      {"x": -69.3, "y":  34.1, "yaw": -89.6},   # OSM 동진설청 slot
    "Naechildang":    {"x": -95.0, "y":  22.0, "yaw":   0.1},
    "Unnamed1":       {"x": -52.2, "y":  -26.3, "yaw":   0.0},   # OSM 단훼문 slot
    "Unnamed2":       {"x": -47.7, "y":    6.0, "yaw":   0.0},   # OSM 안영문 slot
    "Unnamed3":       {"x": -36.7, "y":  -74.6, "yaw":   0.0},   # OSM 경광문 slot
    "HyangsilX":      {"x": -48.5, "y":  -11.5, "yaw":   4.4},   # annex beside Hyangsil
    "Gyeongchumun":   {"x": -152.0, "y": -20.0, "yaw":  90.0},   # gate on the west palace wall
}

ZONE_Z = {   # terrain step: the Seonwonjeon compound sits higher than the court
    "ZONE_01_JINSEONMUN":    0.0,
    "ZONE_02_INJEONGMUN":    0.0,
    "ZONE_03_INJEONGJEON":   1.2,
    "ZONE_04_SEONWONJEON":   2.6,
    "ZONE_05_JINSEOLCHEONG": 2.6,
    "ZONE_06_UIPUNGGAK":     4.0,
    "ZONE_07_GWOLLAEGAKSA":  0.6,
}


def min_area_rect(pts):
    """(cx, cy, length, width, yaw_deg) of the minimum-area rectangle."""
    best = None
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        ux, uy = dx / L, dy / L
        us = [p[0] * ux + p[1] * uy for p in pts]
        vs = [-p[0] * uy + p[1] * ux for p in pts]
        w = max(us) - min(us)
        h = max(vs) - min(vs)
        if best is None or w * h < best[0]:
            cu = (max(us) + min(us)) / 2
            cv = (max(vs) + min(vs)) / 2
            best = (w * h, w, h, math.degrees(math.atan2(uy, ux)),
                    cu * ux - cv * uy, cu * uy + cv * ux)
    _, w, h, ang, cx, cy = best
    if w >= h:
        return cx, cy, w, h, ang
    return cx, cy, h, w, ang + 90.0


def convex_hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def footprint_points(objs, cap=60000):
    """XY point cloud of the whole asset, subsampled."""
    pts = []
    total = sum(len(o.data.vertices) for o in objs)
    step = max(1, total // cap)
    i = 0
    for o in objs:
        mw = o.matrix_world
        for v in o.data.vertices:
            i += 1
            if i % step:
                continue
            w = mw @ v.co
            pts.append((w.x, w.y))
    return pts


def footprint_rect(objs):
    return min_area_rect(convex_hull(footprint_points(objs)))


def grid(pts, cell=1.0):
    return {(int(math.floor(x / cell)), int(math.floor(y / cell))) for x, y in pts}


def poly_fill(poly, cell=1.0):
    """Rasterize a polygon to a cell set (even-odd scanline)."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    out = set()
    y = math.floor(min(ys) / cell)
    ymax = math.ceil(max(ys) / cell)
    n = len(poly)
    while y <= ymax:
        yc = (y + 0.5) * cell
        xhit = []
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                t = (yc - y1) / (y2 - y1)
                xhit.append(x1 + t * (x2 - x1))
        xhit.sort()
        for j in range(0, len(xhit) - 1, 2):
            a = int(math.floor(xhit[j] / cell))
            b = int(math.ceil(xhit[j + 1] / cell))
            for x in range(a, b):
                out.add((x, y))
        y += 1
    return out


def best_alignment(pts, cx, cy, base_yaw, target_cells, tx, ty, cell=1.0):
    """Rectangle matching is 180-degree ambiguous (and 90-degree ambiguous when the
    footprint is near-square), so the rect angle alone put several corridors in
    backwards. Resolve it by SHAPE: rasterize the asset footprint under each of the
    four candidate rotations, plus a small translation search, and keep whichever
    covers the OSM footprint best. The KHS corridors are L-shaped, so their real
    outline does distinguish the flips that a bounding rectangle cannot."""
    best = None
    # Only 0 and 180. min_area_rect always reports the LONG axis angle for both the
    # asset and the OSM target, so a quarter-turn maps long onto short and is never
    # correct - allowing it put the near-square Injeongjeon (46.1 x 41.3) sideways at
    # a meaningless 86% fit. The 180 flip is the only genuine ambiguity left, and
    # anything shape cannot settle is corrected via yaw_fix in cdg_placement.json.
    for quarter in (0, 2):
        yaw = base_yaw + 90.0 * quarter
        r = math.radians(yaw)
        ca, sa = math.cos(r), math.sin(r)
        rot = [((x - cx) * ca - (y - cy) * sa, (x - cx) * sa + (y - cy) * ca)
               for x, y in pts]
        for ddx in (-4, -2, 0, 2, 4):
            for ddy in (-4, -2, 0, 2, 4):
                g = grid([(x + tx + ddx, y + ty + ddy) for x, y in rot], cell)
                inter = len(g & target_cells)
                score = inter / max(len(target_cells), 1)
                if best is None or score > best[0]:
                    best = (score, yaw, tx + ddx, ty + ddy)
    return best


def ground_z(objs):
    z = 1e18
    for o in objs:
        mw = o.matrix_world
        for v in o.data.vertices:
            z = min(z, (mw @ v.co).z)
    return z


def osm_target(way_ids, raw):
    """-> (min_area_rect, filled_cell_set). Each way is rasterized separately and
    unioned, so an L-shaped pair (corridor + wollang) keeps its real outline
    instead of being merged into one convex blob."""
    LAT0, LON0 = 37.5794490, 126.9910907
    MLAT, MLON = 110995.0, 88229.0
    allpts = []
    cells = set()
    for e in raw["elements"]:
        if str(e["id"]) not in way_ids:
            continue
        poly = [((p["lon"] - LON0) * MLON, (p["lat"] - LAT0) * MLAT)
                for p in e.get("geometry", [])]
        if len(poly) > 2 and poly[0] == poly[-1]:
            poly = poly[:-1]
        if len(poly) < 3:
            continue
        allpts.extend(poly)
        cells |= poly_fill(poly)
    if not allpts:
        return None
    return min_area_rect(convex_hull(allpts)), cells


def append_blend(path):
    """Append every mesh object from a reduced blend; return the new objects."""
    before = set(bpy.data.objects)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    added = []
    for o in set(bpy.data.objects) - before:
        if o.type == "MESH":
            bpy.context.scene.collection.objects.link(o)
            added.append(o)
        else:
            bpy.data.objects.remove(o, do_unlink=True)
    return added


def build_osm_guides(raw, z=-0.6):
    """Lay each OSM building footprint down as a flat magenta plate under the map.
    Judging placement from a render by eye is guesswork; with the surveyed outline
    drawn underneath, any asset that is offset or flipped is immediately visible.
    Lives in 00_GUIDES_NO_EXPORT and must never be exported."""
    LAT0, LON0 = 37.5794490, 126.9910907
    MLAT, MLON = 110995.0, 88229.0
    coll = bpy.data.collections.get("00_GUIDES_NO_EXPORT")
    if coll is None:
        coll = bpy.data.collections.new("00_GUIDES_NO_EXPORT")
        bpy.context.scene.collection.children.link(coll)
    # diffuse_color only drives the viewport; an EEVEE render ignores it and the
    # plates came out white and unreadable. Emission makes them unmistakable.
    mat = bpy.data.materials.new("MAT_GUIDE_OSM")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (1.0, 0.0, 0.55, 1.0)
    em.inputs[1].default_value = 6.0
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    n = 0
    for e in raw["elements"]:
        poly = [((p["lon"] - LON0) * MLON, (p["lat"] - LAT0) * MLAT)
                for p in e.get("geometry", [])]
        if len(poly) > 2 and poly[0] == poly[-1]:
            poly = poly[:-1]
        if len(poly) < 3:
            continue
        me = bpy.data.meshes.new("GUIDE_OSM_%s" % e["id"])
        me.from_pydata([(x, y, z) for x, y in poly], [],
                       [tuple(range(len(poly)))])
        me.update()
        me.materials.append(mat)
        o = bpy.data.objects.new("GUIDE_OSM_%s" % e["id"], me)
        coll.objects.link(o)
        n += 1
    print("  osm guide plates:", n)


def main():
    cfg = json.load(open(LAYOUT, encoding="utf-8"))
    raw = json.load(open(RAW_OSM, encoding="utf-8"))
    override = {}
    if os.path.exists(OVERRIDE):
        override = json.load(open(OVERRIDE, encoding="utf-8"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    placement = {}

    for asset in cfg["assets"]:
        key = asset["key"]
        zone = asset["zone"]
        blend = os.path.join(ARCH, zone, "CDG_%s_reduced.blend" % key)
        if not os.path.exists(blend):
            print("  skip (not reduced yet):", key)
            continue

        objs = append_blend(blend)
        if not objs:
            print("  skip (no meshes):", key)
            continue

        coll = bpy.data.collections.get(zone) or bpy.data.collections.new(zone)
        if coll.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(coll)

        fpts = footprint_points(objs)
        cx, cy, L, W, ang = min_area_rect(convex_hull(fpts))
        gz = ground_z(objs)
        score = None

        if key in TARGETS:
            t, cells = osm_target(TARGETS[key], raw)
            tx, ty, tL, tW, tang = t
            score, yaw, tx, ty = best_alignment(
                fpts, cx, cy, tang - ang, cells, tx, ty)
        elif key in MANUAL:
            m = MANUAL[key]
            tx, ty, yaw = m["x"], m["y"], m["yaw"] - ang
            tL = tW = None
        else:
            tx, ty, yaw, tL, tW = cx, cy, 0.0, None, None

        yaw += float(override.get(key, {}).get("yaw_fix", 0.0))
        tx += float(override.get(key, {}).get("dx", 0.0))
        ty += float(override.get(key, {}).get("dy", 0.0))
        tz = ZONE_Z.get(zone, 0.0) + float(override.get(key, {}).get("dz", 0.0))

        r = math.radians(yaw)
        rot = Matrix.Rotation(r, 4, "Z")
        # rotate about the footprint centre, then move that centre onto the target
        pre = Matrix.Translation((-cx, -cy, -gz))
        post = Matrix.Translation((tx, ty, tz))
        M = post @ rot @ pre

        for o in objs:
            o.matrix_world = M @ o.matrix_world
            o.name = "SM_CDG_%s_%s" % (key, o.name.replace("OB_", "")[:28])
            for c in list(o.users_collection):
                c.objects.unlink(o)
            coll.objects.link(o)

        placement[key] = {
            "zone": zone, "x": round(tx, 3), "y": round(ty, 3), "z": round(tz, 3),
            "yaw_applied": round(yaw, 3),
            "local_rect": [round(v, 2) for v in (cx, cy, L, W, ang)],
            "osm_rect": [round(v, 2) for v in t] if key in TARGETS else None,
            "size_delta": ([round(L - tL, 2), round(W - tW, 2)]
                           if tL is not None else None),
            "osm_coverage": round(score, 4) if score is not None else None,
            "objects": len(objs),
        }
        print("  placed {:<18} -> ({:>7.1f},{:>7.1f},{:>5.1f})  yaw {:>7.1f}  "
              "L/W {:>5.1f}/{:>4.1f}{}{}".format(
                  key, tx, ty, tz, yaw, L, W,
                  "  osm {:.1f}/{:.1f}".format(tL, tW) if tL else "",
                  "  fit {:.0%}".format(score) if score is not None else ""))

    build_osm_guides(raw)

    os.makedirs(os.path.dirname(MASTER), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=MASTER)
    with open(os.path.join(ROOT, "_extracted", "PLACEMENT.json"), "w",
              encoding="utf-8") as f:
        json.dump(placement, f, ensure_ascii=False, indent=1)

    tris = 0
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.data.calc_loop_triangles()
            tris += len(o.data.loop_triangles)
    print("\nmaster: {}\n  objects {}   tris {:,}".format(
        MASTER, len([o for o in bpy.data.objects if o.type == 'MESH']), tris))


main()
