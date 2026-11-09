# -*- coding: utf-8 -*-
r"""After the TER5 import: items5.json (4 tiles HWS_TER_A..D) + delete5.json (guids of every live HWS_TER_ij tile).
Usage: python swap5.py [UGCLocalAssetTable.json]"""
import io, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hws_place import load_table

OUT = r"C:\Work\blender\ovdr_export\hwaseong_v25"
D5 = os.path.join(OUT, "_rebatch_tiles5")
PROJ = r"C:\Work\onlyonetap\onlyoneshot.ovdrjm"
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
place = json.load(io.open(os.path.join(D5, "place5.json"), encoding="utf-8"))
items, miss = [], []
for name, p in sorted(place.items()):
    m, t = ids.get(name), tex.get("T_" + name)
    if not m or not t:
        miss.append(name); continue
    items.append({"className": "MeshPart", "name": name.replace("HWS_TER5_", "HWS_TER_"), "props": {
        "meshId": "ovdrassetid://%s" % m, "material": "Basic", "color": [200, 200, 200],
        "position": p["position"], "orientation": [0.0, -180.0, 0.0], "size": p["size"],
        "anchored": True, "mobility": "Static", "castShadow": True, "canCollide": False, "canQuery": False,
        "raw": {"TextureId": "ovdrassetid://%s" % t}}})
json.dump(items, io.open(os.path.join(D5, "items5.json"), "w", encoding="utf-8"), indent=1)

def walk(o):
    if isinstance(o, dict):
        if "ActorGuid" in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
root = json.loads(io.open(PROJ, "rb").read().decode("utf-16"))
dele = [o["ActorGuid"] for o in walk(root) if re.match(r"HWS_TER_\d\d$", o.get("Name", ""))]
json.dump(dele, io.open(os.path.join(D5, "delete5.json"), "w", encoding="utf-8"))
print("items", len(items), "missing", miss, "delete", len(dele))
