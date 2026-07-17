# -*- coding: utf-8 -*-
"""발견공백 MCP 도구 로직(순수 함수 — MCP 비의존, 단위 테스트 가능).

발견 정의(당해 기준): found=maxyear>=(refYear-window) · dormant=기록은 있으나 maxyear<cutoff · undiscovered=기록 없음.
지역 코드: 시도=2자리, 시군구=5자리(행정구역 코드).
"""
import datetime

from . import db

DISCOVERY_WINDOW = 10
_SP_COLS = ("ktsn,korean_name,scientific_name,taxon_group,taxon_group_kor,"
            "endangered_grade,national_redlist_category,has_media")


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


# ─────────────────────────── 도구 ───────────────────────────

def search_species(query, taxon_group=None, limit=10):
    """국명·학명으로 종을 검색한다. 부분일치(대소문자 무시)."""
    q = str(query).strip().lower()
    if not q:
        return []
    like = f"%{q}%"
    pref = f"{q}%"
    where = "(lower(korean_name) LIKE ? OR lower(scientific_name) LIKE ?)"
    params = [like, like]
    if taxon_group:
        where += " AND taxon_group=?"
        params.append(taxon_group)
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
    sp = db.one(f"SELECT {_SP_COLS},class_la,order_la,family_la,genus_la,rank FROM species WHERE ktsn=?", (ktsn,))
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


def _scope_total(taxon_group):
    if taxon_group:
        return db.one("SELECT COUNT(*) c FROM species WHERE taxon_group=?", (taxon_group,))["c"]
    return db.one("SELECT COUNT(*) c FROM species")["c"]


def find_gap_by_region(region, taxon_group=None, state="undiscovered", limit=50):
    """지역(시도 2자리·시군구 5자리)의 발견/휴면/미발견 종을 분류. summary + 요청 state 종목록(상한)."""
    col, code = _region_col(region)
    name, level = _region_name(code)
    cutoff = _cutoff()
    limit = max(1, min(int(limit), 500))

    tclause = " AND taxon_group=?" if taxon_group else ""
    tparam = [taxon_group] if taxon_group else []

    # 지역 내 종별 최신연도(시도면 시군구들 롤업)
    sub = (f"SELECT ktsn, MAX(maxyear) my, SUM(obs_count) oc FROM species_region "
           f"WHERE {col}=?{tclause} GROUP BY ktsn")
    recorded = db.rows(sub, [code] + tparam)
    found = sum(1 for r in recorded if r["my"] and r["my"] >= cutoff)
    dormant = len(recorded) - found
    total = _scope_total(taxon_group)
    undiscovered = total - len(recorded)

    summary = {"total": total, "found": found, "dormant": dormant,
               "undiscovered": undiscovered, "recorded": len(recorded)}

    state = (state or "undiscovered").lower()
    species = []
    truncated = False
    if state == "undiscovered":
        sql = (f"SELECT {_SP_COLS} FROM species s WHERE 1=1{(' AND taxon_group=?' if taxon_group else '')} "
               f"AND ktsn NOT IN (SELECT ktsn FROM species_region WHERE {col}=?) "
               "ORDER BY (endangered_grade!='') DESC, korean_name LIMIT ?")
        params = tparam + [code, limit + 1]
        species = db.rows(sql, params)
    else:  # found / dormant / recorded
        rec_map = {r["ktsn"]: r for r in recorded}
        want = [k for k, r in rec_map.items()
                if state == "recorded"
                or (state == "found" and r["my"] and r["my"] >= cutoff)
                or (state == "dormant" and not (r["my"] and r["my"] >= cutoff))]
        want = want[:limit + 1]
        if want:
            ph = ",".join("?" * len(want))
            sp = {r["ktsn"]: r for r in db.rows(f"SELECT {_SP_COLS} FROM species WHERE ktsn IN ({ph})", want)}
            for k in want:
                if k in sp:
                    r = dict(sp[k]); r["maxyear"] = rec_map[k]["my"]; r["obs_count"] = rec_map[k]["oc"]
                    r["discovery_state"] = _state(rec_map[k]["my"], cutoff)
                    species.append(r)
    if len(species) > limit:
        species = species[:limit]
        truncated = True
    for r in species:
        if "has_media" in r:
            r["has_media"] = bool(r["has_media"])
    return {"region": code, "region_name": name, "level": level,
            "taxon_group": taxon_group, "reference_year": _ref_year(), "discovery_cutoff": cutoff,
            "summary": summary, "state": state, "species": species, "truncated": truncated}


def region_comparison(regions, taxon_group=None):
    """여러 지역의 발견/휴면/미발견 요약을 나란히 비교."""
    if isinstance(regions, str):
        regions = [regions]
    cutoff = _cutoff()
    total = _scope_total(taxon_group)
    tclause = " AND taxon_group=?" if taxon_group else ""
    tparam = [taxon_group] if taxon_group else []
    out = []
    for region in regions:
        try:
            col, code = _region_col(region)
        except ValueError as e:
            out.append({"region": str(region), "error": str(e)})
            continue
        name, level = _region_name(code)
        rec = db.rows(f"SELECT ktsn, MAX(maxyear) my FROM species_region WHERE {col}=?{tclause} GROUP BY ktsn",
                      [code] + tparam)
        found = sum(1 for r in rec if r["my"] and r["my"] >= cutoff)
        out.append({"region": code, "region_name": name, "level": level,
                    "total": total, "found": found, "dormant": len(rec) - found,
                    "undiscovered": total - len(rec), "recorded": len(rec)})
    return {"taxon_group": taxon_group, "reference_year": _ref_year(),
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
    out = []
    for t, b in base.items():
        a = am.get(t, {"recorded": 0, "discovered": 0})
        rec, disc = a["recorded"], a["discovered"]
        out.append({"taxon_group": t, "taxon_group_kor": b["taxon_group_kor"],
                    "n_species": b["n_species"], "discovered": disc,
                    "dormant": rec - disc, "undiscovered": b["n_species"] - rec, "recorded": rec})
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
