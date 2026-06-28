# Finding gap — 데이터 파이프라인 구조

> 원자료(raw) → 정제자료(processed) → 서비스 테이블(5_App/demo/data) 3계층.
> 마지막 갱신: 2026-06-28 (GBIF 9분류군 적재·3원 관측 union 반영).
> 관측 행 수는 GBIF·EcoBank 전량 적재 후 재빌드 시 갱신(아래 일부는 직전 빌드 기준).

```
┌─ 0. 원자료 raw ──────────────┐   ┌─ 1. 정제자료 processed ──────────┐   ┌─ 2. 서비스 테이블 ────────┐
│ NIBR KTSN  ndjson (10분류군)  │→ │ ktsn_master.csv        40,156     │→ │ taxa_summary.js   9그룹    │
│ EcoBank    ndjson (WFS 레이어)│→ │ observation_agg.csv  (재빌드시)   │→ │ obs_by_taxon.js   분류군별 │
│ 국립공원   CSV+ZIP×22         │→ │ observation_nps.csv    91,267     │→ │ species_index.js  39,972   │
│ GBIF       csv (9분류군)      │→ │ observation_gbif.csv  (etl_gbif)  │→ │ demo_mm.js        MM상세   │
│ 멸종위기   xlsx               │→ │ endangered_species.csv    282     │   └───────────────────────────┘
│ 국가적색목록 PDF→txt          │→ │ national_redlist.csv    5,445     │     build_demo_data.py 가 생성
│ 해양생물 MBRIS API            │→ │ species_service_flags.csv 40,156  │     (서비스 제외종 필터 + 관측 union)
│ 행정경계 BND_SIDO_PG shp      │   │ mbris_marine.csv  0 (API 다운)    │
└──────────────────────────────┘   └──────────────────────────────────┘
```

핵심 원칙: **발견공백(gap) = 국가생물종목록(서비스 대상) − 관측종**. 공백은 저장하지 않고 클라이언트가 동적으로 여집합 계산. ETL은 좌표→시도 spatial join까지만 미리 수행하고, 런타임은 평면 집계 질의만 한다.

---

## 0. 원자료 (raw) — `1_Data/raw/`

| 폴더/파일 | 출처 | 형식 | 비고 |
|---|---|---|---|
| `nibr/ktsn_<TX>.ndjson` | 국립생물자원관 KTSN API | NDJSON | 10 관리분류군. `corsynSeYn=Y`(정명)만 마스터 채택 |
| `ecobank/ecobank_*.ndjson` | 국립생태원 EcoBank WFS | NDJSON(+좌표) | 조사사업×분류군 레이어별. `_coords=[lon,lat]` EPSG:4326 |
| `national_park/national_park_2024.csv` | 국립공원공단 생물자원현황 | CSV(CP949) | 2024 단독. 종명=학명, 분류명=국명, 주소+좌표, 일자 M/D/YYYY |
| `national_park/국립공원_생물자원현황_YYYY*.zip` ×22 | 〃 | ZIP(내부 CSV, CP949) | 2002–2023. 좌표만(주소 없음), 일자 YYYY-MM-DD. **종명/분류명이 국명일 수도·학명일 수도** → `학명` 필드가 가장 신뢰 |
| `gbif/gbif_MM_key.txt` | GBIF | download key | MM 다운로드 SUCCEEDED(141,188건)·**아직 미적재**. 그 외 분류군 미제출 |
| `4_References/붙임.멸종위기…xlsx` | 환경부 멸종위기 야생생물 | XLSX | → endangered_species.csv |
| `redlist/*.txt` | 국가생물적색자료집 PDF 추출 | TXT | → national_redlist.csv |
| 해양생물 MBRIS | 해수부 MBRIS OpenAPI | (HTTP 500 다운) | 복구 시 mbris_marine.csv 적재 |
| `spatial/BND_SIDO_PG/*.shp` | 통계청 시도 행정경계 | Shapefile | point-in-polygon으로 좌표→시도 |

---

## 1. 정제자료 (processed) — `1_Data/processed/`

