# -*- coding: utf-8 -*-
"""walkability_grid.json -> 보행성 히트맵 PNG.

Blender 밖에서 도는 순수 PIL 스크립트. jsn_live.walkability()가 먼저 실행돼야 한다.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def _font(size):
    """기본 PIL 폰트는 한글 글리프가 없어 전부 네모로 나온다."""
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
              r"C:\Windows\Fonts\batang.ttc"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "05_Documentation")
OUT = os.path.join(ROOT, "04_Previews", "walkability.png")

COLORS = {
    0: (176, 58, 58),     # 통행 불가
    1: (214, 158, 62),    # 기어오름
    2: (86, 138, 92),     # 보행
}
SCALE = 4


def main():
    with open(os.path.join(DOC, "walkability_grid.json"), encoding="utf-8") as f:
        g = json.load(f)
    with open(os.path.join(DOC, "walkability.json"), encoding="utf-8") as f:
        meta = json.load(f)

    n, cell, half = g["n"], g["cell"], g["half"]
    grid, label, largest = g["grid"], g["label"], g["largest"]

    img = Image.new("RGB", (n, n), (30, 30, 34))
    px = img.load()
    for j in range(n):
        for i in range(n):
            c = COLORS[grid[j][i]]
            # 최대 연결성분이 아닌 통행 가능 셀 = 고립 구역. 보라로 표시.
            if grid[j][i] and label[j][i] != largest:
                c = (150, 80, 190)
            px[i, n - 1 - j] = c

    img = img.resize((n * SCALE, n * SCALE), Image.NEAREST)
    d = ImageDraw.Draw(img)
    f_lbl, f_lg = _font(15), _font(16)

    def to_px(x, y):
        return ((x + half) / cell * SCALE, (n - 1 - (y + half) / cell) * SCALE)

    for name, kp in meta["key_points"].items():
        x, y = kp["xy"]
        cx, cy = to_px(x, y)
        r = 7
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=3)
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(255, 255, 255))
        d.text((cx + 12, cy - 9), name, fill=(255, 255, 255), font=f_lbl,
               stroke_width=3, stroke_fill=(20, 20, 24))

    # 범례
    lg = [("보행 (<=40도)", COLORS[2]), ("기어오름 (40~55도)", COLORS[1]),
          ("통행 불가 (>55도 또는 암반)", COLORS[0]), ("고립 구역", (150, 80, 190))]
    d.rectangle([8, 8, 300, 8 + 22 * len(lg) + 8], fill=(20, 20, 24))
    y0 = 14
    for txt, col in lg:
        d.rectangle([14, y0, 34, y0 + 15], fill=col, outline=(255, 255, 255))
        d.text((42, y0 - 1), txt, fill=(255, 255, 255), font=f_lg)
        y0 += 22

    img.save(OUT)
    print("saved", OUT, img.size)
    print("verdict", meta["verdict"], "| components", meta["components"]["count"])


if __name__ == "__main__":
    sys.exit(main())
