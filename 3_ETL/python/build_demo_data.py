# -*- coding: utf-8 -*-
"""
종 마스터 + observation_agg → 데모용 정적 JSON.
출력:
  5_App/demo/data/demo_mm.json (+ .js)      — 포유류 MM 상세(대시보드·필터·테이블)
  5_App/demo/data/taxa_summary.json (+ .js) — 11분류군 총 종수·수집여부(대문 타일)
구조(demo_mm): {taxon, taxon_kor, generated, sidos[], years[], sources[],
       n_species, n_obs_rows, meta{crs,update_cycle,collected,n_records,n_obs_species,sources[],citation},
       species:[{k:ktsn, s:학명, n:국명, g:멸종위기등급, r:적색목록}],
       obs:[[ktsn, sido, year, obs_count], ...]}
클라이언트가 (연도·시도) 필터로 발견/미발견 complement·통계·CSV를 계산.
사용: python build_demo_data.py [YYYY-MM-DD]
"""
import sys, re, csv, json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
MASTER = PROC / "ktsn_master.csv"
AGG = PROC / "observation_agg.csv"
AGG_NPS = PROC / "observation_nps.csv"               # 국립공원 ETL(다분류군) — 있으면 union
AGG_GBIF = PROC / "observation_gbif.csv"             # GBIF 점유자료 ETL(다분류군) — 있으면 union
AGG_SIGUNGU = PROC / "observation_sigungu.csv"       # 점DB 파생 시군구 집계(region=SIGUNGU_CD) — 있으면 시도CSV 대신 우선
FLAGS = PROC / "species_service_flags.csv"           # 서비스 제외 종(해양포유류·무기록 어류)
OUTDIR = BASE / "5_App" / "demo" / "data"
OUT = OUTDIR / "demo_mm.json"
TAXON = "MM"
TAXON_KOR = "포유류"
GENERATED = sys.argv[1] if len(sys.argv) > 1 else ""   # 'YYYY-MM-DD' 주입(스크립트는 날짜 미생성)
YMAX = int(GENERATED[:4]) if GENERATED[:4].isdigit() else 2026   # 비정상 연도(미래/오류) 상한
YMIN = 1900

TAXON_ORDER = ["MM", "AV", "RP", "AM", "-P", "UC", "CC", "IV", "IN", "VP", "MS"]
CITATION = "국립생태원 EcoBank 조사자료 · 국립공원공단 생물자원현황 · 국립생물자원관 국가생물종목록(KTSN)"


def load_excluded():
    """species_service_flags.csv → in_service=False 인 ktsn 집합(없으면 빈 집합)."""
    excl = set()
    if FLAGS.exists():
        for r in csv.DictReader(FLAGS.open(encoding="utf-8-sig")):
            if (r.get("in_service") or "").strip().lower() == "false":
                excl.add(r["ktsn"])
    return excl


def _clean_year(y):
    """비정상 연도(예 4225)는 미상('')으로 — 관측(발견) 자체는 유지."""
    y = y or ""
    if y:
        try:
            if not (YMIN <= int(y) <= YMAX):
                y = ""
        except ValueError:
            y = ""
    return y


def union_obs():
    """관측 union → [(ktsn,taxon,region,year,source,count)].
    region = 행정구역 키. observation_sigungu.csv(점DB 파생) 가 있으면 region=SIGUNGU_CD(5자리, 미상 '00000'),
    없으면 기존 3개 시도 집계(region=시도명). region 은 하위(인코딩·집계)에서 불투명 키로만 쓰여 형식 무관."""
    rows = []
    if AGG_SIGUNGU.exists():                          # 시군구 집계 우선(시도는 클라이언트가 앞2자리로 롤업)
        for r in csv.DictReader(AGG_SIGUNGU.open(encoding="utf-8-sig")):
            try:
                c = int(r["obs_count"])
            except (KeyError, ValueError):
                continue
            rows.append((r["ktsn"], r.get("taxon_group") or "", r["region"],
                         _clean_year(r.get("year") or ""), r.get("source") or "", c))
        return rows
    for p in (AGG, AGG_NPS, AGG_GBIF):
        if not p.exists():
            continue
        for r in csv.DictReader(p.open(encoding="utf-8-sig")):
            try:
                c = int(r["obs_count"])
            except (KeyError, ValueError):
                continue
            rows.append((r["ktsn"], r.get("taxon_group") or "", r["sido"],
                         _clean_year(r.get("year") or ""), r.get("source") or "", c))
    return rows


