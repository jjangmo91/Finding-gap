# -*- coding: utf-8 -*-
"""발견공백 MCP 도구 단위 테스트 — pytest 또는 단독 실행(python 7_MCP/tests/test_tools.py).
서버(mcp) 의존 없이 tools.py 로직만 검증(데이터: fg_mcp.sqlite[.gz]).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 7_MCP 를 임포트 경로에

from finding_gap_mcp import tools  # noqa: E402


def test_search_species_korean():
    r = tools.search_species("수달")
    assert r and r[0]["scientific_name"] == "Lutra lutra"
    assert r[0]["taxon_group"] == "MM"


def test_search_species_latin_and_taxon_filter():
    r = tools.search_species("Lutra", taxon_group="MM")
    assert all(x["taxon_group"] == "MM" for x in r)
    assert any(x["korean_name"] == "수달" for x in r)


def test_find_region():
    r = tools.find_region("종로")["regions"]
    assert any(x["code"] == "11010" and x["level"] == "sigungu" for x in r)


def test_taxa_summary_nine_taxa_and_consistency():
    ts = tools.taxa_summary()["taxa"]
    assert len(ts) >= 8
    for t in ts:
        # 발견 + 휴면 + 미발견 == 전체 종수 (기록=발견+휴면)
        assert t["discovered"] + t["dormant"] + t["undiscovered"] == t["n_species"]
        assert t["recorded"] == t["discovered"] + t["dormant"]


def test_find_gap_by_region_counts_consistent():
    g = tools.find_gap_by_region("11010", taxon_group="MM", state="undiscovered", limit=5)
    s = g["summary"]
    assert s["found"] + s["dormant"] + s["undiscovered"] == s["total"]
    assert s["recorded"] == s["found"] + s["dormant"]
    assert len(g["species"]) <= 5


def test_find_gap_sido_rollup():
    # 시도(2자리)는 시군구 롤업 — 발견종수가 시군구 하나보다 크거나 같아야
    seoul = tools.find_gap_by_region("11", taxon_group="MM", state="found")["summary"]
    jongno = tools.find_gap_by_region("11010", taxon_group="MM", state="found")["summary"]
    assert seoul["recorded"] >= jongno["recorded"]


def test_get_species_full():
    k = tools.search_species("수달")[0]["ktsn"]
    sp = tools.get_species(k)
    assert sp["family_la"] == "Mustelidae"
    assert sp["national_discovery_state"] in ("found", "dormant", "undiscovered")
    assert sp["recorded_regions"] >= 1


def test_get_species_bioclim():
    k = tools.search_species("수달")[0]["ktsn"]
    b = tools.get_species_bioclim(k, variables="bio01,dem")
    got = {s["var"] for s in b["stats"]}
    assert got <= {"bio01", "dem"} and "bio01" in got


def test_get_species_media():
    k = tools.search_species("수달")[0]["ktsn"]
    m = tools.get_species_media(k, limit=3)
    assert m["count"] >= 1
    assert all(rec.get("full") or rec.get("thumb") for rec in m["media"])


def test_region_comparison():
    c = tools.region_comparison(["11", "26"], taxon_group="AV")["regions"]
    assert len(c) == 2
    assert all("found" in r for r in c)


def test_bad_region_code():
    try:
        tools.find_gap_by_region("999", taxon_group="MM")
        assert False, "잘못된 지역코드는 ValueError 여야 함"
    except ValueError:
        pass


def test_list_protected_national_default():
    r = tools.list_protected_species(limit=20)
    assert r["scope"] == "national"
    assert r["count"] >= 700           # 멸종위기(277) ∪ 적색목록 위협(CR/EN/VU/NT)
    for s in r["species"]:
        assert s["endangered_grade"] or s["national_redlist_category"] in ("CR", "EN", "VU", "NT")


def test_list_protected_redlist_cr():
    r = tools.list_protected_species(redlist_category="CR", limit=100)
    assert r["count"] == 65            # 적색목록 CR = 65종(커밋 데이터)
    assert all(s["national_redlist_category"] == "CR" for s in r["species"])


def test_list_protected_region_endangered_state():
    r = tools.list_protected_species(region="11010", endangered_grade="I", state="undiscovered", limit=10)
    assert r["region"] == "11010"
    s = r["summary"]
    assert s["found"] + s["dormant"] + s["undiscovered"] == s["total"]
    assert s["total"] == 67            # 멸종위기 I급 = 67종
    assert all(x["endangered_grade"] == "I" for x in r["species"])


def test_find_gap_redlist_filter_consistent():
    g = tools.find_gap_by_region("11", taxon_group="AV", redlist_category="EN,VU", state="undiscovered", limit=5)
    s = g["summary"]
    assert s["found"] + s["dormant"] + s["undiscovered"] == s["total"]
    assert all(x["national_redlist_category"] in ("EN", "VU") for x in g["species"])


def test_search_grade_normalization():
    # '1급' / '2' 같은 표기도 I/II 로 정규화되어 필터
    a = tools.list_protected_species(endangered_grade="1급", limit=5)
    b = tools.list_protected_species(endangered_grade="I", limit=5)
    assert a["count"] == b["count"] == 67


def test_taxa_summary_has_protected_fields():
    ts = tools.taxa_summary()["taxa"]
    assert all("endangered" in t and "redlist_threatened" in t for t in ts)
    assert sum(t["endangered"] for t in ts) == 277    # 멸종위기 I(67)+II(210)


def test_get_interest_structure():
    k = tools.search_species("수달")[0]["ktsn"]
    r = tools.get_interest(k)
    assert 0.0 <= r["interest"] <= 1.0
    assert 0.0 <= r["interest_occ"] <= 1.0
    assert r["stratum"]["taxon_group"] == "MM"
    assert r["stratum"]["n"] >= 1 and r["stratum"]["rank"] >= 1


def test_interest_ranking_species_sorted():
    r = tools.interest_ranking(taxon_group="MM", limit=10)
    assert r["level"] == "species" and r["species"]
    vals = [s["interest"] for s in r["species"]]
    assert vals == sorted(vals, reverse=True)          # 내림차순
    assert all("interest" in s for s in r["species"])


def test_interest_ranking_taxon_level():
    r = tools.interest_ranking(level="taxon")
    assert r["level"] == "taxon"
    assert any(t["taxon_group"] == "MM" for t in r["taxa"])
    for t in r["taxa"]:
        assert 0.0 <= t["mean_interest"] <= 1.0


def test_interest_bounds_and_user_zero():
    # 3신호 가중(적용신호 재정규화) → interest 0~1 전 범위. watchlist 미수집 → interest_user 전 종 0.
    import sqlite3
    from pathlib import Path
    dbp = Path(tools.db.DB)
    con = sqlite3.connect(dbp)
    mn, mx = con.execute("SELECT MIN(interest), MAX(interest) FROM species").fetchone()
    nuser = con.execute("SELECT COUNT(*) FROM species WHERE interest_user>0").fetchone()[0]
    active = con.execute("SELECT value FROM meta WHERE key='interest_user_active'").fetchone()[0]
    con.close()
    assert mn >= 0.0 and mx <= 1.0001
    assert nuser == 0 and active == "0"                 # 현재 사용자 관심종 0


def test_interest_wiki_ko_only():
    # 위키 신호(interest_wiki NOT NULL)=한국어 문서 보유종=meta.interest_wiki_species. ko 조회수>0 ⊆ 문서보유.
    import sqlite3
    from pathlib import Path
    con = sqlite3.connect(Path(tools.db.DB))
    n_col = con.execute("SELECT COUNT(*) FROM species WHERE interest_wiki IS NOT NULL").fetchone()[0]
    meta_n = int(con.execute("SELECT value FROM meta WHERE key='interest_wiki_species'").fetchone()[0])
    n_ko_view = con.execute("SELECT COUNT(*) FROM species WHERE wiki_ko>0").fetchone()[0]
    con.close()
    assert n_col == meta_n
    assert 1500 <= n_col <= 6000                         # 한국어 위키 문서 보유 ~2,574
    assert n_ko_view <= n_col                            # 조회수>0 ⊆ 문서보유


def test_get_interest_wiki_split():
    k = tools.search_species("수달")[0]["ktsn"]
    r = tools.get_interest(k)
    wp = r.get("wiki_pageviews")
    assert wp and wp["scored"] == "ko"                  # 점수엔 ko만
    assert wp["ko_12mo"] >= 0 and wp["global_en_12mo"] >= 0


def test_search_output_has_interest():
    r = tools.search_species("수달")
    assert r and "interest" in r[0]


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    return passed == len(fns)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if _run_all() else 1)
