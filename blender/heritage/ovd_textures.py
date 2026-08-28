# -*- coding: utf-8 -*-
"""1단계 — 오버데어용 텍스처 준비.

Blender 밖에서 PIL로 굽는다. `img.scale()`은 헤드리스에서 지연 로딩·팩 이미지
문제로 못 쓰고, 팩된 이미지의 save()는 원본 해상도를 다시 뱉는다.

규칙
- **BC만 남긴다.** 노멀/러프니스/AO를 같이 내보내면 오버데어에서 표면이 오염된다.
- OP(불투명도)가 있으면 BC의 알파 채널로 합성해 RGBA 한 장으로 만든다.
- 512x512. 오버데어 권장이고 4K/8K는 임포터를 죽인다.
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACT = os.path.join(ROOT, "_extracted")
VEG = os.path.join(EXTRACT, "VEG")
TEXLIB = os.path.join(ROOT, "_TexLib")
OUT = os.path.join(ROOT, "06_OVERDARE", "_texwork")

SIZE = 512

# (출력이름, BC 경로, OP 경로 or None)
def _rock(unit):
    d = os.path.join(EXTRACT, "ROCK_Columnar" + unit, "Texture")
    return ("ROCK_%s" % unit, os.path.join(d, "T_MDS_Unit%s_BC.png" % unit), None)


JOBS = [
    _rock("A"), _rock("B"), _rock("C"), _rock("D"), _rock("E"), _rock("F"),
    ("ROCK_MASS",
     os.path.join(EXTRACT, "ROCK_ColumnarMass", "Texture", "T_MDS_Entire_BC.png"), None),
    ("PINE_BARK", os.path.join(VEG, "T_BlackPine_Bark_BC.png"), None),
    ("PINE_LEAF", os.path.join(VEG, "T_BlackPine_Leaf_BC.png"),
     os.path.join(VEG, "T_BlackPine_Leaf_OP.png")),
    ("EULALIA_STEM", os.path.join(VEG, "T_Eulalia_Stem_BC.png"), None),
    ("EULALIA_LEAF", os.path.join(VEG, "T_Eulalia_Leaf_BC.png"),
     os.path.join(VEG, "T_Eulalia_Leaf_OP.png")),
    ("EULALIA_HEAD", os.path.join(VEG, "T_Eulalia_Head_BC.png"),
     os.path.join(VEG, "T_Eulalia_Head_OP.png")),
    ("ARTEMISIA_STEM", os.path.join(VEG, "T_Artemisia_Stem_BC.png"), None),
    ("ARTEMISIA_LEAF", os.path.join(VEG, "T_Artemisia_Leaf_BC.png"),
     os.path.join(VEG, "T_Artemisia_Leaf_OP.png")),
    # 지형 베이크 재료 (3단계에서 씀 — 여기서는 원본 그대로 캐시만)
]

# 지형 베이크에 쓸 소스는 512로 줄이면 타일 표면이 뭉개진다. 별도 폴더에 1024로.
TERRAIN_SRC = [
    ("grass", os.path.join(TEXLIB, "T_Ground02A_BC.png")),
    ("earth", os.path.join(TEXLIB, "T_Ground01A_BC.png")),
    ("rock", os.path.join(EXTRACT, "ROCK_ColumnarA", "Texture", "T_MDS_UnitA_BC.png")),
    ("wet", os.path.join(TEXLIB, "T_Sand_ColorB_BC4k.png")),
    # 암반 반복을 깨기 위한 두 번째 화강암 (jsn_live 의 rock2 와 동일)
    ("rock2", os.path.join(TEXLIB, "T_Stone01B_BC.png")),
]


def bake_one(name, bc, op, size=SIZE):
    if not os.path.exists(bc):
        return {"name": name, "error": "BC 없음: " + bc}
    im = Image.open(bc).convert("RGB").resize((size, size), Image.LANCZOS)
    if op and os.path.exists(op):
        a = Image.open(op).convert("L").resize((size, size), Image.LANCZOS)
        im = im.convert("RGBA")
        im.putalpha(a)
    dst = os.path.join(OUT, name + ".png")
    im.save(dst, optimize=True)
    return {"name": name, "px": size, "alpha": bool(op), "kb": os.path.getsize(dst) // 1024}


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(OUT, "_terrain_src"), exist_ok=True)
    total = 0
    print("=== 머티리얼 텍스처 (512, BC+알파) ===")
    for name, bc, op in JOBS:
        r = bake_one(name, bc, op)
        if "error" in r:
            print("  ERR %-16s %s" % (name, r["error"]))
            continue
        total += r["kb"]
        print("  %-16s %dpx alpha=%-5s %4d KB" % (r["name"], r["px"], r["alpha"], r["kb"]))
    print("=== 지형 베이크 소스 (1024, 타일링용) ===")
    for name, src in TERRAIN_SRC:
        if not os.path.exists(src):
            print("  ERR", name, src)
            continue
        im = Image.open(src).convert("RGB").resize((1024, 1024), Image.LANCZOS)
        dst = os.path.join(OUT, "_terrain_src", name + ".png")
        im.save(dst, optimize=True)
        print("  %-8s -> %4d KB" % (name, os.path.getsize(dst) // 1024))
    print()
    print("머티리얼 텍스처 합계 %.2f MB (원본 735.5 MB)" % (total / 1024.0))


if __name__ == "__main__":
    sys.exit(main())
