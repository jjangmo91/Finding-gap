# -*- coding: utf-8 -*-
"""발견공백 MCP 도구 로직(순수 함수 — MCP 비의존, 단위 테스트 가능).

발견 정의(당해 기준): found=maxyear>=(refYear-window) · dormant=기록은 있으나 maxyear<cutoff · undiscovered=기록 없음.
지역 코드: 시도=2자리, 시군구=5자리(행정구역 코드).
"""
import datetime

from . import db

DISCOVERY_WINDOW = 10
_SP_COLS = ("ktsn,korean_name,scientific_name,taxon_group,taxon_group_kor,"
            "endangered_grade,national_redlist_category,has_media,interest")


def _ref_year():
    return datetime.date.today().year


def _cutoff(window=DISCOVERY_WINDOW):
    return _ref_year() - int(window)


def _state(maxyear, cutoff):
    if not maxyear:
        return "undiscovered"
    return "found" if maxyear >= cutoff else "dormant"


def _region_col(region):
    region = str(region).strip()
    if len(region) == 2:
        return "sido", region
    if len(region) == 5:
        return "region", region
    raise ValueError(f"지역 코드는 시도(2자리) 또는 시군구(5자리)여야 합니다: '{region}'. find_region 으로 코드를 찾으세요.")


def _region_name(code):
    r = db.one("SELECT name,level FROM region WHERE code=? LIMIT 1", (str(code),))
    return (r["name"], r["level"]) if r else (None, "sido" if len(str(code)) == 2 else "sigungu")


# ── 멸종위기·적색목록 필터 ──
_THREAT_REDLIST = ("CR", "EN", "VU", "NT")     # 위협 범주(멸종위기 후보) — 보호종 기본 필터에 사용


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [x for x in (p.strip() for p in v.replace(";", ",").split(",")) if x]
    return [str(x).strip() for x in v if str(x).strip()]


def _norm_grade(v):
    """멸종위기 등급 정규화 → ['I','II']. '1'/'2'/'1급'/'II급' 등 허용."""
    out = []
    for x in _as_list(v):
        x = x.upper().replace("급", "").strip()
        out.append({"1": "I", "2": "II"}.get(x, x))
    return out


def _norm_redlist(v):
    """국가적색목록 범주 정규화 → ['CR','EN',...] (대문자)."""
    return [x.upper() for x in _as_list(v)]


def _species_where(taxon_group=None, endangered_grade=None, redlist_category=None, pfx="", protected=False):
    """species 테이블 필터 절(taxon·등급·적색목록). pfx='s.' 조인 시. protected=True면 등급/범주 미지정 시 위협종 기본."""
    clause, params = "", []
    if taxon_group:
        clause += f" AND {pfx}taxon_group=?"
        params.append(taxon_group)
    g = _norm_grade(endangered_grade)
    if g:
        clause += f" AND {pfx}endangered_grade IN ({','.join('?' * len(g))})"
        params += g
    r = _norm_redlist(redlist_category)
    if r:
        clause += f" AND {pfx}national_redlist_category IN ({','.join('?' * len(r))})"
        params += r
    if protected and not g and not r:
        clause += (f" AND ({pfx}endangered_grade!='' OR {pfx}national_redlist_category "
                   f"IN ({','.join('?' * len(_THREAT_REDLIST))}))")
        params += list(_THREAT_REDLIST)
    return clause, params


