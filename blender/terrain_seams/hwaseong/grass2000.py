# -*- coding: utf-8 -*-
r"""Hwaseong ground dressing — ~2000 Sangok small plants (existing assets, no import), mostly on the TER3 tile borders.
Headless:  blender.exe -b hwaseong_v25.blend --python grass2000.py
Output:    ovdr_export\hwaseong_v25\_grass2000\grass_NN.json (200 items per chunk, overdare_create_instances itemsFile)
Why (2026-09-12): the 40 m tile borders stay visible in Studio (per-mesh sky light, not fixable in the files) and
           the user wants detail by model count, not by texture tricks (TER5 2048 textures came out blurry).
           ~88 % of the budget goes on the border lines (x = -60/-20/20/60, x = +-100, y = -30/10/50, y = -70), the rest
           over the yard. Roads / plazas stay clear. Mostly FERN (40 cm) so sightlines stay open; ARTEMISIA small,
           EULALIA rare."""
import bpy, sys, os, json, io, glob, math, random
V25 = r"C:\Work\blender\hwaseong_rebuild\v25"
sys.path.insert(0, V25)
import hws_stage3 as S3, hws_export as HX

tv = S3.tv; relief = S3.relief
OUT = os.path.join(HX.OUT, "_grass2000"); os.makedirs(OUT, exist_ok=True)
TARGET = 2000; CHUNK = 200
# 2026-09-12: sigma 0.7 m / share 0.88 drew a planted-looking straight row ON the border -> wide band + more yard
SEAM_SHARE = float(os.environ.get("GRASS_SEAM_SHARE", "0.6")); SIGMA = float(os.environ.get("GRASS_SIGMA", "2.5"))
GX0, GX1 = -tv['SX'] / 2, tv['SX'] / 2; GY0, GY1 = tv['CY'] - tv['SY'] / 2, tv['CY'] + tv['SY'] / 2
LINES = [((x, GY0), (x, GY1)) for x in (GX0 + 40, GX0 + 80, GX0 + 120, GX0 + 160)] + \
        [((GX0, y), (GX1, y)) for y in (GY0 + 40, GY0 + 80, GY0 + 120)]
MIX_SEAM = [("FERN", 0.80, (0.6, 1.2)), ("ARTEMISIA", 0.15, (0.5, 0.85)), ("EULALIA", 0.05, (0.45, 0.7))]
MIX_YARD = [("FERN", 0.85, (0.6, 1.1)), ("ARTEMISIA", 0.15, (0.5, 0.8))]


BOUND = (-89.0, 89.0, -64.0, 64.0)     # HWS_Bound_* walls (engine X -67000..-49000, Z -6500..6500) minus 1 m
TOPUP = int(os.environ.get("GRASS_TOPUP", "0")); START = int(os.environ.get("GRASS_START", "0"))


def clear(x, y):
    if not (BOUND[0] < x < BOUND[1] and BOUND[2] < y < BOUND[3]):
        return False
    if min(tv['dist_rect'](x, y, r) for r in tv['ROADS']) < 0.8:
        return False
    return all(math.hypot(x - c[0], y - c[1]) > rad + 0.8 for c, rad in tv['PLAZAS'])


