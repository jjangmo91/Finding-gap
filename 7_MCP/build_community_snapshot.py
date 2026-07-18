# -*- coding: utf-8 -*-
"""관리자 승인된 시민 제보 익명 집계 스냅샷 — MCP community_discoveries 원천 (Feature B P4→MCP).

Supabase 익명 집계 RPC `approved_discoveries()`(SECURITY DEFINER; status='approved' 만, 원시행은
RLS 로 보호, 종×시군구 집계만 반환) 를 publishable 키로 호출 →
data/community_reports.json = [{"ktsn":..,"sigungu":"11010","count":..,"last_year":..}].
개인정보(user_id·정확좌표·URL) 미포함. 미승인·미검증 제보는 미노출. RPC 마이그레이션: 5_App/supabase/reports.sql.

RPC 미배포/승인 0건이면 빈 [] 를 쓴다(MCP community 테이블 빈 상태 = honest).

사용:
  python 7_MCP/build_community_snapshot.py                 # 실 RPC 익명 집계(publishable 키)
  python 7_MCP/build_community_snapshot.py --from-json f   # 로컬 검증용 입력 주입(커밋 금지)
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "5_App" / ".env"
OUT = Path(__file__).resolve().parent / "data" / "community_reports.json"


def env_val(name):
    if not ENV.exists():
        return None
    m = re.search(rf"^\s*{name}\s*=\s*(.*?)\s*$", ENV.read_text(encoding="utf-8"), re.M)
    return m.group(1).split("#", 1)[0].strip().strip('"').strip("'") if m else None


def rpc_rows(url, key):
    endpoint = url.rstrip("/") + "/rest/v1/rpc/approved_discoveries"
    req = urllib.request.Request(
        endpoint, data=b"{}", method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        rows = json.loads(r.read().decode("utf-8"))
    return [{"ktsn": str(x["ktsn"]).strip(), "sigungu": str(x["sigungu"]).strip(),
             "count": int(x.get("cnt", 1)), "last_year": int(x.get("last_year") or 0)}
            for x in rows if x.get("ktsn") and x.get("sigungu")]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    rows = []
    if "--from-json" in args:
        p = Path(args[args.index("--from-json") + 1])
        raw = json.loads(p.read_text(encoding="utf-8"))
        rows = [{"ktsn": str(x["ktsn"]).strip(), "sigungu": str(x["sigungu"]).strip(),
                 "count": int(x.get("count", x.get("cnt", 1))), "last_year": int(x.get("last_year") or 0)}
                for x in raw if x.get("ktsn") and x.get("sigungu")]
        print(f"[주입] {len(rows)}행 (로컬 검증용 — 공개 커밋 전 실 스냅샷/빈값으로 되돌릴 것)")
    else:
        url = env_val("SUPABASE_URL")
        key = env_val("SUPABASE_KEY")                     # publishable(anon RPC)
        if not url or not key:
            print("(정보) SUPABASE_URL/키 없음 → 빈 스냅샷. community=0.")
        else:
            try:
                rows = rpc_rows(url, key)
                print(f"RPC 승인 집계: {len(rows)}행 · 종 {len({r['ktsn'] for r in rows})}")
            except urllib.error.HTTPError as ex:
                print(f"(경고) RPC 실패 status={ex.code} — approved_discoveries 미배포? reports.sql 적용 필요. 빈 스냅샷.")
            except Exception as ex:
                print(f"(경고) 조회 오류: {ex}. 빈 스냅샷.")
    OUT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"출력: {OUT.relative_to(ROOT)} · {len(rows)}행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