def build_mm(excl=frozenset(), obs_rows=None):
    species = []
    for r in csv.DictReader(MASTER.open(encoding="utf-8-sig")):
        if (r.get("taxon_group") or "") != TAXON:
            continue
        if r["ktsn"] in excl:                       # 해양 포유류 제외(육상 위주)
            continue
        species.append({"k": r["ktsn"], "s": r.get("scientific_name", ""),
                        "n": r.get("korean_name", ""), "g": r.get("endangered_grade", ""),
                        "r": r.get("national_redlist_category", "")})
    sp_ids = {s["k"] for s in species}

    obs, sidos, years, sources = [], set(), set(), set()
    src_records, n_records = Counter(), 0
    for k, t, sido, year, src, c in (obs_rows if obs_rows is not None else union_obs()):
        if t != TAXON or k not in sp_ids:           # EcoBank+국립공원 union, MM·서비스 종만
            continue
        obs.append([k, sido, year, c])
        sidos.add(sido)
        if year:
            years.add(year)
        if src:
            sources.add(src)
            src_records[src] += c
        n_records += c

    obs_sp = len({o[0] for o in obs})
    meta = {
        "crs": "EPSG:4326",
        "update_cycle": "6mo",
        "collected": GENERATED,
        "n_records": n_records,
        "n_obs_species": obs_sp,
        "sources": [{"name": s, "records": src_records[s]} for s in sorted(sources)],
        "citation": CITATION,
    }
    data = {
        "taxon": TAXON, "taxon_kor": TAXON_KOR, "generated": GENERATED,
        "sidos": sorted(sidos), "years": sorted(years), "sources": sorted(sources),
        "n_species": len(species), "n_obs_rows": len(obs), "meta": meta,
        "species": sorted(species, key=lambda s: s["n"]),
        "obs": obs,
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(payload, encoding="utf-8")                                   # 정적 JSON(HTTP/배포)
    (OUTDIR / "demo_mm.js").write_text("window.__DEMO_MM__=" + payload + ";",    # file:// 직접열기용
                                       encoding="utf-8")
    print(f"→ {OUT}")
    print(f"  마스터 {len(species)}종 | 관측행 {len(obs)} | 관측종 {obs_sp} | "
          f"미발견 {len(species)-obs_sp} | 누적관측 {n_records}")
    print(f"  시도 {len(sidos)} | 연도 {len(years)} | source {sorted(sources)}")


def build_taxa_summary(excl=frozenset(), obs_rows=None):
    counts, kor = Counter(), {}
    for r in csv.DictReader(MASTER.open(encoding="utf-8-sig")):
        g = r.get("taxon_group") or ""
        if not g or r["ktsn"] in excl:               # 서비스 제외 종은 종수에서도 제외
            continue
        counts[g] += 1
        kor.setdefault(g, r.get("taxon_group_kor", ""))
    recs = Counter()
    obs_sp = {}
    for k, g, sido, year, src, c in (obs_rows if obs_rows is not None else union_obs()):
        if g and k not in excl:
            recs[g] += c
            obs_sp.setdefault(g, set()).add(k)
    order = [g for g in TAXON_ORDER if g in counts] + [g for g in counts if g not in TAXON_ORDER]
    summary = [{"group": g, "kor": kor.get(g, ""), "n_species": counts[g],
                "n_obs_species": len(obs_sp.get(g, ())), "has_data": recs.get(g, 0) > 0,
                "n_records": recs.get(g, 0)} for g in order]
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    (OUTDIR / "taxa_summary.json").write_text(payload, encoding="utf-8")
    (OUTDIR / "taxa_summary.js").write_text("window.__TAXA__=" + payload + ";", encoding="utf-8")
    print(f"→ taxa_summary.json ({len(summary)} groups; "
          f"has_data={[s['group'] for s in summary if s['has_data']]})")


def build_species_index(excl=frozenset()):
    """전체 종 검색용 경량 인덱스(종별 검색 모드). 외부 링크는 클라이언트가 ktsn·등급으로 생성."""
    rows = []
    for r in csv.DictReader(MASTER.open(encoding="utf-8-sig")):
        g = r.get("taxon_group") or ""
        if not g or r["ktsn"] in excl:                   # 서비스 제외 종(해양포유류·무기록 어류)
            continue
        rows.append({
            "k": r["ktsn"],                              # = NIBR species-detail ID
            "n": r.get("korean_name", ""),
            "s": r.get("scientific_name", ""),
            "t": g,                                       # taxon_group (obs 파일 라우팅·표시)
            "g": r.get("endangered_grade", ""),           # 멸종위기 I/II → Naturing 분기
            "r": r.get("national_redlist_category", ""),
        })
    rows.sort(key=lambda x: (x["t"], x["n"] or x["s"]))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    (OUTDIR / "species_index.json").write_text(payload, encoding="utf-8")
    (OUTDIR / "species_index.js").write_text("window.__SPIDX__=" + payload + ";", encoding="utf-8")
    eg = sum(1 for x in rows if x["g"] in ("I", "II"))
    print(f"→ species_index.json ({len(rows)}종 | 멸종위기 {eg}종 → Naturing, 그 외 → EcoBank)")


def _txfile(t):
    """분류군 코드 → 파일명 안전 토큰('-P' → '_P'). service.html 와 규칙 일치."""
    return re.sub(r"[^A-Za-z0-9]", "_", t)


def build_obs_split(excl=frozenset(), obs_rows=None):
    """분류군별 관측을 파일 단위로 분할 + 인코딩(서비스 모드 A/B 지연 로드).
    서비스는 40MB 통짜 대신 (1) 메타로 UI 구성 후 (2) 선택 분류군 파일만 주입·디코드한다.

    - obs_meta.js : window.__OBS__={t:{years,sidos,sources,n_records,n_obs_species}}(obs 배열 제외)
                  + window.__OBSMETA__={generated,citation,update_cycle}
    - obs_<T>.js  : window.__OBS__[t] 에 {k:[ktsn..], s:[sido..], o:[[kIdx,sIdx,year_int,count]..]} 병합
                    (ktsn·sido 는 파일별 사전 인덱스, year 는 정수[0=미상] → 다운로드 용량 축소)
    클라이언트 decodeTaxon() 이 o → [[ktsn, sido, year_str, count]] 로 복원(소비 로직 무변경)."""
    from collections import defaultdict
    rows = obs_rows if obs_rows is not None else union_obs()
    tax = defaultdict(lambda: {"obs": [], "years": set(), "sidos": set(), "sources": set(), "n_records": 0})
    for k, t, sido, year, src, c in rows:
        if not t or k in excl:
            continue
        d = tax[t]
        d["obs"].append((k, sido, year, c))
        if year:
            d["years"].add(year)
        d["sidos"].add(sido)
        if src:
            d["sources"].add(src)
        d["n_records"] += c

    # 재빌드 전 구형 모놀리식 산출물 정리(서비스가 더 이상 참조하지 않음)
    for old in ("obs_by_taxon.js", "obs_by_taxon.json"):
        p = OUTDIR / old
        if p.exists():
            p.unlink()

    meta_tax = {}
    for t, d in sorted(tax.items()):
        kdict, kidx, sdict, sidx, enc = [], {}, [], {}, []
        for k, sido, year, c in d["obs"]:
            if k not in kidx:
                kidx[k] = len(kdict); kdict.append(k)
            if sido not in sidx:
                sidx[sido] = len(sdict); sdict.append(sido)
            enc.append([kidx[k], sidx[sido], (int(year) if year else 0), c])
        meta_tax[t] = {
            "years": sorted(d["years"]), "sidos": sorted(d["sidos"]),
            "sources": sorted(d["sources"]), "n_records": d["n_records"],
            "n_obs_species": len(kdict),
        }
        payload = json.dumps({"k": kdict, "s": sdict, "o": enc},
                             ensure_ascii=False, separators=(",", ":"))
        (OUTDIR / f"obs_{_txfile(t)}.js").write_text(
            f'(window.__OBS__=window.__OBS__||{{}})["{t}"]='
            f'Object.assign(window.__OBS__["{t}"]||{{}},{payload});', encoding="utf-8")

    obsmeta = {"generated": GENERATED, "citation": CITATION, "update_cycle": "6mo"}
    (OUTDIR / "obs_meta.js").write_text(
        "window.__OBS__=" + json.dumps(meta_tax, ensure_ascii=False, separators=(",", ":"))
        + ";window.__OBSMETA__=" + json.dumps(obsmeta, ensure_ascii=False, separators=(",", ":"))
        + ";", encoding="utf-8")
    print("→ obs_meta.js + obs_<T>.js (분류군별 분할·인코딩)")
    for t in sorted(meta_tax, key=lambda t: -meta_tax[t]["n_obs_species"]):
        d = meta_tax[t]
        sz = (OUTDIR / f"obs_{_txfile(t)}.js").stat().st_size
        yr = f"{d['years'][0]}~{d['years'][-1]}" if d["years"] else "-"
        print(f"   [{t}] 관측종 {d['n_obs_species']} · 연도 {yr} · "
              f"기록 {d['n_records']} · {sz/1_048_576:.2f}MB · source {d['sources']}")


def build_species_state(excl=frozenset(), obs_rows=None):
    """대문 대시보드 경량 요약: 관측종 → 최신 관측연도(maxYear). 대문이 대용량 obs_by_taxon 대신 이걸 로드.
    window.__SPSTATE__={generated, maxyear:{ktsn:year}} — 미수록 종 = 미발견. year=0 = 관측되었으나 연도 미상(=휴면 처리).
    종의 분류군·적색범주는 species_index(__SPIDX__)에서, 분류군 누적관측은 taxa_summary(__TAXA__)에서 가져온다."""
    rows = obs_rows if obs_rows is not None else union_obs()
    maxy = {}
    for k, t, sido, year, src, c in rows:
        if not t or k in excl:
            continue
        y = int(year) if year else 0
        if k not in maxy or y > maxy[k]:
            maxy[k] = y
    meta = {"generated": GENERATED, "maxyear": maxy}
    payload = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    (OUTDIR / "species_state.json").write_text(payload, encoding="utf-8")
    (OUTDIR / "species_state.js").write_text("window.__SPSTATE__=" + payload + ";", encoding="utf-8")
    print(f"→ species_state.json (관측종 {len(maxy)} · maxYear 요약 · 대문 경량화용)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    excl = load_excluded()
    rows = union_obs()
    print(f"서비스 제외 종: {len(excl)} | 관측 union 행: {len(rows)}")
    build_mm(excl, rows)
    build_taxa_summary(excl, rows)
    build_species_index(excl)
    build_species_state(excl, rows)
    build_obs_split(excl, rows)


if __name__ == "__main__":
    main()