각 파일은 **utf-8-sig**, 1행 헤더.

### 1-A. 종 마스터 — `ktsn_master.csv` (40,156행) + 별칭 `ktsn_aliases.csv` (760행)
- **생성**: `build_ktsn_master.py` ← nibr ndjson + endangered + redlist
- **스키마**: `ktsn, scientific_name, match_key, korean_name, taxon_group, taxon_group_kor, rank, class_la, order_la, family_la, genus_la, egspcs_yn, endangered_grade, national_redlist_category`
- **규칙**: 정명(corsynSeYn=Y)·종/아종 수준만. 변종/품종은 종·아종으로 폴드. `match_key`=정규화 학명키(저자명 제거, 아종=3명법). 멸종위기등급·적색목록코드는 학명키→국명 폴백으로 조인.
- **역할**: 모든 분류군의 "전체 종 목록"(발견공백의 분모).
- **별칭 `ktsn_aliases.csv`** `(alias_name, alias_type[sci|kor], accepted_ktsn, accepted_korean, accepted_scientific, taxon_group, alias_rank)`: 마스터는 정명만 담아 변종/품종의 국명(예 **남산제비꽃**=Viola albida var.)이 사라진다. 같은 정명으로 폴딩된 비대표 멤버의 국명·학명을 정명 ktsn에 연결해 **조사기록이 옛 변종명을 써도 매칭**되게 한다(주로 VP·MS). KTSN API가 이명(synonym)을 제공하지 않으므로, 이 폴딩 복원이 사실상의 "정명 ktsn을 가지는 이명 목록"이다. etl_*가 sci/kor 사전에 gap-fill(정명 우선)로 흡수.

### 1-B. 관측 집계 — `observation_agg.csv`(EcoBank, 5,049행) · `observation_nps.csv`(국립공원, 91,267행)
- **생성**: `etl_observation.py`(EcoBank ndjson) · `etl_national_park.py`(국립공원 CSV/ZIP). 둘 다 master로 매칭 + 좌표→시도 join.
- **공통 스키마**: `ktsn, taxon_group, sido, year, source, obs_count`
  - `obs_count = COUNT(DISTINCT 좌표)` per (ktsn, taxon_group, sido, year, source)
  - `source`: EcoBank=조사사업코드(bgts/ecpe/ntee/wtl), 국립공원=`nps`
- **매칭 규칙(2026-06-20 개정 — 보정·별칭 + 학명·국명 충돌 폐기)**:
  학명·국명 각각을 (정명 + 별칭 gap-fill) 사전으로 해석. **보정 매핑(override)이 최우선**.
  | 상황 | 처리 |
  |---|---|
  | 보정 매핑 등록 이름(`override`) | 지정 정명 ktsn 확정(충돌보다 우선) |
  | 둘 다 같은 ktsn(`both`) | 매칭(최고신뢰) |
  | 한쪽만 해석(`sci`/`kor`) | 그것으로 매칭 |
  | 둘 다 해석되나 **다른 ktsn**(`conflict`) | **폐기**(확정불가) |
  | 둘 다 미해석(`none`) | 미매칭 |
  - 보정 매핑 `4_References/ktsn_name_overrides.csv`(`match_name, match_type, accepted_ktsn, …`): 정명 재배치·종분할로 자동매칭이 틀리는 케이스를 수기 지정. 예 박새/Parus major→박새(Parus cinereus, 큰박새는 한국 미분포), 꼬리치레도롱뇽→한국꼬리치레도롱뇽(양산종 분할).
  - 국립공원 2026-06-20 결과(보정+별칭 적용): 총 791,120 → 매칭 **742,504(93.9%)** [보정 15,945·일치 123,501·학명단독 1,224·국명단독 601,834], 폐기 48,616(충돌 876·미매칭 47,740). (적용 전 92.4%/폐기 60,355 대비 향상.)
  - 남은 미매칭은 `reconcile_unmatched.py`가 마스터 부분일치·동일속으로 후보 추천 → `observation_nps_unmatched_candidates.csv`(검토 후 override 승격). 남은 충돌(25종)은 학명·국명이 서로 다른 정명을 가리키는 진짜 모호성이라 폐기 유지.

