// fg_supabase.js — Supabase 클라이언트 + 인증·관심종 헬퍼 (ES module)
// 설정값은 config.js(window.SUPABASE_URL/KEY, gitignore)에서 읽음. 미설정이면 configured=false 로 graceful 비활성.
// publishable 키는 공개 전제(RLS 보호). 데이터 접근 권한은 전적으로 Supabase RLS 정책이 통제.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const URL = (window.SUPABASE_URL || '').trim();
const KEY = (window.SUPABASE_KEY || '').trim();
export const configured = !!(URL && KEY);
export const sb = configured ? createClient(URL, KEY) : null;

// ── 인증(이메일 매직링크) ──
export async function getUser() {
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session?.user || null;
}
export function onAuth(cb) {
  if (!sb) { cb(null); return; }
  sb.auth.getSession().then(({ data }) => cb(data.session?.user || null));
  sb.auth.onAuthStateChange((_e, sess) => cb(sess?.user || null));
}
export async function sendMagicLink(email) {
  // 클릭 후 현재 페이지로 복귀(해당 URL 이 Supabase Auth Redirect URLs 에 등록돼 있어야 함)
  return sb.auth.signInWithOtp({ email, options: { emailRedirectTo: location.href.split('#')[0] } });
}
export async function signInWithGoogle() {
  // Google → Supabase 콜백 → 현재 페이지로 복귀(redirectTo 가 Auth Redirect URLs 에 등록돼 있어야 함)
  return sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: location.href.split('#')[0] } });
}
export async function signOut() { return sb?.auth.signOut(); }

// ── 관심 종(watchlist) — user_id 는 DB default auth.uid() 로 자동 채움 ──
export async function watchList() {
  if (!sb) return [];
  const { data, error } = await sb.from('watchlist').select('ktsn').order('created_at', { ascending: false });
  if (error) throw error;
  return (data || []).map(r => r.ktsn);
}
export async function watchAdd(ktsn) { return sb.from('watchlist').insert({ ktsn }); }
export async function watchRemove(ktsn) { return sb.from('watchlist').delete().eq('ktsn', ktsn); }

// ── 익명 관심종 집계(전체 사용자) — species_watch_counts() RPC ──
// 원시 watchlist 는 RLS(본인 행)로 보호되고, 이 RPC(SECURITY DEFINER)는 종별 집계 카운트만 반환(개인식별 불가).
// 마이그레이션: 5_App/supabase/species_watch_counts.sql. 미배포면 빈 배열.
export async function watchCounts() {
  if (!sb) return [];
  const { data, error } = await sb.rpc('species_watch_counts');
  if (error) throw error;
  return (data || []).map(r => ({ ktsn: r.ktsn, count: Number(r.watch_count) || 0 }))
                     .sort((a, b) => b.count - a.count);
}

// ── 시민과학 URL 제보(reports) — Feature B ──
// user_id 는 DB default auth.uid() 로 자동 채움. 정밀 좌표는 원시 행(본인 RLS)에만 저장.
// r = { ktsn, scientific_name, korean_name, taxon_group, url, lat, lon, observed_date, note }
export async function submitReport(r) {
  if (!sb) throw new Error('not configured');
  return sb.from('reports').insert({
    ktsn: r.ktsn,
    scientific_name: r.scientific_name || null,
    korean_name: r.korean_name || null,
    taxon_group: r.taxon_group || null,
    url: r.url,
    lat: r.lat,
    lon: r.lon,
    observed_date: r.observed_date,
    note: (r.note && r.note.trim()) || null
  });
}
// 내 제보 이력(본인 행 — RLS)
export async function myReports() {
  if (!sb) return [];
  const { data, error } = await sb.from('reports')
    .select('id,ktsn,korean_name,scientific_name,taxon_group,url,lat,lon,observed_date,note,status,fills_gap,sigungu,created_at')
    .order('created_at', { ascending: false });
  if (error) throw error;
  return data || [];
}
export async function deleteReport(id) { return sb.from('reports').delete().eq('id', id); }
// 공개 커뮤니티 피드 — community_reports() RPC(좌표 미노출·거부 제외). 미배포/미설정이면 빈 배열.
export async function communityReports(limit = 50) {
  if (!sb) return [];
  const { data, error } = await sb.rpc('community_reports', { lim: limit });
  if (error) throw error;
  return data || [];
}
