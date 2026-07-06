# -*- coding: utf-8 -*-
"""
env_grid 1km 셀 → 시군구 코드 매핑 — 발견공백 A의 '시군구 적합지 비율표'·행클릭 줌 기준.
비율 = (적합&미발견 셀수) / (시군구에 배정된 1km 육지 셀수) — 이 스크립트가 분모(셀→시군구)를 만든다.

입력 : 1_Data/processed/env_grid.csv           (cid,lon,lat,...  — env_layers.R §5 산출, 육지 105,340셀)
       1_Data/spatial/bnd_all_00_2025_2Q.zip   (SGIS 2025 2Q 시군구 full-resolution)
출력 : 1_Data/processed/cell_sigungu.csv        (cid, region=SIGUNGU_CD 5자리; 미상 '00000')

매칭 : full-resolution point-in-polygon(within). 폴리곤 밖(연안·해상)은 2km 이내 최근접 시군구로 폴백,
       그래도 없으면 '00000'. build_sigungu_agg 와 동일 규칙(단순화 geojson 은 화면용일 뿐 매칭엔 미사용).
사용 : python build_cell_sigungu.py
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sigungu_agg import load_sigungu          # 중첩 zip → 4326 GeoDataFrame[code, geometry]
# ⚠ build_sigungu_agg 는 import 시 stdout 을 UTF-8 TextIOWrapper 로 교체한다. 여기서 다시 감싸면
#   먼저 래퍼가 GC 되며 공유 버퍼를 닫아 "closed file" 오류 → 재래핑 금지, reconfigure 만.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
t0 = time.time()

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
GRID = PROC / "env_grid.csv"
OUT = PROC / "cell_sigungu.csv"
NEAR_TOL_M = 2000                                    # 2km(연안 셀 회복; 투영 5179 meter)


def main():
    import geopandas as gpd, pandas as pd
    from shapely.geometry import Point

    sig, tmp = load_sigungu()
    print(f"시군구 {len(sig)}개 로드  {time.time()-t0:.1f}s")

    cells = pd.read_csv(GRID, usecols=["cid", "lon", "lat"])
    pts = gpd.GeoDataFrame(cells.copy(),
                           geometry=[Point(x, y) for x, y in zip(cells.lon, cells.lat)], crs=4326)
    print(f"셀 {len(cells):,}  {time.time()-t0:.1f}s")

    # 1) point-in-polygon
    j = gpd.sjoin(pts, sig, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    pts["code"] = j["code"].values
    miss = pts["code"].isna()
    print(f"within {(~miss).sum():,}/{len(pts):,} = {(~miss).mean()*100:.2f}%  "
          f"미매칭 {miss.sum():,}  {time.time()-t0:.1f}s")

    # 2) 미매칭 → 최근접 시군구(2km) 폴백 — 투영좌표(5179, meter)
    if miss.any():
        sig_m = sig.to_crs(5179)
        miss_m = pts[miss].drop(columns="code").to_crs(5179)
        nn = gpd.sjoin_nearest(miss_m, sig_m, how="left",
                               max_distance=NEAR_TOL_M, distance_col="d")
        nn = nn[~nn.index.duplicated(keep="first")]
        pts.loc[miss, "code"] = nn["code"].values
        rec = pts["code"].notna().sum()
        print(f"근접폴백 후 {rec:,}/{len(pts):,} = {rec/len(pts)*100:.2f}%  "
              f"잔여미상 {pts['code'].isna().sum():,}  {time.time()-t0:.1f}s")

    pts["code"] = pts["code"].fillna("00000")
    out = pts[["cid", "code"]].rename(columns={"code": "region"})
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    vc = out["region"].value_counts()
    print(f"→ {OUT.name}  셀 {len(out):,}  시군구수 {out['region'].nunique()}  "
          f"미상('00000') {int((out['region']=='00000').sum()):,}  "
          f"최다 {vc.index[0]}({int(vc.iloc[0]):,})  {time.time()-t0:.1f}s")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
