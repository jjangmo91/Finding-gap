# Changelog

Finding gap의 릴리스 단위 변경 이력입니다.
버전은 이 파일과 git 태그로만 관리하며, **웹페이지에는 노출하지 않습니다.**
형식은 [Keep a Changelog](https://keepachangelog.com/ko/), 버전 체계는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### 기능
- 발견 제보 근거: URL 입력 대신 **사진 업로드**를 1순위로 지원 — 선택한 사진의 EXIF GPS로 발견 위치 자동입력(없으면 지도 클릭), 업로드 전 클라이언트 압축(최대 1600px·JPEG q0.82). URL 입력은 "사진이 없다면" 폴백으로 유지.
- 사진은 Storage 버킷 `report-photos`(본인 폴더만 업로드/삭제, 읽기는 public)에 저장. `reports.url`은 선택 컬럼으로 변경, `photo_path` 컬럼 추가(둘 중 하나는 필수).

### 배포 전 확인
- `5_App/supabase/reports_photo.sql`을 Supabase SQL Editor에서 적용해야 사진 업로드가 동작함(`reports.sql` 적용 후).

### 수정
- 발견 제보 사진 입력에서 `capture="environment"` 제거 — 모바일에서 무조건 카메라만 뜨고 앨범(저장된 사진)을 고를 수 없던 문제. 속성을 빼면 브라우저가 카메라 촬영·앨범 선택을 모두 제공.

## [0.9.0] - 2026-07-02

최초 버전 기준선 — 현재 라이브 상태를 정리한 스냅숏.

### 기능
- 발견공백 조회: 국가생물종목록(KTSN, 서비스 대상 40,156종) − 3원 관측 union(EcoBank·국립공원·GBIF)의 실시간 여집합으로 미발견·빈발견·지역/연도별 발견 현황 계산.
- 대문 대시보드: 분류군별 발견/미발견 종수, 국가적색목록 현황 도넛.
- 종별 검색·상세: 발견 지역 표시, 한반도 생물다양성(NIBR)·시민 제보(Naturing/EcoBank) 링크.
- 지도: 시도 ⇄ 시군구 토글 choropleth + 환경변수 오버레이(연평균기온·최난월·최한월·연강수·해발고도).
- 종 페이지: 발견지점 기후·고도 지위 막대(전국 분포 대비).
- 로그인(이메일 매직링크 + Google OAuth)과 관심종 저장(Supabase, 행 수준 보안).

### 배포
- GitHub Pages(main `/docs`, OpenStreetMap 배경) 상시 게시.

[Unreleased]: https://github.com/RachHus/Finding-gap/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/RachHus/Finding-gap/releases/tag/v0.9.0
