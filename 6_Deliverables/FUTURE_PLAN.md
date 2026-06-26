# Finding gap — 향후 기능 설계 (로그인 · 유저 평가 · Open MCP)

현재 서비스는 **순수 정적 사이트**(GitHub Pages, 백엔드 없음). 아래 3개 기능을 추가하며 백엔드를 도입한다.
정적 프론트(GitHub Pages)는 **그대로 유지**하고, 동적 부분만 분리된 백엔드 API로 얹는다.

## 권장 스택 (2-평면 분리)

| 평면 | 서비스 | 사유 |
|---|---|---|
| 공개 read + MCP | **Cloudflare Workers + D1(SQLite)** | 엣지 상시가동(슬립 없음)·원격 MCP 1급 지원·무료티어 |
| 로그인 + My data | **Supabase Auth + Postgres(RLS)** | Google OAuth 즉시 지원·행수준 보안·초기 무료 |
| ETL(배치) | 로컬 Postgres/PostGIS 또는 GitHub Actions | 공간연산은 1회만 → 평면 집계만 서빙 DB로 |
| 정적 프론트 | **GitHub Pages (현행 유지)** | 변경 없음, API 호출만 추가 |

비용: **$0~25/월** (초기 무료, 사용자 1,000명+ 시 Supabase 유료 전환 고려).

## 1. Google 로그인 + 관리자 페이지
- Supabase `signInWithOAuth({provider:'google'})` → JWT → API 요청 헤더에 동봉.
- 신규 `admin.html`: 미로그인 리다이렉트 + role 체크. 탭 = 평가 검수 / 의견 관리 / 사용자 활동 / 설정.
- 권한: `user`(제보·평가·의견) vs `admin`(검수·관리). 모든 테이블 RLS 적용.

## 2. 종별 유저 기능 — 입력 항목 (핵심)

연동 지점: `service.html` 종 검색(Mode B) 종 카드에 즐겨찾기/평가/의견 섹션 추가.

### 즐겨찾기 `favorite_species`
| 항목 | 타입 | 필수 | 검증 |
|---|---|---|---|
| 메모 | TEXT | N | 0~500자 |
| (user_id, ktsn) | | | UNIQUE — 종당 1회 |

### 희귀도 평가 `rarity_assessment`
| 항목 | 타입 | 필수 | 검증/선택지 | 비고 |
|---|---|---|---|---|
| 희귀도 스코어 | INT | Y | 1~5 (1흔함·2보통·3드문·4아주드문·5극히드문) | IUCN 간략화 |
| IUCN 범주 매핑 | ENUM | N | CR·EN·VU·NT·LC·DD·(공란) | 전문가 검수용 |
| 근거 메모 | TEXT | N | 0~500자, HTML strip | XSS 방지 |
| 신뢰도 | INT | N | 0~100%, 10단위 | 기여도 가중치 |
| (user_id, ktsn, type) | | | UNIQUE | |

희귀도 5단계 ↔ IUCN: 1=LC, 2=NT, 3=VU, 4=EN, 5=CR. `iucn_category_match`로 학술용 승격 가능.
관계: 종 마스터의 `national_redlist_category`(공식 평가)와 별개의 **시민 체감 평가**로 병기.

### 의견 `comment`
| 항목 | 타입 | 필수 | 검증 |
|---|---|---|---|
| 의견 텍스트 | TEXT | Y | 1~2000자, HTML strip |
| 대댓글 대상 | UUID | N | parent_comment_id 유효성 |
| is_moderated | BOOL | Y | 기본 false(관리자 검수 전) |

## 3. Open MCP 서버 (Cloudflare Workers)
응답에 **원출처(sources[]) 동봉** 원칙. 노출 도구:

| 도구 | 입력 | 출력 | 인증 |
|---|---|---|---|
| search_species | query, limit | 종 기본정보+등급+NIBR링크 | 공개 |
| get_species_status | ktsn | 발견현황(시도·연도)·적색등급·출처 | 공개 |
| find_undiscovered_species | taxon_group?, sido?, year? | 미발견종 목록 | 공개 |
| list_red_list | category?, taxon_group? | 적색목록 종+관측여부 | 공개 |
| region_gap_summary | sido, taxon_group? | 시도별 공백 현황 | 공개 |
| get_user_contributions | user_id | 유저 기여(평가·의견·관심종) | 로그인 |
| submit_rarity_assessment | (평가 스키마) | 제출 결과 | 로그인 |

## 구현 로드맵
1. **Phase 1** (로그인 기반) — Supabase+Google OAuth → users/favorite_species+RLS → service.html 로그인 통합. (난이도 낮음)
2. **Phase 2** (유저 기능) — admin.html 뼈대 → rarity/comment 테이블+API → 검수 탭. (중간)
3. **Phase 3** (MCP) — Cloudflare Workers 뼈대 → 도구 5종 → 클라이언트 연동. (중간, 선택)

총 8~11주 추정. 의존성: 모든 기능이 Phase 1(인증) 위에 쌓임.

## 리스크
- Supabase 무료 용량 → 평가/의견 archive 정책 + 필요시 유료 전환.
- 입력 XSS → 모든 API에서 HTML strip 필수.
- ETL 갱신 누락 → GitHub Actions cron + 멱등 upsert.
- 개인정보(이메일·닉네임) → 탈퇴 시 익명화, 이용약관·처리방침 명시.

---
*이 문서는 설계안이며 구현 전 검토 대상. 현재 정적 사이트 자산은 그대로 보존된다.*