def templates():
    items = [i for f in glob.glob(os.path.join(HX.OUT, "_place", "place_*.json")) for i in json.load(io.open(f, encoding="utf-8"))]
    tm = {}
    for it in items:
        for k in ("FERN", "ARTEMISIA", "EULALIA"):
            if it["name"].startswith("HWS_지면소품_" + k):
                p = it["props"]; X, Y, Z = p["position"]; x, y = (X - S3.X0) / 100, -Z / 100
                tm.setdefault(k, []).append((Y - relief(x, y) * 100, p))
    return {k: (sorted(o for o, _ in v)[len(v) // 2], v[0][1]) for k, v in tm.items()}


def item(rnd, tpl, mix, x, y, n):
    k, _, (s0, s1) = rnd.choices(mix, weights=[m[1] for m in mix])[0]
    off, p = tpl[k]; s = rnd.uniform(s0, s1); q = json.loads(json.dumps(p))
    q["size"] = [round(v * s, 1) for v in p["size"]]
    q["position"] = [round(x * 100 + S3.X0, 1), round(relief(x, y) * 100 + off * s, 1), round(-y * 100, 1)]
    o = p.get("orientation", [0, 0, 0]); q["orientation"] = [o[0], round(rnd.uniform(-180, 180), 1), o[2]]
    q["canCollide"] = False; q["canQuery"] = False
    return {"className": "MeshPart", "name": "HWS_지면소품_grass_%04d" % n, "props": q}


def topup(tpl):
    """GRASS_TOPUP=n GRASS_START=k : n more plants inside BOUND (half on the border lines, half yard) -> topup.json"""
    rnd = random.Random(3000 + START); out = []
    lines = [l for l in LINES if clear((l[0][0] + l[1][0]) / 2 + 0.01, (l[0][1] + l[1][1]) / 2 + 0.01) or True]
    while len(out) < TOPUP // 2:
        (ax, ay), (bx, by) = rnd.choice(lines); t = rnd.random()
        d = max(-2 * SIGMA, min(2 * SIGMA, rnd.gauss(0, SIGMA))); L = math.hypot(bx - ax, by - ay); ux, uy = (bx - ax) / L, (by - ay) / L
        x = ax + (bx - ax) * t - uy * d; y = ay + (by - ay) * t + ux * d
        if clear(x, y):
            out.append(item(rnd, tpl, MIX_SEAM, x, y, START + len(out)))
    while len(out) < TOPUP:
        x, y = rnd.uniform(BOUND[0], BOUND[1]), rnd.uniform(BOUND[2], BOUND[3])
        if clear(x, y):
            out.append(item(rnd, tpl, MIX_YARD, x, y, START + len(out)))
    json.dump(out, io.open(os.path.join(OUT, "topup.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("@@TOPUP", len(out), "from", START, flush=True)


def main():
    tpl = templates(); print("@@TPL", {k: (round(v[0], 1), v[1]["size"]) for k, v in tpl.items()}, flush=True)
    if TOPUP:
        return topup(tpl)
    rnd = random.Random(2000); out = []
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in LINES)
    step = total / (TARGET * SEAM_SHARE)
    for (ax, ay), (bx, by) in LINES:
        L = math.hypot(bx - ax, by - ay); ux, uy = (bx - ax) / L, (by - ay) / L; k = rnd.uniform(0, step)
        while k < L:
            d = max(-2 * SIGMA, min(2 * SIGMA, rnd.gauss(0, SIGMA)))
            x = ax + ux * k - uy * d; y = ay + uy * k + ux * d
            if clear(x, y):
                out.append(item(rnd, tpl, MIX_SEAM, x, y, len(out)))
            k += step * rnd.uniform(0.6, 1.4)
    n_seam = len(out)
    while len(out) < TARGET:
        x, y = rnd.uniform(GX0 + 1, GX1 - 1), rnd.uniform(GY0 + 1, GY1 - 1)
        if clear(x, y):
            out.append(item(rnd, tpl, MIX_YARD, x, y, len(out)))
    for f in glob.glob(os.path.join(OUT, "grass_*.json")):
        os.remove(f)
    for c in range(0, len(out), CHUNK):
        json.dump(out[c:c + CHUNK], io.open(os.path.join(OUT, "grass_%02d.json" % (c // CHUNK)), "w", encoding="utf-8"), ensure_ascii=False)
    print("@@GRASS seam", n_seam, "yard", len(out) - n_seam, "chunks", (len(out) + CHUNK - 1) // CHUNK, "step %.2f m" % step, flush=True)

if __name__ == "__main__":
    main()
