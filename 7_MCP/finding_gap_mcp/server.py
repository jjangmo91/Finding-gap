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
def search_species(query: str, taxon_group: str = "", limit: int = 10) -> list:
    """국명 또는 학명으로 종을 검색(부분일치). 반환: 종코드(ktsn)·국명·학명·분류군·멸종위기등급·적색목록·미디어보유."""
    return tools.search_species(query, taxon_group or None, limit)


@mcp.tool()
def get_species(ktsn: str) -> dict:
    """종 상세: 상위분류(과·속)·멸종위기/적색목록 + 전국 발견상태 요약(발견지역수·최신연도)·환경/미디어 가용."""
    return tools.get_species(ktsn)


@mcp.tool()
def find_gap_by_region(region: str, taxon_group: str = "", state: str = "undiscovered", limit: int = 50) -> dict:
    """지역(시도 2자리·시군구 5자리)의 발견/휴면/미발견 종 분류. summary 집계 + 요청 state('undiscovered'|'found'|'dormant'|'recorded') 종목록(상한 limit)."""
    return tools.find_gap_by_region(region, taxon_group or None, state, limit)


@mcp.tool()
def region_comparison(regions: list[str], taxon_group: str = "") -> dict:
    """여러 지역의 발견/휴면/미발견 종수를 나란히 비교(지역 코드 리스트)."""
    return tools.region_comparison(regions, taxon_group or None)


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
def find_region(name: str = "", level: str = "") -> dict:
    """행정구역 이름으로 코드 찾기(다른 도구의 region 입력용). level='sido'|'sigungu' 로 제한 가능."""
    return tools.find_region(name or None, level or None)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
