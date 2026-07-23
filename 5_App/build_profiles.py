# -*- coding: utf-8 -*-
"""지역·분류군 프로필 페이지 정적 생성(SEO·공유용) — 발견공백 로드맵 ④.

17 시도 × 9 분류군 = 153개 정적 HTML + 허브(regions/index.html) + sitemap.xml + robots.txt
+ 공유 카드용 단일 OG 이미지(og.png, PIL 있을 때). 데이터는 7_MCP/data/fg_mcp.sqlite
(대화형 서비스·MCP와 동일 소스). 발견 정의는 서비스 mode A 와 동일: 발견=최근 10년(기준연도-10) 내
관측 기록 보유, 미발견(공백)=총 분류군 종수 − 발견. 각 페이지는 지도(service.html) 딥링크로 이어진다.

build_dist.py 가 출력 폴더를 정리(wipe)하므로, 이 생성기는 build_dist 말미에서 호출되어
정리 이후 out_dir 에 기록된다. 단독 실행도 가능: python 5_App/build_profiles.py [--out docs]
"""
import html
import sqlite3
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent          # 5_App
BASE = APP.parent                              # repo root
SQLITE = BASE / "7_MCP" / "data" / "fg_mcp.sqlite"
BASE_URL = "https://rachhus.github.io/Finding-gap"
REF_YEAR = 2026                                # 서비스 기준연도(발견 창=최근 10년 → cutoff=REF_YEAR-10)
CUTOFF = REF_YEAR - 10

# 분류군 코드 → (URL 슬러그, 영문 라벨 for og). 한글명은 taxa 테이블에서.
TAXON_SLUG = {"MM": "mammals", "AV": "birds", "RP": "reptiles", "AM": "amphibians",
              "-P": "fish", "IN": "insects", "IV": "invertebrates", "VP": "vascular-plants", "MS": "bryophytes"}
# 시도 코드 → 로마자 슬러그(SEO URL)
SIDO_SLUG = {"11": "seoul", "21": "busan", "22": "daegu", "23": "incheon", "24": "gwangju",
             "25": "daejeon", "26": "ulsan", "29": "sejong", "31": "gyeonggi", "32": "gangwon",
             "33": "chungbuk", "34": "chungnam", "35": "jeonbuk", "36": "jeonnam",
             "37": "gyeongbuk", "38": "gyeongnam", "39": "jeju"}
# 표시·파일 순서(분류군)
TAXON_ORDER = ["MM", "AV", "RP", "AM", "-P", "IN", "IV", "VP", "MS"]

