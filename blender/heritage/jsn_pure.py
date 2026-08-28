# -*- coding: utf-8 -*-
"""jsn_live 의 순수 지형 함수를 Blender 밖에서 쓰기 위한 로더.

지형 텍스처 베이크는 Blender가 필요 없는 순수 수학이다. 그런데 jsn_live 는
모듈 최상단에서 bpy/bmesh/mathutils 를 임포트한다. 함수를 잘라내 복붙하면
곧바로 원본과 어긋나므로(blend_at 은 pine_density·talus_amt 까지 참조한다),
**스텁을 끼워 원본을 그대로 임포트한다.** 정의가 한 곳에만 있게 유지된다.
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def _stub(name, attrs=None):
    m = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(m, k, v)
    return m


def load():
    if "bpy" not in sys.modules:
        app = types.SimpleNamespace(version_string="stub", driver_namespace={})
        data = types.SimpleNamespace(objects={}, meshes={}, materials={}, images={})
        sys.modules["bpy"] = _stub("bpy", {"app": app, "data": data,
                                           "context": types.SimpleNamespace(),
                                           "ops": types.SimpleNamespace(),
                                           "path": types.SimpleNamespace()})
    if "bmesh" not in sys.modules:
        sys.modules["bmesh"] = _stub("bmesh", {"ops": types.SimpleNamespace(),
                                               "types": types.SimpleNamespace()})
    if "mathutils" not in sys.modules:
        class _V(list):
            pass
        sys.modules["mathutils"] = _stub("mathutils", {"Vector": _V, "Matrix": _V,
                                                       "Quaternion": _V, "Euler": _V})
    spec = importlib.util.spec_from_file_location(
        "jsn_live_pure", os.path.join(HERE, "jsn_live.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


if __name__ == "__main__":
    m = load()
    print("blend_at(0,0) =", [round(v, 3) for v in m.blend_at(0.0, 0.0)])
    print("height_at(0,0) =", round(m.height_at(0.0, 0.0), 3))
    print("pine_density(60,0) =", round(m.pine_density(60.0, 0.0), 3))
