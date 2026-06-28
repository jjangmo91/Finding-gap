# -*- coding: utf-8 -*-
"""
GBIF 점유자료(gbif_<group>.csv) → observation_gbif.csv (시도 spatial join + obs_count 집계).
- 입력: 1_Data/raw/gbif/gbif_<group>.csv (gbif_01_all.R import 산출; 좌표·학명 점자료)
- 매칭: 학명(scientificName→species) → managed_key → ktsn. (GBIF vernacular은 노이즈라 미사용,
        학명 단독 매칭. 보정 매핑(override) 최우선. taxon_group은 매칭된 ktsn 기준으로 확정.)
- 시도: decimalLongitude,decimalLatitude EPSG:4326 → BND_SIDO_PG point-in-polygon → sido. 폴리곤 밖=미상.
- 연도: year 컬럼(없으면 eventDate에서 4자리).
- obs_count = COUNT(DISTINCT 좌표) per (ktsn, taxon_group, sido, year, source='gbif').
- source = 'gbif' (고정). observation_agg(EcoBank)·observation_nps(국립공원)와 동일 스키마 → build_demo_data가 union.
사용: python etl_gbif.py
출력: 1_Data/processed/observation_gbif.csv + observation_gbif_report.txt
"""
import sys, csv, re, time
from pathlib import Path
from collections import defaultdict, Counter

from etl_national_park import load_master, resolve_ktsn   # 마스터+별칭, 충돌판정(override 최우선)
from name_overrides import load_overrides
from taxon_key import managed_key

csv.field_size_limit(10**7)

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
GBIF_RAW = BASE / "1_Data" / "raw" / "gbif"
SIDO_SHP = BASE / "1_Data" / "spatial" / "BND_SIDO_PG" / "BND_SIDO_PG.shp"
OUT = PROC / "observation_gbif.csv"
REPORT = PROC / "observation_gbif_report.txt"

SERVICE_GROUPS = ["MM", "AV", "RP", "AM", "-P", "IV", "IN", "VP", "MS"]


