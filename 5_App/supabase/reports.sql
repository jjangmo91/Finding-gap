-- 시민과학 URL 제보(reports) — Feature B.
-- 로그인 사용자가 종 발견을 URL(근거)+좌표(지도 핀)+발견일로 제보한다. RLS=본인 행만(select/insert/delete).
-- 정밀 좌표(멸종위기 보호)는 원시 테이블에만 두고, 공개 피드 RPC(community_reports)는 좌표를 노출하지 않는다.
-- fills_gap·sigungu 는 P2(관리자 검토·배치)에서 산정 — 현재는 NULL.
-- 적용: Supabase 대시보드 SQL Editor 또는 MCP apply_migration 으로 실행.

create table if not exists public.reports (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null default auth.uid() references auth.users(id) on delete cascade,
  ktsn            text not null,
  scientific_name text,
  korean_name     text,
  taxon_group     text,
  url             text not null,
  lat             double precision not null,
  lon             double precision not null,
  observed_date   date not null,
  note            text,
  status          text not null default 'pending' check (status in ('pending','approved','rejected')),
  fills_gap       boolean,                          -- 재발견 후보 여부(P2 산정)
  sigungu         text,                             -- 좌표 파생 시군구(P2 산정)
  created_at      timestamptz not null default now(),
  constraint reports_lat_rng check (lat between 33 and 43),   -- 대한민국 위도 범위(오입력 방지)
  constraint reports_lon_rng check (lon between 124 and 132), -- 대한민국 경도 범위
  constraint reports_date_rng check (observed_date between date '1900-01-01' and current_date),
  constraint reports_url_http check (url ~* '^https?://')     -- http(s) URL 만 허용(javascript: 등 차단)
);

create index if not exists reports_user_idx   on public.reports(user_id, created_at desc);
create index if not exists reports_ktsn_idx   on public.reports(ktsn);
create index if not exists reports_status_idx on public.reports(status, created_at desc);

alter table public.reports enable row level security;

-- 본인 행만 조회/삽입/삭제 (user_id 는 default auth.uid() 로 자동 채움)
drop policy if exists reports_select_own on public.reports;
drop policy if exists reports_insert_own on public.reports;
drop policy if exists reports_delete_own on public.reports;
create policy reports_select_own on public.reports for select using (user_id = auth.uid());
create policy reports_insert_own on public.reports for insert with check (user_id = auth.uid());
create policy reports_delete_own on public.reports for delete using (user_id = auth.uid());

-- 공개 커뮤니티 피드(SECURITY DEFINER) — 정밀 좌표 미노출·거부(rejected) 제외.
-- 제보자 표기는 profiles.display_name(설정 시)만, 없으면 NULL(UI 에서 '익명'). user_id 원값 미노출.
create or replace function public.community_reports(lim int default 50)
returns table(
  id uuid, ktsn text, korean_name text, scientific_name text, taxon_group text,
  observed_date date, note text, url text, status text, fills_gap boolean,
  sigungu text, created_at timestamptz, reporter text
)
language sql
security definer
set search_path = public
stable
as $$
  select r.id, r.ktsn, r.korean_name, r.scientific_name, r.taxon_group,
         r.observed_date, r.note, r.url, r.status, r.fills_gap, r.sigungu, r.created_at,
         p.display_name as reporter
  from public.reports r
  left join public.profiles p on p.id = r.user_id
  where r.status <> 'rejected'
  order by r.created_at desc
  limit greatest(1, least(coalesce(lim, 50), 200))
$$;

revoke all on function public.community_reports(int) from public;
grant execute on function public.community_reports(int) to anon, authenticated;

comment on table public.reports is
  '시민과학 URL 제보(Feature B). 본인 행 RLS. 정밀 좌표는 원시 테이블에만 — 공개는 community_reports() 로 좌표 없이.';
comment on function public.community_reports(int) is
  '공개 커뮤니티 제보 피드. 좌표 미노출·거부 제외·제보자는 display_name(없으면 NULL).';
