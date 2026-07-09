#!/usr/bin/env python3
"""
NIBR (국립생물자원관) 디지털 자료관 미디어 수집 — Finding gap.
종별(KTSN) 사진/그림(세밀화)/표본/동영상/소리를 디지털콘텐츠 API에서 가져와 계약 스키마로 저장.

계약: 2_Planning/media_pipeline_contract.md
출력: 1_Data/processed/media_nibr.json  =  { "<ktsn>": [ {src,type,thumb,full,by,lic,link} ] }

사용:
  python build_media_nibr.py            # 검증셋(위협종 ~25, 식물/어류/곤충 편향)
  python build_media_nibr.py --subset N # species_index 상위 N종
  python build_media_nibr.py --full     # 전체(오래 걸림)

인증(라이브 프로브로 확정):
  - GET https://species.nibr.go.kr/gwsvc/openapi/rest/digital/bispconts/search
  - 쿼리 파라미터: oapiAcsUnqNo(키), schKtsn(KTSN), page, responseType=json
  - 키 = 5_App/.env 의 NIBR_DIGITAL_API_KEY (절대 출력·커밋 금지). 엔드포인트는 NIBR_DIGITAL_API_URL 로 덮어쓸 수 있음.
  - 이미지(thmbViewPath/fileViewPath)는 무인증 공개 URL → 핫링크(빌드시 다운로드 불필요).
"""

import json
import sys
import time
import re
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# ── 설정 ──
API_DEFAULT = "https://species.nibr.go.kr/gwsvc/openapi/rest/digital/bispconts/search"
USER_AGENT = "finding-gap/0.1"
RATE_SLEEP = 1.0            # 초/요청 (정부 API, 정중히)
MEDIA_PER_SPECIES = 6       # 모든 유형 수집(사진/그림/표본/소리/동영상). 퀴즈 UI가 필요한 유형만 사용.

# ── 경로 ──
ROOT = Path(__file__).resolve().parent.parent
SPIDX = ROOT / "5_App" / "demo" / "data" / "species_index.json"
ENV = ROOT / "5_App" / ".env"
OUT = ROOT / "1_Data" / "processed" / "media_nibr.json"

# 검증셋 편향 대상: iNat 이 비었던 분류군
GAP_TAXA = ["VP", "-P", "IN", "IV"]        # 관속식물/어류/곤충/무척추
ANIMAL_TAXA = ["AM", "RP", "MM", "AV"]
THREAT_R = {"CR", "EN", "VU", "NT"}


def env_val(name):
    if not ENV.exists():
        return None
    m = re.search(rf"^\s*{name}\s*=\s*(.*?)\s*$", ENV.read_text(encoding="utf-8"), re.M)
    if not m:
        return None
    return m.group(1).split("#", 1)[0].strip().strip('"').strip("'")


def load_species(subset=None, full=False, taxa=None):
    allsp = json.loads(SPIDX.read_text(encoding="utf-8"))
    if taxa:                                   # --taxa: 해당 분류군 전체(이웃 종에도 미디어 → 비교 퀴즈 성립)
        sel = [s for s in allsp if s.get("t") in taxa]
        return sel[:subset] if subset else sel
    if full:
        return allsp[:subset] if subset else allsp
    if subset:
        return allsp[:subset]
    # 검증셋: 위협종을 gap 분류군 우선으로 taxa별 최대 5종 + 동물 소수
    def threatened(s):
        return (s.get("g") not in ("", None)) or (s.get("r") in THREAT_R)
    picked, per = [], {}
    for s in allsp:
        t = s.get("t")
        if not threatened(s):
            continue
        cap = 5 if t in GAP_TAXA else (2 if t in ANIMAL_TAXA else 0)
        if cap and per.get(t, 0) < cap:
            picked.append(s)
            per[t] = per.get(t, 0) + 1
    return picked


def map_type(cts, cts2):
    if cts == "PH":
        return "specimen" if cts2 == "SP" else "photo"
    if cts == "PI":
        return "specimen" if cts2 == "SP" else "drawing"   # 세밀화/도판
    if cts == "MO":
        return "video"
    if cts == "WA":
        return "sound"
    if cts == "3D":
        return "3d"
    return "photo"


