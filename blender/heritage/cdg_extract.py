# -*- coding: utf-8 -*-
"""
CDG Changdeokgung - stage 1: extract the 17 KHS zips.

Design notes (all verified against the actual archives before writing this):
  * The FBX inside each zip EMBEDS its textures, and the same textures are also
    present as loose PNGs.  We extract only the loose PNGs and never let Blender
    unpack the embedded copies (that would cost 4.0 GB of .fbm folders).
  * Textures are shared across buildings byte-for-byte: 1,011 instances collapse
    to 304 unique files.  Verified: no filename ever maps to two different CRCs,
    so a flat basename-keyed library is safe.  Saves 3,295 MB.
  * Resumable / idempotent: an already-extracted file with the right size is
    skipped, so a crash or a bluescreen costs nothing.

Run with system Python (not Blender's):
    python cdg_extract.py            # all waves
    python cdg_extract.py 1          # wave 1 only
"""
import json
import os
import sys
import zipfile

ROOT = r"C:\Work\blender\CDG_Changdeokgung"
SRC = r"C:\Work\국가유산_3D_건조물"
OUT_FBX = os.path.join(ROOT, "_extracted", "FBX")
OUT_TEX = os.path.join(ROOT, "_extracted", "_TexLib")
MANIFEST = os.path.join(ROOT, "_extracted", "SOURCE_MANIFEST.json")

# key -> (zip filename, wave).  Waves keep a failure from costing the whole 7.4 GB.
ASSETS = [
    # wave 1: the small Seonwonjeon buildings - cheapest full pipeline pass
    ("BukJinseolcheong", "사적_창덕궁_구선원전_북진설청_원본.zip", 1),
    ("Naejaesil",        "사적_창덕궁_구선원전_내재실_원본.zip", 1),
    ("Naechildang",      "사적_창덕궁_구선원전_내칠당_원본.zip", 1),
    ("SeoJinseolcheong", "사적_창덕궁_구선원전_서진설청_원본.zip", 1),
    ("Yangjidang",       "사적_창덕궁_구선원전_양지당_원본.zip", 1),
    # wave 2: the heroes
    ("Injeongjeon",      "국보_창덕궁_인정전_원본.zip", 2),
    ("Seonwonjeon",      "보물_창덕궁_구선원전_원본.zip", 2),
    ("Injeongmun",       "보물_창덕궁_인정문_원본.zip", 2),
    ("Jinseonmun",       "사적_창덕궁_인정전_진선문_원본.zip", 2),
    ("Sukjangmun",       "사적_창덕궁_인정전_숙장문_원본.zip", 2),
    # wave 3: corridors and the rest
    ("CorridorOuter",    "사적_창덕궁_인정전_인정전외행각_원본.zip", 3),
    ("CorridorE",        "사적_창덕궁_인정전_인정전동행각_원본.zip", 3),
    ("CorridorW",        "사적_창덕궁_인정전_인정전서행각_원본.zip", 3),
    ("JinseonmunL",      "사적_창덕궁_인정전_진선문좌행각_원본.zip", 3),
    ("SeonwonjeonS",     "사적_창덕궁_구선원전_남행각및억석루_원본.zip", 3),
    ("YangjidangGak",    "사적_창덕궁_구선원전_양지당행각_원본.zip", 3),
    ("Uipunggak",        "사적_창덕궁_구선원전_의풍각_원본.zip", 3),
    # wave 4: Gwollaegaksa compound + remaining Injeongjeon-zone buildings
    ("Gyujanggak", "사적_창덕궁_궐내각사_규장각_원본.zip", 4),
    ("GyujanggakGate", "사적_창덕궁_궐내각사_규장각문간채_원본.zip", 4),
    ("Bongmodang", "사적_창덕궁_궐내각사_봉모당_원본.zip", 4),
    ("Chaekgo1", "사적_창덕궁_궐내각사_책고1_원본.zip", 4),
    ("Chaekgo2", "사적_창덕궁_궐내각사_책고2_원본.zip", 4),
    ("Chaekgo3", "사적_창덕궁_궐내각사_책고3_원본.zip", 4),
    ("Unhanmun", "사적_창덕궁_궐내각사_운한문_원본.zip", 4),
    ("Naegak", "사적_창덕궁_궐내각사_내각_원본.zip", 4),
    ("Geomseocheong", "사적_창덕궁_궐내각사_검서청_원본.zip", 4),
    ("GeomseocheongX", "사적_창덕궁_궐내각사_검서청부속채_원본.zip", 4),
    ("Manumun", "사적_창덕궁_궐내각사_만우문_원본.zip", 4),
    ("Yeonguisa", "사적_창덕궁_궐내각사_영의사_원본.zip", 4),
    ("Okdang", "사적_창덕궁_궐내각사_옥당_원본.zip", 4),
    ("OkdangS", "사적_창덕궁_궐내각사_옥당_남행각_등영루_원본.zip", 4),
    ("Yakbang", "사적_창덕궁_궐내각사_약방_원본.zip", 4),
    ("YakbangE", "사적_창덕궁_궐내각사_약방_동행각_원본.zip", 4),
    ("JeongcheongX", "사적_창덕궁_궐내각사_정청부속채_원본.zip", 4),
    ("Gyeongchumun", "사적_창덕궁_궐내각사_경추문_원본.zip", 4),
    ("Unnamed1", "사적_창덕궁_궐내각사_무명1_원본.zip", 4),
    ("Unnamed2", "사적_창덕궁_궐내각사_무명2_원본.zip", 4),
    ("Unnamed3", "사적_창덕궁_궐내각사_무명3_원본.zip", 4),
    ("Hyangsil", "사적_창덕궁_인정전_향실_원본.zip", 4),
    ("HyangsilX", "사적_창덕궁_인정전_향실부속건물_원본.zip", 4),
    ("Yemungwan", "사적_창덕궁_인정전_예문관_원본.zip", 4),
    ("Eochago", "사적_창덕궁_인정전_어차고_원본.zip", 4),
]


