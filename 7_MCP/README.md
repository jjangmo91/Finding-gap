# 발견공백 MCP (Finding gap MCP)

한국 생물종 **발견공백**(어느 지역에서 아직 관측되지 않은 종) 데이터를 LLM/에이전트에 제공하는
**공개·읽기전용 MCP 서버**. 국립생물자원관 KTSN·EcoBank·GBIF·국립공원 관측을 시군구/1km 격자 수준으로
사전집계한 값만 노출한다(원시 좌표점 미포함).

- 런타임: Python + stdio(로컬 설치, 백엔드 0)
- 데이터: `data/fg_mcp.sqlite.gz`(약 18MB, 커밋됨) — 서버가 최초 실행 시 로컬 sqlite로 해제
- 비상업 용도(NIBR=KOGL 공공누리, iNat=CC 비상업·귀속)

## 도구 (8)

| 도구 | 설명 |
|------|------|
| `search_species(query, taxon_group?, limit?)` | 국명·학명 부분검색 → 종코드·등급·적색목록·미디어보유 |
| `get_species(ktsn)` | 종 상세 + 전국 발견상태(발견지역수·최신연도)·환경/미디어 가용 |
| `find_gap_by_region(region, taxon_group?, state?, limit?)` | 지역의 발견/휴면/**미발견** 종 분류(summary + 종목록) |
| `region_comparison(regions[], taxon_group?)` | 여러 지역 발견/미발견 비교 |
| `taxa_summary()` | 9개 분류군별 종수·전국 발견/휴면/미발견 |
| `get_species_bioclim(ktsn, variables?)` | 종의 환경지위(bio01/05/06/12·dem·ndvi/ndwi) |
| `get_species_media(ktsn, media_type?, limit?)` | 종 미디어(사진·도판·영상 URL·라이선스·출처) |
| `find_region(name?, level?)` | 행정구역 이름 → 코드(다른 도구의 `region` 입력용) |

**분류군 코드**: MM 포유류 · AV 조류 · RP 파충류 · AM 양서류 · `-P` 어류 · IV 무척추동물(곤충제외) · IN 곤충류 · VP 관속식물 · MS 선태류
**지역 코드**: 시도 2자리 · 시군구 5자리 (이름은 `find_region` 으로 조회)
**발견 정의**: 최근 10년 내 기록=발견 · 기록은 있으나 10년 초과=휴면 · 기록 없음=미발견

## 설치·실행

```bash
# 1) 의존성(서버는 mcp 만 필요; 데이터 빌드에만 pandas)
python -m venv 7_MCP/.venv
7_MCP/.venv/Scripts/python -m pip install -r 7_MCP/requirements.txt   # Windows
# (macOS/Linux: 7_MCP/.venv/bin/python ...)

# 2) 데이터가 없으면 gz로부터 자동 해제됨. 원천에서 새로 만들려면:
python 7_MCP/build_mcp_data.py            # 1_Data/processed → data/fg_mcp.sqlite(.gz)  (pandas 필요)

# 3) 서버 단독 실행(디버그)
cd 7_MCP && .venv/Scripts/python -m finding_gap_mcp
```

### Claude Code / Desktop 등록

프로젝트 루트 `.mcp.json`(로컬용, 예시는 `.mcp.json.example`):

```json
{
  "mcpServers": {
    "finding-gap": {
      "command": "python",
      "args": ["-m", "finding_gap_mcp"],
      "cwd": "7_MCP"
    }
  }
}
```

`command` 는 **mcp가 설치된 파이썬**이어야 한다. 전용 venv를 쓰면 절대경로로:
`"command": "<repo>/7_MCP/.venv/Scripts/python.exe"`(Windows) / `.../bin/python`(macOS·Linux).

## 데이터 갱신

6개월 주기 ETL 후 `python 7_MCP/build_mcp_data.py` 재실행 → `data/fg_mcp.sqlite.gz` 갱신·커밋.
스키마·라이선스·제외 범위는 [`MCP_DATA_CONTRACT.md`](MCP_DATA_CONTRACT.md).

## 테스트

```bash
python 7_MCP/tests/test_tools.py     # 또는  pytest 7_MCP/tests
```