def _region_gap(col, code, name, level, sw, swp, state, limit, cutoff):
    """지역×종필터(sw/swp) 발견 분류 공용 로직 — find_gap_by_region·list_protected_species 공유."""
    recorded = db.rows(
        "SELECT sr.ktsn, MAX(sr.maxyear) my, SUM(sr.obs_count) oc "
        "FROM species_region sr JOIN species s ON s.ktsn=sr.ktsn "
        f"WHERE sr.{col}=?{sw} GROUP BY sr.ktsn", [code] + swp)
    found = sum(1 for r in recorded if r["my"] and r["my"] >= cutoff)
    dormant = len(recorded) - found
    total = db.one(f"SELECT COUNT(*) c FROM species s WHERE 1=1{sw}", swp)["c"]
    summary = {"total": total, "found": found, "dormant": dormant,
               "undiscovered": total - len(recorded), "recorded": len(recorded)}
    state = (state or "undiscovered").lower()
    species, truncated = [], False
    if state == "undiscovered":
        species = db.rows(
            f"SELECT {_SP_COLS} FROM species s WHERE 1=1{sw} "
            f"AND s.ktsn NOT IN (SELECT ktsn FROM species_region WHERE {col}=?) "
            "ORDER BY (s.endangered_grade!='') DESC, s.korean_name LIMIT ?",
            swp + [code, limit + 1])
    else:
        rec_map = {r["ktsn"]: r for r in recorded}
        want = [k for k, r in rec_map.items()
                if state == "recorded"
                or (state == "found" and r["my"] and r["my"] >= cutoff)
                or (state == "dormant" and not (r["my"] and r["my"] >= cutoff))][:limit + 1]
        if want:
            ph = ",".join("?" * len(want))
            spmap = {r["ktsn"]: r for r in db.rows(f"SELECT {_SP_COLS} FROM species WHERE ktsn IN ({ph})", want)}
            for k in want:
                if k in spmap:
                    r = dict(spmap[k]); r["maxyear"] = rec_map[k]["my"]; r["obs_count"] = rec_map[k]["oc"]
                    r["discovery_state"] = _state(rec_map[k]["my"], cutoff)
                    species.append(r)
    if len(species) > limit:
        species, truncated = species[:limit], True
    for r in species:
        if "has_media" in r:
            r["has_media"] = bool(r["has_media"])
    return {"region": code, "region_name": name, "level": level,
            "reference_year": _ref_year(), "discovery_cutoff": cutoff,
            "summary": summary, "state": state, "species": species, "truncated": truncated}


# ─────────────────────────── 도구 ───────────────────────────

def search_species(query, taxon_group=None, limit=10, endangered_grade=None, redlist_category=None):
    """국명·학명으로 종을 검색한다. 부분일치(대소문자 무시). endangered_grade(I/II)·redlist_category(CR/EN/VU/NT/LC/DD/NA) 필터 가능."""
    q = str(query).strip().lower()
    if not q:
        return []
    like = f"%{q}%"
    pref = f"{q}%"
    where = "(lower(korean_name) LIKE ? OR lower(scientific_name) LIKE ?)"
    params = [like, like]
    sw, swp = _species_where(taxon_group, endangered_grade, redlist_category)
    where += sw
    params += swp
    limit = max(1, min(int(limit), 100))
    sql = (f"SELECT {_SP_COLS} FROM species WHERE {where} "
           "ORDER BY CASE WHEN lower(korean_name) LIKE ? THEN 0 "
           "WHEN lower(scientific_name) LIKE ? THEN 1 ELSE 2 END, length(korean_name) "
           "LIMIT ?")
    params += [pref, pref, limit]
    out = db.rows(sql, params)
    for r in out:
        r["has_media"] = bool(r["has_media"])
    return out


def get_species(ktsn):
    """종 상세 — 마스터 정보 + 전국 발견 상태 요약 + 환경/미디어 가용성."""
    ktsn = str(ktsn).strip()
    sp = db.one(f"SELECT {_SP_COLS},interest_occ,interest_wiki,interest_user,stratum_n,interest_fallback,"
                "class_la,order_la,family_la,genus_la,rank FROM species WHERE ktsn=?", (ktsn,))
    if not sp:
        return {"error": f"종을 찾을 수 없습니다: ktsn={ktsn}"}
    sp["has_media"] = bool(sp["has_media"])
    cutoff = _cutoff()
    agg = db.one(
        "SELECT COUNT(*) n_regions, MAX(maxyear) maxyear, SUM(obs_count) obs_count, "
        "SUM(CASE WHEN maxyear>=? THEN 1 ELSE 0 END) found_regions "
        "FROM species_region WHERE ktsn=?", (cutoff, ktsn))
    n_env = db.one("SELECT COUNT(*) c FROM species_env WHERE ktsn=?", (ktsn,))["c"]
    n_media = db.one("SELECT COUNT(*) c FROM media WHERE ktsn=?", (ktsn,))["c"]
    maxyear = agg["maxyear"] if agg else None
    sp["reference_year"] = _ref_year()
    sp["discovery_cutoff"] = cutoff
    sp["national_discovery_state"] = _state(maxyear, cutoff)
    sp["national_max_year"] = maxyear
    sp["recorded_regions"] = agg["n_regions"] if agg else 0
    sp["found_regions"] = agg["found_regions"] if agg else 0
    sp["total_observations"] = agg["obs_count"] if agg else 0
    sp["env_vars_available"] = n_env
    sp["media_count"] = n_media
    return sp


