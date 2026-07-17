# -*- coding: utf-8 -*-
"""위키백과 조회수 수집 — 발견공백 관심도(Interest)의 '대중 관심' 신호.

경로: 서비스 종 학명 → Wikidata(P225) → ko/en 위키백과 문서 → Wikimedia Pageviews API(최근 12개월 합).
출력: 7_MCP/data/wiki_pageviews.json  =  { "<ktsn>": {"ko":int, "en":int, "total":int, "ko_title":..., "en_title":...} }
데이터 라이선스: Wikimedia Pageviews = CC0. 인증 불필요(User-Agent만).

사용:
  python 7_MCP/build_wiki_interest.py               # 전체(오래 걸림·resume)
  python 7_MCP/build_wiki_interest.py --taxa MM,AV  # 특정 분류군만(검증)
  python 7_MCP/build_wiki_interest.py --limit 200   # 상위 N종만
"""
import datetime
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(__file__).resolve().parent / "data" / "fg_mcp.sqlite"
OUT = Path(__file__).resolve().parent / "data" / "wiki_pageviews.json"
UA = "finding-gap-mcp/0.1 (https://github.com/RachHus/Finding-gap; biodiversity discovery-gap; contact via repo)"
SPARQL = "https://query.wikidata.org/sparql"
PV = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{proj}/all-access/all-agents/{art}/monthly/{s}/{e}"
CHUNK = 120           # Wikidata VALUES 청크
SPARQL_SLEEP = 1.0
PV_SLEEP = 0.08       # ~12 req/s (허용 200/s보다 훨씬 정중히)


def _window():
    today = datetime.date.today()
    end = today.replace(day=1) - datetime.timedelta(days=1)       # 지난달 말일
    start = end.replace(day=1)
    for _ in range(11):
        start = (start - datetime.timedelta(days=1)).replace(day=1)  # 12개월 전 1일
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wikidata_map(names):
    """학명 리스트 → {학명: {'ko':title|None, 'en':title|None}} (P225 정확일치)."""
    vals = " ".join('"%s"' % n.replace("\\", "\\\\").replace('"', '\\"') for n in names)
    q = (
        "SELECT ?name ?ko ?en WHERE { VALUES ?name { %s } "
        "?item wdt:P225 ?name . "
        "OPTIONAL { ?ko schema:about ?item ; schema:isPartOf <https://ko.wikipedia.org/> . } "
        "OPTIONAL { ?en schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . } }" % vals
    )
    url = SPARQL + "?format=json&query=" + urllib.parse.quote(q)
    out = {}
    try:
        data = _get(url, timeout=60)
    except Exception as ex:
        print(f"  (SPARQL 오류, 청크 건너뜀) {ex}")
        return out
    for b in data.get("results", {}).get("bindings", []):
        nm = b["name"]["value"]
        rec = out.setdefault(nm, {"ko": None, "en": None})
        for k in ("ko", "en"):
            if k in b and not rec[k]:
                title = urllib.parse.unquote(b[k]["value"].rsplit("/", 1)[-1])
                rec[k] = title
    return out


def pageviews(proj, title, s, e):
    art = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = PV.format(proj=proj, art=art, s=s, e=e)
    try:
        data = _get(url)
    except urllib.error.HTTPError as ex:
        return 0 if ex.code == 404 else -1
    except Exception:
        return -1
    return sum(int(it.get("views", 0)) for it in data.get("items", []))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:]
    taxa = None
    if "--taxa" in argv:
        taxa = set(argv[argv.index("--taxa") + 1].split(","))
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    sql = "SELECT ktsn, scientific_name FROM species WHERE scientific_name!=''"
    params = []
    if taxa:
        sql += " AND taxon_group IN (%s)" % ",".join("?" * len(taxa)); params = list(taxa)
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    if limit:
        rows = rows[:limit]
    s, e = _window()
    print(f"위키 조회수 수집 · 대상 {len(rows)}종 · 창 {s}~{e}")

    out = {}
    if OUT.exists():
        out = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"  이어받기: 기존 {len(out)}종")

    # 1) Wikidata 매핑(청크)
    todo = [r for r in rows if r["ktsn"] not in out]
    name2ktsn = {}
    for r in todo:
        name2ktsn.setdefault(r["scientific_name"], []).append(r["ktsn"])
    names = list(name2ktsn.keys())
    mapping = {}
    for i in range(0, len(names), CHUNK):
        chunk = names[i:i + CHUNK]
        mapping.update(wikidata_map(chunk))
        print(f"  매핑 {min(i+CHUNK,len(names))}/{len(names)} · 문서보유 누적 {sum(1 for v in mapping.values() if v.get('ko') or v.get('en'))}")
        time.sleep(SPARQL_SLEEP)

    # 2) 조회수(문서 있는 종만)
    n_have = 0
    done = 0
    for name, ktsns in name2ktsn.items():
        m = mapping.get(name, {})
        ko_t, en_t = m.get("ko"), m.get("en")
        ko_v = pageviews("ko.wikipedia", ko_t, s, e) if ko_t else 0
        en_v = pageviews("en.wikipedia", en_t, s, e) if en_t else 0
        ko_v = max(ko_v, 0); en_v = max(en_v, 0)
        rec = {"ko": ko_v, "en": en_v, "total": ko_v + en_v, "ko_title": ko_t, "en_title": en_t}
        for k in ktsns:
            out[k] = rec
        if ko_t or en_t:
            n_have += 1
        done += 1
        if ko_t or en_t:
            time.sleep(PV_SLEEP)
        if done % 500 == 0:
            OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            print(f"  조회수 {done}/{len(name2ktsn)} · 문서보유 {n_have} · 중간저장")

    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    have = sum(1 for v in out.values() if (v.get("ko_title") or v.get("en_title")))
    tot = sum(v.get("total", 0) for v in out.values())
    print(f"\n출력: {OUT.relative_to(ROOT)} · {len(out)}종 · 위키문서 보유 {have}종 · 총 조회수 {tot:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
