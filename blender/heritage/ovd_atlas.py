# -*- coding: utf-8 -*-
"""식생 마스터용 아틀라스 시트 굽기 (PIL).

마스터는 배치 테이블이 지목하는 단위라 쪼갤 수 없다. 그런데 오버데어는
MeshPart 하나에 텍스처 하나만 허용한다. 그래서 마스터의 머티리얼들을
한 장으로 합쳐 1머티리얼 = 1오브젝트로 만든다.

rect 배치는 ovd_masters.prep_veg 의 계산과 같아야 한다:
  cols = 2 if n>1 else 1,  rows = ceil(n/cols)
  slot i -> (col = i%cols, row = i//cols)
  u' = (col + u)/cols,  v' = 1 - (row + (1-v))/rows
PIL은 위에서 아래로, Blender v는 아래에서 위로 간다.
"""
import math
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXWORK = os.path.join(ROOT, "06_OVERDARE", "_texwork")
SHEET = 1024

# 마스터: (출력 시트 이름, [슬롯 순서대로 텍스처 이름])
# 슬롯 순서는 메시의 material_index 오름차순과 같아야 한다.
ATLASES = {
    "ATL_PINE": ["PINE_BARK", "PINE_LEAF"],
    "ATL_EULALIA": ["EULALIA_LEAF", "EULALIA_STEM", "EULALIA_HEAD"],
    "ATL_ARTEMISIA": ["ARTEMISIA_STEM", "ARTEMISIA_LEAF"],
}


def build(name, parts):
    n = len(parts)
    cols = 2 if n > 1 else 1
    rows = int(math.ceil(n / float(cols)))
    cw, ch = SHEET // cols, SHEET // rows
    sheet = Image.new("RGBA", (SHEET, SHEET), (0, 0, 0, 0))
    for i, p in enumerate(parts):
        src = os.path.join(TEXWORK, p + ".png")
        if not os.path.exists(src):
            print("  없음:", src)
            continue
        im = Image.open(src).convert("RGBA").resize((cw, ch), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * cw, (i // cols) * ch))
    dst = os.path.join(TEXWORK, name + ".png")
    sheet.save(dst, optimize=True)
    return {"name": name, "parts": parts, "grid": "%dx%d" % (cols, rows),
            "rect_px": "%dx%d" % (cw, ch), "kb": os.path.getsize(dst) // 1024}


def main():
    os.makedirs(TEXWORK, exist_ok=True)
    for name, parts in ATLASES.items():
        r = build(name, parts)
        print("  %-14s %-8s rect %-9s %4d KB  %s"
              % (r["name"], r["grid"], r["rect_px"], r["kb"], r["parts"]))


if __name__ == "__main__":
    sys.exit(main())
