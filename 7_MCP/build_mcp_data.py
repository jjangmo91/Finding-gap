# -*- coding: utf-8 -*-
"""발견공백 MCP 데이터 빌드 — 1_Data/processed 의 정규 집계를 공개 읽기전용 MCP용
컴팩트 SQLite(7_MCP/data/fg_mcp.sqlite)로 변환.

핵심 압축: observation_sigungu.csv(2.04M행: ktsn×시군구×연도×출처)를
(ktsn, region) 최신연도·관측합으로 롤업 → 발견상태 판정에 필요한 최소치만.
원시 좌표점(observations.sqlite)은 절대 포함하지 않는다(민감·집계만 공개).

산출 테이블:
  species        : 서비스 대상 39,972종 마스터(등급·적색목록·상위분류·미디어보유)
  species_region : (ktsn, region=시군구코드) → maxyear, obs_count (발견/휴면/미발견 판정)
  species_env    : 종별 환경지위(bio01/05/06/12/dem × 통계)
  media          : 종별 미디어 메타(사진·도판 URL·라이선스·출처)
  region         : 시도/시군구 코드→이름
  taxa           : 분류군 요약
  meta           : 생성일·버전·발견정의·라이선스

사용: python 7_MCP/build_mcp_data.py         (anaconda python — pandas 필요)
"""
import json
import sqlite3
import sys
import gzip
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent          # repo root
PROC = ROOT / "1_Data" / "processed"
DEMO = ROOT / "5_App" / "demo" / "data"
OUT = Path(__file__).resolve().parent / "data"
DB = OUT / "fg_mcp.sqlite"

MEDIA_CAP = 12                                          # 종당 미디어 상한(메타 크기 억제)
GEN_DATE = "2026-07-18"                                 # 스크립트는 Date 미사용 — 갱신 시 여기 수정


def truthy(s):
    return str(s).strip().lower() in ("1", "true", "t", "y", "yes")


