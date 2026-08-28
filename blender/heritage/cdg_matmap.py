# -*- coding: utf-8 -*-
"""
Build material-name -> texture-file mapping for the Gwollaegaksa (wave-4) assets.

Why this exists
---------------
The first 17 KHS assets and the Gwollaegaksa batch came from different vendors:

  wave 1-3   material `MI_Giwa`      -> FBX references `T_Giwa_BC.png`, which is
                                        also the loose PNG in the zip. Resolves by
                                        basename, and the textures are embedded.
  wave 4     material `M_Capital01A` -> FBX references
                                        `..\\module\\tri\\texture\\MI_..._BaseColor.png`,
                                        a shared authoring library that is NOT shipped,
                                        and nothing is embedded. Blender imported 760
                                        unresolvable images and every Gwollaegaksa
                                        building rendered magenta.

The loose PNGs in those zips ARE the right textures, just under `T_<Name>_BC.png`.
So rebuild the link from the material name, which is parallel to the texture name
(`M_Capital01A` -> `T_Capital01A_BC.png`). Prefixes vary across the batch
(`M_`, `MI_`, `N_`, `Ml_`, `M_TWJ_`) and variant letters drift
(`N_Capital01Y` has no `T_Capital01Y_BC.png`, only `T_Capital01A_BC.png`), so the
resolver falls back stem -> nearest-variant -> keyword -> neutral. Keyword fallback
matters: an unresolved material must still get a plausible surface rather than magenta.

Run with system Python:  python cdg_matmap.py
"""
import json
import os
import re
import sys
from collections import Counter

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
TEXLIB = os.path.join(ROOT, "_extracted", "_TexLib")
REPORT = os.path.join(ROOT, "_extracted", "REDUCE_REPORT.json")
OUT = os.path.join(ROOT, "_scripts", "cdg_matmap.json")

PREFIX = re.compile(r"^(MI_|Ml_|M_TWJ_|M_|N_|mat_|Mat_|SM_)", re.I)
SUFFIX = re.compile(r"(_MTL\d*|_TML|_Mat|_mtl)$", re.I)

# last resort: keyword in the material name -> a sensible KHS surface
KEYWORD = [
    ("giwa", "T_Giwa_BC.png"), ("roof", "T_Giwa_BC.png"),
    ("gongpo", "T_Capital01A_BC.png"), ("judusoro", "T_Capital01A_BC.png"),
    ("capital", "T_Capital01A_BC.png"), ("boaji", "T_Boaji01D_BC.png"),
    ("changbang", "T_ChangBang01G_BC.png"), ("changbong", "T_ChangBang01G_BC.png"),
    ("hwaban", "T_ChangBang01G_BC.png"), ("rafter", "T_AngleRafter01C_BC.png"),
    ("seokkalae", "T_AngleRafter01C_BC.png"),
    ("bluegreen", "T_GreenWood_BC.png"), ("greenwood", "T_GreenWood_BC.png"),
    ("redwood", "T_RedWood_BC.png"), ("darkwood", "T_BrownWood01A_BC.png"),
    ("brownwood", "T_BrownWood01A_BC.png"), ("wood", "T_BrownWood01A_BC.png"),
    ("door", "T_Door01A_BC.png"), ("window", "T_Door01A_BC.png"),
    ("wall", "T_StoneWall01A_BC.png"), ("brick", "T_BrickStone01B_BC.png"),
    ("stone", "T_Stone01A_BC.png"), ("stereobate", "T_Stone01A_BC.png"),
    ("floor", "T_Floor02A_BC.png"), ("ground", "T_Ground01A_BC.png"),
    ("concrat", "T_Concrate_BC.png"), ("concret", "T_Concrate_BC.png"),
    ("metal", "T_Blackmetal_BC.png"), ("black", "T_Blackmetal_BC.png"),
    ("paper", "T_Door01A_BC.png"),
]
NEUTRAL = "T_BrownWood01A_BC.png"


def build():
    lib = {f.lower(): f for f in os.listdir(TEXLIB)}
    cores = {}
    for k, v in lib.items():
        if not k.endswith("_bc.png"):
            continue
        c = k[2:-7] if k.startswith("t_") else k[:-7]
        if c and c not in cores:
            cores[c] = v

    def pick(name):
        return lib.get(name.lower())

    def resolve(mat):
        x = re.sub(r"\.\d+$", "", mat)
        x = PREFIX.sub("", x)
        x = SUFFIX.sub("", x)
        xl = re.sub(r"[^a-z0-9]", "", x.lower())
        if xl:
            if xl in cores:
                return cores[xl], "exact"
            stem = re.sub(r"\d+[a-z]?$", "", xl)
            if stem and stem in cores:
                return cores[stem], "stem"
            cand = sorted([(c, v) for c, v in cores.items()
                           if stem and c.startswith(stem)], key=lambda t: len(t[0]))
            if cand:
                return cand[0][1], "variant"
            cand = sorted([(c, v) for c, v in cores.items()
                           if stem and len(c) > 3 and stem.startswith(c)],
                          key=lambda t: -len(t[0]))
            if cand:
                return cand[0][1], "partial"
        low = mat.lower()
        for kw, tex in KEYWORD:
            if kw in low:
                hit = pick(tex)
                if hit:
                    return hit, "keyword"
        hit = pick(NEUTRAL)
        return (hit, "neutral") if hit else (None, "none")

    rep = json.load(open(REPORT, encoding="utf-8"))
    mats = set()
    tri = Counter()
    for k, r in rep.items():
        for m in r.get("materials", []):
            mats.add(m["material"])
            tri[m["material"]] += m["out_tris"]

    out = {}
    how = Counter()
    tri_by = Counter()
    for m in sorted(mats):
        t, kind = resolve(m)
        how[kind] += 1
        tri_by[kind] += tri[m]
        if t:
            out[m] = t
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    total = sum(tri.values())
    print("materials %d, mapped %d" % (len(mats), len(out)))
    for kind, n in how.most_common():
        print("   {:<9} {:>4} materials  {:>10,} tris ({:.1%})".format(
            kind, n, tri_by[kind], tri_by[kind] / max(total, 1)))
    print("wrote", OUT)


build()
