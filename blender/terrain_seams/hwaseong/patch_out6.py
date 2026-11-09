# -*- coding: utf-8 -*-
r"""After the OUT6 import: HWS_OUT_ij (10 live ring tiles) -> OUT6 mesh/texture/position/size/UnitExtent,
deltas_out6.json -> Position.Y += dY. One pass over onlyoneshot.ovdrjm (backup .bak_out6), then overdare_apply."""
import io, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hws_place import load_table

D = r"C:\Work\blender\ovdr_export\hwaseong_v25\_rebatch_out6"
PROJ = r"C:\Work\onlyonetap\onlyoneshot.ovdrjm"
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
place = json.load(io.open(os.path.join(D, "place_out6.json"), encoding="utf-8"))
dy = json.load(io.open(os.path.join(D, "deltas_out6.json"), encoding="utf-8"))
miss = [n for n in place if not ids.get(n) or not tex.get("T_" + n)]
if miss:
    sys.exit("not imported yet: %s" % miss)
shutil.copy2(PROJ, PROJ + ".bak_out6")
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
    if n.startswith("HWS_OUT_") and len(n) == 10 and n[-2:].isdigit() and "HWS_OUT6_" + n[-2:] in place:
        k = "HWS_OUT6_" + n[-2:]; p = place[k]
        o["MeshId"] = "ovdrassetid://%s" % ids[k]; o["TextureId"] = "ovdrassetid://%s" % tex["T_" + k]
        o["CFrame"]["Position"].update(X=p["position"][0], Y=p["position"][1], Z=p["position"][2])
        o["Size"].update(X=p["size"][0], Y=p["size"][1], Z=p["size"][2])
        o["UnitExtent"].update(X=p["size"][0] / 2, Y=p["size"][1] / 2, Z=-p["size"][2] / 2); tiles += 1
    if o["ActorGuid"] in dy:
        o["CFrame"]["Position"]["Y"] = round(o["CFrame"]["Position"]["Y"] + dy[o["ActorGuid"]], 1); moved += 1
s = json.dumps(root, ensure_ascii=False, indent="\t")
json.loads(s)
io.open(PROJ, "wb").write(s.encode("utf-16"))
print("tiles", tiles, "of", len(place), "re-seated", moved, "of", len(dy))
