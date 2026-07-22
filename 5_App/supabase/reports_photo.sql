-- 발견 제보 사진 업로드(Feature B 확장) — URL 전용 제보의 불편함을 보완.
-- reports.url 을 선택으로 바꾸고 photo_path(Storage 경로)를 추가. url·photo_path 중 최소 하나는 필수.
-- 사진은 Storage 버킷 report-photos 에 저장(public read — 기존 URL 제보와 동일한 공개 수준).
-- 적용 순서: reports.sql 적용 후 이 파일을 Supabase 대시보드 SQL Editor에서 실행.

alter table public.reports alter column url drop not null;
alter table public.reports add column if not exists photo_path text;
alter table public.reports add constraint reports_evidence_chk
  check (url is not null or photo_path is not null);

comment on column public.reports.photo_path is
  'Storage report-photos 버킷 내 경로(<user_id>/<uuid>.jpg). url 과 최소 하나는 필수(reports_evidence_chk).';

-- ── Storage 버킷: report-photos (public read) ──
insert into storage.buckets (id, name, public)
values ('report-photos', 'report-photos', true)
on conflict (id) do nothing;

-- 본인 폴더(<user_id>/...)에만 업로드·삭제 가능. 읽기는 버킷 public=true 로 별도 정책 없이 공개.
drop policy if exists report_photos_insert_own on storage.objects;
drop policy if exists report_photos_delete_own on storage.objects;
create policy report_photos_insert_own on storage.objects for insert to authenticated
  with check (bucket_id = 'report-photos' and (storage.foldername(name))[1] = auth.uid()::text);
create policy report_photos_delete_own on storage.objects for delete to authenticated
  using (bucket_id = 'report-photos' and (storage.foldername(name))[1] = auth.uid()::text);

-- community_reports() 에 photo_path 포함하도록 재정의. 반환 컬럼이 바뀌므로 CREATE OR REPLACE 불가 → DROP 후 재생성(+재GRANT).
drop function if exists public.community_reports(int);
create or replace function public.community_reports(lim int default 50)
returns table(
  id uuid, ktsn text, korean_name text, scientific_name text, taxon_group text,
  observed_date date, note text, url text, photo_path text, status text, fills_gap boolean,
  sigungu text, created_at timestamptz, reporter text
)
language sql
security definer
set search_path = public
stable
as $$
  select r.id, r.ktsn, r.korean_name, r.scientific_name, r.taxon_group,
         r.observed_date, r.note, r.url, r.photo_path, r.status, r.fills_gap, r.sigungu, r.created_at,
         p.display_name as reporter
  from public.reports r
  left join public.profiles p on p.id = r.user_id
  where r.status <> 'rejected'
  order by r.created_at desc
  limit greatest(1, least(coalesce(lim, 50), 200))
$$;
-- DROP 로 사라진 실행 권한 재부여(reports.sql 과 동일)
revoke all on function public.community_reports(int) from public;
grant execute on function public.community_reports(int) to anon, authenticated;
