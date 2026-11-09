# -*- coding: utf-8 -*-
r"""After the SGK6 import (Studio saved): replace Sangok's 12 STA_TER_ij + 6 STA_WALL_* with 30 STA_TER6_ij in
onlyoneshot.ovdrjm (clones of the live STA_TER_00: same orientation/material/flags, new guid/ObjectKey, mesh, texture,
position, size, UnitExtent = half size). Backup .bak_sgk6, then overdare_apply.
Usage: python sgk6_patch.py [UGCLocalAssetTable.json]"""
import io, json, os, re, shutil, sys, uuid, copy
sys.path.insert(0, r"C:\Work\blender\hwaseong_rebuild\v25")
from hws_place import load_table

D = r"C:\Work\blender\JSN_Sangok2\06_OVERDARE\_rebatch_sgk6"
PROJ = r"C:\Work\onlyonetap\onlyoneshot.ovdrjm"
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
place = json.load(io.open(os.path.join(D, "place_sgk6.json"), encoding="utf-8"))
miss = [n for n in place if not ids.get(n) or not tex.get("T_" + n)]
if miss:
    sys.exit("not imported yet: %s" % miss)
shutil.copy2(PROJ, PROJ + ".bak_sgk6")
root = json.loads(io.open(PROJ, "rb").read().decode("utf-16"))
OLD = re.compile(r"STA_TER_\d\d$|STA_WALL_(N1|N2|S1|S2|E|W)$")


def lists(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from lists(v)
    elif isinstance(o, list):
        yield o
        for v in o:
            yield from lists(v)


def walk(o):
    if isinstance(o, dict):
        if "ActorGuid" in o:
            yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


objs = list(walk(root)); maxkey = max(o.get("ObjectKey", 0) for o in objs)
tpl = next(o for o in objs if o.get("Name") == "STA_TER_00")
home = next(l for l in lists(root) if any(x is tpl for x in l))
old = [x for x in home if isinstance(x, dict) and OLD.match(x.get("Name", ""))]
if len(old) != 18:
    sys.exit("expected 18 old Sangok tiles/walls in one list, found %d" % len(old))
new = []
for n, p in sorted(place.items()):
    maxkey += 1; o = copy.deepcopy(tpl)
    o["Name"] = n.replace("SGK6_TER_", "STA_TER6_"); o["ActorGuid"] = uuid.uuid4().hex.upper(); o["ObjectKey"] = maxkey
    o["MeshId"] = "ovdrassetid://%s" % ids[n]; o["TextureId"] = "ovdrassetid://%s" % tex["T_" + n]
    o["CFrame"]["Position"].update(X=p["position"][0], Y=p["position"][1], Z=p["position"][2])
    o["Size"].update(X=p["size"][0], Y=p["size"][1], Z=p["size"][2])
    o["UnitExtent"].update(X=p["size"][0] / 2, Y=p["size"][1] / 2, Z=-p["size"][2] / 2)
    new.append(o)
home[:] = [x for x in home if not any(x is y for y in old)] + new
s = json.dumps(root, ensure_ascii=False, indent="\t")
objs2 = list(walk(json.loads(s)))
assert len({o["ActorGuid"] for o in objs2}) == len(objs2)
io.open(PROJ, "wb").write(s.encode("utf-16"))
print("removed", len(old), "added", len(new), "STA_TER6", sum(1 for o in objs2 if o.get("Name", "").startswith("STA_TER6_")))
