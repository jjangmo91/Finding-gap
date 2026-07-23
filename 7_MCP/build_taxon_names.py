"""
분류 계층(강·목·과·속) 라틴↔한글 이름 매핑 자산 생성 — taxon_names.json.gz

대화형 도우미(Edge Function chat)의 fg_taxon_name 적재용 백엔드 참조 자산.
- 출처: 1_Data/raw/nibr/ktsn_*.ndjson 의 classKtsnLtnNm/classKtsnKrnNm,
        orderKtsnLtnNm/orderKtsnKrnNm, fmlyKtsnLtnNm/fmlyKtsnKrnNm,
        gnusKtsnLtnNm/gnusKtsnKrnNm (라틴명당 최빈 한글명 채택).
- 프런트 퀴즈용 taxon_ko.js(사진 보유 종 범위 한정)와 달리 KTSN 전체를 담는다.
- 출력: 7_MCP/data/taxon_names.json.gz
        → {"class":{la:ko}, "order":{la:ko}, "family":{la:ko}, "genus":{la:ko}}

사용:  python 7_MCP/build_taxon_names.py
"""
import glob
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NIBR = ROOT / "1_Data" / "raw" / "nibr"
OUT = Path(__file__).resolve().parent / "data" / "taxon_names.json.gz"

# rank → (라틴명 필드, 한글명 필드)
FIELDS = {
    "class": ("classKtsnLtnNm", "classKtsnKrnNm"),
    "order": ("orderKtsnLtnNm", "orderKtsnKrnNm"),
    "family": ("fmlyKtsnLtnNm", "fmlyKtsnKrnNm"),
    "genus": ("gnusKtsnLtnNm", "gnusKtsnKrnNm"),
}


def build():
    counters = {rank: {} for rank in FIELDS}
    files = glob.glob(str(NIBR / "ktsn_*.ndjson"))
    if not files:
        print(f"경고: KTSN ndjson 없음 — {NIBR}")
        return None
    for p in files:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            for rank, (lf, kf) in FIELDS.items():
                la = (r.get(lf) or "").strip()
                ko = (r.get(kf) or "").strip()
                if la and ko:
                    counters[rank].setdefault(la, Counter())[ko] += 1
    return {rank: {la: c.most_common(1)[0][0] for la, c in d.items()}
            for rank, d in counters.items()}


def main():
    maps = build()
    if maps is None:
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(maps, ensure_ascii=False, separators=(",", ":"))
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        f.write(body)
    total = sum(len(v) for v in maps.values())
    print("[taxon_names] " + " · ".join(f"{rank} {len(maps[rank])}" for rank in FIELDS))
    print(f"[출력] {OUT.relative_to(ROOT)} · {OUT.stat().st_size/1024:.1f} KB · 총 {total} 매핑")
    if not total:
        print("경고: 매핑이 비었습니다(ktsn ndjson 확인).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
