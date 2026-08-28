"""Resolve a delivered file to the assets a MeshPart actually needs.

This module exists because of a defect that cost a whole placement pass: `MeshPart.MeshId` was
set to the MODEL asset. Studio accepted it, every property read back correctly, the spawner
reported "9986 spawned, 0 failed" - and nothing rendered, because a MODEL is a grouping node
and has no geometry. The tell was `UnitExtent`: it stayed at one inherited value for every
part, and only changed to the mesh's real bounds once a STATIC_MESH id was assigned.

So: a MeshPart needs the STATIC_MESH, not the MODEL. The MODEL is what the importer drops
into Workspace on its own, and it is the only thing that carries a multi-material file
correctly - which is why `texture_ids` is returned in full rather than as one id.

Naming, learned from the table rather than assumed:

    <stem>            MODEL        e.g. BUILDINGS_01_overdare
    <stem>_N          STATIC_MESH  e.g. BUILDINGS_01_overdare_1
    <stem>_T_N        TEXTURE      e.g. BUILDINGS_01_overdare_T_1 .. _T_4

That holds for the single-file import path. The earlier Bulk imports produced STATIC_MESHes
named after the mesh inside the file (TERRAIN_05_EXP_GROUND_c0102) and no MODEL at all; those
are half-imports and are deliberately not resolvable here.

Where a name was published more than once - a retry duplicates rather than replaces - the
highest id wins, which is the most recent upload.
"""
import io
import json
import os
import re

# The delivery is being re-imported into a CLEAN project: `PJ` accumulated 784 rows with the
# same file published up to four times (a retry does not replace, it publishes again), and
# every duplicate competes for the same per-session ceiling. Override with OVERDARE_PROJECT
# to point at a different one.
PROJECT = os.environ.get("OVERDARE_PROJECT", r"C:\Work\SHIBUYA")
TABLE = os.path.join(PROJECT, "UGCLocalAssetTable.json")


def load(table=TABLE):
    if not os.path.exists(table):
        raise SystemExit(
            "no asset table at %s\n"
            "  Nothing has been imported into that project yet - or it does not exist.\n"
            "  Create it in Studio, or point elsewhere with  set OVERDARE_PROJECT=<dir>"
            % table)
    d = json.load(io.open(table, encoding="utf-8"))
    rows = []
    for aid, v in d.get("localAssetList", {}).items():
        try:
            rows.append((int(aid), v.get("name") or "", v.get("worldAssetType") or ""))
        except ValueError:
            continue
    return rows


def resolve(table=TABLE):
    """-> {stem: {"model": id, "mesh": id, "textures": [id, ...]}} for every complete import."""
    rows = load(table)
    models, meshes, textures = {}, {}, {}
    for aid, name, kind in rows:
        if kind == "MODEL":
            models[name] = max(aid, models.get(name, 0))
        elif kind == "STATIC_MESH":
            # Two spellings, both from the single-file path: usually "<stem>_1", but a file
            # whose mesh already carried the stem's name is published as just "<stem>".
            # Matching only the suffixed form silently dropped LANDMARKS_02 from the plan.
            m = re.match(r"^(.*_overdare)_(\d+)$", name)
            stem, idx = (m.group(1), int(m.group(2))) if m else (
                (name, 0) if name.endswith("_overdare") else (None, None))
            if stem:
                meshes.setdefault(stem, {})[idx] = max(aid, meshes.get(stem, {}).get(idx, 0))
        elif kind == "TEXTURE":
            m = re.match(r"^(.*_overdare)_T_(\d+)$", name)
            if m:
                textures.setdefault(m.group(1), {})[int(m.group(2))] = max(
                    aid, textures.get(m.group(1), {}).get(int(m.group(2)), 0))

    out = {}
    for stem, mid in models.items():
        mesh = meshes.get(stem)
        if not mesh:
            continue                       # MODEL without geometry: nothing placeable
        out[stem] = {
            "model": mid,
            # index 1 is the joined mesh; prepare_all makes exactly one per file
            "mesh": mesh[min(mesh)],
            "textures": [textures.get(stem, {})[k] for k in sorted(textures.get(stem, {}))],
        }
    return out


if __name__ == "__main__":
    r = resolve()
    n_tex = sum(len(v["textures"]) for v in r.values())
    multi = {k: len(v["textures"]) for k, v in r.items() if len(v["textures"]) > 1}
    print("resolved %d stems | %d textures total" % (len(r), n_tex))
    print("  with more than one texture: %d  (a MeshPart shows only its TextureId)" % len(multi))
    for k, n in sorted(multi.items(), key=lambda kv: -kv[1])[:8]:
        print("     %-40s %d" % (k, n))
    ex = r.get("BUILDINGS_01_overdare")
    print("\n  sample BUILDINGS_01_overdare -> %s" % ex)