def find_gap_by_region(region, taxon_group=None, state="undiscovered", limit=50,
                       endangered_grade=None, redlist_category=None):
    """지역(시도 2자리·시군구 5자리)의 발견/휴면/미발견 종을 분류. summary + 요청 state 종목록(상한). endangered_grade·redlist_category 필터 가능."""
    col, code = _region_col(region)
    name, level = _region_name(code)
    cutoff = _cutoff()
    limit = max(1, min(int(limit), 500))
    sw, swp = _species_where(taxon_group, endangered_grade, redlist_category, pfx="s.")
    out = _region_gap(col, code, name, level, sw, swp, state, limit, cutoff)
    out["taxon_group"] = taxon_group
    if endangered_grade or redlist_category:
        out["filter"] = {"endangered_grade": endangered_grade, "redlist_category": redlist_category}
    return out


def list_protected_species(region=None, endangered_grade=None, redlist_category=None, state=None, limit=50):
    """멸종위기종·국가적색목록 종 목록. 등급/범주 미지정 시 위협종(멸종위기 I/II 또는 적색목록 CR/EN/VU/NT) 기본.
    region 지정 시 해당 지역의 발견/휴면/미발견(state) 분류 — 예: 종로구 미발견 멸종위기 I급."""
    cutoff = _cutoff()
    limit = max(1, min(int(limit), 500))
    is_default = not (_norm_grade(endangered_grade) or _norm_redlist(redlist_category))
    if region:
        col, code = _region_col(region)
        name, level = _region_name(code)
        sw, swp = _species_where(None, endangered_grade, redlist_category, pfx="s.", protected=True)
        out = _region_gap(col, code, name, level, sw, swp, state or "undiscovered", limit, cutoff)
        out["filter"] = {"endangered_grade": endangered_grade, "redlist_category": redlist_category,
                         "protected_default": is_default}
        return out
    sw, swp = _species_where(None, endangered_grade, redlist_category, protected=True)
    total = db.one(f"SELECT COUNT(*) c FROM species WHERE 1=1{sw}", swp)["c"]
    species = db.rows(
        f"SELECT {_SP_COLS} FROM species WHERE 1=1{sw} "
        "ORDER BY (endangered_grade!='') DESC, national_redlist_category, korean_name LIMIT ?",
        swp + [limit + 1])
    truncated = len(species) > limit
    species = species[:limit]
    for r in species:
        r["has_media"] = bool(r["has_media"])
    return {"scope": "national", "count": total, "reference_year": _ref_year(),
            "filter": {"endangered_grade": endangered_grade, "redlist_category": redlist_category,
                       "protected_default": is_default},
            "species": species, "truncated": truncated}


def region_comparison(regions, taxon_group=None, redlist_category=None, endangered_grade=None):
    """여러 지역의 발견/휴면/미발견 요약을 나란히 비교. endangered_grade·redlist_category 필터 가능."""
    if isinstance(regions, str):
        regions = [regions]
    cutoff = _cutoff()
    sw, swp = _species_where(taxon_group, endangered_grade, redlist_category, pfx="s.")
    total = db.one(f"SELECT COUNT(*) c FROM species s WHERE 1=1{sw}", swp)["c"]
    out = []
    for region in regions:
        try:
            col, code = _region_col(region)
        except ValueError as e:
            out.append({"region": str(region), "error": str(e)})
            continue
        name, level = _region_name(code)
        rec = db.rows(
            "SELECT sr.ktsn, MAX(sr.maxyear) my FROM species_region sr JOIN species s ON s.ktsn=sr.ktsn "
            f"WHERE sr.{col}=?{sw} GROUP BY sr.ktsn", [code] + swp)
        found = sum(1 for r in rec if r["my"] and r["my"] >= cutoff)
        out.append({"region": code, "region_name": name, "level": level,
                    "total": total, "found": found, "dormant": len(rec) - found,
                    "undiscovered": total - len(rec), "recorded": len(rec)})
    return {"taxon_group": taxon_group, "redlist_category": redlist_category,
            "endangered_grade": endangered_grade, "reference_year": _ref_year(),
            "discovery_cutoff": cutoff, "regions": out}


