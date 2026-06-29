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
PAGES = ["index.html", "service.html", "fg_supabase.js"]
DATA_FILES = ["taxa_summary.js", "demo_mm.js",
              "species_index.js", "species_state.js", "sido.geojson", "sigungu.geojson"]
# 분류군별 관측은 분할 산출 — obs_meta.js + obs_<T>.js 전부 복사(서비스가 지연 로드)
DATA_GLOBS = ["obs_*.js"]

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


def env_val(name):
    env = APP / ".env"
    if not env.exists():
        return ""
    m = re.search(rf"^\s*{name}\s*=\s*(.+?)\s*$", env.read_text(encoding="utf-8"), re.M)
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
    for pat in DATA_GLOBS:
        hit = sorted(DATA.glob(pat))
        for src in hit:
            shutil.copy2(src, DIST / "demo" / "data" / src.name)
        if not hit:
            print(f"(경고) 글롭 누락: {pat}")

    osm_only = "--osm-only" in args
    no_supabase = "--no-supabase" in args              # docs(public) 에서 Supabase 키 제외하고 싶을 때
    key = "" if osm_only else env_val("VWORLD_KEY")
    sb_url = "" if no_supabase else env_val("SUPABASE_URL")
    sb_key = "" if no_supabase else env_val("SUPABASE_KEY")   # publishable 키(공개 전제·RLS 보호)
    (DIST / "config.js").write_text(
        f'window.VWORLD_KEY = "{key}";\n'
        f'window.SUPABASE_URL = "{sb_url}";\n'
        f'window.SUPABASE_KEY = "{sb_key}";\n', encoding="utf-8")
    (DIST / "_headers").write_text(HEADERS, encoding="utf-8")

    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    print(f"dist 조립 완료 → {DIST.relative_to(BASE)}")
    print(f"  파일 {sum(1 for _ in DIST.rglob('*') if _.is_file())}개 · 총 {total/1_048_576:.1f} MB")
    print(f"  배경지도: {'OSM 전용(vworld 키 미포함)' if osm_only else ('vworld+OSM 폴백' if key else 'OSM(키 없음)')}")
    print(f"  Supabase: {'포함(publishable 키, RLS 보호)' if sb_url and sb_key else '미포함'}")
    print("  배포: npx wrangler pages deploy 6_Deliverables/dist --project-name finding-gap")


if __name__ == "__main__":
    main()
