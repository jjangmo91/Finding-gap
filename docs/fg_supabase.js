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
