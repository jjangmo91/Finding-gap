-- 익명 관심종 집계 RPC — interest(user 0.3) 신호 + '많이 담긴 종' 위젯용.
-- 원시 watchlist 는 RLS(본인 행만)를 그대로 유지하고, 이 함수는 SECURITY DEFINER 로
-- 소유자 권한에서 집계해 **종별 카운트만** 반환한다(user_id·시각 등 개인정보 미노출).
-- 적용: Supabase 대시보드 SQL Editor 또는 MCP apply_migration 으로 실행.
-- 소비: build_watch_snapshot.py(빌드타임 집계) · fg_supabase.js watchCounts()(웹 실시간 위젯).

create or replace function public.species_watch_counts()
returns table(ktsn text, watch_count bigint)
language sql
security definer
set search_path = public
stable
as $$
  select ktsn, count(*)::bigint as watch_count
  from public.watchlist
  group by ktsn
$$;

-- 익명/로그인 사용자 모두 집계 카운트는 조회 가능(개인 행은 여전히 RLS 로 보호).
revoke all on function public.species_watch_counts() from public;
grant execute on function public.species_watch_counts() to anon, authenticated;

comment on function public.species_watch_counts() is
  '종별 관심종(watchlist) 익명 집계 카운트. 개인 행은 RLS 로 보호되며 집계 수치만 노출.';