def taxa_summary():
    """9개 분류군별 종수·전국 발견/휴면/미발견 요약."""
    cutoff = _cutoff()
    base = {r["taxon_group"]: dict(r) for r in
            db.rows("SELECT taxon_group,taxon_group_kor,n_species FROM taxa")}
    agg = db.rows(
        "SELECT taxon_group, COUNT(*) recorded, SUM(CASE WHEN my>=? THEN 1 ELSE 0 END) discovered FROM "
        "(SELECT taxon_group, ktsn, MAX(maxyear) my FROM species_region GROUP BY taxon_group, ktsn) "
        "GROUP BY taxon_group", (cutoff,))
    am = {r["taxon_group"]: r for r in agg}
    # 분류군별 위협종 수(멸종위기 I/II · 적색목록 CR/EN/VU/NT)
    prot = {r["taxon_group"]: r for r in db.rows(
        "SELECT taxon_group, "
        "SUM(CASE WHEN endangered_grade!='' THEN 1 ELSE 0 END) endangered, "
        "SUM(CASE WHEN national_redlist_category IN ('CR','EN','VU','NT') THEN 1 ELSE 0 END) redlist_threatened "
        "FROM species GROUP BY taxon_group")}
    out = []
    for t, b in base.items():
        a = am.get(t, {"recorded": 0, "discovered": 0})
        rec, disc = a["recorded"], a["discovered"]
        p = prot.get(t, {"endangered": 0, "redlist_threatened": 0})
        out.append({"taxon_group": t, "taxon_group_kor": b["taxon_group_kor"],
                    "n_species": b["n_species"], "discovered": disc,
                    "dormant": rec - disc, "undiscovered": b["n_species"] - rec, "recorded": rec,
                    "endangered": p["endangered"], "redlist_threatened": p["redlist_threatened"]})
    out.sort(key=lambda x: -x["n_species"])
    return {"reference_year": _ref_year(), "discovery_cutoff": cutoff, "taxa": out}


def get_species_bioclim(ktsn, variables=None):
    """종의 환경지위(기후 bio01/05/06/12 · 고도 dem · 식생 ndvi/ndwi) 통계."""
    ktsn = str(ktsn).strip()
    sp = db.one("SELECT ktsn,korean_name,scientific_name,taxon_group FROM species WHERE ktsn=?", (ktsn,))
    if not sp:
        return {"error": f"종을 찾을 수 없습니다: ktsn={ktsn}"}
    sql = "SELECT var,n,min,q1,median,q3,max,mean,sd FROM species_env WHERE ktsn=?"
    params = [ktsn]
    if variables:
        if isinstance(variables, str):
            variables = [v.strip() for v in variables.split(",")]
        variables = [v for v in variables if v and v.lower() != "all"]
        if variables:
            sql += f" AND var IN ({','.join('?' * len(variables))})"
            params += variables
    stats = db.rows(sql, params)
    return {**sp, "stats": stats, "note": "발견 기록 지점의 환경값 분포 — 실제 분포역과 다를 수 있음."}


def get_species_media(ktsn, media_type=None, limit=20):
    """종의 미디어 메타(사진·도판 URL·라이선스·출처). NIBR=KOGL, iNat=CC(비상업·귀속)."""
    ktsn = str(ktsn).strip()
    limit = max(1, min(int(limit), 100))
    sql = "SELECT src,type,license,attribution,thumb,full FROM media WHERE ktsn=?"
    params = [ktsn]
    if media_type and media_type.lower() != "all":
        sql += " AND type=?"
        params.append(media_type)
    sql += " LIMIT ?"
    params.append(limit)
    media = db.rows(sql, params)
    return {"ktsn": ktsn, "count": len(media), "media": media,
            "license_note": "비상업 용도. iNat 사진은 귀속(attribution) 표기 필수(CC-BY/-NC)."}


