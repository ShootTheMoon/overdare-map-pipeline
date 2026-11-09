# -*- coding: utf-8 -*-
r"""After the SGK7 import: point the 30 live STA_TER6_ij at the SGK7 mesh/texture (same geometry as SGK6 -> position,
size and UnitExtent unchanged; checked against place_sgk7.json). Backup .bak_sgk7, then overdare_apply."""
import io, json, os, shutil, sys
sys.path.insert(0, r"C:\Work\blender\hwaseong_rebuild\v25")
from hws_place import load_table

OVD = r"C:\Work\blender\JSN_Sangok2\06_OVERDARE"
PROJ = r"C:\Work\onlyonetap\onlyoneshot.ovdrjm"
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
p6 = json.load(io.open(os.path.join(OVD, "_rebatch_sgk6", "place_sgk6.json"), encoding="utf-8"))
p7 = json.load(io.open(os.path.join(OVD, "_rebatch_sgk7", "place_sgk7.json"), encoding="utf-8"))
diff = [k for k in p7 if p7[k]["size"] != p6[k.replace("SGK7", "SGK6")]["size"] or p7[k]["position"] != p6[k.replace("SGK7", "SGK6")]["position"]]
if diff:
    sys.exit("geometry changed, use a full swap: %s" % diff)
miss = [n for n in p7 if not ids.get(n) or not tex.get("T_" + n)]
if miss:
    sys.exit("not imported yet: %s" % miss)
shutil.copy2(PROJ, PROJ + ".bak_sgk7")
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


n = 0
for o in walk(root):
    nm = o.get("Name", "")
    if nm.startswith("STA_TER6_"):
        k = "SGK7_TER_" + nm[-2:]
        o["MeshId"] = "ovdrassetid://%s" % ids[k]; o["TextureId"] = "ovdrassetid://%s" % tex["T_" + k]; n += 1
s = json.dumps(root, ensure_ascii=False, indent="\t"); json.loads(s)
io.open(PROJ, "wb").write(s.encode("utf-16"))
print("swapped", n, "of", len(p7))
