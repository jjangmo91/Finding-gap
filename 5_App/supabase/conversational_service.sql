-- 대화형 발견공백 도우미 백엔드 스키마.
-- fg_* = 발견공백 MCP 집계(7_MCP/data)의 Postgres 사본 = Edge Function 'chat' 도구의 데이터원.
-- RLS 활성 + 공개 정책 없음 + anon/authenticated 권한 회수 → 직접 REST 조회 차단.
-- Edge Function 은 DB 직결(SUPABASE_DB_URL)로 조회하므로 RLS/권한과 무관.
-- 데이터 적재: python 5_App/supabase/load_reference.py (SUPABASE_DB_URL 필요).
-- 적용: Supabase 대시보드 SQL Editor 또는 마이그레이션(conversational_service_reference)으로 이미 반영됨.

create table if not exists public.fg_species (
  ktsn text primary key,
  korean_name text,
  scientific_name text,
  taxon_group text,
  taxon_group_kor text,
  endangered_grade text,
  national_redlist_category text,
  has_media smallint,
  interest real
);
create index if not exists idx_fg_species_taxon on public.fg_species (taxon_group);
create index if not exists idx_fg_species_interest on public.fg_species (taxon_group, interest desc);

create table if not exists public.fg_species_region (
  ktsn text,
  taxon_group text,
  region text,        -- 시군구 5자리
  sido text,          -- 시도 2자리
  maxyear int,
  obs_count bigint
);
create index if not exists idx_fg_sr_region on public.fg_species_region (region);
create index if not exists idx_fg_sr_sido on public.fg_species_region (sido);
create index if not exists idx_fg_sr_ktsn on public.fg_species_region (ktsn);
create index if not exists idx_fg_sr_region_taxon on public.fg_species_region (region, taxon_group);

create table if not exists public.fg_region (
  code text primary key,
  name text,
  level text,
  sido_cd text
);
create index if not exists idx_fg_region_level on public.fg_region (level);
create index if not exists idx_fg_region_name on public.fg_region (name text_pattern_ops);

create table if not exists public.fg_taxa (
  taxon_group text primary key,
  taxon_group_kor text,
  n_species int
);

alter table public.fg_species enable row level security;
alter table public.fg_species_region enable row level security;
alter table public.fg_region enable row level security;
alter table public.fg_taxa enable row level security;
revoke all on public.fg_species, public.fg_species_region, public.fg_region, public.fg_taxa from anon, authenticated;

-- 일일 사용 한도 — Edge Function(DB 직결)만 증가. 사용자는 본인 사용량 읽기만.
create table if not exists public.chat_usage (
  user_id uuid not null,
  day date not null,
  count int not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, day)
);
alter table public.chat_usage enable row level security;
drop policy if exists chat_usage_read_own on public.chat_usage;
create policy chat_usage_read_own on public.chat_usage
  for select to authenticated using (user_id = auth.uid());
