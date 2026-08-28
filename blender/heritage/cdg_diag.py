import bpy, os, re, collections
V=r"C:\Work\blender\CDG_Changdeokgung\20_ARCHITECTURE\CDG_Master_view.blend"
bpy.ops.wm.open_mainfile(filepath=V)
print("collections:", [c.name for c in bpy.data.scenes[0].collection.children])
g=bpy.data.collections.get("30_GROUND")
print("30_GROUND objects:", len(g.objects) if g else "MISSING")
bad=[i for i in bpy.data.images if i.name not in ("Render Result","Viewer Node") and not i.has_data and not i.packed_file]
print("images total:", len(bpy.data.images), " no-data:", len(bad))
for i in bad[:8]:
    print("   ", repr(i.name), "|", i.filepath)
sfx=collections.Counter()
for i in bpy.data.images:
    m=re.search(r"\.(\d{3})$", i.name)
    sfx["dupsuffix" if m else "plain"]+=1
print(dict(sfx))
