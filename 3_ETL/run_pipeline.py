# -*- coding: utf-8 -*-
"""
Finding gap 데이터 파이프라인 오케스트레이터 — 재빌드 체인을 순서대로·검증하며 실행.

목적: 6개월 갱신·부분 재빌드를 한 커맨드로. 각 단계는 이름으로 선택 실행 가능(--only/--from/--skip).
R 실행의 Windows 함정(공백경로·인용)은 subprocess 리스트 + `-e source()` 로 회피한다.

현재 구현(환경적합 후보 하위체인 — 검증 완료):
  sentinel  : NDVI/NDWI zip → 평문 .tif 로컬 캐시 추출(**.ovr 제외** — 손상 오버뷰가 heap 크래시 유발)
  env_layers: 3_ETL/R/env_layers.R  → species_env_stats·env_national·env_layers_meta·env_grid·env/*.png
  ndwi_sp   : python/build_ndwi_species.py → ndwi_species.csv(어류+저서무척추 = NDWI 적용 종)
  env_data  : 5_App/build_env_data.py → species_env.js·env_meta.js
  dist      : 5_App/build_dist.py --osm-only --out docs → docs/ 정적 배포본(vworld 키 미주입)

전체 6개월 갱신 체인(수동 스텝은 아래 주석 참조 — DATA_PIPELINE.md):
  etl_observation/etl_national_park/etl_gbif → build_points_db → build_sigungu_agg
  → (R)bioclim_points·env_layers → build_demo_data·build_env_data → build_dist

사용:
  python 3_ETL/run_pipeline.py --list
  python 3_ETL/run_pipeline.py                     # 기본 세트(sentinel..env_data) 순서 실행
  python 3_ETL/run_pipeline.py --only env_layers
  python 3_ETL/run_pipeline.py --from ndwi_sp
  python 3_ETL/run_pipeline.py --only dist         # 배포본만
"""
import argparse, os, subprocess, sys, time, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYDIR = REPO / "3_ETL" / "python"
RDIR = REPO / "3_ETL" / "R"
SPATIAL = REPO / "1_Data" / "spatial"
PROC = REPO / "1_Data" / "processed"
APP = REPO / "5_App"
CACHE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "fg_cache" / "sentinel"
RSCRIPT = os.environ.get("RSCRIPT_EXE", r"C:\Program Files\R\R-4.5.0\bin\Rscript.exe")

SENTINEL = [  # (zip, member .tif) — .ovr/.tfw/.aux 는 추출하지 않음(오버뷰 손상 → GDAL heap 크래시)
    ("Sentinel_위성영상의_정규식생지수_NDVI_2024.zip", "S2_NDVI.tif"),
    ("Sentinel_위성영상의_정규물지수_NDWI_2024.zip", "S2_NDWI.tif"),
]


def sh(cmd, cwd=None):
    """리스트 커맨드 실행(shell 미사용 → 공백경로/인용 안전). 실패 시 예외."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None, check=True)


def need(path, label):
    p = Path(path)
    if not p.exists():
        sys.exit(f"[검증 실패] {label} 없음: {p}")
    print(f"  ✓ {label}: {p.name}")


# ── 단계 함수 ─────────────────────────────────────────────────────────
def step_sentinel():
    """NDVI/NDWI 평문 .tif 를 로컬 캐시로 추출(없을 때만). .ovr 는 절대 추출하지 않는다."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for zname, member in SENTINEL:
        dst = CACHE / member
        if dst.exists() and dst.stat().st_size > 0:
            print(f"  ✓ 캐시 존재: {member}")
            continue
        zpath = SPATIAL / zname
        need(zpath, f"원본 zip {zname}")
        print(f"  추출 {member} ← {zname}")
        with zipfile.ZipFile(zpath) as z:
            with z.open(member) as src, dst.open("wb") as out:
                while True:
                    buf = src.read(1 << 20)
                    if not buf:
                        break
                    out.write(buf)
    for _, member in SENTINEL:
        need(CACHE / member, f"캐시 {member}")


def step_env_layers():
    """R env_layers.R — 점추출·1km 집계·env_grid·PNG. 진행로그는 LOCALAPPDATA/fg_cache/env_layers_run.log."""
    script = (RDIR / "env_layers.R").as_posix()
    sh([RSCRIPT, "-e", f"source('{script}')"])
    for f in ("species_env_stats.csv", "env_national.csv", "env_layers_meta.csv", "env_grid.csv"):
        need(PROC / f, f)


def step_ndwi_sp():
    sh([sys.executable, PYDIR / "build_ndwi_species.py"])
    need(PROC / "ndwi_species.csv", "ndwi_species.csv")


def step_env_data():
    sh([sys.executable, APP / "build_env_data.py"])
    need(APP / "demo" / "data" / "species_env.js", "species_env.js")


def step_dist():
    """공개 배포본 — 반드시 --osm-only(vworld 키 미주입, docs/config.js 빈 키 유지)."""
    sh([sys.executable, APP / "build_dist.py", "--osm-only", "--out", "docs"])
    need(REPO / "docs" / "index.html", "docs/index.html")


STEPS = [  # 순서 = 의존관계
    ("sentinel", "NDVI/NDWI zip→평문 .tif 캐시(.ovr 제외)", step_sentinel),
    ("env_layers", "env_layers.R (점추출·1km 집계·env_grid·PNG)", step_env_layers),
    ("ndwi_sp", "build_ndwi_species.py (어류+저서무척추)", step_ndwi_sp),
    ("env_data", "build_env_data.py (species_env.js·env_meta.js)", step_env_data),
    ("dist", "build_dist.py --osm-only --out docs (배포본)", step_dist),
]
DEFAULT = ["sentinel", "env_layers", "ndwi_sp", "env_data"]  # dist 는 명시 요청 시만


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Finding gap 데이터 파이프라인")
    ap.add_argument("--list", action="store_true", help="단계 목록만 출력")
    ap.add_argument("--only", nargs="+", metavar="STEP", help="지정 단계만 실행")
    ap.add_argument("--from", dest="from_", metavar="STEP", help="해당 단계부터 끝까지")
    ap.add_argument("--skip", nargs="+", metavar="STEP", default=[], help="제외할 단계")
    a = ap.parse_args()
    names = [n for n, _, _ in STEPS]

    if a.list:
        print("단계(순서):")
        for n, d, _ in STEPS:
            tag = " [기본]" if n in DEFAULT else ""
            print(f"  {n:11s} {d}{tag}")
        return

    if a.only:
        run = [n for n in a.only if n in names] or sys.exit(f"알 수 없는 단계: {a.only}")
    elif a.from_:
        if a.from_ not in names:
            sys.exit(f"알 수 없는 단계: {a.from_}")
        run = names[names.index(a.from_):]
    else:
        run = list(DEFAULT)
    run = [n for n in run if n not in a.skip]

    fn = {n: f for n, _, f in STEPS}
    t0 = time.time()
    print(f"파이프라인 실행: {' → '.join(run)}\n")
    for n in run:
        print(f"[{n}] {dict((x, y) for x, y, _ in STEPS)[n]}")
        ts = time.time()
        fn[n]()
        print(f"  완료 ({time.time()-ts:.1f}s)\n")
    print(f"전체 완료 ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
