# -*- coding: utf-8 -*-
"""
좌표 점 기본 DB(observations.sqlite / obs_points) → 시군구 키 서빙 집계.

배경: obs_count = (ktsn,taxon_group,sido,year,source) 그룹의 고유좌표 수(obs_common.write_points 주석).
      따라서 점을 시군구로 다시 묶어 세면 obs_count 가 보존되고, 시도는 시군구코드 앞 2자리로 롤업된다.
      → ETL raw 재실행 없이 점 DB 에서 시군구 집계를 파생한다(점 DB 단일 원천 원칙).

입력 : 1_Data/processed/observations.sqlite (obs_points: ktsn,taxon_group,source,year,sido,lon,lat)
       1_Data/spatial/bnd_sigungu_00_2025_2Q.* (SGIS 2025 2Q 시군구, EPSG:5179)
출력 : 1_Data/processed/observation_sigungu.csv
        스키마 ktsn,taxon_group,region,year,source,obs_count  (region = SIGUNGU_CD 5자리, 미상='00000')

좌표→시군구: full-resolution point-in-polygon(within). 폴리곤 밖(해상·연안)은 2km 이내 최근접 시군구로 폴백,
그래도 없으면 '00000'(미상). 단순화 geojson 은 화면 표시용일 뿐 이 매칭엔 쓰지 않는다(정확도 보존).
"""
import sys, io, time, sqlite3, zipfile, tempfile, shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
t0 = time.time()

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
SPAT = BASE / "1_Data" / "spatial"
DB = PROC / "observations.sqlite"
OUT = PROC / "observation_sigungu.csv"
SIGU_ZIP = SPAT / "bnd_all_00_2025_2Q.zip"          # 중첩 zip: 안에 bnd_sigungu_00_2025_2Q.zip
NEAR_TOL_M = 2000                                    # 2km(연안 점 회복; 투영 5179 meter 기준)


def load_sigungu():
    """중첩 zip 에서 시군구 shapefile 을 임시폴더로 풀어 4326 GeoDataFrame[code, geometry] 반환."""
    import geopandas as gpd
    tmp = Path(tempfile.mkdtemp(prefix="sigungu_"))
    with zipfile.ZipFile(SIGU_ZIP) as z:
        inner = z.read("bnd_sigungu_00_2025_2Q.zip")
    with zipfile.ZipFile(io.BytesIO(inner)) as iz:
        iz.extractall(tmp)
    shp = next(tmp.glob("*.shp"))
    g = gpd.read_file(shp).to_crs(4326)[["SIGUNGU_CD", "geometry"]].rename(
        columns={"SIGUNGU_CD": "code"})
    g["code"] = g["code"].astype(str)
    return g, tmp


def main():
    import geopandas as gpd, pandas as pd
    from shapely.geometry import Point

    sig, tmp = load_sigungu()
    print(f"시군구 {len(sig)}개 로드  {time.time()-t0:.1f}s")

    con = sqlite3.connect(DB)
    uc = pd.read_sql("SELECT DISTINCT lon,lat FROM obs_points WHERE lon IS NOT NULL", con)
    pts = gpd.GeoDataFrame(uc.copy(),
                           geometry=[Point(x, y) for x, y in zip(uc.lon, uc.lat)], crs=4326)
    print(f"고유좌표 {len(uc):,}  {time.time()-t0:.1f}s")

    # 1) point-in-polygon
    j = gpd.sjoin(pts, sig, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    pts["code"] = j["code"].values
    miss = pts["code"].isna()
    print(f"within 매칭 {(~miss).sum():,}/{len(pts):,} = {(~miss).mean()*100:.2f}%  "
          f"미매칭 {miss.sum():,}  {time.time()-t0:.1f}s")

    # 2) 미매칭 → 최근접 시군구(2km 이내) 폴백 — 투영좌표(5179, meter)에서 정확히 계산
    if miss.any():
        sig_m = sig.to_crs(5179)
        miss_m = pts[miss].drop(columns="code").to_crs(5179)
        nn = gpd.sjoin_nearest(miss_m, sig_m, how="left",
                               max_distance=NEAR_TOL_M, distance_col="d")
        nn = nn[~nn.index.duplicated(keep="first")]
        pts.loc[miss, "code"] = nn["code"].values
        rec = pts["code"].notna().sum()
        print(f"근접폴백 후 매칭 {rec:,}/{len(pts):,} = {rec/len(pts)*100:.2f}%  "
              f"잔여미상 {pts['code'].isna().sum():,}  {time.time()-t0:.1f}s")

    pts["code"] = pts["code"].fillna("00000")

    # 3) 메모리 DB 에 좌표→코드 적재 후 obs_points 와 join 하여 시군구 집계(원본 DB 무변경)
    con.execute("ATTACH ':memory:' AS mem")
    con.execute("CREATE TABLE mem.cc(lon REAL, lat REAL, code TEXT)")
    con.executemany("INSERT INTO mem.cc VALUES (?,?,?)",
                    list(zip(pts.lon.tolist(), pts.lat.tolist(), pts.code.tolist())))
    con.execute("CREATE INDEX mem.cc_xy ON cc(lon,lat)")
    print(f"좌표→코드 {len(pts):,} 적재  {time.time()-t0:.1f}s")

    rows = con.execute("""
        SELECT p.ktsn, p.taxon_group, COALESCE(cc.code,'00000') AS region,
               p.year, p.source, COUNT(*) AS obs_count
        FROM obs_points p
        LEFT JOIN mem.cc cc ON p.lon=cc.lon AND p.lat=cc.lat
        GROUP BY p.ktsn, p.taxon_group, region, p.year, p.source
    """).fetchall()
    print(f"집계 {len(rows):,}행  {time.time()-t0:.1f}s")

    import csv
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ktsn", "taxon_group", "region", "year", "source", "obs_count"])
        w.writerows(rows)

    # 검증: 총 obs_count, 시도(앞2자리) 롤업 상위
    tot = sum(r[5] for r in rows)
    by_sido = {}
    for k, t, region, y, s, c in rows:
        sd = region[:2]
        by_sido[sd] = by_sido.get(sd, 0) + c
    print(f"→ {OUT.name}  총 obs_count={tot:,}  시도(코드)수={len(by_sido)}  "
          f"미상('00')={by_sido.get('00',0):,}")
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