def get_interest(ktsn):
    """종의 관심도(Interest) 상세 — 층(분류군×적색목록등급) 내 백분위 신호와 층 내 순위.
    신호: P_occ(관측기록수)·P_wiki(한국어 위키백과 조회수)·P_user(관심종 watchlist).
    interest = 적용 신호의 가중평균(occ0.5/wiki0.2/user0.3, 결측 신호 몫은 재정규화). 점수엔 ko 조회수만(en=전세계는 참고). 문헌: conservation culturomics."""
    ktsn = str(ktsn).strip()
    sp = db.one(
        "SELECT ktsn,korean_name,scientific_name,taxon_group,taxon_group_kor,national_redlist_category,"
        "interest,interest_occ,interest_wiki,interest_user,wiki_ko,wiki_en,watch_count,stratum_n,interest_fallback "
        "FROM species WHERE ktsn=?", (ktsn,))
    if not sp:
        return {"error": f"종을 찾을 수 없습니다: ktsn={ktsn}"}
    sp["interest_fallback"] = bool(sp["interest_fallback"])
    sp["user_watch_count"] = sp.pop("watch_count")          # 관심종 익명 집계수(개인식별 불가)
    strat = sp["national_redlist_category"] or ""
    rk = db.one("SELECT COUNT(*) n, SUM(CASE WHEN interest>? THEN 1 ELSE 0 END) above "
                "FROM species WHERE taxon_group=? AND national_redlist_category=?",
                (sp["interest"], sp["taxon_group"], strat))
    m = db.meta()
    sp["stratum"] = {"taxon_group": sp["taxon_group"], "redlist_category": strat or "none",
                     "n": rk["n"], "rank": (rk["above"] or 0) + 1}
    sp["wiki_pageviews"] = {"ko_12mo": sp.pop("wiki_ko"), "global_en_12mo": sp.pop("wiki_en"), "scored": "ko"}
    sp["weights"] = m.get("interest_weights")
    sp["definition"] = m.get("interest_definition")
    sp["note"] = ("층 내 백분위(0~1). 신호↑=관심↑. 점수엔 한국어 위키(ko)만 반영, en(전세계)은 참고. "
                  "위키 문서 없는 종은 관측(occ)만으로, 사용자 관심종 미수집 시 그 몫은 재정규화.")
    return sp


def interest_ranking(taxon_group=None, redlist_category=None, level="species", limit=20):
    """관심도 순위. level='species'(종별 상위) 또는 'taxon'(분류군별 평균). taxon_group·redlist_category로 층 한정."""
    limit = max(1, min(int(limit), 200))
    sw, swp = _species_where(taxon_group, None, redlist_category)
    if str(level).lower() == "taxon":
        rows = db.rows(
            "SELECT taxon_group, taxon_group_kor, COUNT(*) n, "
            "ROUND(AVG(interest),4) mean_interest, ROUND(AVG(interest_occ),4) mean_occ, "
            "ROUND(AVG(CASE WHEN interest_wiki IS NOT NULL THEN interest_wiki END),4) mean_wiki "
            f"FROM species WHERE 1=1{sw} GROUP BY taxon_group ORDER BY mean_interest DESC", swp)
        return {"level": "taxon", "redlist_category": redlist_category, "taxa": rows}
    rows = db.rows(
        f"SELECT {_SP_COLS} FROM species WHERE 1=1{sw} ORDER BY interest DESC, korean_name LIMIT ?",
        swp + [limit])
    for r in rows:
        r["has_media"] = bool(r["has_media"])
    return {"level": "species", "taxon_group": taxon_group, "redlist_category": redlist_category,
            "count": len(rows), "species": rows}