### 1-C. 폐기 종목록(검토용) — `observation_nps_unmatched.csv` (2,780행)
- **생성**: `etl_national_park.py` 부산물
- **스키마**: `종명, 분류명_국명, 생물분류, 사유, 학명해석_ktsn, 국명해석_ktsn, 폐기_건수`
- `사유`=충돌/미매칭. 충돌 26종은 두 해석 ktsn을 함께 기록 → 사용자가 마스터 동의어 정비 판단.

### 1-D. 등급/적색목록 — `endangered_species.csv`(282) · `national_redlist.csv`(5,445)
- **생성**: `extract_endangered.py`(xlsx) · `extract_redlist.py`(PDF txt). 마스터 조인 소스.
- endangered: `분류군, 등급, 국명, 학명, sci_key, binom` / redlist: `분류군명, 학명, 한글명, 적색목록코드, source_year`

### 1-E. 서비스 제외 플래그 — `species_service_flags.csv` (40,156행)
- **생성**: `improve_species_list.py` ← master + 관측(agg+nps[+gbif]) + (mbris)
- **스키마**: `ktsn, taxon_group, korean_name, scientific_name, in_service, exclude_reason`
- **규칙(육상 생태계 집중)**:
  | 분류군 | 제외 조건 | exclude_reason |
  |---|---|---|
  | MM 포유류 | 해양포유류(Cetacea·기각/해우 과 + MBRIS) | marine_mammal (42종) |
  | -P 어류 | 해양(MBRIS)∧무기록∧비적색목록 | marine_fish_unrecorded (MBRIS 다운 시 0) |
  | UC 미삭동물 | 전량(멍게·미더덕 등 해양 피낭동물) | tunicate_marine (142종) |
  | 그 외 | — | (유지) |
- 2026-06-20: 서비스 39,972 / 제외 184(marine_mammal 42 + tunicate_marine 142).

### 1-F. GBIF 관측 — `observation_gbif.csv` (etl_gbif.py 산출)
- **다운로드**: `R/gbif_01_all.R`(신규, `gbif_00_download.R` 자동화) — 9 서비스분류군 `occ_download` 일괄 제출(occ_download_queue 3동시)·SUCCEEDED 대기·import → `1_Data/raw/gbif/gbif_<group>.csv`.
  - 술어: `country=KR ∧ taxonKey∈(classKey ∪ order폴백키) ∧ hasCoordinate ∧ !geoIssue ∧ PRESENT ∧ year≥1900 ∧ basisOfRecord∉{FOSSIL,LIVING,MATERIAL_CITATION}`. 자격증명=`~/.Renviron` GBIF_USER/PWD/EMAIL(비대화형은 `R_ENVIRON_USER` 지정).
  - class 미해석(어류 Actinopterygii·Chondrichthyes·Petromyzontida=NONE, 파충류 Reptilia=HIGHERRANK 등)은 하위 order(목) 학명을 `name_backbone(rank="order")`로 폴백 해석(`4_References/gbif_order_keys.csv`). 다운로드 9분류군 총 ~400만 레코드(예: -P 1.56M·MS 778k·IN 760k·AM 363k·IV 292k·MM 141k·RP 71k·AV 24k·VP 4k).
- **어댑터**: `etl_gbif.py` ← `gbif_<group>.csv` → 관측 스키마(`observation_nps`와 동일, **source='gbif'**). **학명 단독 매칭**(GBIF vernacular은 노이즈라 미사용; managed_key 정확일치). **분류군은 매칭된 ktsn의 master `taxon_group` 기준**(다운로드 파일 그룹이 아님) — 일부 다운로드가 order 폴백으로 광범위해도 각 레코드가 진짜 분류군으로 귀속. 좌표→시도 sjoin(BND_SIDO_PG) + (ktsn,taxon_group,sido,year) DISTINCT 좌표 집계.
- **union**: `build_demo_data.union_obs()`가 agg(EcoBank)+nps(국립공원)+**gbif** 3원 합류(코드 반영). `improve_species_list`도 관측원에 gbif 포함.
- ⚠ **geopandas 필요** → anaconda python(`C:\Users\yssfr\anaconda3\python.exe`)으로 실행(Windows Store python엔 geopandas 없음). EcoBank/국립공원 ETL도 동일.

