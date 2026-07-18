# -*- coding: utf-8 -*-
"""
시민과학 제보(reports) 지오 보강 — Feature B P2.
제보 좌표(lat/lon) → ⑴ 시군구(point-in-polygon, SGIS full-res) ⑵ fills_gap(그 시군구에서
해당 종이 최근 10년 내 미발견이면 True = 발견공백을 메우는 재발견/신규 후보).

- 시군구 = build_sigungu_agg.load_sigungu (within, 연안 2km 근접폴백; cell_sigungu 와 동일 규칙)
- fills_gap = species_region(7_MCP/data/fg_mcp.sqlite; ktsn×시군구→maxyear) 에서 found(maxyear≥올해−10)
  이 아니면 True. 미기록·휴면(dormant) 모두 gap 을 메움.

입출력 두 모드:
  ① 온라인(운영): Supabase reports 중 sigungu IS NULL 인 행을 읽어 보강 후 UPDATE.
     서비스롤 필요 —  env  SUPABASE_URL, SUPABASE_SERVICE_KEY (절대 커밋·출력 금지).
       python build_report_geo.py
  ② 오프라인(검증): 좌표 JSON 을 읽어 보강 결과 JSON 출력(네트워크·키 불요).
       python build_report_geo.py --from-json in.json --to-json out.json
     in.json  = [{"id":..,"ktsn":"..","lat":..,"lon":..}, ...]
     out.json = [{"id":..,"sigungu":"11010","fills_gap":true}, ...]
"""
import sys, os, json, time, argparse, sqlite3
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sigungu_agg import load_sigungu              # 중첩 zip → 4326 GeoDataFrame[code, geometry]
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parents[2]
MCP_SQLITE = BASE / "7_MCP" / "data" / "fg_mcp.sqlite"
NEAR_TOL_M = 2000
CUTOFF = date.today().year - 10                          # found = maxyear ≥ cutoff


def _found_index():
    """species_region → {(ktsn, sigungu)} 중 found(maxyear≥cutoff) 인 조합 집합."""
    if not MCP_SQLITE.exists():
        raise SystemExit(f"MCP sqlite 없음: {MCP_SQLITE} (7_MCP 빌드 필요)")
    con = sqlite3.connect(str(MCP_SQLITE))
    rows = con.execute(
        "SELECT ktsn, region, maxyear FROM species_region WHERE region<>'00000'"
    ).fetchall()
    con.close()
    found = set()
    for ktsn, region, maxyear in rows:
        if maxyear is not None and int(maxyear) >= CUTOFF:
            found.add((str(ktsn), str(region)))
    return found


def enrich_points(points):
    """points=[{id,ktsn,lat,lon}] → [{id,sigungu,fills_gap}]. 시군구 PIP + fills_gap."""
    import geopandas as gpd, pandas as pd
    from shapely.geometry import Point
    if not points:
        return []
    sig, tmp = load_sigungu()
    try:
        df = pd.DataFrame(points)
        pts = gpd.GeoDataFrame(
            df.copy(), geometry=[Point(x, y) for x, y in zip(df.lon, df.lat)], crs=4326)
        j = gpd.sjoin(pts, sig, how="left", predicate="within")
        j = j[~j.index.duplicated(keep="first")]
        pts["code"] = j["code"].values
        miss = pts["code"].isna()
        if miss.any():                                   # 연안 → 2km 근접폴백(투영 5179)
            sig_m = sig.to_crs(5179)
            miss_m = pts[miss].drop(columns="code").to_crs(5179)
            nn = gpd.sjoin_nearest(miss_m, sig_m, how="left",
                                   max_distance=NEAR_TOL_M, distance_col="d")
            nn = nn[~nn.index.duplicated(keep="first")]
            pts.loc[miss, "code"] = nn["code"].values
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    found = _found_index()
    out = []
    for _, r in pts.iterrows():
        sg = None if pd.isna(r["code"]) else str(r["code"])
        # 시군구를 못 찾으면(해상 등) fills_gap 판정 보류(False)
        fg = bool(sg and sg != "00000" and (str(r["ktsn"]), sg) not in found)
        out.append({"id": r["id"], "sigungu": sg, "fills_gap": fg})
    return out


# ── 온라인(운영) I/O — Supabase 서비스롤 ──
def _sb_headers():
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    url = os.environ.get("SUPABASE_URL", "").strip()
    if not (key and url):
        raise SystemExit("env SUPABASE_URL, SUPABASE_SERVICE_KEY 필요(오프라인은 --from-json).")
    return url.rstrip("/"), {"apikey": key, "Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"}


def run_online():
    import requests
    url, h = _sb_headers()
    # sigungu 미보강 행만
    q = f"{url}/rest/v1/reports?select=id,ktsn,lat,lon&sigungu=is.null"
    rows = requests.get(q, headers=h, timeout=30).json()
    if not isinstance(rows, list) or not rows:
        print("보강할 제보 없음(sigungu IS NULL 0건)."); return
    print(f"보강 대상 {len(rows)}건")
    res = enrich_points([{"id": r["id"], "ktsn": r["ktsn"],
                          "lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows])
    n = 0
    for e in res:
        patch = {"sigungu": e["sigungu"], "fills_gap": e["fills_gap"]}
        rr = requests.patch(f"{url}/rest/v1/reports?id=eq.{e['id']}",
                            headers={**h, "Prefer": "return=minimal"},
                            data=json.dumps(patch), timeout=30)
        if rr.status_code < 300:
            n += 1
    print(f"UPDATE 완료 {n}/{len(res)}건  (fills_gap True {sum(1 for e in res if e['fills_gap'])})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="좌표 JSON 입력(오프라인 검증)")
    ap.add_argument("--to-json", help="보강 결과 JSON 출력")
    a = ap.parse_args()
    t0 = time.time()
    if a.from_json:
        pts = json.loads(Path(a.from_json).read_text(encoding="utf-8"))
        res = enrich_points([{"id": p["id"], "ktsn": str(p["ktsn"]),
                              "lat": float(p["lat"]), "lon": float(p["lon"])} for p in pts])
        out = a.to_json or (a.from_json + ".out.json")
        Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ {out}  {len(res)}건  fills_gap True {sum(1 for e in res if e['fills_gap'])}  "
              f"cutoff≥{CUTOFF}  {time.time()-t0:.1f}s")
    else:
        run_online()


if __name__ == "__main__":
    main()
