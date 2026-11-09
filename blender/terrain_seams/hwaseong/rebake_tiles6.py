# -*- coding: utf-8 -*-
r"""TER6 — the 20 inner 40 m tiles on relief6 (terrain6.py: +-15 cm bumps), 1024 textures (2048 came out blurry in
Studio), identical bounds (1 mm buried markers, 40 x H x 40 m), world-continuous PAD bake, analytic normals,
pine/fern litter, weak mottling (all reused from rebake_tiles5).
Headless:  blender.exe -b hwaseong_v25.blend --python rebake_tiles6.py
Output:    ovdr_export\hwaseong_v25\_rebatch_tiles6\HWS_TER6_ij.fbx + place6.json
           deltas6.json {guid: dY_cm} — plants / props / pines re-seated on the new ground (read from the live .ovdrjm)"""
import bpy, os, sys, json, io
import numpy as np
V25 = r"C:\Work\blender\hwaseong_rebuild\v25"
sys.path.insert(0, V25)
import hws_stage3 as S3, hws_export as HX
import rebake_tiles5 as R5
import terrain6 as T6

PROJ = r"C:\Work\onlyonetap\onlyoneshot.ovdrjm"
DST = os.path.join(HX.OUT, "_rebatch_tiles6"); os.makedirs(DST, exist_ok=True)
R5.N = 1024; R5.relief = T6.relief6; R5.DST = DST; R5.BW = 40.0; R5.BH = 40.0


def walk(o):
    if isinstance(o, dict):
        if "ActorGuid" in o:
            yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def deltas():
    root = json.loads(io.open(PROJ, "rb").read().decode("utf-16")); out = {}
    for o in walk(root):
        n = o.get("Name", "")
        if not (n.startswith("HWS_지면소품_") or n.startswith("HWS_수목_") or (n.startswith("HWS_") and " " in n)):
            continue
        p = o["CFrame"]["Position"]; x, y = (p["X"] - S3.X0) / 100, -p["Z"] / 100
        d = T6.bump(x, y) * 100
        if abs(d) >= 0.5:
            out[o["ActorGuid"]] = round(d, 1)
    json.dump(out, io.open(os.path.join(DST, "deltas6.json"), "w", encoding="utf-8"))
    print("@@DELTAS", len(out), "max %.1f min %.1f cm" % (max(out.values()), min(out.values())), flush=True)


def main():
    HX.ensure_dirs(); R5.fill_trees(); fld = R5.build_field()
    tv = S3.tv; SX, SY, CY = tv['SX'], tv['SY'], tv['CY']
    zhi = max(T6.relief6(x, y) for x in np.arange(-SX / 2, SX / 2 + 0.5, 1.0) for y in np.arange(CY - SY / 2, CY + SY / 2 + 0.5, 1.0)) + 0.01
    place = {}
    for i in range(5):
        for j in range(4):
            x0 = -SX / 2 + 40.0 * i; y0 = CY - SY / 2 + 40.0 * j
            x1, y1 = min(x0 + 40.0, SX / 2), min(y0 + 40.0, CY + SY / 2)
            name = "HWS_TER6_%d%d" % (i, j)
            path, rect = R5.bake(name, x0, x1, y0, y1, fld)
            place[name] = R5.build(name, x0, x1, y0, y1, path, rect, zhi)
            print("@@TILE", name, place[name]["size"], flush=True)
    json.dump(place, open(os.path.join(DST, "place6.json"), "w"), indent=1)
    deltas()
    print("@@REBAKE6 done", DST)

if __name__ == "__main__":
    main()
