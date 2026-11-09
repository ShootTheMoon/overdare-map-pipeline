# -*- coding: utf-8 -*-
"""TER6 ground: the v25 relief + a gentle +-15 cm bump field (3-8 m) so flat yards stop showing the per-mesh
brightness step of the 40 m tiles (user 2026-09-12: "밖쪽 튀어나온 부분은 선이 안 보인다").
  * zero-mean +-A: ground stays above the live collision slab tops (plane - 0.3 m) -> slabs unchanged
  * fades to 0 on roads / plazas (gate passage, spawns, door swing) and within 4 m of the inner-terrain edge
    (outer HWS_OUT tiles keep matching)
  * next to the 담장 modules (their base sits at z = 0) the bump may only rise -> no gap under a wall"""
import math
from mathutils import Vector, noise
import hws_stage3 as S3

tv = S3.tv
A = 0.15
DAMJANG = [(-36.0, 36.0, 20.8, 27.2), (-36.0, 36.0, 52.8, 59.2), (29.7, 36.0, 24.0, 56.0), (-36.0, -29.7, 24.0, 56.0)]
GX0, GX1 = -tv['SX'] / 2, tv['SX'] / 2
GY0, GY1 = tv['CY'] - tv['SY'] / 2, tv['CY'] + tv['SY'] / 2


def _n(x, y):
    return (noise.noise(Vector((x / 6.0, y / 6.0, 61.0))) + 0.5 * noise.noise(Vector((x / 2.7, y / 2.7, 67.0)))) / 1.5


def bump(x, y):
    sm, dr = tv['smooth'], tv['dist_rect']
    b = max(-A, min(A, A * _n(x, y) / 0.6))
    f = sm(min(dr(x, y, r) for r in tv['ROADS']) / 2.0)
    for c, rad in tv['PLAZAS']:
        f = min(f, sm((math.hypot(x - c[0], y - c[1]) - rad) / 2.0))
    f = min(f, sm(min(x - GX0, GX1 - x, y - GY0, GY1 - y) / 4.0))
    w = sm(min(dr(x, y, r) for r in DAMJANG) / 1.5)
    b = w * b + (1 - w) * max(b, 0.0)
    return b * f


def relief6(x, y):
    return S3.relief(x, y) + bump(x, y)


def bump_outer(x, y):
    """outer ring (HWS_OUT, berm): same +-A field, fading to 0 within 4 m of the inner terrain so both meet at berm"""
    b = max(-A, min(A, A * _n(x, y) / 0.6))
    return b * tv['smooth'](tv['dist_rect'](x, y, (GX0, GX1, GY0, GY1)) / 4.0)


def relief6_outer(x, y):
    return tv['berm'](x, y) + bump_outer(x, y)
