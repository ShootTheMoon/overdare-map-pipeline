# -*- coding: utf-8 -*-
r"""After the TER4 import: items4.json (20 new inner tiles, same names HWS_TER_ij, new mesh/texture/position/size)
+ delete4.json (guids of the 20 live HWS_TER_ij instances). Outer HWS_OUT_* tiles are untouched.
Usage: python swap4.py [UGCLocalAssetTable.json]"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hws_place import load_table

OUT = r"C:\Work\blender\ovdr_export\hwaseong_v25"
D4 = os.path.join(OUT, "_rebatch_tiles4")
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
place = json.load(io.open(os.path.join(D4, "place4.json"), encoding="utf-8"))
old = {r["name"]: r["guid"] for r in json.load(io.open(os.path.join(OUT, "_rebatch_tiles2", "swap_plan.json"), encoding="utf-8"))}
items, dele, miss = [], [], []
for name, p in sorted(place.items()):
    m, t = ids.get(name), tex.get("T_" + name)
    if not m or not t:
        miss.append(name); continue
    items.append({"className": "MeshPart", "name": p["old"], "props": {
        "meshId": "ovdrassetid://%s" % m, "material": "Basic", "color": [200, 200, 200],
        "position": p["position"], "orientation": [0.0, -180.0, 0.0], "size": [p["size"][0], max(1.0, p["size"][1]), p["size"][2]],   # flat courtyard tiles: Y 0 -> 1 (as hws_place did)
        "anchored": True, "mobility": "Static", "castShadow": True, "canCollide": False, "canQuery": False,
        "raw": {"TextureId": "ovdrassetid://%s" % t}}})
    if p["old"] in old:
        dele.append(old[p["old"]])
json.dump(items, io.open(os.path.join(D4, "items4.json"), "w", encoding="utf-8"), indent=1)
json.dump(dele, io.open(os.path.join(D4, "delete4.json"), "w", encoding="utf-8"))
print("items", len(items), "delete", len(dele), "missing", miss)
