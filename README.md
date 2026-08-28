# overdare-map-pipeline

Blender에서 만든 대형 씬을 **OVERDARE Studio**(Roblox 계열 UGC 플랫폼, Unreal 기반, Luau 스크립트)로
옮기기 위해 실제 프로덕션에서 쓴 파이썬/Luau 툴킷.

베를린 냉전 맵 38개 에셋 → 262 FBX, 창덕궁 25 M 트라이앵글 유산 스캔, 시부야 PLATEAU LOD2 도시 데이터,
조선 산곡 지형 맵을 전부 이 코드로 변환·배치했다. 실측으로 확인한 규칙과 함정만 담았다.

## OVERDARE 하드 룰 (지키지 않으면 임포트가 조용히 실패한다)

| 항목 | 값 |
|---|---|
| FBX 1개당 트라이앵글 | **30,000** 이하 |
| MeshPart 1개당 텍스처 | **1장** |
| 텍스처 해상도 | 1024 px |
| 축 / 단위 | **Y-up, cm** (Blender 1 m = 100 스터드) |
| 좌표 매핑 | Blender `(x, y, z)` → OVERDARE `(X, Z, Y)` |
| 방위 | Blender `+Y`(북) → OVERDARE `−Z` |

## 임포트는 2단계다 — 이걸 구분 못 하면 반드시 망가진다

1. **발행**: FBX를 Studio에 등록 → 에셋 ID 생성. `UGCLocalAssetTable.json`에 영구 기록되고 **되돌릴 수 없다.**
   같은 파일을 다시 올리면 교체가 아니라 새 ID가 또 생긴다.
2. **배치**: 그 ID로 `MeshPart`를 씬에 놓기. 얼마든지 지우고 다시 해도 된다.

맵이 깨졌을 때 다시 해야 하는 건 **2단계뿐**이다. 자세한 절차는 [`docs/IMPORT_GUIDE.md`](docs/IMPORT_GUIDE.md).

## 구성

```
blender/core/       플랫폼 무관 변환기
  overdare_convert.py    핵심. Blender에서 exec() 후 convert(asset, strategy) 호출.
                         트랜스폼 베이크 → 머티리얼 분할 → 30k 분할 → 텍스처 정규화 → FBX 출력
  asset_reduce.py        폴리곤 감축 (재질별 정책)
  atlas_bake/pack/masters.py  텍스처 아틀라스 (MeshPart당 1텍스처 규칙 대응)
  prepare_all.py         일괄 준비 파이프라인
  make_collision_parts.py    DEM 기반 충돌 슬랩 생성
  make_import_batches.py     발행 배치 분할
  make_placement_items.py    배치 매니페스트 생성
  make_spawner.py        Luau 스포너 생성
blender/heritage/   국가유산청 스캔 전용 파이프라인
  cdg_*.py    창덕궁: 머티리얼 분할, 재질별 데시메이션, OSM 기반 레이아웃 해석
  jsn_*.py, ovd_*.py    산곡: 해석적 지형 + 스캔 드레싱, 마스터/텍스처/배치 빌드
  ssw_live.py    소쇄원 (77 KB). KHS FBX 임포트(축 -Z/Y), OP 알파 배선,
                 height_at 기반 스캐터, 정점컬러 PBR — 이후 프로젝트가 재사용한 원본
studio/recipes/     Studio 안에서 도는 Luau 레시피 (정렬, 충돌 프록시, 배치 보정)
docs/               임포트 절차서, 임포트 순서, 배치 스펙
```

## 검증된 함정

- **트랜스폼 베이크 누락**: `object.location`이 아니라 `mesh.transform()`으로 정점에 구워야 한다.
  좌표가 크면(예: 도쿄 평면직각좌표 38 km) float32 오차로 메시가 흔들린다.
- **`rotation_mode`가 QUATERNION**: 임포트된 오브젝트 대부분이 여기 해당해서 `rotation_euler` 대입이
  **조용히 무시된다.** 회전 주기 전에 `o.rotation_mode='XYZ'`를 먼저 설정할 것.
- **`bound_box`는 낡는다**: 메시 편집 후에는 정점 기준으로 직접 bbox를 계산한다 (`dims_of`).
- **KHS FBX = Geometry 노드 1개**: 통짜 메시에 N개 머티리얼 슬롯. 첫 작업은 무조건 머티리얼별 분할.
- **FBX 파일 크기 ≠ 폴리곤 수**: 대부분이 임베드 텍스처다. `PolygonVertexIndex`를 파싱해서 세라.
- **텍스처는 건물 간 바이트 동일 중복**: 창덕궁 1,011개 인스턴스 → 고유 304개. 파일명 키 라이브러리로
  3.3 GB를 절약했다.
- **`Model.WorldPivot`은 자식을 움직이지 않는다** (이 Studio 빌드 기준). 최종 보정은 각 MeshPart의
  CFrame에 동일한 강체 변환을 적용해야 한다.
- **재발행 금지**: 위의 2단계 구분 참조.

## 쓰는 법

```bash
blender --background scene.blend --python blender/core/prepare_all.py
```
또는 Blender 텍스트 에디터/MCP에서 `exec(open("blender/core/overdare_convert.py").read())` 후
`convert(asset, strategy)` 호출.

경로 상수는 로컬 작업 루트(`C:\Work\...`)를 가정한다. 본인 환경에 맞게 파일 상단에서 바꿔 쓸 것.

## 라이선스

MIT. 이 리포에는 3자 3D 에셋이 포함되어 있지 않다 — 코드와 문서뿐이다.
에셋과 그 출처 표기는 각 에셋 팩 리포를 참조.
