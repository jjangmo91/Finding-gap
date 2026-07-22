# chat — 발견공백 대화형 도우미 (Supabase Edge Function)

로그인 사용자의 질문을 Gemini(함수호출)로 처리하고, 도구는 `fg_*` 참조 테이블만 조회한다.
원시 좌표·개인정보는 노출하지 않으며, 하루 사용 횟수를 제한한다.

## 활성화 순서

1. **스키마** — `5_App/supabase/conversational_service.sql` 적용(마이그레이션 `conversational_service_reference`로 이미 반영).

2. **데이터 적재** — `.env`에 `SUPABASE_DB_URL` 추가 후 실행:
   - 값: Supabase Dashboard → Project Settings → Database → Connection string → URI.
     **Direct connection 또는 Session pooler** URI 사용(포트 6543 Transaction pooler는 COPY 불가).
   - `python 5_App/supabase/load_reference.py` → `fg_species`·`fg_species_region`·`fg_region`·`fg_taxa` 적재.

3. **Gemini 키** — 함수 비밀키 설정:
   - `supabase secrets set GEMINI_API_KEY=...` (필수)
   - 선택: `GEMINI_MODEL`(기본 `gemini-flash-lite-latest`), `CHAT_DAILY_CAP`(기본 20)
   - ⚠ 무료 tier 한도는 모델별 하루 요청수(RPD)로 매우 낮다: `gemini-flash-latest`(=gemini-3.6-flash)는 **20/일**(실측). 질문 1개당 2~4요청이라 기본값을 별도 할당량이 있는 `gemini-flash-lite-latest`로 둔다(함수호출 정상). 실사용 규모라면 Gemini 종량제 결제 권장.
   - `SUPABASE_URL`·`SUPABASE_ANON_KEY`·`SUPABASE_DB_URL`은 Supabase가 자동 주입.

4. **배포** — `supabase functions deploy chat`.

5. **프런트 노출** — `.env`에 `CHAT_ENABLED=1` 추가 → `python 5_App/build_dist.py --osm-only --out docs` 재빌드 → 커밋·푸시.
   플래그가 off면 `chat.html`은 "곧 제공" 안내만 표시하고, 홈 진입점은 숨겨진다.

## 요청/응답

`POST /functions/v1/chat` · 헤더 `Authorization: Bearer <user_jwt>` (로그인 필수).
- 본문: `{ "messages": [{ "role": "user"|"assistant", "content": "..." }] }`
- 응답: `{ "reply": "...", "remaining": <int>, "used_tools": ["..."] }`
- 한도 초과 시 429, 미로그인 401, 키 미설정 503.

## 도구

`find_region` · `region_discovery_summary` · `undiscovered_priority_species` ·
`search_species` · `species_detail` · `list_protected_species` · `taxa_summary`.
발견 정의: 발견=최근 10년 내 기록, 휴면=기록은 있으나 10년 이상 미보고, 미발견=기록 없음.
