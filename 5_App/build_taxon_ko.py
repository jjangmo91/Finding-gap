"""
과·속 라틴명 → 한글명 룩업 자산 생성 — taxon_ko.js

퀴즈 범위(과·속) 드롭다운·검색에 한글 분류명을 병기하기 위한 소형 룩업.
- 대상: media_<T>.js 의 tax맵에 실제로 등장하는 과(family)·속(genus) 라틴명만.
- 출처: 1_Data/raw/nibr/ktsn_*.ndjson 의 fmlyKtsnLtnNm/fmlyKtsnKrnNm,
        gnusKtsnLtnNm/gnusKtsnKrnNm (라틴명당 최빈 한글명 채택).
- 출력: 5_App/demo/data/taxon_ko.js  →  window.__TAXON_KO__={"fam":{la:ko},"gen":{la:ko}};

사용:  python 5_App/build_taxon_ko.py
"""
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "5_App" / "demo" / "data"
NIBR = ROOT / "1_Data" / "raw" / "nibr"


def media_latin_sets():
    """media_<T>.js tax맵에 등장하는 과·속 라틴명 집합."""
    fam, gen = set(), set()
    for p in glob.glob(str(DATA / "media_*.js")):
        if "media_meta" in p:
            continue
        m = re.match(r"window\.__SPMEDIA__=(.*);\s*$", Path(p).read_text(encoding="utf-8").strip(), re.S)
        if not m:
            continue
        for v in (json.loads(m.group(1)).get("tax") or {}).values():
            if len(v) > 0 and v[0]:
                gen.add(v[0])
            if len(v) > 1 and v[1]:
                fam.add(v[1])
    return fam, gen


def latin_to_korean():
    """ktsn_*.ndjson → (fam_la→ko, gen_la→ko), 라틴명당 최빈 한글명."""
    famc, genc = {}, {}
    for p in glob.glob(str(NIBR / "ktsn_*.ndjson")):
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            fla, fko = (r.get("fmlyKtsnLtnNm") or "").strip(), (r.get("fmlyKtsnKrnNm") or "").strip()
            gla, gko = (r.get("gnusKtsnLtnNm") or "").strip(), (r.get("gnusKtsnKrnNm") or "").strip()
            if fla and fko:
                famc.setdefault(fla, Counter())[fko] += 1
            if gla and gko:
                genc.setdefault(gla, Counter())[gko] += 1
    fam = {la: c.most_common(1)[0][0] for la, c in famc.items()}
    gen = {la: c.most_common(1)[0][0] for la, c in genc.items()}
    return fam, gen


def main():
    fam_la, gen_la = media_latin_sets()
    fam_ko_all, gen_ko_all = latin_to_korean()
    fam = {la: fam_ko_all[la] for la in sorted(fam_la) if la in fam_ko_all}
    gen = {la: gen_ko_all[la] for la in sorted(gen_la) if la in gen_ko_all}
    body = json.dumps({"fam": fam, "gen": gen}, ensure_ascii=False, separators=(",", ":"))
    out = DATA / "taxon_ko.js"
    out.write_text("window.__TAXON_KO__=" + body + ";\n", encoding="utf-8")
    fam_miss = len(fam_la) - len(fam)
    gen_miss = len(gen_la) - len(gen)
    print(f"[taxon_ko] 과 {len(fam)}/{len(fam_la)} (미스 {fam_miss}) · "
          f"속 {len(gen)}/{len(gen_la)} (미스 {gen_miss})")
    print(f"[출력] {out.relative_to(ROOT)} · {out.stat().st_size/1024:.1f} KB")
    if not fam and not gen:
        print("경고: 매핑이 비었습니다(media_*.js 또는 ktsn ndjson 확인).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
