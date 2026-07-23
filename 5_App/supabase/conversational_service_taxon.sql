-- 대화형 도우미: 과·속(family/genus) 단위 질의 지원.
-- fg_species 에 family_la/genus_la 추가(MCP sqlite의 species.family_la/genus_la 그대로),
-- 한글 과·속명 해석용 fg_taxon_name 테이블 신설(taxon_ko.js 의 라틴↔한글 매핑을 적재).
-- 적용: conversational_service.sql 적용 후 Supabase 대시보드 SQL Editor에서 실행.
-- 데이터 적재: python 5_App/supabase/load_reference.py (family_la/genus_la·fg_taxon_name 포함하도록 갱신됨).

alter table public.fg_species add column if not exists family_la text;
alter table public.fg_species add column if not exists genus_la text;
create index if not exists idx_fg_species_family on public.fg_species (lower(family_la));
create index if not exists idx_fg_species_genus on public.fg_species (lower(genus_la));

create table if not exists public.fg_taxon_name (
  rank   text not null check (rank in ('family', 'genus')),
  latin  text not null,
  korean text not null,
  primary key (rank, latin)
);
create index if not exists idx_fg_taxon_name_korean on public.fg_taxon_name (rank, korean);

alter table public.fg_taxon_name enable row level security;
revoke all on public.fg_taxon_name from anon, authenticated;

comment on table public.fg_taxon_name is
  '과·속 라틴↔한글 이름 매핑(출처: 5_App/demo/data/taxon_ko.js). Edge Function chat 의 한글 분류명 해석용.';
