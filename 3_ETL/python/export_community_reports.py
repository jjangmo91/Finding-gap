# -*- coding: utf-8 -*-
"""
승인된 시민 제보 → 관측 포맷 export (Feature B P4 재빌드 훅).
관리자 승인(status='approved')된 제보를 (ktsn × 시군구 × 연도) 로 집계해 source='community' 관측으로
내보낸다. 다음 재빌드에서 이 파일을 3원 관측 union 에 합류시키면 '시민 재발견'이 서비스에 반영된다.

출력: 1_Data/processed/observation_community.csv
       (ktsn, region=시군구5, sido2, year, source='community', obs_count)
       — observation_sigungu.csv(집계본)와 같은 열 규격. build 파이프라인에서 union.

두 모드:
  ① 온라인: env SUPABASE_URL, SUPABASE_SERVICE_KEY 로 approved 제보 읽기.
       python export_community_reports.py
  ② 오프라인(검증): approved 제보 JSON 입력.
       python export_community_reports.py --from-json approved.json
     approved.json = [{"ktsn":"..","sigungu":"11010","observed_date":"2026-04-04"}, ...]
"""
import sys, os, json, csv, argparse
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parents[2]
OUT = BASE / "1_Data" / "processed" / "observation_community.csv"


def aggregate(rows):
    """rows=[{ktsn,sigungu,observed_date}] → [(ktsn,region,sido,year,'community',count)]."""
    agg = defaultdict(int)
    for r in rows:
        sg = (r.get("sigungu") or "").strip()
        if not sg or sg == "00000":                      # 시군구 미상은 제외(집계 오염 방지)
            continue
        yr = str(r.get("observed_date") or "")[:4]
        if not yr.isdigit():
            continue
        agg[(str(r["ktsn"]), sg, sg[:2], int(yr))] += 1
    return [(k[0], k[1], k[2], k[3], "community", v) for k, v in sorted(agg.items())]


def write_csv(recs):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ktsn", "region", "sido", "year", "source", "obs_count"])
        w.writerows(recs)
    print(f"→ {OUT.name}  {len(recs)}행  종 {len({r[0] for r in recs})}  "
          f"시군구 {len({r[1] for r in recs})}")


def read_online():
    import requests
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    url = os.environ.get("SUPABASE_URL", "").strip()
    if not (key and url):
        raise SystemExit("env SUPABASE_URL, SUPABASE_SERVICE_KEY 필요(오프라인은 --from-json).")
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    q = f"{url.rstrip('/')}/rest/v1/reports?select=ktsn,sigungu,observed_date&status=eq.approved"
    return requests.get(q, headers=h, timeout=30).json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="approved 제보 JSON(오프라인 검증)")
    a = ap.parse_args()
    rows = json.loads(Path(a.from_json).read_text(encoding="utf-8")) if a.from_json else read_online()
    if not isinstance(rows, list):
        raise SystemExit(f"예상치 못한 응답: {rows}")
    write_csv(aggregate(rows))


if __name__ == "__main__":
    main()