HOME_SVG = ('<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true" style="display:block">'
            '<path d="M3.5 11.3 12 4.2l8.5 7.1" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>'
            '<path d="M6 10.1V19.6h4.2v-5.1h3.6v5.1H18V10.1" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>')

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#fafaf8;color:#1b201d;font-family:system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;line-height:1.6}
a{color:inherit}
.wrap{max-width:860px;margin:0 auto;padding:20px 16px 56px}
header{display:flex;align-items:center;gap:10px;margin-bottom:20px}
header .home{color:#6b7280;border:1px solid #e7e7e2;border-radius:8px;padding:7px 9px;background:#fff;text-decoration:none;display:inline-flex;align-items:center}
header .home:hover{color:#2f6f5e;border-color:#2f6f5e}
header .brand{font-size:13.5px;color:#6b7280;text-decoration:none}
header .brand b{color:#2f6f5e}
.crumb{font-size:12.5px;color:#9aa0a6;margin-bottom:6px}
.crumb a{text-decoration:none} .crumb a:hover{color:#2f6f5e}
h1{font-size:23px;letter-spacing:-.01em;margin:0 0 6px}
.lead{color:#4b5563;font-size:14.5px;margin:0 0 20px}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:22px}
.stat{flex:1 1 150px;background:#fff;border:1px solid #e7e7e2;border-radius:12px;padding:14px 16px}
.stat .n{font-size:26px;font-weight:700;letter-spacing:-.02em}
.stat .l{font-size:12px;color:#6b7280;margin-top:2px}
.stat.gap .n{color:#d73027} .stat.found .n{color:#2f6f5e}
.cta{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:26px}
.cta a{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;font-weight:600;text-decoration:none;border-radius:9px;padding:9px 15px}
.cta a.primary{background:#2f6f5e;color:#fff}
.cta a.primary:hover{background:#255a4c}
.cta a.sec{background:#fff;color:#33403b;border:1px solid #e7e7e2}
.cta a.sec:hover{border-color:#2f6f5e;color:#2f6f5e}
h2{font-size:16px;margin:26px 0 10px}
.sub{font-size:12.5px;color:#6b7280;margin:-6px 0 14px}
.splist{list-style:none;padding:0;margin:0;border:1px solid #e7e7e2;border-radius:12px;overflow:hidden;background:#fff}
.splist li{display:flex;align-items:center;gap:10px;padding:10px 14px;border-top:1px solid #f1f1ee;font-size:13.5px}
.splist li:first-child{border-top:0}
.splist .rank{color:#9aa0a6;font-variant-numeric:tabular-nums;font-size:12px;min-width:20px}
.splist .nm{font-weight:600}
.splist .sci{color:#6b7280;font-style:italic;font-size:12.5px}
.splist .badges{margin-left:auto;display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}
.badge{font-size:11px;font-weight:600;border-radius:6px;padding:2px 7px;white-space:nowrap}
.badge.eg{background:#fdeae4;color:#c2410c} .badge.eg1{background:#fbe4e2;color:#7f1d1d}
.badge.rl{background:#eef3f1;color:#2f6f5e}
.empty{background:#fff;border:1px solid #e7e7e2;border-radius:12px;padding:16px;color:#6b7280;font-size:13.5px}
.nav{margin-top:30px}
.nav h3{font-size:12.5px;color:#6b7280;font-weight:600;margin:0 0 8px}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:16px}
.chips a{font-size:12.5px;text-decoration:none;border:1px solid #e7e7e2;background:#fff;border-radius:999px;padding:5px 11px;color:#3a4a43}
.chips a:hover{border-color:#2f6f5e;color:#2f6f5e}
.chips a.on{background:#2f6f5e;color:#fff;border-color:#2f6f5e}
footer{margin-top:34px;padding-top:16px;border-top:1px solid #e7e7e2;font-size:11.5px;color:#9aa0a6;line-height:1.7}
@media(max-width:560px){ h1{font-size:20px} .stat .n{font-size:22px} }
"""


def esc(s):
    return html.escape(str(s or ""), quote=True)


def shorten(name):
    for suf in ("특별자치도", "특별자치시", "특별시", "광역시", "자치도"):
        if name.endswith(suf):
            return name[:-len(suf)]
    return name[:-1] if name.endswith("도") else name


def load(conn):
    """taxa·sido·발견셋·종목록(관심도순)을 메모리로."""
    taxa = {}  # code -> (kor, total)
    for code, kor, n in conn.execute(
            "select taxon_group, taxon_group_kor, count(*) from species group by taxon_group"):
        taxa[code] = (kor, n)
    sidos = [(c, n) for c, n in conn.execute("select code, name from region where level='sido' order by code")]
    found = {}  # (sido, taxon) -> set(ktsn)  최근 발견
    for sido, tg, ktsn in conn.execute("select sido, taxon_group, ktsn from species_region "
                                       "where maxyear>=? and sido!='00'", (CUTOFF,)):
        found.setdefault((sido, tg), set()).add(ktsn)
    species = {}  # taxon -> [ (ktsn, kor, sci, grade, redlist) ] 관심도 내림차순
    for ktsn, kor, sci, tg, grade, rl in conn.execute(
            "select ktsn, korean_name, scientific_name, taxon_group, endangered_grade, national_redlist_category "
            "from species order by interest desc, korean_name"):
        species.setdefault(tg, []).append((ktsn, kor, sci, grade or "", rl or ""))
    return taxa, sidos, found, species


def badges(grade, rl):
    out = []
    if grade in ("I", "II"):
        cls = "eg1" if grade == "I" else "eg"
        out.append(f'<span class="badge {cls}">멸종위기 {grade}급</span>')
    if rl in ("CR", "EN", "VU", "NT"):
        out.append(f'<span class="badge rl">적색 {rl}</span>')
    return "".join(out)


def page_html(sido, sido_name, taxon, taxon_kor, total, found_n, gap_n, undiscovered, taxa, sidos):
    slug = f"{SIDO_SLUG[sido]}-{TAXON_SLUG[taxon]}"
    url = f"{BASE_URL}/regions/{slug}.html"
    gap_pct = round(gap_n / total * 100) if total else 0
    title = f"{sido_name} {taxon_kor} 발견공백 (미발견 {gap_n}종) · Finding gap"
    desc = (f"{sido_name} {taxon_kor} 발견공백: 국가생물종목록 {total}종 중 최근 10년 관측 기록이 없는 "
            f"미발견 {gap_n}종({gap_pct}%). 시민 관찰로 채울 수 있는 종과 지도를 확인하세요.")
    map_link = f"../service.html?taxon={esc(taxon)}&sido={esc(sido)}&metric=gap"

    # 미발견 종 목록(상위 관심도)
    if undiscovered:
        items = []
        for i, (ktsn, kor, sci, grade, rl) in enumerate(undiscovered, 1):
            nm = esc(kor) if kor else esc(sci)
            sci_html = f'<span class="sci">{esc(sci)}</span>' if kor and sci else ""
            items.append(f'<li><span class="rank">{i}</span><span class="nm">{nm}</span>{sci_html}'
                         f'<span class="badges">{badges(grade, rl)}</span></li>')
        splist = '<ul class="splist">' + "".join(items) + "</ul>"
    else:
        splist = '<div class="empty">이 지역·분류군은 최근 10년 내 모든 종이 관측되어 미발견 공백이 없습니다.</div>'

    # 같은 지역 다른 분류군
    taxa_chips = "".join(
        f'<a class="{"on" if t == taxon else ""}" href="{SIDO_SLUG[sido]}-{TAXON_SLUG[t]}.html">{esc(taxa[t][0])}</a>'
        for t in TAXON_ORDER if t in taxa)
    # 같은 분류군 다른 지역
    sido_chips = "".join(
        f'<a class="{"on" if s == sido else ""}" href="{SIDO_SLUG[s]}-{TAXON_SLUG[taxon]}.html">{esc(shorten(nm))}</a>'
        for s, nm in sidos)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Finding gap">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:image" content="{BASE_URL}/og.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{BASE_URL}/og.png">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <a class="home" href="../index.html" aria-label="홈" title="홈">{HOME_SVG}</a>
    <a class="brand" href="../index.html"><b>Finding gap</b> · 발견공백</a>
  </header>
  <nav class="crumb"><a href="index.html">지역·분류군</a> › {esc(sido_name)} › {esc(taxon_kor)}</nav>
  <h1>{esc(sido_name)} {esc(taxon_kor)} 발견공백</h1>
  <p class="lead">국가생물종목록 {total}종 가운데 최근 10년({CUTOFF}년~) 안에 {esc(sido_name)}에서 관측 기록이 없는 <b>미발견(공백) {gap_n}종</b>입니다.</p>
  <div class="stats">
    <div class="stat"><div class="n">{total}</div><div class="l">국가생물종목록 {esc(taxon_kor)}</div></div>
    <div class="stat found"><div class="n">{found_n}</div><div class="l">최근 발견</div></div>
    <div class="stat gap"><div class="n">{gap_n}</div><div class="l">미발견(공백) · {gap_pct}%</div></div>
  </div>
  <div class="cta">
    <a class="primary" href="{map_link}">지도에서 보기 →</a>
    <a class="sec" href="../chat.html">대화로 물어보기</a>
  </div>
  <h2>주목할 미발견 종</h2>
  <p class="sub">관심도(관측·위키 조회수·관심종) 순 상위. 관찰 기록이 공백을 메웁니다.</p>
  {splist}
  <div class="nav">
    <h3>같은 지역 · 다른 분류군</h3>
    <div class="chips">{taxa_chips}</div>
    <h3>같은 분류군 · 다른 지역</h3>
    <div class="chips">{sido_chips}</div>
  </div>
  <footer>
    발견공백 = 국가생물종목록 − 최근 10년 관측(동적). 출처: 국립생물자원관 KTSN · EcoBank · GBIF · 국립공원.
    종 상세 © 국립생물자원관 한반도의 생물다양성. 기준연도 {REF_YEAR} · 생성 자동.
    본 통계는 조사 노력의 공백을 함께 반영하며 실제 부재를 의미하지 않습니다.
  </footer>
</div>
</body>
</html>
"""


def hub_html(sidos, taxa):
    rows = []
    for s, nm in sidos:
        links = " · ".join(
            f'<a href="{SIDO_SLUG[s]}-{TAXON_SLUG[t]}.html">{esc(taxa[t][0])}</a>'
            for t in TAXON_ORDER if t in taxa)
        rows.append(f'<div class="rrow"><div class="rn">{esc(nm)}</div><div class="rl">{links}</div></div>')
    body = "".join(rows)
    title = "지역·분류군별 발견공백 · Finding gap"
    desc = "전국 17개 시도 × 9개 분류군의 발견공백(최근 10년 미관측 종) 요약. 지역·분류군을 골라 미발견 종과 지도를 확인하세요."
    extra = ("\n.rrow{display:flex;gap:12px;padding:12px 0;border-top:1px solid #f1f1ee;align-items:baseline}"
             ".rrow:first-child{border-top:0}.rn{min-width:96px;font-weight:700;font-size:14px}"
             ".rl{font-size:13px;color:#3a4a43}.rl a{text-decoration:none}.rl a:hover{color:#2f6f5e}"
             "@media(max-width:560px){.rrow{flex-direction:column;gap:3px}}")
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{BASE_URL}/regions/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Finding gap">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{BASE_URL}/regions/">
<meta property="og:image" content="{BASE_URL}/og.png">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}{extra}</style>
</head>
<body>
<div class="wrap">
  <header>
    <a class="home" href="../index.html" aria-label="홈" title="홈">{HOME_SVG}</a>
    <a class="brand" href="../index.html"><b>Finding gap</b> · 발견공백</a>
  </header>
  <h1>지역·분류군별 발견공백</h1>
  <p class="lead">전국 17개 시도 × 9개 분류군. 지역과 분류군을 골라 최근 10년간 관측되지 않은 <b>미발견 종</b>과 지도를 확인하세요.</p>
  {body}
  <footer>발견공백 = 국가생물종목록 − 최근 10년 관측. 출처: 국립생물자원관 KTSN · EcoBank · GBIF · 국립공원. 기준연도 {REF_YEAR}.</footer>
</div>
</body>
</html>
"""


def make_og(path):
    """공유 카드용 단일 OG 이미지(1200×630). PIL·한글 폰트 없으면 조용히 건너뜀 → True/False."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False
    font_path = None
    for cand in (r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf",
                 "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"):
        if Path(cand).exists():
            font_path = cand
            break
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), "#0f2e26")
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 12, W, H], fill="#2f6f5e")
    try:
        f_big = ImageFont.truetype(font_path, 92) if font_path else ImageFont.load_default()
        f_mid = ImageFont.truetype(font_path, 44) if font_path else ImageFont.load_default()
        f_sm = ImageFont.truetype(font_path, 30) if font_path else ImageFont.load_default()
    except Exception:
        f_big = f_mid = f_sm = ImageFont.load_default()
    d.text((80, 150), "발견공백", font=f_big, fill="#ffffff")
    d.text((82, 268), "Finding gap", font=f_mid, fill="#8fd3bf")
    d.text((80, 430), "한국 생물종, 아직 발견되지 않은 곳을 찾다", font=f_sm, fill="#cfe6dc")
    d.text((80, 474), "지역·분류군별 발견 지도 · 시민과학 제보", font=f_sm, fill="#9ec3b2")
    img.save(path, "PNG", optimize=True)
    return True


def generate(out_dir, verbose=True):
    out = Path(out_dir).resolve()
    if not SQLITE.exists():
        print(f"(경고) 프로필 생성 건너뜀 — sqlite 없음: {SQLITE}")
        return 0
    conn = sqlite3.connect(str(SQLITE))
    try:
        taxa, sidos, found, species = load(conn)
    finally:
        conn.close()

    rdir = out / "regions"
    rdir.mkdir(parents=True, exist_ok=True)
    sitemap = [f"{BASE_URL}/", f"{BASE_URL}/service.html", f"{BASE_URL}/chat.html",
               f"{BASE_URL}/quiz.html", f"{BASE_URL}/regions/"]
    n = 0
    for sido, sido_name in sidos:
        for taxon in TAXON_ORDER:
            if taxon not in taxa:
                continue
            taxon_kor, total = taxa[taxon]
            found_set = found.get((sido, taxon), set())
            found_n = len(found_set)
            gap_n = total - found_n
            undiscovered = [row for row in species.get(taxon, []) if row[0] not in found_set][:20]
            slug = f"{SIDO_SLUG[sido]}-{TAXON_SLUG[taxon]}"
            (rdir / f"{slug}.html").write_text(
                page_html(sido, sido_name, taxon, taxon_kor, total, found_n, gap_n, undiscovered, taxa, sidos),
                encoding="utf-8")
            sitemap.append(f"{BASE_URL}/regions/{slug}.html")
            n += 1
    (rdir / "index.html").write_text(hub_html(sidos, taxa), encoding="utf-8")

    # sitemap.xml · robots.txt
    urls = "".join(f"<url><loc>{u}</loc></url>" for u in sitemap)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>\n",
        encoding="utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")
    og_ok = make_og(out / "og.png")

    if verbose:
        print(f"프로필 생성 완료 → {out.name}/regions/  ({n}개 페이지 + 허브)")
        print(f"  sitemap {len(sitemap)}개 URL · robots.txt · OG 이미지 {'생성' if og_ok else '건너뜀(PIL/폰트 없음)'}")
    return n


if __name__ == "__main__":
    args = sys.argv[1:]
    out = (BASE / args[args.index("--out") + 1]) if "--out" in args else (BASE / "docs")
    generate(out)