def discovery_priorities(region, taxon_group=None, endangered_grade=None, redlist_category=None,
                         include_dormant=False, limit=20):
    """지역의 **미발견 종을 관심도(Interest) 높은 순**으로 — '아직 발견 안 됐지만 주목할 종'(발견공백×관심도).
    include_dormant=True면 휴면(오래전 기록)도 포함. endangered_grade(I/II)·redlist_category(CR/EN/…) 필터 가능."""
    col, code = _region_col(region)
    name, level = _region_name(code)
    cutoff = _cutoff()
    limit = max(1, min(int(limit), 200))
    sw, swp = _species_where(taxon_group, endangered_grade, redlist_category, pfx="s.")
    undis = db.rows(
        f"SELECT {_SP_COLS} FROM species s WHERE 1=1{sw} "
        f"AND s.ktsn NOT IN (SELECT ktsn FROM species_region WHERE {col}=?) "
        "ORDER BY s.interest DESC, s.korean_name LIMIT ?", swp + [code, limit])
    for r in undis:
        r["discovery_state"] = "undiscovered"
        r["has_media"] = bool(r["has_media"])
    species = undis
    if include_dormant:
        rec = db.rows(f"SELECT ktsn, MAX(maxyear) my FROM species_region WHERE {col}=? GROUP BY ktsn", (code,))
        dmap = {r["ktsn"]: r["my"] for r in rec}
        dormant_ktsn = [k for k, my in dmap.items() if not (my and my >= cutoff)]
        if dormant_ktsn:
            ph = ",".join("?" * len(dormant_ktsn))
            dorm = db.rows(f"SELECT {_SP_COLS} FROM species s WHERE 1=1{sw} AND s.ktsn IN ({ph}) "
                           "ORDER BY s.interest DESC, s.korean_name LIMIT ?", swp + dormant_ktsn + [limit])
            for r in dorm:
                r["discovery_state"] = "dormant"
                r["last_year"] = dmap.get(r["ktsn"])
                r["has_media"] = bool(r["has_media"])
            species = sorted(undis + dorm, key=lambda r: (-(r["interest"] or 0), r["korean_name"]))[:limit]
    # 요약(후보 총수·발견/휴면/미발견)
    total = db.one(f"SELECT COUNT(*) c FROM species s WHERE 1=1{sw}", swp)["c"]
    recq = db.rows("SELECT sr.ktsn, MAX(sr.maxyear) my FROM species_region sr JOIN species s ON s.ktsn=sr.ktsn "
                   f"WHERE sr.{col}=?{sw} GROUP BY sr.ktsn", [code] + swp)
    found = sum(1 for r in recq if r["my"] and r["my"] >= cutoff)
    return {"region": code, "region_name": name, "level": level, "reference_year": _ref_year(),
            "discovery_cutoff": cutoff, "include_dormant": bool(include_dormant),
            "summary": {"candidates": total, "found": found, "dormant": len(recq) - found,
                        "undiscovered": total - len(recq), "returned": len(species)},
            "filter": {"taxon_group": taxon_group, "endangered_grade": endangered_grade,
                       "redlist_category": redlist_category},
            "note": "관심도=관심 상위(주목). 미발견 우선순위 후보 — 실제 조사 계획엔 서식·계절 정보 별도 필요.",
            "species": species}


def region_profile(region, top=5):
    """지역 생물다양성 프로파일(한 번에) — 분류군별 발견/휴면/미발견 + 위협종 공백 + 미발견 주목종 Top."""
    col, code = _region_col(region)
    name, level = _region_name(code)
    cutoff = _cutoff()
    top = max(1, min(int(top), 50))
    taxa_total = {r["taxon_group"]: r for r in db.rows("SELECT taxon_group,taxon_group_kor,n_species FROM taxa")}
    rec = db.rows(
        "SELECT taxon_group, COUNT(*) recorded, SUM(CASE WHEN my>=? THEN 1 ELSE 0 END) found FROM "
        f"(SELECT taxon_group, ktsn, MAX(maxyear) my FROM species_region WHERE {col}=? GROUP BY taxon_group, ktsn) "
        "GROUP BY taxon_group", (cutoff, code))
    recmap = {r["taxon_group"]: r for r in rec}
    taxa = []
    for t, b in taxa_total.items():
        a = recmap.get(t, {"recorded": 0, "found": 0})
        taxa.append({"taxon_group": t, "taxon_group_kor": b["taxon_group_kor"], "n_species": b["n_species"],
                     "found": a["found"], "dormant": a["recorded"] - a["found"],
                     "undiscovered": b["n_species"] - a["recorded"], "recorded": a["recorded"]})
    taxa.sort(key=lambda x: -x["n_species"])
    protsw = " AND (s.endangered_grade!='' OR s.national_redlist_category IN ('CR','EN','VU','NT'))"
    prot_total = db.one(f"SELECT COUNT(*) c FROM species s WHERE 1=1{protsw}")["c"]
    prot_rec = db.one("SELECT COUNT(DISTINCT sr.ktsn) c FROM species_region sr JOIN species s ON s.ktsn=sr.ktsn "
                      f"WHERE sr.{col}=?{protsw}", (code,))["c"]
    top_species = db.rows(                                # 큐레이션 하이라이트 — 국명 없는 종(placeholder) 제외
        f"SELECT {_SP_COLS} FROM species s WHERE 1=1 AND s.korean_name NOT IN ('국명미정','') "
        f"AND s.ktsn NOT IN (SELECT ktsn FROM species_region WHERE {col}=?) "
        "ORDER BY s.interest DESC, s.korean_name LIMIT ?", (code, top))
    for r in top_species:
        r["has_media"] = bool(r["has_media"])
    totals = {"n_species": sum(t["n_species"] for t in taxa), "found": sum(t["found"] for t in taxa),
              "dormant": sum(t["dormant"] for t in taxa), "undiscovered": sum(t["undiscovered"] for t in taxa)}
    return {"region": code, "region_name": name, "level": level, "reference_year": _ref_year(),
            "discovery_cutoff": cutoff, "totals": totals, "taxa": taxa,
            "protected": {"total": prot_total, "recorded": prot_rec, "undiscovered": prot_total - prot_rec},
            "top_undiscovered_by_interest": top_species}


