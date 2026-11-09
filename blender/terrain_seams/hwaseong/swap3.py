# -*- coding: utf-8 -*-
r"""After the TER3/OUT3 import: map the 30 live tile instances (swap_plan.json guids) to the new mesh/texture IDs.
Usage: python swap3.py [UGCLocalAssetTable.json]  ->  _rebatch_tiles3\swap_plan3.json"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hws_place import load_table

OUT = r"C:\Work\blender\ovdr_export\hwaseong_v25"
TABLE = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\onlyonetap\UGCLocalAssetTable.json"
ids = load_table(TABLE); tex = ids.pop("__tex__", {})
old = json.load(io.open(os.path.join(OUT, "_rebatch_tiles2", "swap_plan.json"), encoding="utf-8"))
plan, miss = [], []
for r in old:
    new = r["name"].replace("HWS_TER_", "HWS_TER3_").replace("HWS_OUT_", "HWS_OUT3_")
    m, t = ids.get(new), tex.get("T_" + new)
    if not m or not t:
        miss.append(new); continue
    plan.append({"guid": r["guid"], "name": r["name"], "meshId": "ovdrassetid://%s" % m, "textureId": "ovdrassetid://%s" % t})
json.dump(plan, io.open(os.path.join(OUT, "_rebatch_tiles3", "swap_plan3.json"), "w", encoding="utf-8"), indent=1)
print("resolved", len(plan), "missing", miss)
