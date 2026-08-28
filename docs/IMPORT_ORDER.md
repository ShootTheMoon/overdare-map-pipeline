# JSN_Sangok 오버데어 반입 순서

## 절대 규칙 — 한 번에 파일 하나

`overdare_mesh_bulk_import` 는 넘긴 파일들을 **한 번들 FBX로 합친다.**
이 프로젝트 메시는 개당 최대 27,000 tris라 두 개만 합쳐도 파일 총합 30k를
넘는다. 실측 결과:

| 번들 구성 | 총 tris | 결과 |
|---|---:|---|
| 곰솔 단독 | 8,329 | 등록 3 — 성공 |
| 바위A 단독 | 26,999 | 등록 2 — 성공 |
| 바위A + 곰솔 | 36,329 | 등록 0 — 실패 |
| 바위 B+C+D | 81,000 | **Studio 크래시** |

따라서 `files` 에는 **항상 파일 하나만** 넘긴다.

## 순서 (30개, 56.1 MB)

  1. `10_MASTERS/MST_ARTEMISIA_overdare.fbx` — 0.93 MB
  2. `10_MASTERS/MST_EULALIA_overdare.fbx` — 1.15 MB
  3. `10_MASTERS/MST_PEBBLE_overdare.fbx` — 0.47 MB
  4. `10_MASTERS/MST_PINE_overdare.fbx` — 1.71 MB
  5. `10_MASTERS/MST_ROCK_A_overdare.fbx` — 1.49 MB
  6. `10_MASTERS/MST_ROCK_B_overdare.fbx` — 1.34 MB
  7. `10_MASTERS/MST_ROCK_C_overdare.fbx` — 1.42 MB
  8. `10_MASTERS/MST_ROCK_D_overdare.fbx` — 1.39 MB
  9. `10_MASTERS/MST_ROCK_E_overdare.fbx` — 1.42 MB
 10. `10_MASTERS/MST_ROCK_F_overdare.fbx` — 1.55 MB
 11. `10_MASTERS/MST_ROCK_MASS_overdare.fbx` — 1.99 MB
 12. `01_TERRAIN/STA_TER_00_overdare.fbx` — 2.62 MB

> **여기서 Studio 재시작** — 세션당 40유닛 한계, 파일당 3유닛

 13. `01_TERRAIN/STA_TER_01_overdare.fbx` — 2.58 MB
 14. `01_TERRAIN/STA_TER_02_overdare.fbx` — 2.56 MB
 15. `01_TERRAIN/STA_TER_03_overdare.fbx` — 2.64 MB
 16. `01_TERRAIN/STA_TER_10_overdare.fbx` — 2.61 MB
 17. `01_TERRAIN/STA_TER_11_overdare.fbx` — 2.52 MB
 18. `01_TERRAIN/STA_TER_12_overdare.fbx` — 2.51 MB
 19. `01_TERRAIN/STA_TER_13_overdare.fbx` — 2.56 MB
 20. `01_TERRAIN/STA_TER_20_overdare.fbx` — 2.52 MB
 21. `01_TERRAIN/STA_TER_21_overdare.fbx` — 2.42 MB
 22. `01_TERRAIN/STA_TER_22_overdare.fbx` — 2.44 MB
 23. `01_TERRAIN/STA_TER_23_overdare.fbx` — 2.52 MB
 24. `01_TERRAIN/STA_TER_30_overdare.fbx` — 2.56 MB

> **여기서 Studio 재시작** — 세션당 40유닛 한계, 파일당 3유닛

 25. `01_TERRAIN/STA_TER_31_overdare.fbx` — 2.50 MB
 26. `01_TERRAIN/STA_TER_32_overdare.fbx` — 2.51 MB
 27. `01_TERRAIN/STA_TER_33_overdare.fbx` — 2.58 MB
 28. `02_STATIC/STA_STEPS_overdare.fbx` — 0.47 MB
 29. `02_STATIC/STA_StreamWater_overdare.fbx` — 0.09 MB
 30. `02_STATIC/STA_TribWater_overdare.fbx` — 0.05 MB

반입이 끝나면 `placements.csv`(2,383행)로 인스턴스를 배치한다.
STATIC(지형 16 + 수면 2 + 석단 1)은 월드 좌표 그대로라 (0,0,0)에 놓으면 된다.
