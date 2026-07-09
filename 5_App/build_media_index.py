"""
종 미디어 인덱스 병합 — media_nibr.json + media_inat.json → species_media.js
계약: 2_Planning/media_pipeline_contract.md

- 두 소스의 per-ktsn 레코드({src,type,thumb,full,by,lic,link})를 ktsn별로 합침.
- 정렬: NIBR(공식) 먼저, 그다음 iNat. 같은 소스 내 순서는 입력 순서 유지.
- 중복 제거: full URL 기준.
- 출력: window.__SPMEDIA__ = {generated, m:{ktsn:[...]}}  (JS 자산) + 동일 내용 .json.

사용:  python build_media_index.py
       (media_nibr.json 없으면 iNat만으로, 반대도 동일 — 있는 소스만 병합)
"""
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 프로젝트 루트
PROC = ROOT / "1_Data" / "processed"
OUT_DIR = ROOT / "5_App" / "demo" / "data"
MASTER = PROC / "ktsn_master.csv"                       # 분류체계(속/과/목)

SOURCES = [
    ("nibr", PROC / "media_nibr.json"),                # 공식 우선
    ("inat", PROC / "media_inat.json"),
]


def load(path):
    if not path.exists():
        print(f"  - {path.name}: 없음(건너뜀)")
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"  - {path.name}: {len(data)}종")
    return data


def main():
    print("[병합] 소스 로드")
    per_source = [(name, load(path)) for name, path in SOURCES]

    merged = {}                                        # ktsn -> [record]
    for name, data in per_source:                      # SOURCES 순서 = 우선순위
        for ktsn, recs in data.items():
            bucket = merged.setdefault(ktsn, [])
            seen = {r.get("full") for r in bucket}
            for r in recs:
                if r.get("full") in seen:
                    continue
                seen.add(r.get("full"))
                bucket.append(r)

    total_photos = sum(len(v) for v in merged.values())
    print(f"[병합] 종 {len(merged)} · 미디어 {total_photos}")

    # 분류체계 부착(퀴즈 오답: 속→과 폴백) + 분류군(분할 키). tax[ktsn]=[genus, family, order]
    tax = {}
    tgmap = {}
    if MASTER.exists():
        want = set(merged.keys())
        with open(MASTER, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                k = row.get("ktsn")
                if k in want:
                    tax[k] = [row.get("genus_la", ""), row.get("family_la", ""), row.get("order_la", "")]
                    tgmap[k] = row.get("taxon_group", "")
        print(f"[병합] 분류체계 부착: {len(tax)}종")
    else:
        print("  - ktsn_master.csv 없음 → tax 생략")

    gen = date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 전체 결합본(기록·디버그용 json만; 브라우저는 분류군별 분할 로드)
    (OUT_DIR / "species_media.json").write_text(
        json.dumps({"generated": gen, "m": merged, "tax": tax}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    # 분류군별 분할: media_<T>.js — 퀴즈가 해당 분류군만 지연 로드(6MB 단일 로드 방지)
    def fname(t):
        return "media_" + re.sub(r"[^A-Za-z0-9]", "_", t or "NA") + ".js"
    groups = {}
    for k in merged:
        groups.setdefault(tgmap.get(k) or "NA", []).append(k)
    meta = {}
    for t, ks in sorted(groups.items()):
        body = json.dumps({"generated": gen, "t": t,
                           "m": {k: merged[k] for k in ks},
                           "tax": {k: tax[k] for k in ks if k in tax}},
                          ensure_ascii=False, separators=(",", ":"))
        (OUT_DIR / fname(t)).write_text("window.__SPMEDIA__=" + body + ";\n", encoding="utf-8")
        meta[t] = len(ks)
    (OUT_DIR / "media_meta.js").write_text(
        "window.__SPMEDIA_META__=" + json.dumps({"generated": gen, "taxa": meta},
                                                ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")

    # 스테일 결합본(.js, 6MB) 제거 — 더 이상 미사용
    stale = OUT_DIR / "species_media.js"
    if stale.exists():
        stale.unlink()

    print(f"[출력] 분류군별 media_<T>.js {len(meta)}개 + media_meta.js")
    for t in sorted(meta):
        print(f"    {fname(t)}: {meta[t]}종")

    if not merged:
        print("경고: 병합 결과가 비었습니다(입력 json 확인).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
