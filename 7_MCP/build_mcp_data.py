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

    meta = pd.DataFrame([
        ("generated", GEN_DATE),
        ("version", "0.1.0"),
        ("data_max_year", str(data_max_year)),
        ("discovery_window_years", "10"),
        ("n_species", str(len(sp))),
        ("discovery_definition", "found=maxyear>=(refYear-10); dormant=has record but maxyear<(refYear-10); undiscovered=no record"),
        ("license", "관측집계·종정보: 공공데이터 기반. 미디어: NIBR=KOGL(공공누리), iNat=CC(비상업·귀속 필수). 비상업 용도."),
        ("source", "국립생물자원관 KTSN·EcoBank·GBIF·국립공원(집계). 원시 좌표점 미포함."),
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
