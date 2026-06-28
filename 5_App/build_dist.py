# -*- coding: utf-8 -*-
"""정적 배포본(dist) 조립 — Cloudflare Pages 등 정적 호스팅용.
출력: 6_Deliverables/dist/  (index.html·service.html·config.js·demo/data/*·_headers)
config.js 는 5_App/.env 의 VWORLD_KEY 로 생성(키 값은 출력하지 않음).
지도 배경은 항상 OSM 기본 + (키 있을 때만) vworld overlay. vworld 키가 해당 도메인에 등록 안 됐으면
자동으로 OSM 폴백된다(service.html). 공개 도메인용 키가 없으면 --osm-only 로 키 없이(순수 OSM) 빌드.
사용: python 5_App/build_dist.py [--osm-only] [--out <경로>]
  --out 기본 6_Deliverables/dist (Cloudflare 등). GitHub Pages(main /docs)용은 --out docs.
배포: npx wrangler pages deploy 6_Deliverables/dist --project-name finding-gap
"""
import re
import sys
import shutil
from pathlib import Path

APP = Path(__file__).resolve().parent          # 5_App
BASE = APP.parent                              # repo root
DIST = BASE / "6_Deliverables" / "dist"
DATA = APP / "demo" / "data"

# dist 에 포함할 정적 자산(서비스/대문이 실제 참조하는 것만)
PAGES = ["index.html", "service.html"]
DATA_FILES = ["taxa_summary.js", "demo_mm.js", "obs_by_taxon.js",
              "species_index.js", "species_state.js", "sido.geojson"]

HEADERS = """\
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: SAMEORIGIN

/demo/data/*
  Cache-Control: public, max-age=3600, must-revalidate

/config.js
  Cache-Control: no-store
"""


def vworld_key():
    env = APP / ".env"
    if not env.exists():
        return ""
    m = re.search(r"^\s*VWORLD_KEY\s*=\s*(.+?)\s*$", env.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def main():
    global DIST
    args = sys.argv[1:]
    if "--out" in args:
        DIST = (BASE / args[args.index("--out") + 1]).resolve()
    # 기존 산출물 제거(파일만; Google Drive 동기화가 폴더 핸들을 잡는 경우 rmtree 가 실패하므로 파일 단위로 정리)
    if DIST.exists():
        for p in sorted(DIST.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            try:
                p.unlink() if p.is_file() else p.rmdir()
            except OSError:
                pass
    (DIST / "demo" / "data").mkdir(parents=True, exist_ok=True)

    for p in PAGES:
        shutil.copy2(APP / p, DIST / p)
    for f in DATA_FILES:
        src = DATA / f
        if src.exists():
            shutil.copy2(src, DIST / "demo" / "data" / f)
        else:
            print(f"(경고) 누락: {src.relative_to(BASE)}")

    osm_only = "--osm-only" in sys.argv[1:]
    key = "" if osm_only else vworld_key()
    (DIST / "config.js").write_text(f'window.VWORLD_KEY = "{key}";\n', encoding="utf-8")
    (DIST / "_headers").write_text(HEADERS, encoding="utf-8")

    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    print(f"dist 조립 완료 → {DIST.relative_to(BASE)}")
    print(f"  파일 {sum(1 for _ in DIST.rglob('*') if _.is_file())}개 · 총 {total/1_048_576:.1f} MB")
    print(f"  배경지도: {'OSM 전용(vworld 키 미포함)' if osm_only else ('vworld+OSM 폴백' if key else 'OSM(키 없음)')}")
    print("  배포: npx wrangler pages deploy 6_Deliverables/dist --project-name finding-gap")


if __name__ == "__main__":
    main()
