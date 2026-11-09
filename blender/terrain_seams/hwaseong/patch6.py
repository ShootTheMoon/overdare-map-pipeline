# -*- coding: utf-8 -*-
r"""After the TER6 import (Studio saved, playtest stopped): edit onlyoneshot.ovdrjm in one pass, then overdare_apply.
  * HWS_TER_ij (20 live inner tiles) -> TER6 mesh/texture ids + position/size from place6.json
  * deltas6.json -> CFrame.Position.Y += dY for plants / props / pines (same ground as TER6)
Backup: onlyoneshot.ovdrjm.bak_ter6.  Usage: python patch6.py [UGCLocalAssetTable.json]"""
import io, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hws_place import load_table

D6 = r"C:\Work\blender\ovdr_export\hwaseong_v25\_rebatch_tiles6"
PROJ = r"C:\Work\onlyonetap\onlyoneshot.ovdrjm"
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
place = json.load(io.open(os.path.join(D6, "place6.json"), encoding="utf-8"))
dy = json.load(io.open(os.path.join(D6, "deltas6.json"), encoding="utf-8"))
miss = [n for n in place if not ids.get(n) or not tex.get("T_" + n)]
if miss:
    sys.exit("not imported yet: %s" % miss)
shutil.copy2(PROJ, PROJ + ".bak_ter6")
root = json.loads(io.open(PROJ, "rb").read().decode("utf-16"))


def walk(o):
    if isinstance(o, dict):
        if "ActorGuid" in o:
            yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


tiles = moved = 0
for o in walk(root):
    n = o.get("Name", "")
    if n.startswith("HWS_TER_") and len(n) == 10 and n[-2:].isdigit():
        k = "HWS_TER6_" + n[-2:]; p = place[k]
        o["MeshId"] = "ovdrassetid://%s" % ids[k]; o["TextureId"] = "ovdrassetid://%s" % tex["T_" + k]
        o["CFrame"]["Position"].update(X=p["position"][0], Y=p["position"][1], Z=p["position"][2])
        o["Size"].update(X=p["size"][0], Y=p["size"][1], Z=p["size"][2]); tiles += 1
        # UnitExtent = the mesh's half extent (Z negated). Studio scales by Size/UnitExtent, so a swapped mesh with a
        # stale UnitExtent (old flat tile: Y 0.0005) came out stretched ~500,000x vertically (2026-09-12)
        o["UnitExtent"].update(X=p["size"][0] / 2, Y=p["size"][1] / 2, Z=-p["size"][2] / 2)
    if o["ActorGuid"] in dy:
        o["CFrame"]["Position"]["Y"] = round(o["CFrame"]["Position"]["Y"] + dy[o["ActorGuid"]], 1); moved += 1
s = json.dumps(root, ensure_ascii=False, indent="\t")
json.loads(s)
io.open(PROJ, "wb").write(s.encode("utf-16"))
print("tiles", tiles, "re-seated", moved, "of", len(dy))
