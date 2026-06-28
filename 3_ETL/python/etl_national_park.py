# -*- coding: utf-8 -*-
"""
국립공원 생물자원현황 (2002-2024) → observation_nps.csv (시도 spatial join + obs_count 집계).
설계 근거: 개발계획_v1 §1.3/§1.4 (D2 확정).
- 입력: 1_Data/raw/national_park/national_park_2024.csv (CP949, M/D/YYYY 일자)
         + 국립공원_생물자원현황_YYYY (NNNNN).zip × 22개 (2002-2023, CP949, YYYY-MM-DD 일자)
- 매칭: 종명(학명) → managed_key → ktsn. 미스 시 분류명(국명) 폴백.
- 시도: lon,lat EPSG:4326 → BND_SIDO_PG point-in-polygon → sido. 폴리곤 밖=미상.
- 연도: 조사일자 파싱 (M/D/YYYY 또는 YYYY-MM-DD).
- obs_count = COUNT(DISTINCT 좌표) per (ktsn, taxon_group, sido, year, source='nps').
- source = 'nps' (고정).
사용: python etl_national_park.py
출력: 1_Data/processed/observation_nps.csv + observation_nps_report.txt (+ 콘솔 리포트)
"""
import sys, csv, json, time, re, zipfile
from pathlib import Path
from collections import defaultdict, Counter
from taxon_key import managed_key
from name_overrides import load_overrides
from obs_common import load_master, resolve_ktsn, _kor, sido_lookup, write_points

BASE = Path(__file__).resolve().parents[2]
PROC = BASE / "1_Data" / "processed"
RAW_NP = BASE / "1_Data" / "raw" / "national_park"
OUT = PROC / "observation_nps.csv"
REPORT = PROC / "observation_nps_report.txt"


def parse_date(date_str):
    """조사일자 파싱: M/D/YYYY 또는 YYYY-MM-DD → 4자리 연도 추출."""
    if not date_str:
        return ""
    date_str = date_str.strip()
    # YYYY-MM-DD 형식
    m = re.match(r"(\d{4})-\d{2}-\d{2}", date_str)
    if m:
        return m.group(1)
    # M/D/YYYY 형식
    m = re.search(r"(\d{4})", date_str)  # 4자리 숫자 찾기
    if m:
        return m.group(1)
    return ""


