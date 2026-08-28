# -*- coding: utf-8 -*-
"""3단계 — 지형 타일 분할 + 텍스처 베이크.

지형 재질은 정점컬러 4방 블렌드(잔디/마사토/암반/젖은하상) + BOX 투영이라
타일 텍스처 한 장으로 낼 수 없다. `bpy.ops.object.bake`는 이 파이프라인에서
쓸 수 없는 것으로 기록돼 있으므로, **`blend_at()`을 파이썬에서 직접 평가해
PIL로 굽는다** — 텍셀마다 월드 좌표를 구해 마스크를 계산하고 4장을 합성한다.
결정적이고 재현 가능하며 GPU도 필요 없다.

타일은 4x4 = 16장. 260 m / 4 = 65 m/타일, 1024 px → 15.8 px/m.
(시부야 납품이 9.5 px/m 였으므로 이 정도면 충분하다.)
"""
import json
import math
import os

TILES = 4
SHEET = 1024
EXTENT = 260.0
HALF = EXTENT * 0.5

# 각 소스가 실제 세계에서 덮는 거리(m) — jsn_live._terrain_material 의 tile 값
TILE_M = {"grass": 5.0, "earth": 4.0, "rock": 3.5, "rock2": 9.0, "wet": 3.0}
# jsn_live 에서 적용한 MULTIPLY 틴트
TINT = {"grass": (0.44, 0.50, 0.31), "earth": (0.56, 0.45, 0.33),
        "rock": (1.05, 1.00, 0.92), "rock2": (1.05, 1.00, 0.92),
        "wet": (0.60, 0.59, 0.55)}


def _value_noise(shape, cells, seed):
    """저주파 값 노이즈. 암반 두 장을 섞어 타일 반복을 깨는 용도."""
    import numpy as np
    rng = np.random.RandomState(seed)
    g = rng.rand(cells + 1, cells + 1).astype(np.float32)
    g[-1, :] = g[0, :]
    g[:, -1] = g[:, 0]
    from PIL import Image
    im = Image.fromarray((g * 255).astype("uint8"), "L").resize(shape, Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def bake_tiles(blend_at, outdir, tiles=TILES, sheet=SHEET):
    """blend_at(x,y)->(r,g,b) 를 받아 타일 텍스처를 굽는다."""
    from PIL import Image
    import numpy as np

    src_dir = os.path.join(os.path.dirname(outdir), "_texwork", "_terrain_src")
    src = {}
    for k in ("grass", "earth", "rock", "rock2", "wet"):
        p = os.path.join(src_dir, k + ".png")
        im = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0
        t = np.array(TINT[k], dtype=np.float32)
        src[k] = np.clip(im * t, 0.0, 1.0)

    os.makedirs(outdir, exist_ok=True)
    step = EXTENT / tiles
    made = []
    # 마스크는 가우시안·사인으로 만들어진 **저주파**다. 텍셀마다 파이썬으로 부르면
    # 1024^2 x 16 = 1,677만 번이라 몇 시간이 걸린다. 성글게 평가해 업샘플하고,
    # 고주파 디테일은 소스 텍스처가 담당하게 한다.
    MASK = 128
    for ty in range(tiles):
        for tx in range(tiles):
            x0 = -HALF + tx * step
            y0 = -HALF + ty * step

            m = np.zeros((MASK, MASK, 3), dtype=np.float32)
            for j in range(MASK):
                wy = y0 + step * (1.0 - (j + 0.5) / MASK)
                for i in range(MASK):
                    wx = x0 + step * ((i + 0.5) / MASK)
                    m[j, i] = blend_at(wx, wy)
            masks = np.asarray(
                Image.fromarray((np.clip(m, 0, 1) * 255).astype("uint8"), "RGB")
                .resize((sheet, sheet), Image.BILINEAR), dtype=np.float32) / 255.0

            # 월드 좌표 격자 (벡터)
            ii = (np.arange(sheet, dtype=np.float32) + 0.5) / sheet
            jj = (np.arange(sheet, dtype=np.float32) + 0.5) / sheet
            wx = x0 + step * ii[None, :]
            wy = y0 + step * (1.0 - jj)[:, None]

            def sample(k):
                s = src[k]
                n = s.shape[0]
                u = (((wx / TILE_M[k]) % 1.0) * n).astype(np.int32) % n
                v = (((wy / TILE_M[k]) % 1.0) * n).astype(np.int32) % n
                return s[n - 1 - np.broadcast_to(v, (sheet, sheet)),
                         np.broadcast_to(u, (sheet, sheet))]

            # 암반은 한 장만 3.5 m로 깔면 타일 격자가 그대로 드러난다.
            # jsn_live 처럼 두 화강암을 저주파 노이즈(0.08~0.42)로 섞어 깬다.
            nz = _value_noise((sheet, sheet), 6, seed=1000 + ty * 10 + tx)
            f = (0.08 + nz * 0.34)[:, :, None]
            rock_mix = sample("rock") * (1.0 - f) + sample("rock2") * f

            out = sample("grass")
            for c, w in ((sample("earth"), masks[:, :, 0]),
                         (sample("wet"), masks[:, :, 2]),
                         (rock_mix, masks[:, :, 1])):
                a = w[:, :, None]
                out = out * (1.0 - a) + c * a
            # 근거리 색 얼룩 — jsn_live 의 0.80~1.18 배 변조와 같은 역할
            out = out * (0.86 + _value_noise((sheet, sheet), 22, seed=7000 + ty * 10 + tx)
                         * 0.28)[:, :, None]
            img = Image.fromarray((np.clip(out, 0, 1) * 255).astype("uint8"), "RGB")
            name = "TER_%d%d" % (tx, ty)
            img.save(os.path.join(outdir, name + ".png"), optimize=True)
            made.append({"name": name, "x0": x0, "y0": y0, "size": step})
    with open(os.path.join(outdir, "_tiles.json"), "w", encoding="utf-8") as f:
        json.dump({"tiles": tiles, "sheet": sheet, "extent": EXTENT, "list": made}, f,
                  ensure_ascii=False, indent=1)
    return made
