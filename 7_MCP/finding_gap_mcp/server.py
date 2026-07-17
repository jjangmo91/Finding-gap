# -*- coding: utf-8 -*-
"""발견공백 MCP 서버 — FastMCP(stdio) 래퍼. 도구 로직은 tools.py.

실행: python -m finding_gap_mcp   (7_MCP 를 작업/PYTHONPATH 기준으로)
분류군 코드: MM 포유류 · AV 조류 · RP 파충류 · AM 양서류 · -P 어류 ·
             IV 무척추동물(곤충제외) · IN 곤충류 · VP 관속식물 · MS 선태류.
지역 코드: 시도=2자리, 시군구=5자리(find_region 으로 이름→코드).
발견 정의: 최근 10년 내 기록=발견 / 기록은 있으나 10년 초과=휴면 / 기록 없음=미발견.
"""
from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP(
    "finding-gap",
    instructions=(
        "한국 생물종 '발견공백' 공개 데이터. 종 검색, 지역별 발견/휴면/미발견 종, "
        "종의 환경지위(기후·고도·식생), 미디어(사진·도판)를 읽기 전용으로 제공. "
        "분류군: MM/AV/RP/AM/-P(어류)/IV/IN/VP/MS. 지역은 시도(2자리)·시군구(5자리) 코드, "
        "이름으로는 find_region 사용. 원시 좌표점은 제공하지 않음(집계만). 비상업 용도."
    ),
)


@mcp.tool()
def search_species(query: str, taxon_group: str = "", limit: int = 10,
                   endangered_grade: str = "", redlist_category: str = "") -> list:
    """국명 또는 학명으로 종을 검색(부분일치). endangered_grade(I/II)·redlist_category(CR/EN/VU/NT/LC/DD/NA, 쉼표 다중) 필터. 반환: ktsn·국명·학명·분류군·멸종위기등급·적색목록·미디어보유."""
    return tools.search_species(query, taxon_group or None, limit, endangered_grade or None, redlist_category or None)


@mcp.tool()
def get_species(ktsn: str) -> dict:
    """종 상세: 상위분류(과·속)·멸종위기/적색목록 + 전국 발견상태 요약(발견지역수·최신연도)·환경/미디어 가용."""
    return tools.get_species(ktsn)


@mcp.tool()
def find_gap_by_region(region: str, taxon_group: str = "", state: str = "undiscovered", limit: int = 50,
                       endangered_grade: str = "", redlist_category: str = "") -> dict:
    """지역(시도 2자리·시군구 5자리)의 발견/휴면/미발견 종 분류. summary 집계 + 요청 state('undiscovered'|'found'|'dormant'|'recorded') 종목록(상한 limit). endangered_grade(I/II)·redlist_category(CR/EN/…) 필터 가능."""
    return tools.find_gap_by_region(region, taxon_group or None, state, limit, endangered_grade or None, redlist_category or None)


@mcp.tool()
def list_protected_species(region: str = "", endangered_grade: str = "", redlist_category: str = "",
                           state: str = "", limit: int = 50) -> dict:
    """멸종위기종·국가적색목록 종 목록. 등급/범주 미지정 시 위협종(멸종위기 I/II 또는 적색목록 CR/EN/VU/NT) 기본. region(시도2·시군구5) 지정 시 그 지역의 발견/휴면/미발견(state) 분류 — 예: '종로구(11010) 미발견 멸종위기 I급'."""
    return tools.list_protected_species(region or None, endangered_grade or None, redlist_category or None, state or None, limit)


@mcp.tool()
def region_comparison(regions: list[str], taxon_group: str = "", redlist_category: str = "", endangered_grade: str = "") -> dict:
    """여러 지역의 발견/휴면/미발견 종수를 나란히 비교(지역 코드 리스트). endangered_grade·redlist_category 필터 가능."""
    return tools.region_comparison(regions, taxon_group or None, redlist_category or None, endangered_grade or None)


@mcp.tool()
def taxa_summary() -> dict:
    """9개 분류군별 전체 종수·전국 발견/휴면/미발견 요약."""
    return tools.taxa_summary()


@mcp.tool()
def get_species_bioclim(ktsn: str, variables: str = "") -> dict:
    """종의 환경지위 통계(기후 bio01/05/06/12·고도 dem·식생 ndvi/ndwi). variables=쉼표구분 또는 생략(전체)."""
    return tools.get_species_bioclim(ktsn, variables or None)


@mcp.tool()
def get_species_media(ktsn: str, media_type: str = "", limit: int = 20) -> dict:
    """종의 미디어 메타(사진·도판·영상 URL·라이선스·출처). media_type='photo'|'illustration'|'all'. NIBR=KOGL, iNat=CC(비상업·귀속)."""
    return tools.get_species_media(ktsn, media_type or None, limit)


@mcp.tool()
def get_interest(ktsn: str) -> dict:
    """종의 관심도(Interest) 상세 — 층(분류군×적색목록등급) 내 백분위 신호(관측기록수·한국어 위키조회수·사용자관심종)와 층 내 순위. interest=적용신호 가중평균(occ0.5/wiki0.2/user0.3, 결측 몫 재정규화). 점수엔 한국어 위키(ko)만, en=전세계는 참고. 문헌: conservation culturomics(위키 조회수=대중 관심)."""
    return tools.get_interest(ktsn)


@mcp.tool()
def interest_ranking(taxon_group: str = "", redlist_category: str = "", level: str = "species", limit: int = 20) -> dict:
    """관심도 순위. level='species'(종별 상위) 또는 'taxon'(분류군별 평균). taxon_group·redlist_category(CR/EN/…)로 층 한정 — 예: 적색목록 CR 곤충 중 관심도 상위."""
    return tools.interest_ranking(taxon_group or None, redlist_category or None, level, limit)


@mcp.tool()
def discovery_priorities(region: str, taxon_group: str = "", endangered_grade: str = "",
                         redlist_category: str = "", include_dormant: bool = False, limit: int = 20) -> dict:
    """지역(시도2·시군구5)에서 아직 발견되지 않았지만 관심도가 높은 종을 우선순위로 반환 — 발견공백×관심도 교집합. include_dormant=True면 휴면(오래전 기록)도 포함. endangered_grade(I/II)·redlist_category(CR/EN/…) 필터."""
    return tools.discovery_priorities(region, taxon_group or None, endangered_grade or None,
                                      redlist_category or None, include_dormant, limit)


@mcp.tool()
def region_profile(region: str, top: int = 5) -> dict:
    """지역 생물다양성 프로파일 — 분류군별 발견/휴면/미발견 종수 + 위협종(멸종위기·적색목록) 발견 공백 + 미발견 관심도 상위종 Top을 한 번에."""
    return tools.region_profile(region, top)


@mcp.tool()
def find_region(name: str = "", level: str = "") -> dict:
    """행정구역 이름으로 코드 찾기(다른 도구의 region 입력용). level='sido'|'sigungu' 로 제한 가능."""
    return tools.find_region(name or None, level or None)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
