# -*- coding: utf-8 -*-
"""
발견공백 A(환경적합 미발견후보) 클라이언트 자산 빌드.

입력 : 1_Data/processed/{env_grid.csv, cell_sigungu.csv, species_cells.csv,
        ndwi_species.csv, species_env_stats.csv, ktsn_master.csv}
출력 : 5_App/demo/data/
  env_grid.js   window.__GRID__      — 전국 1km 육지셀: 환경값(양자화 정수 병렬배열) + 시군구 인덱스 + 시군구별 셀수
  cells_<T>.js  window.__CELLS__[T]  = {ktsn:{c:[cid..], y:[maxyear..]}}  — 종별 점유(분류군 지연로드, obs_<T> 와 동일 라우팅)
  gap_meta.js   window.__GAPMETA__   — generated·모델변수·NDWI 적용종·종별 관측 n(신뢰게이트)

클라이언트 계산(자산 최소화): 종 엔벨로프는 이미 로드된 __ENV__(종별 분위수)에서 변수별
  [Q1-1.5·IQR, Q3+1.5·IQR] 로 즉석 산출 → __GRID__ 셀을 AND·binary 판정. __CELLS__ 로 발견/미발견,
  재발견(maxyear ≤ 현재연도-10) 구분. 시군구별 (적합&미발견)/(총 배정셀) = 적합지 비율.
  NDWI 는 __GAPMETA__.ndwi 수록 종(어류+저서무척추)만 모델 변수에 포함(그래프는 전 종 일괄, 무관).

사용 : python build_gap_data.py [YYYY-MM-DD]   (env_layers·species_cells·cell_sigungu 이후)
"""
import sys, re, csv, json, gzip
from pathlib import Path
from collections import defaultdict

APP = Path(__file__).resolve().parent
BASE = APP.parent
PROC = BASE / "1_Data" / "processed"
OUT = APP / "demo" / "data"
GEN = sys.argv[1] if len(sys.argv) > 1 else ""

MODEL_VARS = ["bio01", "bio06", "bio12", "dem", "ndvi", "ndwi"]      # ndwi = 수생 종만(클라이언트 분기)
SCALE = {"lon": 10000, "lat": 10000, "bio01": 10, "bio06": 10,
         "bio12": 1, "dem": 1, "ndvi": 1000, "ndwi": 1000}           # 정수 양자화 계수(클라이언트가 나눠 복원)


def _txfile(t):
    """분류군 코드 → 파일명 토큰('-P'→'_P'). build_demo_data/service.html 규칙과 일치."""
    return re.sub(r"[^A-Za-z0-9]", "_", t)


def _q(x, s):
    """문자열 수치 → round(x*s) 정수(빈값·NaN=None)."""
    if x is None or x == "":
        return None
    try:
        f = float(x)
    except ValueError:
        return None
    if f != f:
        return None
    return int(round(f * s))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    csv.field_size_limit(10 ** 7)
    OUT.mkdir(parents=True, exist_ok=True)

    # ktsn → taxon_group (cells 분류군 분할용)
    tx = {}
    for r in csv.DictReader(open(PROC / "ktsn_master.csv", encoding="utf-8-sig")):
        tx[r["ktsn"]] = r.get("taxon_group") or "?"

    # cid → 시군구 코드
    csig = {}
    for r in csv.DictReader(open(PROC / "cell_sigungu.csv", encoding="utf-8-sig")):
        csig[int(r["cid"])] = r["region"]

    # ── env_grid → 병렬배열(cid 오름차순) ────────────────────────────────
    rows = list(csv.DictReader(open(PROC / "env_grid.csv", encoding="utf-8")))
    rows.sort(key=lambda r: int(r["cid"]))
    sgcodes, sgidx = [], {}
    cols = ("cid", "lon", "lat", "bio01", "bio06", "bio12", "dem", "ndvi", "ndwi", "sg")
    G = {k: [] for k in cols}
    for r in rows:
        cid = int(r["cid"])
        G["cid"].append(cid)
        G["lon"].append(_q(r["lon"], SCALE["lon"]))
        G["lat"].append(_q(r["lat"], SCALE["lat"]))
        for k in ("bio01", "bio06", "bio12", "dem", "ndvi", "ndwi"):
            G[k].append(_q(r.get(k), SCALE[k]))
        code = csig.get(cid, "00000")
        if code not in sgidx:
            sgidx[code] = len(sgcodes); sgcodes.append(code)
        G["sg"].append(sgidx[code])
    sgn = [0] * len(sgcodes)
    for s in G["sg"]:
        sgn[s] += 1
    grid = {**G, "sgcodes": sgcodes, "sgn": sgn, "scale": SCALE}
    (OUT / "env_grid.js").write_text(
        "window.__GRID__=" + json.dumps(grid, separators=(",", ":")) + ";\n", encoding="utf-8")
    graw = (OUT / "env_grid.js").stat().st_size
    ggz = len(gzip.compress((OUT / "env_grid.js").read_bytes()))
    print(f"env_grid.js 셀 {len(G['cid']):,} · 시군구 {len(sgcodes)} · "
          f"{graw/1024:.0f}KB (gzip {ggz/1024:.0f}KB)")

    # ── species_cells → 분류군별 {ktsn:{c,y}} ────────────────────────────
    byt = defaultdict(dict)                                          # taxon → {ktsn:([cids],[years])}
    with open(PROC / "species_cells.csv", encoding="utf-8") as f:
        next(f)
        for line in f:
            k, c, y = line.rstrip("\n").split(",")
            d = byt[tx.get(k, "?")]
            cy = d.get(k)
            if cy is None:
                cy = ([], []); d[k] = cy
            cy[0].append(int(c)); cy[1].append(int(y))
    print("cells_<T>.js:")
    for t, spd in sorted(byt.items()):
        obj = {k: {"c": cy[0], "y": cy[1]} for k, cy in spd.items()}
        payload = json.dumps(obj, separators=(",", ":"))
        p = OUT / f"cells_{_txfile(t)}.js"
        p.write_text(f'(window.__CELLS__=window.__CELLS__||{{}})["{t}"]='
                     f'Object.assign(window.__CELLS__["{t}"]||{{}},{payload});', encoding="utf-8")
        pairs = sum(len(cy[0]) for cy in spd.values())
        print(f"   [{t}] 종 {len(spd):,} · (종,셀) {pairs:,} · {p.stat().st_size/1_048_576:.2f}MB")

    # ── gap_meta: NDWI 적용종 · 종별 관측 n(신뢰게이트) ──────────────────
    ndwi = [r["ktsn"] for r in csv.DictReader(open(PROC / "ndwi_species.csv", encoding="utf-8-sig"))]
    n = {}
    for r in csv.DictReader(open(PROC / "species_env_stats.csv", encoding="utf-8-sig")):
        if r["var"] == "bio01":
            try:
                n[r["ktsn"]] = int(float(r["n"]))
            except ValueError:
                pass
    meta = {"generated": GEN, "vars": MODEL_VARS, "ndwiVar": "ndwi", "ndwi": ndwi, "n": n}
    (OUT / "gap_meta.js").write_text(
        "window.__GAPMETA__=" + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    print(f"gap_meta.js NDWI적용종 {len(ndwi):,} · 관측n 종 {len(n):,} · generated={GEN or '(미지정)'}")


if __name__ == "__main__":
    main()
