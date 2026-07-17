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
