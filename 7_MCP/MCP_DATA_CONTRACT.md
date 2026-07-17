# 발견공백 MCP 데이터 계약

`data/fg_mcp.sqlite`(gz 커밋본을 서버가 해제) 스키마·의미·라이선스·제외 범위.
빌드: `build_mcp_data.py` ← `1_Data/processed/*.csv`.

## 테이블

### `species` — 서비스 종 마스터 (39,972)
`ktsn`(PK) · `korean_name` · `scientific_name` · `taxon_group` · `taxon_group_kor` ·
`class_la` `order_la` `family_la` `genus_la` · `rank` · `endangered_grade`(I/II/'') ·
`national_redlist_category`(CR/EN/VU/NT/LC/DD/…) · `has_media`(0/1)
- 서비스 제외: 해양포유류·미삭동물(species_service_flags 기준).

### `species_region` — (종 × 지역) 발견 집계 (590,179)
`ktsn` · `taxon_group` · `region`(시군구 5자리) · `sido`(2자리) · `maxyear` · `obs_count`
- `observation_sigungu.csv`(2.04M행: ktsn×시군구×연도×출처)를 **(ktsn, region) 최신연도·관측합**으로 롤업.
- 유효연도 1900–2026만(오염값 제거). 원시 좌표·연도별·출처별 세부는 **미포함**.

### `species_env` — 종별 환경지위 (126,996 long)
`ktsn` · `var`(bio01/bio05/bio06/bio12/dem/ndvi/ndwi) · `n·min·q1·median·q3·max·mean·sd`
- 발견 지점의 환경값 분포(실제 분포역과 다를 수 있음).

### `media` — 종별 미디어 메타 (43,441)
`ktsn` · `src`(nibr/inat) · `type`(photo/illustration/specimen/video/sound) ·
`license`(KOGL/CC-BY[-NC]) · `attribution` · `thumb` · `full`(공개 핫링크 URL). 종당 최대 12.

### `region` (269) · `taxa` (9) · `meta`
- `region`: `code·name·level`(sido/sigungu)·`sido_cd`
- `taxa`: `taxon_group·taxon_group_kor·n_species`
- `meta`: `generated·version·data_max_year·discovery_window_years·license·source`

## 발견 상태 정의
기준연도 = 서버 실행 시점의 당해연도. `cutoff = 기준연도 − 10`.
- **발견(found)**: 해당 지역 `maxyear ≥ cutoff`
- **휴면(dormant)**: 기록은 있으나 `maxyear < cutoff`
- **미발견(undiscovered)**: 해당 지역에 기록 없음
- 시도(2자리) 질의는 소속 시군구를 롤업(종별 MAX(maxyear)).

## 제외(공개 금지·비노출)
- **원시 좌표점**(`observations.sqlite` 5.3M행) — 절대 미포함. 민감·개인정보. 집계만.
- 연도별/출처별 세부 관측 — v1 미노출(최신연도·총계만).
- 로그인·관심종(Supabase RLS) — 인증 필요, 공개 MCP 범위 밖.
- 1km 격자 환경적합 미발견후보(`where_undiscovered`) — 데이터 무거워 v2.

## 라이선스·이용
- 관측집계·종정보: 공공데이터(KTSN·EcoBank·GBIF·국립공원) 기반. **비상업**.
- 미디어: NIBR=공공누리(KOGL), iNaturalist=CC(대개 BY 또는 BY-NC) → **귀속(attribution) 표기 필수·비상업**.
- 미디어 URL은 공개 핫링크(무인증). 상업적 재배포 금지.

## 갱신
ETL 6개월 주기 → `build_mcp_data.py` 재실행 → `fg_mcp.sqlite.gz` 커밋. `meta.generated`·`data_max_year` 확인.
