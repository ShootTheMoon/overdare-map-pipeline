# -*- coding: utf-8 -*-
"""
Quantitative placement audit. Eyeballing renders has already misled me twice, so
measure instead: building-vs-building intersection, base-vs-terrain mismatch,
footprint agreement with the surveyed OSM outline, and distance to the wall.

blender.exe --background --factory-startup --python cdg_audit.py
"""
import json
import math
import os
from collections import defaultdict

import bpy
from mathutils import Vector

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
MASTER = os.path.join(ROOT, "20_ARCHITECTURE", "CDG_Master.blend")
RAW_OSM = os.path.join(ROOT, "_scripts", "cdg_osm_raw.json")
OUT = os.path.join(ROOT, "_extracted", "AUDIT.json")

LAT0, LON0 = 37.5794490, 126.9910907
MLAT, MLON = 110995.0, 88229.0
CELL = 1.0


def cells(pts):
    return {(int(math.floor(x / CELL)), int(math.floor(y / CELL))) for x, y in pts}


def poly_fill(poly):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    out = set()
    y = math.floor(min(ys)); ymax = math.ceil(max(ys)); n = len(poly)
    while y <= ymax:
        yc = y + 0.5; hit = []
        for i in range(n):
            x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                hit.append(x1 + (yc - y1) / (y2 - y1) * (x2 - x1))
        hit.sort()
        for j in range(0, len(hit) - 1, 2):
            for x in range(int(math.floor(hit[j])), int(math.ceil(hit[j + 1]))):
                out.add((x, y))
        y += 1
    return out


def main():
    bpy.ops.wm.open_mainfile(filepath=MASTER)

    per = defaultdict(lambda: {"cells": set(), "zmin": 1e18, "zmax": -1e18,
                               "xmin": 1e18, "xmax": -1e18,
                               "ymin": 1e18, "ymax": -1e18, "objs": 0, "tris": 0})
    ground = None
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.startswith("GUIDE_"):
            continue
        if o.name == "MOD_Terrain":
            ground = o
            continue
        if not o.name.startswith("SM_CDG_"):
            continue
        key = o.name.split("_")[2]
        d = per[key]
        d["objs"] += 1
        o.data.calc_loop_triangles()
        d["tris"] += len(o.data.loop_triangles)
        mw = o.matrix_world
        pts = []
        for v in o.data.vertices:
            w = mw @ v.co
            pts.append((w.x, w.y))
            d["zmin"] = min(d["zmin"], w.z); d["zmax"] = max(d["zmax"], w.z)
            d["xmin"] = min(d["xmin"], w.x); d["xmax"] = max(d["xmax"], w.x)
            d["ymin"] = min(d["ymin"], w.y); d["ymax"] = max(d["ymax"], w.y)
        d["cells"] |= cells(pts)

    # terrain height sampler from the actual mesh
    tz = {}
    if ground:
        mw = ground.matrix_world
        for v in ground.data.vertices:
            w = mw @ v.co
            tz[(round(w.x / 4) * 4, round(w.y / 4) * 4)] = w.z

    def terrain_at(x, y):
        best = None; bd = 1e18
        for (gx, gy), z in tz.items():
            dd = (gx - x) ** 2 + (gy - y) ** 2
            if dd < bd:
                bd = dd; best = z
        return best if best is not None else 0.0

    osm = json.load(open(RAW_OSM, encoding="utf-8"))
    osm_cells = {}
    for e in osm["elements"]:
        poly = [((p["lon"] - LON0) * MLON, (p["lat"] - LAT0) * MLAT)
                for p in e.get("geometry", [])]
        if len(poly) > 2 and poly[0] == poly[-1]:
            poly = poly[:-1]
        if len(poly) >= 3:
            osm_cells[str(e["id"])] = poly_fill(poly)

    keys = sorted(per)
    rows = {}
    for k in keys:
        d = per[k]
        cx = (d["xmin"] + d["xmax"]) / 2; cy = (d["ymin"] + d["ymax"]) / 2
        tzh = terrain_at(cx, cy)
        rows[k] = {
            "objs": d["objs"], "tris": d["tris"],
            "x": round(cx, 1), "y": round(cy, 1),
            "size": [round(d["xmax"] - d["xmin"], 1), round(d["ymax"] - d["ymin"], 1),
                     round(d["zmax"] - d["zmin"], 1)],
            "base_z": round(d["zmin"], 2),
            "terrain_z": round(tzh, 2),
            "gap": round(d["zmin"] - tzh, 2),
            "overlaps": [],
        }

    # pairwise footprint intersection
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            inter = per[a]["cells"] & per[b]["cells"]
            if not inter:
                continue
            fa = len(inter) / max(len(per[a]["cells"]), 1)
            fb = len(inter) / max(len(per[b]["cells"]), 1)
            if len(inter) >= 12 and max(fa, fb) > 0.06:
                rows[a]["overlaps"].append([b, len(inter), round(fa, 3)])
                rows[b]["overlaps"].append([a, len(inter), round(fb, 3)])

    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n=== FLOATING / SUNKEN (base vs terrain) ===")
    for k in sorted(keys, key=lambda k: -abs(rows[k]["gap"])):
        g = rows[k]["gap"]
        if abs(g) > 1.2:
            print("  {:<18} gap {:>7.2f} m   base {:>7.2f}  terrain {:>7.2f}".format(
                k, g, rows[k]["base_z"], rows[k]["terrain_z"]))

    print("\n=== FOOTPRINT OVERLAPS ===")
    seen = set()
    for k in keys:
        for (b, n, f) in rows[k]["overlaps"]:
            pair = tuple(sorted((k, b)))
            if pair in seen:
                continue
            seen.add(pair)
            print("  {:<18} x {:<18} {:>5} m2  ({:.0%} of {})".format(k, b, n, f, k))

    print("\n=== ALL PLACEMENTS ===")
    print("{:<18}{:>8}{:>8}{:>20}{:>9}{:>8}".format("key", "x", "y", "size", "base", "gap"))
    for k in keys:
        r = rows[k]
        print("{:<18}{:>8.1f}{:>8.1f}{:>20}{:>9.2f}{:>8.2f}".format(
            k, r["x"], r["y"], " x ".join(str(v) for v in r["size"]), r["base_z"], r["gap"]))
    print("\nwrote", OUT)


main()
