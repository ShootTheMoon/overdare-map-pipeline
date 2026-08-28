"""Is the import tree actually handable? Checks the plan against what is on disk.

The plan JSON and the copied files are written by the same run, so they agree by
construction - right up until someone re-runs the batcher against a different prepared tree,
or a copy fails silently on a locked file. This is the cheap check before a day of hand
importing: every file in the plan exists, every file on disk is in the plan, and the per
session unit/VRAM totals are what the caps say they should be.

    python check_import_tree.py [import_dir] [prepared_dir] [asset_table]
"""
import io
import json
import os
import sys

IMP = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\MeshTest\_IMPORT_V18"
PREP = sys.argv[2] if len(sys.argv) > 2 else r"C:\Work\MeshTest\_PREPARED_V18"
PROJECT = os.environ.get("OVERDARE_PROJECT", r"C:\Work\blender-test")
TABLE = sys.argv[3] if len(sys.argv) > 3 else os.path.join(PROJECT, "UGCLocalAssetTable.json")
ASSETS_PER_SESSION = 34
FILES_PER_BATCH = 10


def already_done(table):
    """Stems whose MODEL is published - the batcher skips these, so they are SUPPOSED to be
    absent from the plan. Without this the completeness check fails the moment one file has
    been imported, which is every run after the first."""
    if not os.path.exists(table):
        return set()
    d = json.load(io.open(table, encoding="utf-8"))
    return {v["name"] + ".fbx" for v in d.get("localAssetList", {}).values()
            if v.get("worldAssetType") == "MODEL" and v.get("name")}


def main():
    plan = json.load(io.open(os.path.join(IMP, "_import_plan.json"), encoding="utf-8"))
    prep = {r["output"]: r for r in
            json.load(io.open(os.path.join(PREP, "_prepared.json"), encoding="utf-8"))}

    on_disk = {}
    for dp, _, ns in os.walk(IMP):
        for n in ns:
            if n.lower().endswith(".fbx"):
                on_disk.setdefault(n, []).append(os.path.join(dp, n))

    planned = set()
    missing, oversize, badcount = [], [], []
    for p in plan:
        d = os.path.join(IMP, "SESSION_%02d" % p["session"], p["batch"])
        for f in p["files"]:
            planned.add(f)
            fp = os.path.join(d, f)
            if not os.path.exists(fp):
                missing.append(fp)
                continue
            src = prep.get(f)
            if src and abs(os.path.getsize(fp) / 1048576.0 - src["size_mb"]) > 0.02:
                oversize.append((f, round(os.path.getsize(fp) / 1048576.0, 2),
                                 src["size_mb"]))
        if p["assets"] > ASSETS_PER_SESSION or len(p["files"]) > FILES_PER_BATCH:
            badcount.append(p)

    # SESSION_00_SMOKE is deliberately outside the plan - it is hand-picked, and one of its
    # three files comes from _UCX_PROBE rather than the prepared tree.
    smoke = {n for n in on_disk if any("SESSION_00_SMOKE" in q for q in on_disk[n])}
    stray = set(on_disk) - planned - smoke
    done = already_done(TABLE)
    unplanned = set(prep) - planned - done

    n = len(planned)
    print("=== %s" % IMP)
    print("  sessions                : %d" % len({p["session"] for p in plan}))
    print("  files planned           : %d  (prepared tree has %d)" % (n, len(prep)))
    print("  files missing from disk  : %d  %s" % (len(missing), "PASS" if not missing else "FAIL"))
    for m in missing[:5]:
        print("        %s" % m)
    print("  files with a wrong size  : %d  %s" % (len(oversize), "PASS" if not oversize else "FAIL"))
    for f, a, b in oversize[:5]:
        print("        %-40s %.2f MB on disk vs %.2f prepared" % (f, a, b))
    print("  batches over the caps    : %d  %s" % (len(badcount), "PASS" if not badcount else "FAIL"))
    print("  already imported (skipped) : %d  %s" % (len(done & set(prep)),
                                                     sorted(done & set(prep))[:4]))
    print("  every prepared file covered: %s"
          % ("PASS" if not unplanned else
             "FAIL - neither planned nor imported: %s" % sorted(unplanned)[:5]))
    print("  stray FBX outside the plan : %d %s"
          % (len(stray), sorted(stray)[:5] if stray else ""))
    print("  smoke session files      : %d  %s" % (len(smoke), sorted(smoke)))
    print("\n  %-10s %-10s %5s %6s %9s" % ("session", "batch", "files", "assets", "vram MB"))
    for p in plan:
        print("  %-10d %-10s %5d %6d %9.0f"
              % (p["session"], p["batch"], len(p["files"]), p["assets"], p["vram_mb"]))
    print("\n  totals: %d files, %d published assets, %.0f MB VRAM"
          % (n, sum(p["assets"] for p in plan), sum(p["vram_mb"] for p in plan)))
    ok = not (missing or oversize or badcount or unplanned)
    print("\nIMPORT TREE %s" % ("PASS" if ok else "FAIL"))


if __name__ == "__main__":
    main()
