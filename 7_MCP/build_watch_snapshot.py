# -*- coding: utf-8 -*-
"""사용자 관심종(watchlist) 익명 집계 스냅샷 — 관심도(Interest)의 '사용자 수요' 신호(user 0.3).

Supabase 익명 집계 RPC `species_watch_counts()`(SECURITY DEFINER; 원시 watchlist 는 RLS 로 보호,
종별 카운트만 반환) 를 publishable 키로 호출 → data/watch_counts.json = { "<ktsn>": count }.
개인정보(user_id·시각) 미포함. RPC 마이그레이션: 5_App/supabase/species_watch_counts.sql.

RPC 미배포/무사용자면 빈 {} 를 쓴다(사용자 성분=0).

사용:
  python 7_MCP/build_watch_snapshot.py                  # 실 RPC 익명 집계(publishable 키)
  python 7_MCP/build_watch_snapshot.py --synthetic 500  # 로컬 검증용 임의 유저 500명 시뮬(관심도 가중) — 커밋 금지
"""
import bisect
import json
import random
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "5_App" / ".env"
DB = Path(__file__).resolve().parent / "data" / "fg_mcp.sqlite"
OUT = Path(__file__).resolve().parent / "data" / "watch_counts.json"

# 분류군 대중성(카리스마) 가중 — 합성 시뮬에서 담길 확률에 곱함.
# 실제 관심종은 척추동물에 강하게 쏠림 → 종수 많은 곤충 롱테일이 지배하지 않도록 per-species 배율을 크게.
TAXON_POP = {"MM": 40, "AV": 22, "AM": 8, "RP": 8, "-P": 5, "VP": 1.5, "IN": 0.25, "IV": 0.2, "MS": 0.1}


def env_val(name):
    if not ENV.exists():
        return None
    m = re.search(rf"^\s*{name}\s*=\s*(.*?)\s*$", ENV.read_text(encoding="utf-8"), re.M)
    return m.group(1).split("#", 1)[0].strip().strip('"').strip("'") if m else None


def rpc_counts(url, key):
    """species_watch_counts() RPC 호출 → {ktsn: count}."""
    endpoint = url.rstrip("/") + "/rest/v1/rpc/species_watch_counts"
    req = urllib.request.Request(
        endpoint, data=b"{}", method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        rows = json.loads(r.read().decode("utf-8"))
    return {str(x["ktsn"]).strip(): int(x["watch_count"]) for x in rows if x.get("ktsn")}


def synthetic_counts(n_users, seed=42):
    """임의 유저 시뮬 — 관심도 높은·대중적 분류군 종을 더 자주 담는 현실적 long-tail 분포.
    interest(관측+위키) 로 담길 확률을 가중(관심종은 순환참조 아님: interest_user 는 아직 0)."""
    if not DB.exists():
        raise FileNotFoundError(f"MCP sqlite 없음: {DB}. 먼저 build_mcp_data.py 실행.")
    con = sqlite3.connect(DB)
    sp = con.execute("SELECT ktsn, COALESCE(interest,0), taxon_group FROM species").fetchall()
    con.close()
    ktsns, cum, s = [], [], 0.0
    for k, itr, t in sp:
        s += (0.05 + float(itr)) ** 2 * TAXON_POP.get(t, 0.3)  # (바닥값+관심도)² × 분류군 대중성 → 인지도 높은 종에 집중
        ktsns.append(k); cum.append(s)
    total = s
    rnd = random.Random(seed)

    def pick_one():
        return ktsns[bisect.bisect(cum, rnd.random() * total)]

    counts = {}
    for _ in range(int(n_users)):
        n_watch = rnd.choices([1, 2, 3, 4, 5, 8], weights=[30, 25, 20, 12, 8, 5])[0]
        picks = set()
        guard = 0
        while len(picks) < n_watch and guard < n_watch * 20:
            picks.add(pick_one()); guard += 1
        for k in picks:
            counts[k] = counts.get(k, 0) + 1
    return counts


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if "--synthetic" in args:
        i = args.index("--synthetic")
        n = int(args[i + 1]) if i + 1 < len(args) else 500
        counts = synthetic_counts(n)
        OUT.write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
        print(f"[합성] 임의 유저 {n}명 → {sum(counts.values())}건 · {len(counts)}종 "
              f"(로컬 검증용 — 공개 커밋 전 실 스냅샷으로 되돌릴 것)")
        return 0

    url = env_val("SUPABASE_URL")
    key = env_val("SUPABASE_KEY") or env_val("SUPABASE_SERVICE_ROLE_KEY")   # publishable 우선(anon RPC)
    counts = {}
    if not url or not key:
        print("(정보) SUPABASE_URL/키 없음 → 빈 스냅샷. 사용자 성분=0.")
    else:
        try:
            counts = rpc_counts(url, key)
            print(f"RPC 집계: {sum(counts.values())}건 · {len(counts)}종")
        except urllib.error.HTTPError as ex:
            print(f"(경고) RPC 실패 status={ex.code} — species_watch_counts RPC 미배포? "
                  f"5_App/supabase/species_watch_counts.sql 적용 필요. 빈 스냅샷.")
        except Exception as ex:
            print(f"(경고) 조회 오류: {ex}. 빈 스냅샷.")
    OUT.write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
    print(f"출력: {OUT.relative_to(ROOT)} · {len(counts)}종")
    return 0


if __name__ == "__main__":
    sys.exit(main())