def trending_species(taxon_group=None, redlist_category=None, limit=20):
    """가장 많이 관심종으로 담긴 종(익명 집계) — 집단 사용자 관심(watchlist). watch_count>0만 반환하며,
    사용자 관심종 미수집 시 빈 목록. 개인정보 미포함(종별 집계수만). taxon_group·redlist_category 로 한정."""
    limit = max(1, min(int(limit), 200))
    sw, swp = _species_where(taxon_group, None, redlist_category)
    rows = db.rows(
        f"SELECT {_SP_COLS}, watch_count FROM species WHERE watch_count>0{sw} "
        "ORDER BY watch_count DESC, interest DESC, korean_name LIMIT ?", swp + [limit])
    for r in rows:
        r["has_media"] = bool(r["has_media"])
    agg = db.one("SELECT COUNT(*) n, COALESCE(SUM(watch_count),0) s FROM species WHERE watch_count>0")
    return {"level": "species", "taxon_group": taxon_group, "redlist_category": redlist_category,
            "watched_species": agg["n"], "total_marks": agg["s"], "count": len(rows),
            "note": ("관심종 익명 집계 기반(개인식별 불가)." if rows
                     else "사용자 관심종 미수집 — 빈 목록. Supabase RPC(species_watch_counts) 배포·집계 후 활성."),
            "species": rows}


def community_discoveries(region=None, taxon_group=None, limit=50):
    """관리자 승인된 시민 제보(시민 재발견·신규)의 익명 집계 — 종×시군구 제보수. 미승인·미검증 제보,
    정확 좌표·URL·개인정보는 미노출(시군구 단위 집계만). 승인 제보 없으면 빈 목록.
    region(시도 2자리/시군구 5자리)·taxon_group 로 한정."""
    limit = max(1, min(int(limit), 200))
    if not db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='community'"):
        return {"level": "community", "count": 0, "records": [],
                "note": "커뮤니티 제보 테이블 없음(데이터 재빌드 전) — 빈 목록."}
    where, params = "1=1", []
    if region:
        code = str(region).strip()
        where += " AND sido=?" if len(code) == 2 else " AND region=?"
        params.append(code)
    if taxon_group:
        tg = str(taxon_group).strip()
        where += " AND taxon_group=?"
        params.append(tg if tg == "-P" else tg.upper())
    rows = db.rows(
        "SELECT ktsn,korean_name,scientific_name,taxon_group,region,sido,region_name,count,last_year "
        f"FROM community WHERE {where} ORDER BY count DESC, last_year DESC, korean_name LIMIT ?", params + [limit])
    agg = db.one(f"SELECT COUNT(*) n, COALESCE(SUM(count),0) s FROM community WHERE {where}", params)
    return {"level": "community", "region": region, "taxon_group": taxon_group,
            "discoveries": agg["n"], "total_reports": agg["s"], "count": len(rows),
            "note": ("관리자 승인된 시민 제보 익명 집계(시군구 단위·개인정보 미포함)." if rows
                     else "승인된 시민 제보 없음 — 빈 목록. 제보·관리자 검토 축적 후 활성."),
            "records": rows}


def find_region(name=None, level=None):
    """행정구역 코드 찾기 — 이름으로 시도/시군구 코드 조회(다른 도구의 region 입력용)."""
    where = "1=1"
    params = []
    if name:
        where += " AND name LIKE ?"
        params.append(f"%{str(name).strip()}%")
    if level:
        where += " AND level=?"
        params.append(level)
    return {"regions": db.rows(f"SELECT code,name,level,sido_cd FROM region WHERE {where} ORDER BY level,code", params)}
