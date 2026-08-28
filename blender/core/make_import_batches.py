"""Split a prepared delivery into import batches and Studio sessions.

Two independent limits govern how much can be imported at once, and they are NOT the same
limit - conflating them is what produced four import crashes:

  * VRAM, per BATCH.  The importer decompresses every embedded texture at once. 386 embedded
    copies decompressing to 699 MB is what OOM'd it. A batch is therefore capped on
    `tex_vram_mb` (w*h*4 summed), not on file size - a 4096 atlas sheet is 8 MB on disk and
    64 MB decompressed, an eightfold difference that file size hides completely.

  * The transient-world leak, per SESSION.  Studio's importer creates a transient world named
    "Untitled" per PUBLISHED ASSET and never frees it, until either unique-name generation
    fails (LevelActor.cpp:583, "Cannot generate unique name for MetaBaseWorldSettings in
    /Engine/Transient.Untitled") or the object array collides (UObjectArray.cpp:234,
    "Attempting to add Untitled at index N"). Same root cause, two failure modes.

    A PUBLISHED ASSET IS NOT A FILE AND NOT A MATERIAL. Measured from UGCLocalAssetTable.json:
    one TEXTURE per material, one STATIC_MESH per file, and - on the single-file path only -
    one MODEL per file. Costing a batch in materials alone under-counts it; BATCH_01 was sized
    as 20 and was really 30.

    And the ceiling is per PATH, not a constant. See the table above ASSETS_PER_SESSION.

Batches are laid out first-fit-decreasing on VRAM, then packed into sessions on units. Files
are copied, not moved, so the prepared tree stays intact and this can be re-run.

    python make_import_batches.py [prepared_dir] [out_dir]
"""
import json
import os
import shutil
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\MeshTest\_PREPARED_V17"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"C:\Work\MeshTest\_IMPORT_V17"
# The project's own asset table, read to skip what is already in. Pass "" to plan from scratch.
TABLE = sys.argv[3] if len(sys.argv) > 3 else r"C:\Work\PJ\UGCLocalAssetTable.json"

# Measured 2026-08-04 over twelve real imports into this project, split by which import path
# was used (they are distinguishable after the fact: only the single-file path publishes a
# MODEL asset):
#
#     Bulk Import      26 · 24 · 21 · 25 · 18 assets   -> every one crashed
#     single-file      12 ·  3 ·  3 · 31 ·  3 · 34 · 20
#
# Texture volume is not the driver - a 74 MB batch died sooner than a 400 MB one - and the
# ceiling is not a constant either: it depends on the path. Bulk never got past 26 and the
# last attempt died at 18, while single-file reached 34. So: import ONE FILE AT A TIME.
#
# Cost per file differs too, which is why the same delivery is a different number of assets
# on each path:
#     bulk         assets = materials + 1   (textures + STATIC_MESH, no MODEL)
#     single-file  assets = materials + 2   (textures + STATIC_MESH + MODEL)
# 34 is the largest single-file session observed to finish. The number matters less than it
# looks, though: completion is tracked per file by its MODEL asset, so a crash mid-session
# costs one restart and a re-run of this script - it will skip everything already complete.
# Predicting the ceiling exactly is not worth another experiment when resuming is cheap.
ASSETS_PER_SESSION = 34
FILES_PER_BATCH = 10     # keeps one session's list short enough to work through by hand
VRAM_PER_BATCH = 400.0   # MB decompressed, sanity bound only
ASSETS_PER_FILE_OVERHEAD = 2  # STATIC_MESH + MODEL, per the single-file path


def pack(items, keys_caps, count_cap=None):
    """first-fit-decreasing against SEVERAL simultaneous caps.

    Several, because one cap is never enough here: a batch that fits the VRAM budget can still
    carry more import units than a whole session may spend, and then the session cap silently
    does nothing. keys_caps is [(key_fn, cap), ...] and every one must hold.
    """
    prim = keys_caps[0][0]
    bins = []
    for it in sorted(items, key=lambda x: -prim(x)):
        for b in bins:
            if count_cap is not None and len(b) >= count_cap:
                continue
            if all(sum(k(y) for y in b) + k(it) <= c for k, c in keys_caps):
                b.append(it)
                break
        else:
            bins.append([it])
    return bins


def already_imported(table):
    """Stems whose STATIC_MESH or MODEL is already in the project's asset table.

    Re-importing a file does not replace its asset, it publishes a SECOND one - this project
    carries BUILDINGS_15_overdare four times because the same batch was retried three times,
    and every duplicate is another published asset competing for the same session ceiling. So
    a resumed plan must skip what is already in rather than start from the top.
    """
    if not table or not os.path.exists(table):
        return set()
    with open(table, encoding="utf-8") as f:
        d = json.load(f)
    # MODEL is the completion marker, not STATIC_MESH. Bulk Import publishes the textures
    # and the mesh and then dies before the MODEL, so a STATIC_MESH on its own is a HALF
    # import - SF_TrafficSignal_A and UP_UtilityPole_A are sitting in this project exactly
    # that way. Treating those as done is how a resumed plan silently skips broken assets.
    return {
        v["name"]
        for v in d.get("localAssetList", {}).values()
        if v.get("worldAssetType") == "MODEL" and v.get("name")
    }


