"""Blit each file's textures into its 4096 sheet. System Python (PIL), no Blender.

Reads _atlas_plan.json from atlas_pack.py and writes one PNG per export file. The rects were
already solved there; this only resizes each source to its delivered size and pastes it at
the assigned position.

Two things that matter and are easy to get wrong:

  * PAD gutter. Bilinear filtering taps outside a texel's own footprint, so a rect butted
    straight against its neighbour bleeds that neighbour's colour along the seam. Each rect
    was placed with 4 texels of margin and the source's edge rows are smeared into it, which
    is cheaper and more robust than trying to clamp UVs.
  * The source is read from disk at full resolution and resized ONCE, here. The delivered
    size is what prep_image would have shipped, so the atlas is pixel-for-pixel what the
    unatlased delivery carried - repacked, not resampled twice.

    python atlas_bake.py [atlas_dir]
"""
import json
import os
import sys

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
ATLAS = sys.argv[1] if len(sys.argv) > 1 else r"C:\Work\MeshTest\_ATLAS"
SHEET = 4096
PAD = 4


BLEND_DIR = r"C:\Work\blender\Shibuya"
TEXW = r"C:\Work\MeshTest\_texwork_v14"


def resolve(src, mat):
    """Prefer the already-capped EX_ copy, fall back to the blend-relative original.

    _texwork_v14 holds exactly what prep_image would have shipped, so using it means the
    atlas is the delivered pixels repacked rather than the source resampled a second time.
    448 of the 1,016 references resolve there; the remaining 568 have no EX_ copy because
    they were already under the cap, and those come from the .blend's own `//` path.
    """
    ex = os.path.join(TEXW, "EX_" + mat.split('.')[0] + ".png")
    if os.path.exists(ex):
        return ex
    if src.startswith("//"):
        src = os.path.join(BLEND_DIR, src[2:].replace('/', os.sep))
    return src if src and os.path.exists(src) else ""


def bleed(sheet, box, pad):
    """smear the pasted rect's edge rows outward into the gutter"""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return
    left = sheet.crop((x, y, x + 1, y + h)).resize((pad, h))
    sheet.paste(left, (x - pad, y))
    right = sheet.crop((x + w - 1, y, x + w, y + h)).resize((pad, h))
    sheet.paste(right, (x + w, y))
    top = sheet.crop((x - pad, y, x + w + pad, y + 1)).resize((w + 2 * pad, pad))
    sheet.paste(top, (x - pad, y - pad))
    bot = sheet.crop((x - pad, y + h - 1, x + w + pad, y + h)).resize((w + 2 * pad, pad))
    sheet.paste(bot, (x - pad, y + h))


def main():
    plan = json.load(open(os.path.join(ATLAS, "_atlas_plan.json"), encoding="utf-8"))
    print("=== baking %d atlas sheets at %d px" % (len(plan), SHEET))
    done = 0
    missing = []
    for rec in plan:
        if not rec.get("fits") or not rec.get("rects"):
            continue
        name = "ATLAS_%s_%02d.png" % (rec["folder"].split("_", 1)[-1], rec["index"])
        sheet = Image.new("RGB", (SHEET, SHEET), (28, 28, 30))
        n_ok = 0
        for mat, (x, y, w, h) in rec["rects"].items():
            src = resolve(rec["images"].get(mat, ""), mat)
            if not src:
                missing.append((name, mat, rec["images"].get(mat, "")))
                continue
            try:
                im = Image.open(src).convert("RGB")
            except Exception as ex:
                missing.append((name, mat, "%s (%s)" % (src, ex)))
                continue
            if im.size != (w, h):
                im = im.resize((w, h), Image.LANCZOS)
            sheet.paste(im, (x, y))
            bleed(sheet, (x, y, w, h), PAD)
            n_ok += 1
        p = os.path.join(ATLAS, name)
        sheet.save(p, optimize=True)
        done += 1
        print("  %-30s %3d/%3d rects  %6.1f MB" %
              (name, n_ok, len(rec["rects"]), os.path.getsize(p) / 1048576.0))
    print("\n  baked %d sheets | missing sources: %d" % (done, len(missing)))
    for n, m, s in missing[:10]:
        print("     %-24s %-28s %s" % (n, m, s[:70]))
    print("ATLAS BAKE DONE")


if __name__ == "__main__":
    main()