def parse_year(year_str, event_date):
    s = (year_str or "").strip()
    m = re.match(r"(\d{4})", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4})", event_date or "")
    return m.group(1) if m else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()

    sci, kor, ktsn_tx = load_master()
    ov_sci, ov_kor = load_overrides()
    print(f"마스터 로드: 학명키 {len(sci):,} · ktsn {len(ktsn_tx):,} | 보정매핑 학명 {len(ov_sci)}  ({time.time()-t0:.1f}s)")

    # (ktsn, taxon_group, year) → set((lon,lat))  : 스트리밍 dedup으로 메모리 절감
    grp_pre = defaultdict(set)
    uniq = set()
    n_all = n_match = n_override = n_sci = n_none = n_nocoord = n_taxon_mismatch = 0
    per_group_files = 0
    unmatched = Counter()
    mismatch_pairs = Counter()        # (파일그룹 → 매칭ktsn 분류군) 진단

    for g in SERVICE_GROUPS:
        fp = GBIF_RAW / f"gbif_{g}.csv"
        if not fp.exists():
            print(f"  [{g}] gbif_{g}.csv 없음 — skip")
            continue
        per_group_files += 1
        n_g = 0
        with fp.open(encoding="utf-8", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                n_all += 1
                n_g += 1
                sciname = (r.get("scientificName") or "").strip() or (r.get("species") or "").strip()
                year = parse_year(r.get("year"), r.get("eventDate"))
                try:
                    lon = float(r.get("decimalLongitude"))
                    lat = float(r.get("decimalLatitude"))
                except (TypeError, ValueError):
                    lon, lat = None, None
                if lon is None:
                    n_nocoord += 1
                    continue
                # 학명 단독 매칭(override 최우선). kor_name=None → both/conflict 미발생.
                ktsn, how = resolve_ktsn(sci, kor, sciname, None, ov_sci, ov_kor)
                if how == "override":
                    n_override += 1; n_match += 1
                elif how == "sci":
                    n_sci += 1; n_match += 1
                else:                                  # none → 미매칭 폐기
                    n_none += 1
                    if sciname:
                        unmatched[sciname] += 1
                    continue
                tx = ktsn_tx.get(ktsn, "")
                if tx and tx != g:
                    n_taxon_mismatch += 1            # 학명이 타 분류군 ktsn으로 매칭 — 매칭 ktsn 기준 사용
                    mismatch_pairs[(g, tx)] += 1
                grp_pre[(ktsn, tx, year)].add((lon, lat))
                uniq.add((lon, lat))
        print(f"  [{g}] {n_g:,} 행 처리")

    print(f"매칭: 총 {n_all:,} | 매칭 {n_match:,} ({n_match/max(n_all,1)*100:.1f}%) "
          f"[보정 {n_override:,} · 학명 {n_sci:,}] | 미매칭 {n_none:,} · 무좌표 {n_nocoord:,} · 타분류군매칭 {n_taxon_mismatch:,}  ({time.time()-t0:.1f}s)")

    # 시도 spatial join (고유 좌표만)
    import geopandas as gpd
    from shapely.geometry import Point
    t2 = time.time()
    uniq_list = sorted(uniq)
    n_coords = len(uniq_list)
    sido_gdf = gpd.read_file(SIDO_SHP)
    name_col = next((c for c in sido_gdf.columns
                     if c.upper() in ("CTP_KOR_NM", "SIDO_NM", "CTPRVN_NM", "SIDONM")), None)
    if name_col is None:
        name_col = next(c for c in sido_gdf.columns if sido_gdf[c].dtype == object and c != "geometry")
    sido_gdf = sido_gdf.to_crs(4326)[[name_col, "geometry"]].rename(columns={name_col: "sido"})
    pts = gpd.GeoDataFrame({"i": range(n_coords)},
                           geometry=[Point(lo, la) for lo, la in uniq_list], crs=4326)
    joined = gpd.sjoin(pts, sido_gdf, how="left", predicate="within")
    coord_sido = {}
    for i, sd in zip(joined["i"], joined["sido"]):
        coord_sido.setdefault(uniq_list[i], sd if isinstance(sd, str) else "미상")
    n_unknown = sum(1 for v in coord_sido.values() if v == "미상")
    print(f"시도조인: 고유좌표 {n_coords:,} | 시도밖(미상) {n_unknown:,}  ({time.time()-t2:.1f}s)")

    # 집계: (ktsn, taxon_group, sido, year, 'gbif') → DISTINCT 좌표 수
    t3 = time.time()
    grp = defaultdict(set)
    for (ktsn, tx, year), coords in grp_pre.items():
        for (lon, lat) in coords:
            sd = coord_sido.get((lon, lat), "미상")
            grp[(ktsn, tx, sd, year, "gbif")].add((lon, lat))
    rows = [{"ktsn": k, "taxon_group": tx, "sido": s, "year": y, "source": sr, "obs_count": len(p)}
            for (k, tx, s, y, sr), p in grp.items()]
    rows.sort(key=lambda r: (r["taxon_group"], r["sido"], r["year"], -r["obs_count"]))

    PROC.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ktsn", "taxon_group", "sido", "year", "source", "obs_count"])
        w.writeheader(); w.writerows(rows)
    print(f"집계: observation_gbif 행 {len(rows):,}  ({time.time()-t3:.1f}s) → {OUT.name}")

    # 리포트
    tx_sp = {}
    for tx in sorted({r["taxon_group"] for r in rows}):
        tx_sp[tx] = len({r["ktsn"] for r in rows if r["taxon_group"] == tx})
    lines = [
        "=" * 70, "GBIF 점유자료 ETL 리포트", "=" * 70,
        f"생성일시: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"입력 파일: {per_group_files}개 분류군 csv",
        "",
        f"총 기록 {n_all:,} | 매칭 {n_match:,} ({n_match/max(n_all,1)*100:.1f}%; 보정 {n_override:,}·학명 {n_sci:,}) "
        f"| 미매칭 {n_none:,} · 무좌표 {n_nocoord:,} · 타분류군매칭 {n_taxon_mismatch:,}",
        f"출력 행 {len(rows):,} | 고유 좌표 {n_coords:,} | 시도밖 {n_unknown:,}",
        "",
        "▪ 분류군별 관측종 수(GBIF):",
    ]
    for tx in sorted(tx_sp): lines.append(f"  [{tx}] {tx_sp[tx]:,} 종")
    lines += ["", "▪ 타분류군매칭 top 15 (파일그룹 → 매칭ktsn 분류군 : 건수):"]
    for (g, tx), c in mismatch_pairs.most_common(15): lines.append(f"  {g:>3s} → {tx:<3s} : {c:,}")
    lines += ["", "▪ 미매칭 학명 top 15:"]
    for nm, c in unmatched.most_common(15): lines.append(f"  {c:,}x  {nm}")
    lines += ["", f"총 소요 {time.time()-t0:.1f}s", "=" * 70]
    txt = "\n".join(lines)
    print(txt)
    with REPORT.open("w", encoding="utf-8-sig") as f: f.write(txt)
    print(f"\n리포트 저장: {REPORT.name}")


if __name__ == "__main__":
    main()
