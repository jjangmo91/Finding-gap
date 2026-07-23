-- 대화형 도우미: 과·속 질의를 강·목까지 확대 + 한글명 커버리지 전체화.
-- fg_taxon_name.rank 를 class/order 까지 허용하도록 CHECK 확대(기존은 family/genus만).
-- 데이터는 KTSN 전체(7_MCP/data/taxon_names.json.gz)로 재적재 — load_reference.py 참고.
-- 적용: conversational_service_taxon.sql 적용 후 Supabase 대시보드 SQL Editor에서 실행(멱등).

alter table public.fg_taxon_name drop constraint if exists fg_taxon_name_rank_check;
alter table public.fg_taxon_name
  add constraint fg_taxon_name_rank_check check (rank in ('class', 'order', 'family', 'genus'));

-- 한글명 퍼지 매칭(오타·철자변형: 딱따구리↔딱다구리, 통칭 등) — 정확 일치 실패 시 후보 제시용.
create extension if not exists pg_trgm;
create index if not exists idx_fg_taxon_name_korean_trgm
  on public.fg_taxon_name using gin (korean gin_trgm_ops);

comment on table public.fg_taxon_name is
  '강·목·과·속 라틴↔한글 이름 매핑(출처: KTSN 원천 1_Data/raw/nibr/ktsn_*.ndjson → 7_MCP/build_taxon_names.py). Edge Function chat 의 한글 분류명 해석용.';
