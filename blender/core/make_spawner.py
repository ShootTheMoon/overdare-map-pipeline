"""Generate the runtime spawner for the instanced half of the map.

The map splits in two and only one half belongs in the editor:

  STATIC    39 files baked in world coordinates - the ground, buildings, roads, station,
            viaduct, landmarks. These ARE the map's skeleton, they are placed once, and you
            want to see and select them in Studio. Already placed as MeshParts.
  INSTANCED 66 masters cloned ~10,000 times (core) or ~43,500 times (full). Writing those
            into the .ovdrjm costs 3,843 bytes each - 37 MB for the core set, 160 MB for the
            full one - and every subsequent edit has to read and rewrite that file. They are
            signboards and paving tiles; nobody opens Studio to nudge one.

So the clones are spawned at runtime from a data table instead. The CFrame recipe is the one
verified in PLACEMENT_GUIDE.md, including the trap that the CSV Y is the asset's BASE while a
CFrame is its CENTRE.

    python make_spawner.py [out_dir] [--core] [--rows-per-module 2500]

Writes ShibuyaPlacements_N.lua (data) + ShibuyaSpawner.lua (the loop) ready for
overdare_script_add.
"""
import csv
import io
import json
import os
import sys

MT = r"C:\Work\MeshTest"
DELIVERY = os.path.join(MT, "Shibuya_OVERDARE_v17")
TABLE = r"C:\Work\PJ\UGCLocalAssetTable.json"

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = argv[0] if argv else os.path.join(MT, "_SPAWNER")
CORE = "--core" in sys.argv
ROWS = 2500
for i, a in enumerate(sys.argv):
    if a == "--rows-per-module" and i + 1 < len(sys.argv):
        ROWS = int(sys.argv[i + 1])


def model_ids():
    """prepared stem -> {mesh, textures}. NOT the MODEL id.

    A MeshPart renders its STATIC_MESH. Pointing MeshId at the MODEL asset made the first
    spawner run report "9986 spawned, 0 failed" and draw nothing at all, because a MODEL is a
    grouping node with no geometry. See asset_resolve.py.
    """
    sys.path.insert(0, MT)
    from asset_resolve import resolve
    return resolve(TABLE)


SPAWNER = """--[[ ShibuyaSpawner - clone the instanced half of the map at runtime.

Why this is not editor geometry: %(n)d clones would add ~%(mb).0f MB to the .ovdrjm, and every
later edit has to rewrite that whole file. The static half - ground, buildings, roads,
station, landmarks - IS placed in the editor. This covers only the masters that exist to be
repeated: sign rails, window and storefront modules, tactile paving.

The data is packed as one string per master rather than a table per placement because the
source has to travel through a tool call to reach Studio; a Lua table per row came to 720 KB.
Coordinates are whole centimetres and yaw whole degrees - a millimetre of precision on a
signboard is not visible, and rounding cut the payload by two thirds.

Two things here are load-bearing, both established by measurement rather than assumption:

  * The packed y is already the mesh's bbox CENTRE - the generator applied the offset,
    because it is (bbox_min.z + bbox_max.z)/2 and NOT half the height. Those agree only when
    a master's pivot sits at its base; the signboard stacks start 0.35 m up and the
    shopfronts 0.10 m up, so half-height put 2,954 placements 1.7 m out.
  * Size must be assigned explicitly. Left alone it stores 0 and the part never renders,
    while every other property reads back correctly - a silent, invisible failure.
]]
local RS = game:GetService("ReplicatedStorage")
local MODULES = { %(mods)s }

local root = Instance.new("Folder")
root.Name = "SHIBUYA_INSTANCED"
root.Parent = workspace

-- Clones left in Workspace by the earlier editor-side experiment. Leaving them would double
-- every prop they cover; they are recognisable by the four-digit suffix the placement pass
-- gave them, which the static placements (two digits) do not have.
local swept = 0
for _, o in ipairs(workspace:GetChildren()) do
	if o ~= root and string.match(o.Name, "_%%d%%d%%d%%d$") then
		o:Destroy()
		swept = swept + 1
	end
end

local made, failed = 0, 0
for _, name in ipairs(MODULES) do
	local ok, groups = pcall(function() return require(RS:WaitForChild(name, 10)) end)
	if not ok then
		warn("[Shibuya] missing data module " .. name)
	else
		for _, g in ipairs(groups) do
			local meshId, texId, sx, sy, sz, packed = g[1], g[2], g[3], g[4], g[5], g[6]
			local size = Vector3.new(sx, sy, sz)
			for x, y, z, yaw in string.gmatch(packed, "(-?%%d+),(-?%%d+),(-?%%d+),(-?%%d+)") do
				local p = Instance.new("MeshPart")
				local good = pcall(function()
					p.MeshId = meshId
					if texId ~= "" then p.TextureId = texId end
					p.Size = size
					p.Anchored = true
					p.CanCollide = false
					p.CFrame = CFrame.new(tonumber(x), tonumber(y), tonumber(z))
						* CFrame.Angles(0, math.rad(tonumber(yaw)), 0)
				end)
				if good then
					p.Parent = root
					made = made + 1
				else
					p:Destroy()
					failed = failed + 1
				end
			end
		end
	end
end
print(string.format("[Shibuya] swept %%d stale, spawned %%d, failed %%d", swept, made, failed))
"""


