"""How far the delivery has actually got into OVERDARE, read from the project's asset table.

Studio's own "imported" feedback cannot answer this: Bulk Import publishes a file's textures
and its STATIC_MESH and can then die before the MODEL, and that half-imported state looks
like success in the UI. The MODEL asset is the only marker that means the file is usable.

    python import_status.py [prepared_dir] [asset_table]
"""
import io
import json
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\MeshTest\_PREPARED_V17"
TABLE = sys.argv[2] if len(sys.argv) > 2 else r"C:\Work\PJ\UGCLocalAssetTable.json"


def main():
    d = json.load(io.open(TABLE, encoding="utf-8"))
    types, dupes = {}, {}
    for v in d.get("localAssetList", {}).values():
        n = v.get("name") or ""
        types.setdefault(n, set()).add(v.get("worldAssetType"))
        if v.get("worldAssetType") in ("MODEL", "STATIC_MESH"):
            dupes[n] = dupes.get(n, 0) + 1

    prep = json.load(open(os.path.join(SRC, "_prepared.json"), encoding="utf-8"))
    full, half, absent = [], [], []
    for r in prep:
        stem = r["output"].replace(".fbx", "")
        t = types.get(stem, set())
        (full if "MODEL" in t else half if "STATIC_MESH" in t else absent).append(r)

    n = len(prep)
    print("=== %s" % SRC)
    print("  complete (MODEL present) : %3d / %d   %5.1f%%" % (len(full), n, 100 * len(full) / n))
    print("  half (STATIC_MESH only)  : %3d        <- unusable, must be re-imported" % len(half))
    print("  not imported             : %3d" % len(absent))
    print("  assets still to publish  : %3d"
          % sum(r["materials"] + 2 for r in half + absent))

    if half:
        print("\n  half-imported:")
        for r in sorted(half, key=lambda x: x["output"]):
            print("     %-40s %2d materials" % (r["output"].replace("_overdare.fbx", ""),
                                                r["materials"]))
    over = {k: c for k, c in dupes.items() if c > 1 and k.endswith("_overdare")}
    if over:
        print("\n  published more than once (retries do not replace, they duplicate):")
        for k, c in sorted(over.items(), key=lambda kv: -kv[1])[:10]:
            print("     %-40s %d entries" % (k, c))
    print("\n  total rows in the asset table: %d" % len(d.get("localAssetList", {})))


if __name__ == "__main__":
    main()
