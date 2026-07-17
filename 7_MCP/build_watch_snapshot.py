# -*- coding: utf-8 -*-
"""사용자 관심종(watchlist) 익명 집계 스냅샷 — 관심도(Interest)의 '사용자 수요' 신호(0.2).

Supabase `watchlist(user_id, ktsn, created_at)` → 종별 카운트만(개인식별 없음) → data/watch_counts.json.
출력: { "<ktsn>": count }.  개인정보(user_id·시각) 미포함.

전제(둘 중 하나):
  (a) watchlist 에 공개 SELECT RLS 정책 추가 → publishable 키로 집계 가능, 또는
  (b) service_role 키로 서버측 실행(SUPABASE_SERVICE_ROLE_KEY, 절대 커밋 금지 · CI secret/.env 전용).
키·정책이 없으면(현재 사용자 ~0) 빈 {} 를 쓴다(관심도 사용자 성분=0).

사용: python 7_MCP/build_watch_snapshot.py
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "5_App" / ".env"
OUT = Path(__file__).resolve().parent / "data" / "watch_counts.json"


def env_val(name):
    if not ENV.exists():
        return None
    m = re.search(rf"^\s*{name}\s*=\s*(.*?)\s*$", ENV.read_text(encoding="utf-8"), re.M)
    return m.group(1).split("#", 1)[0].strip().strip('"').strip("'") if m else None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    url = env_val("SUPABASE_URL")
    key = env_val("SUPABASE_SERVICE_ROLE_KEY") or env_val("SUPABASE_KEY")
    counts = {}
    if not url or not key:
        print("(정보) SUPABASE_URL/키 없음 → 빈 스냅샷. 사용자 성분=0.")
        OUT.write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
        return 0
    endpoint = url.rstrip("/") + "/rest/v1/watchlist?select=ktsn"
    req = urllib.request.Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            rows = json.loads(r.read().decode("utf-8"))
        for row in rows:
            k = str(row.get("ktsn", "")).strip()
            if k:
                counts[k] = counts.get(k, 0) + 1
        print(f"watchlist 집계: {sum(counts.values())}건 · {len(counts)}종")
    except urllib.error.HTTPError as ex:
        print(f"(경고) watchlist 조회 실패 status={ex.code} — RLS 공개 SELECT 정책 또는 service_role 필요. 빈 스냅샷.")
    except Exception as ex:
        print(f"(경고) 조회 오류: {ex}. 빈 스냅샷.")
    OUT.write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
    print(f"출력: {OUT.relative_to(ROOT)} · {len(counts)}종")
    return 0


if __name__ == "__main__":
    sys.exit(main())
