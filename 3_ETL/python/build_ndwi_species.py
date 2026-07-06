# -*- coding: utf-8 -*-
"""
NDWI(정규수분지수) 적용 종 집합 산출 → ndwi_species.csv

환경적합 후보(feature A)의 엔벨로프 모델에서 NDWI 축은 **수생 종에만** 적용한다(사용자 확정):
  - 어류: 종 마스터 taxon_group == '-P' 전체
  - 저서성대형무척추동물: EcoBank 저서무척추(bnin) 레이어에서 매칭된 ktsn
표시 막대(그래프)는 모든 종에 NDVI/NDWI를 일괄 표시하되, 모델 계산에서만 이 집합으로 NDWI 적용 여부를 분기한다.

입력: 1_Data/raw/ecobank/ecobank_mv_map_{bgts,ecpe,ntee}_bnin_point.ndjson  +  ktsn_master(별칭·override 포함)
출력: 1_Data/processed/ndwi_species.csv  (ktsn, reason ∈ {fish, benthic, both})
사용: python build_ndwi_species.py
"""
import sys, csv, json, glob
from pathlib import Path
from collections import Counter
from name_overrides import load_overrides
from obs_common import load_master, resolve_ktsn, _kor

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
RAW = BASE / "1_Data" / "raw" / "ecobank"
OUT = PROC / "ndwi_species.csv"
FISH_GROUP = "-P"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sci, kor, tx = load_master()
    ov_sci, ov_kor = load_overrides()
    print(f"마스터: ktsn {len(tx):,} · 학명키 {len(sci):,} · 국명 {len(kor):,} | 보정 학명 {len(ov_sci)} · 국명 {len(ov_kor)}")

    # 1) 어류 = taxon_group '-P'
    fish = {k for k, g in tx.items() if g == FISH_GROUP}
    print(f"어류(-P) 종: {len(fish):,}")

    # 2) 저서무척추 = bnin 레이어 ndjson 에서 매칭된 ktsn
    benthic = set()
    files = sorted(glob.glob(str(RAW / "ecobank_mv_map_*_bnin_point.ndjson")))
    if not files:
        sys.exit(f"bnin ndjson 없음: {RAW}")
    n_all = n_match = 0
    unmatched = Counter()
    for fp in files:
        fp = Path(fp)
        cnt = 0
        for line in fp.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_all += 1; cnt += 1
            sciname = (r.get("spcs_scncenm") or "").strip()
            kn = _kor(r.get("spcs_korean_nm") or r.get("spcs_lcnm"))
            ktsn, how = resolve_ktsn(sci, kor, sciname, kn, ov_sci, ov_kor)
            if ktsn:
                benthic.add(ktsn); n_match += 1
            else:
                unmatched[sciname or kn or "(빈값)"] += 1
        print(f"  {fp.name}: {cnt:,}행")
    print(f"bnin 매칭: 총 {n_all:,} | 매칭 {n_match:,} ({n_match/n_all*100:.1f}%) | 고유 ktsn {len(benthic):,}")
    if unmatched:
        print(f"  미매칭 top: {[n for n, _ in unmatched.most_common(6)]}")

    # 3) union + reason
    allk = fish | benthic
    rows = []
    for k in sorted(allk):
        reason = "both" if (k in fish and k in benthic) else ("fish" if k in fish else "benthic")
        rows.append({"ktsn": k, "taxon_group": tx.get(k, ""), "reason": reason})
    PROC.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ktsn", "taxon_group", "reason"])
        w.writeheader(); w.writerows(rows)
    rc = Counter(r["reason"] for r in rows)
    print(f"\nndwi_species.csv: {len(rows):,}종  (fish {rc['fish']:,} · benthic {rc['benthic']:,} · both {rc['both']:,}) → {OUT.name}")
    # 저서무척추 매칭 종의 분류군 분포(검증용)
    bt = Counter(tx.get(k, "?") for k in benthic)
    print(f"  bnin 매칭 종 분류군 분포: {dict(bt.most_common())}")


if __name__ == "__main__":
    main()