def fetch(ktsn, key, url):
    params = {"oapiAcsUnqNo": key, "schKtsn": ktsn, "page": 1, "responseType": "json"}
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        try:
            j = json.loads(ex.read().decode("utf-8", "replace"))
            return {"status": j.get("status", ex.code), "errorCode": j.get("errorCode"), "_err": True}
        except Exception:
            return {"status": ex.code, "_err": True}
    except Exception as ex:
        return {"status": 0, "error": str(ex), "_err": True}


def to_record(item):
    typ = map_type(item.get("contsType"), item.get("contsType2"))
    thumb = item.get("thmbViewPath") or item.get("thumbPath500") or item.get("thmbDownloadPath") or ""
    full = item.get("fileViewPath") or item.get("fileDownloadPath") or thumb
    if not thumb and not full:
        return None
    shtr = (item.get("shtr") or "").strip()
    by = "국립생물자원관" + (f", 촬영 {shtr}" if shtr else "")
    return {
        "src": "nibr",
        "type": typ,
        "thumb": thumb or full,
        "full": full or thumb,
        "by": by,
        "lic": "KOGL",                        # 공공누리 추정 — 유형(1~4) 공개 전 확인 필요
        "link": "",
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    full = "--full" in sys.argv
    subset = None
    if "--subset" in sys.argv:
        i = sys.argv.index("--subset")
        if i + 1 < len(sys.argv):
            try:
                subset = int(sys.argv[i + 1])
            except ValueError:
                pass
    taxa = None
    if "--taxa" in sys.argv:
        i = sys.argv.index("--taxa")
        if i + 1 < len(sys.argv):
            taxa = set(sys.argv[i + 1].split(","))

    key = env_val("NIBR_DIGITAL_API_KEY")
    if not key:
        print("ERROR: 5_App/.env 에 NIBR_DIGITAL_API_KEY 없음")
        return 1
    url = env_val("NIBR_DIGITAL_API_URL") or API_DEFAULT

    print("NIBR 디지털 자료관 미디어 수집")
    print(f"  endpoint: {url}  (GET)")
    print(f"  key: .env (masked)")

    species = load_species(subset=subset, full=full, taxa=taxa)
    print(f"  대상 종: {len(species)}" + (f"  (taxa={sorted(taxa)})" if taxa else ""))

    out = {}
    if OUT.exists():
        out = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"  이어받기: 기존 {len(out)}종")

    st = {"attempt": 0, "with": 0, "empty": 0, "err": 0, "auth": 0}
    by_taxon = {}
    for i, s in enumerate(species, 1):
        ktsn, t = s["k"], s.get("t")
        if ktsn in out:
            continue
        st["attempt"] += 1
        time.sleep(RATE_SLEEP)
        r = fetch(ktsn, key, url)
        if r.get("_err"):
            code = r.get("status")
            if code in (401, 403, 404):
                st["auth"] += 1
                print(f"[{i}/{len(species)}] {s['s']} ({ktsn}) 인증/승인 오류 status={code} errorCode={r.get('errorCode')}")
            else:
                st["err"] += 1
                print(f"[{i}/{len(species)}] {s['s']} ({ktsn}) 오류 status={code}")
            continue
        if r.get("status") != 200:
            st["err"] += 1
            continue
        content = (r.get("data") or {}).get("content") or []
        recs = []
        for it in content:
            rec = to_record(it)
            if rec and rec["full"] not in {x["full"] for x in recs}:
                recs.append(rec)
            if len(recs) >= MEDIA_PER_SPECIES:
                break
        if recs:
            out[ktsn] = recs
            st["with"] += 1
            by_taxon[t] = by_taxon.get(t, 0) + 1
            print(f"[{i}/{len(species)}] {s['s']} ({ktsn}) [{t}] 미디어 {len(recs)}")
        else:
            st["empty"] += 1
            print(f"[{i}/{len(species)}] {s['s']} ({ktsn}) [{t}] 미디어 없음")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"출력: {OUT}")
    print(f"시도 {st['attempt']} · 미디어확보 {st['with']} · 없음 {st['empty']} · 오류 {st['err']} · 인증오류 {st['auth']}")
    print(f"확보 종 분류군 분포: {by_taxon}")
    print(f"출력 총 종수: {len(out)}")
    if st["auth"]:
        print("\n인증/승인 오류 발생 — 키·IP·서비스 승인 상태 확인 필요(species.nibr.go.kr).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
