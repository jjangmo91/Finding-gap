# 발견공백 MCP 데이터 계약

`data/fg_mcp.sqlite`(gz 커밋본을 서버가 해제) 스키마·의미·라이선스·제외 범위.
빌드: `build_mcp_data.py` ← `1_Data/processed/*.csv`.

## 테이블

### `species` — 서비스 종 마스터 (39,972)
`ktsn`(PK) · `korean_name` · `scientific_name` · `taxon_group` · `taxon_group_kor` ·
`class_la` `order_la` `family_la` `genus_la` · `rank` · `endangered_grade`(I/II/'') ·
`national_redlist_category`(CR/EN/VU/NT/LC/DD/…) · `has_media`(0/1) ·
`interest`(0~1) · `interest_occ` · `interest_wiki`(nullable) · `interest_user` · `stratum_n` · `interest_fallback`(0/1) ·
`wiki_ko`(한국어 위키 12개월 조회수·정수) · `wiki_en`(영어 위키 조회수·참고용·점수 미반영) ·
`watch_count`(관심종 익명 집계수·정수; 개인식별 불가·`interest_user`·`trending_species` 원천)
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

### `community` — 승인된 시민 제보 익명 집계 (Feature B)
`ktsn` · `korean_name` · `scientific_name` · `taxon_group` · `region`(시군구5) · `sido` · `region_name` · `count` · `last_year`
- 관리자 **승인(status='approved')** 된 시민 제보를 (종 × 시군구) 로 집계. `build_community_snapshot.py`(approved_discoveries RPC) → `community_reports.json` → 이 테이블.
- **미승인·미검증 제보, 정확 좌표·URL·user_id 는 미포함**(시군구 단위 집계·개인식별 불가). 승인 제보 0이면 빈 테이블(honest). `community_discoveries` 툴의 원천.

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

## 관심도(Interest) 산식
문헌: conservation culturomics / iEcology — 관측 기록 수·위키백과 조회수를 종에 대한 '주목·관심'의 대리지표로 사용(Species Awareness Index 등). 표집 편향(관측=노력·매력도·희소성)을 통제하기 위해 **(분류군 × 적색목록 등급) 층 내에서 비교**.
- **층(stratum)** = `(taxon_group × national_redlist_category)`. 층 내 **백분위**(0~1)로 정규화(스케일-프리). 신호 0이면 백분위 0. 층 n<5는 **분류군 단위 폴백**(`interest_fallback=1`).
- 신호 세 가지(모두 층 내 백분위): `interest_occ`=관측기록수(iNat/GBIF/EcoBank/국립공원), `interest_wiki`=**한국어 위키백과 조회수**(ko·12개월·CC0; 한국어 문서 없으면 NULL), `interest_user`=관심종 watchlist(배치 스냅샷).
- **가중치** `occ=0.5, wiki=0.2, user=0.3`. **적용 가능한 신호끼리 재정규화**: `interest = Σ(wₛ·Pₛ)/Σwₛ` (occ는 항상 포함). 한국어 위키 문서가 없는 종은 wiki 몫(0.2)이 나머지로, watchlist 미수집 시 user 몫(0.3)이 나머지로 분배. 가중치·정의는 `meta`(interest_weights·interest_definition).
- **국내 관심 = ko 전용**: `total`(ko+en) 조회수는 영어권에 지배돼(예: 등줄쥐 ko 1,611 vs en 16,193) 국내 관심을 왜곡 → 점수엔 **ko 조회수만** 반영. `wiki_en`은 참고용으로 저장(점수 미반영), `get_interest` 출력에 '전세계 조회수'로 병기.
- **위키 창·주기**: 최근 **12개월** 합, **월 1회** 갱신(`interest_wiki_window_months`·`interest_wiki_update`).
- **제외한 대안 신호**: 구글 트렌드(공식 API alpha·대기자 한정·상대값·비재현), 네이버 검색광고(광고용 ToS·주제 부적합), 인스타/페북 해시태그(카운트 미제공·MCL 연구자 게이팅·재배포 금지) — 재현가능·합법·국내성 요건을 모두 만족하는 ko 위키로 확정.

## 제외(공개 금지·비노출)
- **원시 좌표점**(`observations.sqlite` 5.3M행) — 절대 미포함. 민감·개인정보. 집계만.
- 연도별/출처별 세부 관측 — v1 미노출(최신연도·총계만).
- 개별 사용자 관심종 데이터(user_id·시각) — 미포함. **종별 익명 집계수만** 관심도(interest_user)에 반영(개인식별 불가).
- 1km 격자 환경적합 미발견후보(`where_undiscovered`) — 데이터 무거워 v2.

## 라이선스·이용
- 관측집계·종정보: 공공데이터(KTSN·EcoBank·GBIF·국립공원) 기반. **비상업**.
- 미디어: NIBR=공공누리(KOGL), iNaturalist=CC(대개 BY 또는 BY-NC) → **귀속(attribution) 표기 필수·비상업**.
- 미디어 URL은 공개 핫링크(무인증). 상업적 재배포 금지.

## 갱신
1. `build_wiki_interest.py` — 한국어 위키 조회수 재수집(`wiki_pageviews.json`, 최근 12개월 창). **월 1회 권장**(조회수는 가벼워 6개월 ETL과 별개로 최신화).
2. (선택) `build_watch_snapshot.py` — 관심종 익명 집계(`watch_counts.json`). Supabase RPC **`species_watch_counts()`**(SECURITY DEFINER; 원시 watchlist RLS 유지·집계 카운트만) 를 publishable 키로 호출. 마이그레이션 `5_App/supabase/species_watch_counts.sql`. 집계 있으면 `interest_user_active=1`. 로컬 검증: `--synthetic N`(임의 유저 시뮬 — 공개 커밋 전 실 스냅샷으로 되돌릴 것).
3. `build_mcp_data.py` 재실행 → `fg_mcp.sqlite.gz` 커밋. `meta.generated`·`data_max_year`·`interest_wiki_species`·`interest_user_active` 확인.
관측·환경 ETL은 6개월 주기, 위키 조회수는 월 주기, 관심종 집계는 수시(사용자 증가 시).