def read_ndjson_file(fpath, encoding="utf-8-sig"):
    """한 줄 JSON 파일 읽기."""
    rows = []
    try:
        with fpath.open(encoding=encoding, errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    t0 = time.time()

    # 1) 마스터 로드 + 보정 매핑(override) 로드
    sci, kor, ktsn_tx = load_master()
    ov_sci, ov_kor = load_overrides()
    print(f"마스터 로드: 학명키 {len(sci):,} · 국명 {len(kor):,} · ktsn {len(ktsn_tx):,} | "
          f"보정매핑 학명 {len(ov_sci)} · 국명 {len(ov_kor)}  ({time.time()-t0:.1f}s)")

    # 2) 데이터 읽기 + 매칭
    t1 = time.time()
    obs = []  # (ktsn, taxon_group, year, lon, lat)  — sido는 2단계 후 채움
    n_all = n_override = n_both = n_sci = n_kor = n_conflict = 0
    unmatched = Counter()          # (종명, 분류명) → 폐기 건수(충돌+미매칭)
    unmatched_bunryu = {}          # (종명, 분류명) → 생물분류(원천 힌트)
    unmatched_reason = {}          # (종명, 분류명) → '충돌' | '미매칭'
    conflict_pair = {}             # (종명, 분류명) → (학명해석ktsn, 국명해석ktsn)

    # 2.1) national_park_2024.csv (CP949)
    npy_2024 = RAW_NP / "national_park_2024.csv"
    if npy_2024.exists():
        for r in csv.DictReader(npy_2024.open(encoding="cp949", errors="replace")):
            n_all += 1
            sciname = (r.get("종명") or "").strip()
            kor_name = (r.get("분류명") or "").strip()
            year = parse_date(r.get("조사일자") or "")

            try:
                lon = float((r.get("경도") or "").strip()) if (r.get("경도") or "").strip() else None
                lat = float((r.get("위도") or "").strip()) if (r.get("위도") or "").strip() else None
            except (ValueError, AttributeError):
                lon, lat = None, None

            # 매칭(보정 매핑 우선 → 학명·국명 충돌 판정 — 확정불가 폐기)
            ktsn, how = resolve_ktsn(sci, kor, sciname, kor_name, ov_sci, ov_kor)
            if how == "override":
                n_override += 1
            elif how == "both":
                n_both += 1
            elif how == "sci":
                n_sci += 1
            elif how == "kor":
                n_kor += 1
            else:                                   # conflict | none → 폐기
                key = (sciname, kor_name)
                unmatched[key] += 1
                unmatched_bunryu.setdefault(key, (r.get("생물분류") or "").strip())
                if how == "conflict":
                    n_conflict += 1
                    unmatched_reason[key] = "충돌"
                    conflict_pair.setdefault(key, (sci.get(managed_key(sciname)), kor.get(_kor(kor_name))))
                else:
                    unmatched_reason.setdefault(key, "미매칭")
                continue

            obs.append([ktsn, ktsn_tx.get(ktsn, ""), year, lon, lat])

    # 2.2) 국립공원_생물자원현황_YYYY.zip (2002-2023, CP949, YYYY-MM-DD 일자)
    for zpath in sorted(RAW_NP.glob("국립공원_생물자원현황_*.zip")):
        try:
            with zipfile.ZipFile(zpath) as z:
                # CSV 파일명 찾기
                csv_names = [n for n in z.namelist() if n.endswith(".csv")]
                if not csv_names:
                    continue
                csv_name = csv_names[0]

                with z.open(csv_name) as f:
                    import io
                    text = io.TextIOWrapper(f, encoding="cp949", errors="replace")
                    for r in csv.DictReader(text):
                        n_all += 1
                        sciname = (r.get("종명") or "").strip()
                        kor_name = (r.get("분류명") or "").strip()
                        year = parse_date(r.get("조사일자") or "")

                        try:
                            lon = float((r.get("경도") or "").strip()) if (r.get("경도") or "").strip() else None
                            lat = float((r.get("위도") or "").strip()) if (r.get("위도") or "").strip() else None
                        except (ValueError, AttributeError):
                            lon, lat = None, None

                        # 매칭(보정 매핑 우선 → 학명·국명 충돌 판정 — 확정불가 폐기)
                        ktsn, how = resolve_ktsn(sci, kor, sciname, kor_name, ov_sci, ov_kor)
                        if how == "override":
                            n_override += 1
                        elif how == "both":
                            n_both += 1
                        elif how == "sci":
                            n_sci += 1
                        elif how == "kor":
                            n_kor += 1
                        else:                                   # conflict | none → 폐기
                            key = (sciname, kor_name)
                            unmatched[key] += 1
                            unmatched_bunryu.setdefault(key, (r.get("생물분류") or "").strip())
                            if how == "conflict":
                                n_conflict += 1
                                unmatched_reason[key] = "충돌"
                                conflict_pair.setdefault(key, (sci.get(managed_key(sciname)), kor.get(_kor(kor_name))))
                            else:
                                unmatched_reason.setdefault(key, "미매칭")
                            continue

                        obs.append([ktsn, ktsn_tx.get(ktsn, ""), year, lon, lat])
        except Exception as e:
            print(f"경고: {zpath.name} 읽기 실패 — {e}", file=sys.stderr)

    n_match = n_override + n_both + n_sci + n_kor
    n_discard = n_all - n_match
    print(f"매칭: 총 {n_all:,} | 매칭 {n_match:,} ({n_match/n_all*100:.1f}%) "
          f"[보정 {n_override:,} · 일치 {n_both:,} · 학명단독 {n_sci:,} · 국명단독 {n_kor:,}] | "
          f"폐기 {n_discard:,} (충돌 {n_conflict:,} · 미매칭 {n_discard-n_conflict:,})  ({time.time()-t1:.1f}s)")

    # 3) 시도 spatial join (고유 좌표만)
    t2 = time.time()
    uniq = sorted({(o[3], o[4]) for o in obs if o[3] is not None})
    n_coords = len(uniq)
    coord_sido = sido_lookup(uniq)
    n_unknown = sum(1 for v in coord_sido.values() if v == "미상")
    print(f"시도조인: 고유좌표 {n_coords:,} | 시도밖(미상) {n_unknown:,}  ({time.time()-t2:.1f}s)")

    # 4) 집계: obs_count = COUNT(DISTINCT 좌표) per (ktsn, taxon_group, sido, year, source='nps')
    t3 = time.time()
    grp = defaultdict(set)
    for ktsn, tx, year, lon, lat in obs:
        sd = coord_sido.get((lon, lat), "미상") if lon is not None else "미상"
        grp[(ktsn, tx, sd, year, "nps")].add((lon, lat))
    rows = [{"ktsn": k, "taxon_group": tx, "sido": s, "year": y, "source": sr, "obs_count": len(p)}
            for (k, tx, s, y, sr), p in grp.items()]
    rows.sort(key=lambda r: (r["taxon_group"], r["sido"], r["year"], -r["obs_count"]))

    PROC.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ktsn", "taxon_group", "sido", "year", "source", "obs_count"])
        w.writeheader()
        w.writerows(rows)
    print(f"집계: observation_nps 행 {len(rows):,}  ({time.time()-t3:.1f}s) → {OUT.name}")

    # 좌표 보존 점 단위 기본 DB(파생: 위 시도 집계와 카운트 일치) — bioclim 등 점 기반 분석용
    npt = write_points(PROC / "observation_points_nps.csv", grp)
    print(f"점 DB: observation_points_nps.csv 행 {npt:,}")

    # 5) 리포트 생성
    yr_list = sorted({r["year"] for r in rows if r["year"]})
    sido_list = sorted({r["sido"] for r in rows})
    tx_stats = {}
    for tx in sorted({r["taxon_group"] for r in rows}):
        sp = len({r["ktsn"] for r in rows if r["taxon_group"] == tx})
        tx_stats[tx] = sp

    report_lines = [
        "=" * 70,
        "국립공원 생물자원현황 ETL 리포트",
        "=" * 70,
        f"생성일시: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "▪ 입력 통계",
        f"  총 기록: {n_all:,}",
        f"  매칭됨: {n_match:,} ({n_match/n_all*100:.1f}%) [보정 {n_override:,} · 일치 {n_both:,} · 학명단독 {n_sci:,} · 국명단독 {n_kor:,}]",
        f"  폐기: {n_discard:,} (충돌 {n_conflict:,} · 미매칭 {n_discard-n_conflict:,})",
        "",
        "▪ 출력 통계",
        f"  총 행: {len(rows):,}",
        f"  고유 좌표: {n_coords:,}",
        f"  시도 외 좌표(미상): {n_unknown:,} ({n_unknown/n_coords*100:.1f}%)" if n_coords > 0 else "  고유 좌표: 0",
        "",
        "▪ 분류군별 종 수",
    ]
    for tx in sorted(tx_stats.keys()):
        report_lines.append(f"  [{tx}] {tx_stats[tx]:,} 종")

    report_lines.extend([
        "",
        "▪ 시도 커버리지",
        f"  총 시도: {len(sido_list)}",
    ])
    for sd in sido_list:
        report_lines.append(f"    - {sd}")

    report_lines.extend([
        "",
        "▪ 연도 범위",
    ])
    if yr_list:
        report_lines.append(f"  {yr_list[0]} ~ {yr_list[-1]} ({len(yr_list)} 연도)")
        # 연도별 행 수
        yr_counts = {}
        for r in rows:
            yr = r["year"]
            yr_counts[yr] = yr_counts.get(yr, 0) + 1
        for yr in sorted(yr_counts.keys()):
            report_lines.append(f"    {yr}: {yr_counts[yr]:,} 행")
    else:
        report_lines.append("  (데이터 없음)")

    # 폐기 종목록 별도 CSV 저장(사용자 검토용) — 사유(충돌/미매칭) + 충돌 시 두 해석 ktsn
    UNMATCHED_CSV = PROC / "observation_nps_unmatched.csv"
    with UNMATCHED_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["종명", "분류명_국명", "생물분류", "사유", "학명해석_ktsn", "국명해석_ktsn", "폐기_건수"])
        for (sci_, kn_), cnt in unmatched.most_common():
            reason = unmatched_reason.get((sci_, kn_), "미매칭")
            ks, kk = conflict_pair.get((sci_, kn_), ("", ""))
            w.writerow([sci_, kn_, unmatched_bunryu.get((sci_, kn_), ""), reason, ks or "", kk or "", cnt])
    n_conf_uniq = sum(1 for k in unmatched if unmatched_reason.get(k) == "충돌")
    print(f"폐기 종목록 저장: {UNMATCHED_CSV.name} (고유 {len(unmatched):,}건 · 충돌 {n_conf_uniq:,} · 미매칭 {len(unmatched)-n_conf_uniq:,})")

    if unmatched:
        report_lines.extend([
            "",
            f"▪ 폐기 고유 {len(unmatched):,}건 (충돌 {n_conf_uniq:,} · 미매칭 {len(unmatched)-n_conf_uniq:,}; 전체: {UNMATCHED_CSV.name}) — top 10",
        ])
        for (sci_, kn_), cnt in unmatched.most_common(10):
            tag = unmatched_reason.get((sci_, kn_), "미매칭")
            report_lines.append(f"  [{tag}] {cnt:,}x {sci_ or kn_ or '(빈값)'}")

    report_lines.extend([
        "",
        "▪ 실행 시간",
        f"  총 소요: {time.time()-t0:.1f}s",
        "=" * 70,
    ])

    report_text = "\n".join(report_lines)
    print(report_text)

    # 파일로 저장
    with REPORT.open("w", encoding="utf-8-sig") as f:
        f.write(report_text)
    print(f"\n리포트 저장: {REPORT.name}")


if __name__ == "__main__":
    main()
