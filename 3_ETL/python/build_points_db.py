# -*- coding: utf-8 -*-
"""
관측 점 단위 기본 DB 구축 — 좌표를 보존한 단일 원천(ktsn,taxon_group,source,year,sido,lon,lat).
입력: 1_Data/processed/observation_points_{ecobank,gbif,nps}.csv  (각 관측 ETL 부산물 write_points)
출력: 1_Data/processed/observations.sqlite  (table obs_points + 인덱스)
검증: obs_points 를 (ktsn,taxon_group,sido,year,source) 로 센 카운트가
      기존 observation_{agg,gbif,nps}.csv 의 obs_count 와 정확히 일치하는지 비교(키집합·카운트).
      → 시도 집계(서빙)가 이 점 DB에서 그대로 파생됨을 보증.
용도: bioclim 등 점 기반 분석의 단일 원천. (좌표 없는 관측은 lon/lat NULL·sido 미상으로 보존.)
사용: python build_points_db.py
"""
import sys, csv, sqlite3, time
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
DB = PROC / "observations.sqlite"

POINT_FILES = ["observation_points_ecobank.csv",
               "observation_points_gbif.csv",
               "observation_points_nps.csv"]
AGG_FILES = {                       # source 계열 → 기존 시도 집계 CSV(검증 대상)
    "ecobank": "observation_agg.csv",
    "gbif": "observation_gbif.csv",
    "nps": "observation_nps.csv",
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    csv.field_size_limit(10**7)
    t0 = time.time()

    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""CREATE TABLE obs_points(
        ktsn TEXT, taxon_group TEXT, source TEXT, year INTEGER,
        sido TEXT, lon REAL, lat REAL)""")

    n_total = 0
    derived = defaultdict(int)      # (ktsn,tx,sido,year,source) → 점 수 (검증용; year 는 원본 문자열 유지)
    for fn in POINT_FILES:
        fp = PROC / fn
        if not fp.exists():
            print(f"(경고) 누락: {fn} — skip")
            continue
        batch = []
        with fp.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                yr = (r["year"] or "").strip()
                year = int(yr) if yr.isdigit() else None
                lon = float(r["lon"]) if (r["lon"] or "").strip() else None
                lat = float(r["lat"]) if (r["lat"] or "").strip() else None
                batch.append((r["ktsn"], r["taxon_group"], r["source"], year, r["sido"], lon, lat))
                derived[(r["ktsn"], r["taxon_group"], r["sido"], yr, r["source"])] += 1
        cur.executemany("INSERT INTO obs_points VALUES (?,?,?,?,?,?,?)", batch)
        con.commit()
        n_total += len(batch)
        print(f"  적재 {fn}: {len(batch):,} 행")

    cur.execute("CREATE INDEX ix_ktsn ON obs_points(ktsn)")
    cur.execute("CREATE INDEX ix_tx ON obs_points(taxon_group)")
    cur.execute("CREATE INDEX ix_coord ON obs_points(lon, lat)")
    con.commit()
    print(f"obs_points 총 {n_total:,} 행 · 인덱스 3 → {DB.name}  ({time.time()-t0:.1f}s)")

    # 검증: 점 DB 집계 == 기존 시도 집계 CSV
    print("\n검증(점 DB 집계 == 기존 시도 집계 CSV):")
    ok = True
    for srcfam, aggfn in AGG_FILES.items():
        ap = PROC / aggfn
        if not ap.exists():
            print(f"  [{srcfam}] {aggfn} 없음 — skip")
            continue
        agg = {}
        with ap.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                agg[(r["ktsn"], r["taxon_group"], r["sido"], r["year"], r["source"])] = int(r["obs_count"])
        srcset = {k[4] for k in agg}                          # 이 집계 파일이 담는 source 계열
        dsub = {k: v for k, v in derived.items() if k[4] in srcset}
        same = (dsub == agg)
        ok = ok and same
        n_pts = sum(dsub.values())
        print(f"  [{srcfam}] 집계행 {len(agg):,} · 점파생행 {len(dsub):,} · 점합계 {n_pts:,} · 일치 {same}")
    print(f"\n전체 검증 {'통과 — 점 DB에서 시도 집계 동일 파생' if ok else '불일치(확인 필요)'}  ({time.time()-t0:.1f}s)")
    con.close()


if __name__ == "__main__":
    main()