---

## 2. 서비스 테이블 — `5_App/demo/data/` (정적 .js + .json)

- **생성**: `build_demo_data.py 2026-06-20` ← master + species_service_flags + observation_agg + observation_nps
- `.json`=HTTP/배포용, `.js`=`window.__X__=…`(file:// 직접열기용). 클라이언트가 (분류군·연도·시도) 필터로 발견/미발견·통계·CSV 동적 계산.

| 파일 | 내용 | 핵심 구조 |
|---|---|---|
| `taxa_summary.js` | 대문 타일(분류군별 종수·관측종수·데이터유무) | `window.__TAXA__=[{group,kor,n_species,n_obs_species,has_data,n_records}]` — UC 제외로 **9그룹** |
| `obs_by_taxon.js` | 분류군별 조회(모드 A) | `window.__OBS__={TX:{obs:[[ktsn,sido,year,c]],years,sidos,sources,n_records,n_obs_species}}` + `window.__OBSMETA__` |
| `species_index.js` | 종별 검색(모드 B) | `window.__SPIDX__=[{k,n,s,t,g,r}]` — 서비스 대상 **39,972종**(멸종위기 I/II→Naturing, 그 외→EcoBank 링크) |
| `demo_mm.js` | 포유류 상세 대시보드 | `window.__DEMO_MM__={species,obs,meta,…}` (88종·54발견·204,569관측) |

**제외종 일관 적용**: `build_demo_data`의 `load_excluded()`가 species_service_flags의 `in_service=False` ktsn을 읽어 taxa_summary·obs_by_taxon·species_index·demo_mm 모두에서 제거 → 종수·검색·지도·관측이 항상 동일 모집단.

---

## 3. 실행 순서 (전체 재빌드)

> **주의: geopandas가 필요한 단계(etl_observation·etl_national_park·etl_gbif·improve_species_list)는
> anaconda python으로 실행** — `C:\Users\yssfr\anaconda3\python.exe` (PATH의 Windows Store python엔 geopandas 없음).
> GBIF 다운로드(R)는 비대화형이면 `$env:R_ENVIRON_USER='…\.Renviron'` 선설정.

```bash
cd 3_ETL/python
python build_ktsn_master.py                 # nibr+등급+적색 → ktsn_master.csv (+ktsn_aliases.csv)
# GBIF (R, 자격증명 필요): submit(제출+대기) → import(zip→csv)
Rscript ../R/gbif_01_all.R submit           # → gbif_<group>_key.txt (9분류군 occ_download)
Rscript ../R/gbif_01_all.R import           # → 1_Data/raw/gbif/gbif_<group>.csv
python etl_observation.py <ecobank ndjson…> # → observation_agg.csv  (override+alias 적용)
python etl_national_park.py                 # → observation_nps.csv (+unmatched)
python etl_gbif.py                          # → observation_gbif.csv (학명매칭·매칭ktsn 분류군 기준)
python reconcile_unmatched.py               # → observation_nps_unmatched_candidates.csv (검토용)
python improve_species_list.py              # → species_service_flags.csv
python build_demo_data.py 2026-06-28        # → 5_App/demo/data/*.js (+.json)
cd ../../5_App && python build_dist.py --osm-only --out ../docs   # → docs/ (GitHub Pages)
```

의존: master(+aliases) → 관측 ETL 3종(EcoBank/국립공원/GBIF, override+alias 흡수) → reconcile → flags → demo_data → dist.
GBIF는 `gbif_<group>.csv`만 있으면 etl_gbif가 매칭ktsn 분류군 기준으로 정확 귀속(다운로드 파일 라벨에 비의존).
보정 워크플로: reconcile 후보 검토 → `4_References/ktsn_name_overrides.csv` 승격 → 관측 ETL 재실행.