def main():
    ids = model_ids()
    masters = {m["master"]: m for m in
               json.load(io.open(os.path.join(DELIVERY, "_manifest_masters.json"),
                                 encoding="utf-8"))}
    csv_name = "placements_core120m.csv" if CORE else "placements.csv"
    with io.open(os.path.join(DELIVERY, csv_name), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Group by master: the meshId and the size are per-master constants, so repeating them on
    # every one of ~10,000 rows was most of the payload.
    groups, skipped = {}, {}
    for r in rows:
        m = r["master"]
        man, a = masters.get(m), ids.get(m + "_overdare")
        if not man or not a:
            skipped[m] = "not fully imported" if man else "not in the masters manifest"
            continue
        lo, hi = man["bbox_min"], man["bbox_max"]
        g = groups.setdefault(m, {
            "mesh": "ovdrassetid://%d" % a["mesh"],
            "tex": ("ovdrassetid://%d" % a["textures"][0]) if a["textures"] else "",
            "size": (max((hi[0]-lo[0])*100, 1.0), max((hi[2]-lo[2])*100, 1.0),
                     max((hi[1]-lo[1])*100, 1.0)),
            "rows": []})
        # Ship the CENTRE height, already offset, rather than the base. The Lua side used to
        # add sy/2, which is only the bbox centre when the master's pivot is its base - false
        # for every signboard stack and shopfront, 2,954 of 9,995 placements.
        g["rows"].append("%d,%d,%d,%d" % (
            round(float(r["X"])),
            round(float(r["Y"]) + (lo[2] + hi[2]) / 2.0 * 100.0),
            round(float(r["Z"])), round(float(r["yaw_deg"]))))
    n_rows = sum(len(g["rows"]) for g in groups.values())

    os.makedirs(OUT, exist_ok=True)
    for n in os.listdir(OUT):
        if n.endswith(".lua"):
            os.remove(os.path.join(OUT, n))

    # Split on ROWS placements, not on masters: one master can hold 3,594 of them.
    mods, chunk, chunk_rows, idx = [], [], 0, 1

    def flush():
        nonlocal chunk, chunk_rows, idx
        if not chunk:
            return
        name = "ShibuyaPlacements_%d" % idx
        header = ("-- %d placements. Each entry: "
                  "{meshId, textureId, sx, sy, sz, \"x,y_CENTRE,z,yaw|...\"}")
        body = "\n".join([header % chunk_rows, "return {", ",\n".join(chunk), "}", ""])
        io.open(os.path.join(OUT, name + ".lua"), "w", encoding="utf-8").write(body)
        mods.append(name)
        chunk, chunk_rows, idx = [], 0, idx + 1

    for m, g in sorted(groups.items()):
        pending = g["rows"]
        while pending:
            room = max(1, ROWS - chunk_rows)
            take, pending = pending[:room], pending[room:]
            chunk.append('{"%s","%s",%.1f,%.1f,%.1f,"%s"}'
                         % (g["mesh"], g["tex"], g["size"][0], g["size"][1], g["size"][2],
                            "|".join(take)))
            chunk_rows += len(take)
            if chunk_rows >= ROWS:
                flush()
    flush()

    io.open(os.path.join(OUT, "ShibuyaSpawner.lua"), "w", encoding="utf-8").write(
        SPAWNER % {"n": n_rows, "mb": n_rows * 3843 / 1048576.0,
                   "mods": ", ".join('"%s"' % m for m in mods)})
    out_rows = [None] * n_rows

    print("=== %s  (%s)" % (OUT, csv_name))
    print("  placements   : %d in %d master group(s)" % (len(out_rows), len(groups)))
    print("  data modules : %d  (<=%d placements each)" % (len(mods), ROWS))
    print("  .ovdrjm saved: ~%.0f MB by not placing these in the editor"
          % (len(out_rows) * 3843 / 1048576.0))
    for m in mods:
        print("     %-26s %6.0f KB" % (m + ".lua",
                                       os.path.getsize(os.path.join(OUT, m + ".lua")) / 1024))
    if skipped:
        print("\n  skipped: %s" % ", ".join("%s (%s)" % kv for kv in sorted(skipped.items())))
    print("\nSPAWNER DONE")


if __name__ == "__main__":
    main()