def main():
    recs = json.load(open(os.path.join(SRC, "_prepared.json"), encoding="utf-8"))
    done = already_imported(TABLE)
    if done:
        before = len(recs)
        recs = [r for r in recs if r["output"].replace(".fbx", "") not in done]
        print("  already in the asset table: %d file(s) skipped, %d to go"
              % (before - len(recs), len(recs)))
    # UCX_* are collision hulls. In Unreal that prefix means "the convex hull for the render
    # mesh IN THIS SAME FILE", so as standalone files they have nothing to attach to and the
    # importer rejects all five. They were rejected once already; shipping them in the import
    # plan just sends the user into a dead end per session.
    ucx = [r for r in recs if r["output"].startswith("UCX_")]
    if ucx:
        recs = [r for r in recs if not r["output"].startswith("UCX_")]
        print("  excluded %d UCX_ collider file(s) - not importable standalone" % len(ucx))
    for r in recs:
        r["path"] = os.path.join(SRC, r.get("folder") or "", r["output"])
    missing = [r for r in recs if not os.path.exists(r["path"])]
    if missing:
        print("  !! %d prepared files listed in the manifest are not on disk" % len(missing))
        for r in missing[:5]:
            print("       %s" % r["path"])
        recs = [r for r in recs if os.path.exists(r["path"])]

    # A single file over the batch cap still has to go somewhere - it becomes its own batch.
    # one batch per session now: the ceiling is per Studio process, and a session that can
    # only afford ~18 assets has no room for a second batch anyway
    for r in recs:
        r["assets"] = r["materials"] + ASSETS_PER_FILE_OVERHEAD
    batches = pack(recs,
                   [(lambda r: r["assets"], ASSETS_PER_SESSION),
                    (lambda r: r["tex_vram_mb"], VRAM_PER_BATCH)],
                   FILES_PER_BATCH)
    batches.sort(key=lambda b: -sum(r["assets"] for r in b))
    sessions = [[b] for b in batches]

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    plan = []
    n = 0
    for si, sess in enumerate(sessions, 1):
        for b in sess:
            n += 1
            name = "BATCH_%02d" % n
            d = os.path.join(OUT, "SESSION_%02d" % si, name)
            os.makedirs(d, exist_ok=True)
            for r in b:
                shutil.copy2(r["path"], os.path.join(d, r["output"]))
            plan.append({"session": si, "batch": name,
                         "files": [r["output"] for r in b],
                         "assets": sum(r["assets"] for r in b),
                         "vram_mb": round(sum(r["tex_vram_mb"] for r in b), 1),
                         "tris": sum(r["tris_out"] for r in b),
                         "size_mb": round(sum(r["size_mb"] for r in b), 1)})
    json.dump(plan, open(os.path.join(OUT, "_import_plan.json"), "w"), indent=1)

    print("=== %d files -> %d batches in %d Studio sessions" % (len(recs), n, len(sessions)))
    print("    <= %d published assets per batch, one batch per Studio session, <= %d files"
          % (ASSETS_PER_SESSION, FILES_PER_BATCH))
    print("\n  %-10s %-10s %5s %6s %9s %8s" % ("session", "batch", "files", "assets",
                                               "vram MB", "tris"))
    for si in range(1, len(sessions) + 1):
        rows = [p for p in plan if p["session"] == si]
        for p in rows:
            print("  %-10d %-10s %5d %6d %9.0f %8s"
                  % (si, p["batch"], len(p["files"]), p["assets"], p["vram_mb"],
                     format(p["tris"], ',')))
        print("  %-10s %-10s %5d %6d %9.0f %8s" %
              ("", "-> session", sum(len(p["files"]) for p in rows),
               sum(p["assets"] for p in rows), sum(p["vram_mb"] for p in rows),
               format(sum(p["tris"] for p in rows), ',')))
    print("\n  totals: %d files, %d units, %.0f MB VRAM, %s tris"
          % (len(recs), sum(p["assets"] for p in plan),
             sum(p["vram_mb"] for p in plan),
             format(sum(p["tris"] for p in plan), ',')))
    print("  Import ONE FILE AT A TIME (Home > Import), not Bulk Import - see the header.")
    print("  RESTART OVERDARE Studio between sessions - the leak only resets on restart.")
    print("BATCHES DONE")


if __name__ == "__main__":
    main()