def extract_member(z, info, dest):
    """Write one member unless an identical-size file is already there."""
    if os.path.exists(dest) and os.path.getsize(dest) == info.file_size:
        return False
    tmp = dest + ".part"
    with z.open(info) as fsrc, open(tmp, "wb") as fdst:
        while True:
            chunk = fsrc.read(1 << 22)
            if not chunk:
                break
            fdst.write(chunk)
    os.replace(tmp, dest)
    return True


def main():
    waves = {int(a) for a in sys.argv[1:] if a.isdigit()} or {1, 2, 3, 4}
    os.makedirs(OUT_FBX, exist_ok=True)
    os.makedirs(OUT_TEX, exist_ok=True)

    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)

    tex_written = tex_skipped = 0
    for key, zipname, wave in ASSETS:
        if wave not in waves:
            continue
        path = os.path.join(SRC, zipname)
        if not os.path.exists(path):
            print("MISSING ZIP:", zipname)
            continue

        z = zipfile.ZipFile(path)
        fbx_info = next(i for i in z.infolist()
                        if i.filename.lower().endswith(".fbx"))
        fbx_dest = os.path.join(OUT_FBX, key + ".fbx")
        wrote = extract_member(z, fbx_info, fbx_dest)

        textures = []
        for i in z.infolist():
            if not i.filename.lower().endswith(".png"):
                continue
            base = i.filename.rsplit("/", 1)[-1]
            if ".mayaSwatches" in i.filename:
                continue
            dest = os.path.join(OUT_TEX, base)
            if extract_member(z, i, dest):
                tex_written += 1
            else:
                tex_skipped += 1
            textures.append(base)

        manifest[key] = {
            "zip": zipname,
            "fbx": key + ".fbx",
            "fbx_src_name": fbx_info.filename,
            "fbx_bytes": fbx_info.file_size,
            "wave": wave,
            "textures": sorted(set(textures)),
        }
        print("[w{}] {:<18} fbx {:>7.1f} MB {:<8} textures {:>3}".format(
            wave, key, fbx_info.file_size / 1048576,
            "(new)" if wrote else "(cached)", len(set(textures))))

        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)

    print("\ntextures: {} new, {} already present".format(tex_written, tex_skipped))
    tex_total = sum(os.path.getsize(os.path.join(OUT_TEX, n))
                    for n in os.listdir(OUT_TEX))
    fbx_total = sum(os.path.getsize(os.path.join(OUT_FBX, n))
                    for n in os.listdir(OUT_FBX))
    print("_TexLib : {:>5} files  {:>8.2f} GB".format(
        len(os.listdir(OUT_TEX)), tex_total / 1073741824))
    print("FBX     : {:>5} files  {:>8.2f} GB".format(
        len(os.listdir(OUT_FBX)), fbx_total / 1073741824))
    print("manifest:", MANIFEST)


if __name__ == "__main__":
    main()
