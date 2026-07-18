# -*- coding: utf-8 -*-
"""
유망 공백 미션보드 자산 — Feature B P3.
MCP sqlite(단일 소스)에서 '시도별 고관심 미발견 종'을 뽑아 window.__MISSIONS__ 로 export.
미션 = 그 시도에서 최근 10년 미발견이지만 전국적으로는 기록이 있고 관심도 높은 종
       (= 발견공백 × 관심도를 지역 미션으로 표면화; discovery_priorities 의 정적 축약).

출력: 5_App/demo/data/missions.js  (window.__MISSIONS__=[{region,region_name,ktsn,name,sci,taxon,grade,interest}])
사용: python 5_App/build_missions.py
"""
import sqlite3, json
from pathlib import Path
from datetime import date

BASE = Path(__file__).resolve().parents[1]
SQLITE = BASE / "7_MCP" / "data" / "fg_mcp.sqlite"
OUT = BASE / "5_App" / "demo" / "data" / "missions.js"
CUTOFF = date.today().year - 10
PER_SIDO = 2                                              # 시도당 미션 수
MIN_INTEREST = 0.55                                       # 관심도 하한(주목할 만한 종만)


def main():
    con = sqlite3.connect(str(SQLITE))
    con.row_factory = sqlite3.Row
    sp = {r["ktsn"]: r for r in con.execute(
        "SELECT ktsn, korean_name, scientific_name, taxon_group, endangered_grade, interest "
        "FROM species WHERE korean_name NOT IN ('','국명미정') AND interest >= ?", (MIN_INTEREST,))}
    sido_name = {r["code"]: r["name"] for r in con.execute(
        "SELECT code, name FROM region WHERE level='sido'")}
    # (ktsn, sido) found 여부 — species_region 롤업(sido MAX)
    found = {}                                            # sido -> set(ktsn found)
    seen = {}                                             # sido -> set(ktsn recorded any)
    for r in con.execute("SELECT ktsn, sido, maxyear FROM species_region WHERE sido<>'00'"):
        s = r["sido"]; k = r["ktsn"]
        seen.setdefault(s, set()).add(k)
        if r["maxyear"] is not None and int(r["maxyear"]) >= CUTOFF:
            found.setdefault(s, set()).add(k)
    con.close()

    # 전국 어딘가엔 기록이 있는 종만(유령 후보 배제)
    recorded_anywhere = set()
    for s in seen:
        recorded_anywhere |= seen[s]

    missions, used = [], set()
    for s in sorted(sido_name):
        if s == "00":
            continue
        fnd = found.get(s, set())
        cands = [sp[k] for k in sp
                 if k in recorded_anywhere and k not in fnd and k not in used]
        # 보전 의미 우선: 멸종위기 I>II>일반, 그 안에서 관심도 높은 종(지역 미션의 설득력)
        grank = {"I": 0, "II": 1}
        cands.sort(key=lambda r: (grank.get(r["endangered_grade"] or "", 2),
                                  -(r["interest"] or 0), r["korean_name"]))
        for r in cands[:PER_SIDO]:
            used.add(r["ktsn"])
            missions.append({
                "region": s, "region_name": sido_name.get(s, s),
                "ktsn": r["ktsn"], "name": r["korean_name"], "sci": r["scientific_name"],
                "taxon": r["taxon_group"], "grade": r["endangered_grade"] or "",
                "interest": round((r["interest"] or 0), 3),
            })
    # 관심도 높은 미션 우선 노출
    missions.sort(key=lambda m: -m["interest"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.__MISSIONS__=" + json.dumps(missions, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"→ {OUT.name}  미션 {len(missions)}개  시도 {len({m['region'] for m in missions})}  "
          f"관심도≥{MIN_INTEREST}  cutoff≥{CUTOFF}")


if __name__ == "__main__":
    main()