def _load_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)

    # ── 1. 서비스 종 마스터 ──
    master = pd.read_csv(PROC / "ktsn_master.csv", dtype=str, keep_default_na=False)
    flags = pd.read_csv(PROC / "species_service_flags.csv", dtype=str, keep_default_na=False)
    print("in_service 고유값:", flags["in_service"].unique()[:6])
    inservice = set(flags.loc[flags["in_service"].map(truthy), "ktsn"])
    print(f"서비스 종: {len(inservice)}")

    keep = ["ktsn", "korean_name", "scientific_name", "taxon_group", "taxon_group_kor",
            "class_la", "order_la", "family_la", "genus_la", "rank",
            "endangered_grade", "national_redlist_category"]
    sp = master[master["ktsn"].isin(inservice)][keep].copy()
    sp = sp.drop_duplicates(subset=["ktsn"]).reset_index(drop=True)

    # ── 2. 관측 집계 → (ktsn, region) 롤업 ──
    obs = pd.read_csv(PROC / "observation_sigungu.csv",
                      dtype={"ktsn": str, "taxon_group": str, "region": str},
                      keep_default_na=False,
                      usecols=["ktsn", "taxon_group", "region", "year", "obs_count"])
    obs = obs[obs["ktsn"].isin(inservice)].copy()
    obs["year"] = pd.to_numeric(obs["year"], errors="coerce")
    obs["obs_count"] = pd.to_numeric(obs["obs_count"], errors="coerce").fillna(0).astype("int64")
    n_before = len(obs)
    obs = obs[(obs["year"] >= 1900) & (obs["year"] <= 2026)]      # 오염 연도값(예: 4229) 제거
    print(f"관측행: {n_before:,} → 유효연도 {len(obs):,} ({n_before - len(obs):,} drop)")
    reg = (obs.groupby(["ktsn", "taxon_group", "region"], as_index=False)
              .agg(maxyear=("year", "max"), obs_count=("obs_count", "sum")))
    reg["maxyear"] = reg["maxyear"].fillna(0).astype("int64")
    reg["sido"] = reg["region"].str[:2]
    data_max_year = int(reg["maxyear"].max())
    print(f"species_region 행: {len(reg):,} · 데이터 최신연도: {data_max_year}")

    # ── 3. 종별 환경지위(long) ──
    env = pd.read_csv(PROC / "species_env_stats.csv", dtype={"ktsn": str},
                      keep_default_na=False)
    env = env[env["ktsn"].isin(inservice)].copy()
    for c in ["n", "min", "q1", "median", "q3", "max", "mean", "sd"]:
        env[c] = pd.to_numeric(env[c], errors="coerce")
    print(f"species_env 행: {len(env):,} · 변수: {sorted(env['var'].unique())}")

    # ── 4. 미디어 메타(nibr + inat) ──
    media_rows = []
    have_media = set()
    for fname in ("media_nibr.json", "media_inat.json"):
        fp = PROC / fname
        if not fp.exists():
            print(f"(경고) 미디어 없음: {fname}")
            continue
        blob = json.loads(fp.read_text(encoding="utf-8"))
        for ktsn, recs in blob.items():
            if ktsn not in inservice:
                continue
            for r in (recs or [])[:MEDIA_CAP]:
                media_rows.append((ktsn, r.get("src", ""), r.get("type", ""),
                                   r.get("lic", ""), r.get("by", ""),
                                   r.get("thumb", ""), r.get("full", "")))
                have_media.add(ktsn)
    media = pd.DataFrame(media_rows, columns=["ktsn", "src", "type", "license", "attribution", "thumb", "full"])
    print(f"media 행: {len(media):,} · 미디어보유 종: {len(have_media):,}")
    sp["has_media"] = sp["ktsn"].isin(have_media).astype(int)

    # ── 5. 지역명(시도·시군구) ──
    reg_rows = []
    sg = json.loads((DEMO / "sigungu.geojson").read_text(encoding="utf-8"))
    for f in sg["features"]:
        p = f["properties"]
        reg_rows.append((p["code"], p.get("sigungu", ""), "sigungu", p.get("sido_cd", p["code"][:2])))
    sd = json.loads((DEMO / "sido.geojson").read_text(encoding="utf-8"))
    for f in sd["features"]:
        p = f["properties"]
        reg_rows.append((p["code"], p.get("sido", ""), "sido", p["code"]))
    region = pd.DataFrame(reg_rows, columns=["code", "name", "level", "sido_cd"])
    print(f"region 행: {len(region)} (시군구 {len(sg['features'])} + 시도 {len(sd['features'])})")

    # ── 6. 분류군 요약 ──
    taxa = (sp.groupby(["taxon_group", "taxon_group_kor"], as_index=False)
              .agg(n_species=("ktsn", "nunique")))

    # ── 7. 관심도(Interest) — (분류군 × 적색목록 등급) 층 내 백분위 · 3신호 가중 ──
    #   신호(층내 백분위 0~1): P_occ 관측기록수 · P_wiki 한국어 위키조회수(ko, 12개월) · P_user 관심종 watchlist
    #   interest = 적용신호 가중평균(가중치 재정규화). wiki는 한국어 문서 보유종만, user는 watchlist 수집 시만 적용.
    #   ko 전용: total(ko+en)은 영어권에 지배돼 국내관심 왜곡 → 국내 신호로 ko 조회수만 채점(en은 참고 저장).
    W = {"occ": 0.5, "wiki": 0.2, "user": 0.3}
    MIN_STRATUM = 5
    occ_total = reg.groupby("ktsn")["obs_count"].sum()
    sp["occ_total"] = sp["ktsn"].map(occ_total).fillna(0.0)
    wiki = _load_json(OUT / "wiki_pageviews.json")
    sp["wiki_ko"] = sp["ktsn"].map({k: int(v.get("ko", 0) or 0) for k, v in wiki.items()}).fillna(0).astype("int64")
    sp["wiki_en"] = sp["ktsn"].map({k: int(v.get("en", 0) or 0) for k, v in wiki.items()}).fillna(0).astype("int64")
    ko_article = {k for k, v in wiki.items() if v.get("ko_title")}   # 한국어 위키 문서 보유 = 위키신호 적용 대상
    sp["wiki_has"] = sp["ktsn"].isin(ko_article)
    watch = _load_json(OUT / "watch_counts.json")
    sp["watch_count"] = sp["ktsn"].map({k: int(v) for k, v in watch.items()}).fillna(0).astype("int64")  # 익명 집계(트렌딩·user신호)
    user_active = bool(sp["watch_count"].sum() > 0)                  # watchlist 수집 전이면 user 신호 미적용(몫 재분배)

    sp["_stratum"] = sp["national_redlist_category"].replace("", "none")
    grp = ["taxon_group", "_stratum"]
    sp["stratum_n"] = sp.groupby(grp)["ktsn"].transform("size")

    def _pct(col):                                    # 층 내 백분위(0~1); 작은 층(n<5)은 분류군 폴백; 신호 0이면 0
        s = sp.groupby(grp)[col].rank(pct=True)
        t = sp.groupby("taxon_group")[col].rank(pct=True)
        p = np.where(sp["stratum_n"] >= MIN_STRATUM, s.values, t.values)
        return np.where(sp[col].values > 0, p, 0.0)   # 신호 없으면(0) 백분위 0 — 동점 0.5 허위주입 방지

    p_occ, p_wiki, p_user = _pct("occ_total"), _pct("wiki_ko"), _pct("watch_count")
    n = len(sp)                                       # 적용 가능한 신호끼리 가중치 재정규화(occ 항상 포함 → Z>=0.5>0)
    wt_occ = np.full(n, W["occ"])
    wt_wiki = np.where(sp["wiki_has"].values, W["wiki"], 0.0)
    wt_user = np.full(n, W["user"] if user_active else 0.0)
    Z = wt_occ + wt_wiki + wt_user
    interest = (wt_occ * p_occ + wt_wiki * p_wiki + wt_user * p_user) / Z
    sp["interest_occ"] = np.round(p_occ, 4)
    sp["interest_wiki"] = [round(float(x), 4) if h else None for x, h in zip(p_wiki, sp["wiki_has"].values)]
    sp["interest_user"] = np.round(p_user, 4)
    sp["interest"] = np.round(interest, 4)
    sp["interest_fallback"] = (sp["stratum_n"] < MIN_STRATUM).astype(int)
    n_wiki = int(sp["wiki_has"].sum())
    n_user = int((sp["interest_user"] > 0).sum())
    sp = sp.drop(columns=["occ_total", "wiki_has", "_stratum"])   # wiki_ko·wiki_en·watch_count 은 보존(참고·트렌딩)
    print(f"관심도: 층=분류군×적색목록 · 가중치 occ{W['occ']}/wiki{W['wiki']}/user{W['user']}(재정규화) · "
          f"위키신호(ko문서) {n_wiki}종 · 사용자신호 {n_user}종 · user_active={user_active}")

    # ── SQLite 기록 ──
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    sp.to_sql("species", con, index=False)
    reg.to_sql("species_region", con, index=False)
    env.to_sql("species_env", con, index=False)
    media.to_sql("media", con, index=False)
    region.to_sql("region", con, index=False)
    taxa.to_sql("taxa", con, index=False)

    # ── community: 관리자 승인된 시민 제보 익명 집계(시군구 단위) — Feature B P4→MCP ──
    #   community_reports.json(build_community_snapshot.py) = [{ktsn,sigungu,count,last_year}]. 미수집이면 빈 테이블.
    comm = _load_json(OUT / "community_reports.json") or []
    spm = sp.set_index("ktsn")[["korean_name", "scientific_name", "taxon_group"]].to_dict("index")
    regm = dict(zip(region["code"], region["name"]))
    comm_rows = []
    for r in comm:
        k = str(r["ktsn"]); sg = str(r["sigungu"])
        m = spm.get(k, {})
        comm_rows.append({
            "ktsn": k, "korean_name": m.get("korean_name", ""),
            "scientific_name": m.get("scientific_name", ""), "taxon_group": m.get("taxon_group", ""),
            "region": sg, "sido": sg[:2], "region_name": regm.get(sg, sg),
            "count": int(r.get("count", 1)), "last_year": int(r.get("last_year", 0) or 0)})
    comm_df = pd.DataFrame(comm_rows, columns=["ktsn", "korean_name", "scientific_name",
                                               "taxon_group", "region", "sido", "region_name", "count", "last_year"])
    comm_df.to_sql("community", con, index=False)

    meta = pd.DataFrame([
        ("generated", GEN_DATE),
        ("version", "0.1.0"),
        ("data_max_year", str(data_max_year)),
        ("discovery_window_years", "10"),
        ("n_species", str(len(sp))),
        ("discovery_definition", "found=maxyear>=(refYear-10); dormant=has record but maxyear<(refYear-10); undiscovered=no record"),
        ("license", "관측집계·종정보: 공공데이터 기반. 미디어: NIBR=KOGL(공공누리), iNat=CC(비상업·귀속 필수). 위키 조회수=CC0. 비상업 용도."),
        ("source", "국립생물자원관 KTSN·EcoBank·GBIF·국립공원(집계). 원시 좌표점 미포함."),
        ("interest_definition", "층=(분류군×적색목록등급) 내 백분위; 신호 P_occ(관측)·P_wiki(한국어위키조회수)·P_user(관심종); interest=적용신호 가중평균(가중치 재정규화); wiki는 한국어문서 보유종만·user는 watchlist 수집 시 적용; 백분위=층내(n<5 분류군폴백)"),
        ("interest_weights", "occ=0.5, wiki=0.2, user=0.3, min_stratum=5 (적용가능 신호끼리 재정규화; 결측 신호 몫은 나머지로 분배)"),
        ("interest_signals", "occ=관측기록수(iNat/GBIF/EcoBank/국립공원), wiki=한국어 위키백과 조회수(ko, 12개월, 월갱신, conservation culturomics; en=전세계는 참고만), user=관심종 watchlist(배치 스냅샷)"),
        ("interest_wiki_window_months", "12"),
        ("interest_wiki_update", "monthly"),
        ("interest_wiki_species", str(len(ko_article))),
        ("interest_user_active", "1" if user_active else "0"),
        ("community_reports", str(len(comm_rows))),
        ("community_source", "관리자 승인된 시민 제보(익명 집계, 시군구 단위, source='community'). 정확좌표·개인정보 미포함. 미승인·미검증 제보는 미노출."),
    ], columns=["key", "value"])
    meta.to_sql("meta", con, index=False)

    # 인덱스
    cur = con.cursor()
    cur.execute("CREATE UNIQUE INDEX idx_species_ktsn ON species(ktsn)")
    cur.execute("CREATE INDEX idx_species_taxon ON species(taxon_group)")
    cur.execute("CREATE INDEX idx_sr_region ON species_region(region)")
    cur.execute("CREATE INDEX idx_sr_ktsn ON species_region(ktsn)")
    cur.execute("CREATE INDEX idx_sr_region_taxon ON species_region(region, taxon_group)")
    cur.execute("CREATE INDEX idx_sr_sido ON species_region(sido)")
    cur.execute("CREATE INDEX idx_env_ktsn ON species_env(ktsn)")
    cur.execute("CREATE INDEX idx_media_ktsn ON media(ktsn)")
    cur.execute("CREATE INDEX idx_region_level ON region(level)")
    cur.execute("CREATE INDEX idx_species_interest ON species(taxon_group, interest)")
    cur.execute("CREATE INDEX idx_comm_region ON community(region)")
    cur.execute("CREATE INDEX idx_comm_taxon ON community(taxon_group)")
    con.commit()
    con.execute("VACUUM")
    con.commit()
    con.close()

    size_mb = DB.stat().st_size / 1_048_576
    print(f"\nSQLite: {DB.relative_to(ROOT)} · {size_mb:.1f} MB")

    # 20MB 초과면 gzip 동봉본도 생성(커밋용 압축), 아니면 sqlite 직접 커밋
    gz = OUT / "fg_mcp.sqlite.gz"
    with open(DB, "rb") as fin, gzip.open(gz, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)
    gz_mb = gz.stat().st_size / 1_048_576
    print(f"gzip: {gz.relative_to(ROOT)} · {gz_mb:.1f} MB")
    print(f"\n권장 커밋: {'gzip(.gz) — 서버가 최초 실행 시 해제' if size_mb > 25 else 'sqlite 직접 — 서버가 바로 open'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
