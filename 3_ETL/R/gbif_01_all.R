# ============================================================
# gbif_01_all.R  —  Finding gap GBIF 전 분류군 일괄 다운로드 자동화
#
# gbif_00_download.R(분류군 1개씩 수동 토글)를 9개 서비스 분류군 일괄로 자동화.
# class 미해석분(어류 -P, 파충류 RP 등)은 order(목) 폴백키로 보강한다.
#
# 사용:
#   Rscript gbif_01_all.R submit   # PHASE1: 분류군별 occ_download 제출+SUCCEEDED까지 대기(3동시 제한 큐), 키/DOI 저장
#   Rscript gbif_01_all.R import   # PHASE2: SUCCEEDED 키 → import → 품질필터 → gbif_<group>.csv
#
# 자격증명: ~/.Renviron 의 GBIF_USER/GBIF_PWD/GBIF_EMAIL (비대화형은 R_ENVIRON_USER 지정 필요)
# 출력: 1_Data/raw/gbif/gbif_<group>_key.txt, gbif_dois.csv, gbif_<group>.csv
#       4_References/gbif_order_keys.csv (없으면 생성)
# ============================================================

suppressPackageStartupMessages({
  library(rgbif); library(dplyr); library(stringr); library(readr); library(tidyr)
})

ARG <- commandArgs(trailingOnly = TRUE)
MODE <- if (length(ARG) >= 1) ARG[1] else "submit"
if (!MODE %in% c("submit", "import"))
  stop("MODE는 submit 또는 import")
cat(sprintf("=== gbif_01_all (mode=%s) ===\n\n", MODE))

# ── 경로/설정 ────────────────────────────────────────────────────────────────
BASE        <- "D:/Google_Drive/Finding gap"
MASTER      <- file.path(BASE, "1_Data/processed/ktsn_master.csv")
KEYS_CACHE  <- file.path(BASE, "4_References/gbif_class_keys.csv")
ORDER_CACHE <- file.path(BASE, "4_References/gbif_order_keys.csv")
GBIF_RAW    <- file.path(BASE, "1_Data/raw/gbif")
dir.create(GBIF_RAW, recursive = TRUE, showWarnings = FALSE)

# 서비스 9분류군(CC=마스터 0종, UC=서비스 제외 → 다운로드 대상 아님)
SERVICE_GROUPS <- c("MM", "AV", "RP", "AM", "-P", "IV", "IN", "VP", "MS")
TARGET_GROUPS  <- SERVICE_GROUPS          # 키 해석 대상
YEAR_MIN         <- 1900
COORD_UNCERT_MAX <- 5000
BAD_MATCH        <- c("NONE", "HIGHERRANK")

GBIF_USER  <- Sys.getenv("GBIF_USER")
GBIF_PWD   <- Sys.getenv("GBIF_PWD")
GBIF_EMAIL <- Sys.getenv("GBIF_EMAIL")

# ── 키 해석(class 캐시 + order 폴백 캐시) ───────────────────────────────────
class_keys <- read_csv(KEYS_CACHE, show_col_types = FALSE)

resolve_order_keys <- function() {
  if (file.exists(ORDER_CACHE)) {
    cat("orderKey 캐시 사용:", ORDER_CACHE, "\n"); return(read_csv(ORDER_CACHE, show_col_types = FALSE))
  }
  cols <- c("taxon_group","class_la","order_la","gbif_key","gbif_rank","gbif_match","gbif_canon")
  bad <- class_keys %>% filter(is.na(gbif_key) | gbif_match %in% BAD_MATCH) %>% distinct(taxon_group, class_la)
  if (nrow(bad) == 0) {
    write_csv(setNames(data.frame(matrix(ncol = length(cols), nrow = 0)), cols), ORDER_CACHE)
    return(read_csv(ORDER_CACHE, show_col_types = FALSE))
  }
  cat("미해석 class", nrow(bad), "건 → 하위 order(목) 학명 해석(name_backbone, rank=order)…\n")
  master <- read_csv(MASTER, show_col_types = FALSE)
  orders <- master %>%
    filter(taxon_group %in% TARGET_GROUPS, !is.na(order_la), order_la != "") %>%
    distinct(taxon_group, class_la, order_la) %>%
    semi_join(bad, by = c("taxon_group","class_la")) %>%
    arrange(taxon_group, class_la, order_la)
  resolved <- orders %>%
    rowwise() %>%
    mutate(bb = list(tryCatch(name_backbone(name = order_la, rank = "order", kingdom = NULL),
                              error = function(e) NULL))) %>%
    mutate(
      gbif_key   = ifelse(!is.null(bb) && !is.null(bb$usageKey),      bb$usageKey,      NA_integer_),
      gbif_rank  = ifelse(!is.null(bb) && !is.null(bb$rank),          bb$rank,          NA_character_),
      gbif_match = ifelse(!is.null(bb) && !is.null(bb$matchType),     bb$matchType,     "NONE"),
      gbif_canon = ifelse(!is.null(bb) && !is.null(bb$canonicalName), bb$canonicalName, NA_character_)
    ) %>% select(-bb) %>% ungroup()
  write_csv(resolved, ORDER_CACHE)
  cat("저장:", ORDER_CACHE, " (", nrow(resolved), "개 order)\n")
  resolved
}
order_keys <- resolve_order_keys()

group_taxon_keys <- function(group) {
  ck <- class_keys %>% filter(taxon_group == group, !is.na(gbif_key), !(gbif_match %in% BAD_MATCH)) %>% pull(gbif_key) %>% unique()
  ok <- order_keys %>% filter(taxon_group == group, !is.na(gbif_key), !(gbif_match %in% BAD_MATCH)) %>% pull(gbif_key) %>% unique()
  keys <- unique(c(ck, ok))
  if (length(keys) == 0) stop(sprintf("'%s' taxonKey 없음 — 캐시 확인", group))
  cat(sprintf("  taxonKey(%s): class %d + order(폴백) %d = 합 %d개\n", group, length(ck), length(ok), length(keys)))
  keys
}

keyfile_of <- function(g) file.path(GBIF_RAW, sprintf("gbif_%s_key.txt", g))

# ============================================================
# PHASE 1: 제출 + SUCCEEDED 대기 (3동시 제한은 occ_download_queue가 관리)
# ============================================================
if (MODE == "submit") {
  if (GBIF_USER == "" || GBIF_PWD == "" || GBIF_EMAIL == "")
    stop("GBIF 자격증명 미설정 — R_ENVIRON_USER로 .Renviron 지정 후 재실행")

  status_of <- function(g) {
    kf <- keyfile_of(g); if (!file.exists(kf)) return("MISSING")
    k <- trimws(readLines(kf, warn = FALSE)[1]); if (!nzchar(k)) return("MISSING")
    tryCatch(occ_download_meta(k)$status, error = function(e) "ERR")
  }
  # 이미 SUCCEEDED/진행중인 분류군은 재제출 생략(재개 가능)
  need <- Filter(function(g) !(status_of(g) %in% c("SUCCEEDED","RUNNING","PREPARING")), SERVICE_GROUPS)
  cat("제출 대상:", if (length(need)) paste(need, collapse=",") else "(없음 — 전부 준비됨/진행중)", "\n\n")

  if (length(need) > 0) {
    make_prep <- function(group) {
      keys <- group_taxon_keys(group)
      occ_download_prep(
        type = "and",
        pred("country", "KR"),
        pred_in("taxonKey", keys),
        pred("hasCoordinate", TRUE),
        pred("hasGeospatialIssue", FALSE),
        pred("occurrenceStatus", "PRESENT"),
        pred_not(pred_in("basisOfRecord", c("FOSSIL_SPECIMEN","LIVING_SPECIMEN","MATERIAL_CITATION"))),
        pred_gte("year", YEAR_MIN),
        user = GBIF_USER, pwd = GBIF_PWD, email = GBIF_EMAIL
      )
    }
    preps <- lapply(need, make_prep)
    cat("\nocc_download_queue 제출(최대 3동시)·SUCCEEDED까지 대기…\n")
    res <- occ_download_queue(.list = preps, status_ping = 60)
    # ⚠ occ_download_queue는 입력 .list 순서를 보장하지 않음 → 결과 키를 순서가 아니라
    #   그 다운로드의 taxonKey 집합으로 그룹에 역매핑(순서 기반 배정 시 라벨이 뒤섞임).
    want <- setNames(lapply(need, function(g) sort(unique(as.character(group_taxon_keys(g))))), need)
    extract_tkeys <- function(k) {
      pr <- tryCatch(occ_download_meta(k)$request$predicate, error = function(e) NULL)
      acc <- character(0)
      rec <- function(p) {
        if (is.list(p)) {
          ky <- p[["key"]]
          if (!is.null(ky) && toupper(ky) %in% c("TAXON_KEY", "TAXONKEY")) {
            v <- p[["values"]]; if (is.null(v)) v <- p[["value"]]
            acc <<- c(acc, as.character(unlist(v)))
          }
          for (e in p) if (is.list(e)) rec(e)
        }
      }
      rec(pr); sort(unique(acc))
    }
    for (i in seq_along(res)) {
      k <- as.character(res[[i]])
      tk <- extract_tkeys(k)
      g_match <- NULL
      for (g in need) if (length(tk) && identical(want[[g]], tk)) { g_match <- g; break }
      if (is.null(g_match)) { g_match <- need[i]; cat(sprintf("  ⚠ key=%s taxonKey 역매핑 실패 → 순서기준 %s\n", k, g_match)) }
      writeLines(k, keyfile_of(g_match))
      cat(sprintf("  %s → key=%s 저장\n", g_match, k))
    }
  }

  # 전 분류군 DOI/키 요약 저장
  rows <- lapply(SERVICE_GROUPS, function(g) {
    kf <- keyfile_of(g); if (!file.exists(kf)) return(NULL)
    k <- trimws(readLines(kf, warn = FALSE)[1]); if (!nzchar(k)) return(NULL)
    m <- tryCatch(occ_download_meta(k), error = function(e) NULL)
    data.frame(group = g, key = k,
               status = if (!is.null(m)) m$status else "ERR",
               totalRecords = if (!is.null(m)) m$totalRecords else NA_integer_,
               doi = if (!is.null(m)) m$doi else NA_character_,
               stringsAsFactors = FALSE)
  })
  summ <- bind_rows(rows)
  write_csv(summ, file.path(GBIF_RAW, "gbif_dois.csv"))
  cat("\n키/상태/DOI 요약:\n"); print(summ %>% select(group, status, totalRecords))
  cat("\n=== submit 단계 종료 — 전부 SUCCEEDED면 import 실행 ===\n")
}

# ============================================================
# PHASE 2: import → 품질필터 → gbif_<group>.csv
# ============================================================
if (MODE == "import") {
  import_one <- function(group) {
    kf <- keyfile_of(group)
    if (!file.exists(kf)) { cat(sprintf("[%s] 키 없음 — 건너뜀\n", group)); return(invisible(NULL)) }
    k <- trimws(readLines(kf, warn = FALSE)[1])
    m <- tryCatch(occ_download_meta(k), error = function(e) NULL)
    if (is.null(m) || m$status != "SUCCEEDED") {
      cat(sprintf("[%s] 상태 %s — 건너뜀\n", group, if (!is.null(m)) m$status else "ERR")); return(invisible(NULL))
    }
    out <- file.path(GBIF_RAW, sprintf("gbif_%s.csv", group))
    cat(sprintf("[%s] import (key=%s, %s건)…\n", group, k, m$totalRecords))
    # overwrite=FALSE: 이미 받은 zip 재사용(재다운로드 회피)
    raw <- occ_download_get(k, path = GBIF_RAW, overwrite = FALSE) %>% occ_download_import()
    n0 <- nrow(raw)
    # DWCA 버전에 따라 일부 컬럼 부재(예: publishingOrgKey) → NA로 보강해 transmute 안전화
    need_cols <- c("gbifID","species","scientificName","vernacularName","class","order","family","genus",
                   "year","eventDate","decimalLongitude","decimalLatitude","coordinateUncertaintyInMeters",
                   "basisOfRecord","datasetKey","publishingOrgKey","institutionCode","samplingProtocol")
    for (c in need_cols) if (!c %in% names(raw)) raw[[c]] <- NA
    clean <- raw %>%
      filter(!is.na(decimalLongitude), !is.na(decimalLatitude),
             !is.na(species), species != "",
             is.na(year) | (year >= YEAR_MIN),
             is.na(coordinateUncertaintyInMeters) | coordinateUncertaintyInMeters <= COORD_UNCERT_MAX) %>%
      transmute(gbifID, species, scientificName,
                vernacularName = coalesce(as.character(vernacularName), ""),
                class, order, family, genus, year, eventDate,
                decimalLongitude, decimalLatitude, coordinateUncertaintyInMeters,
                basisOfRecord, datasetKey, publishingOrgKey, institutionCode, samplingProtocol,
                taxon_group = group) %>%
      distinct(species, eventDate, decimalLongitude, decimalLatitude, .keep_all = TRUE)
    write_csv(clean, out)
    cat(sprintf("[%s] 저장 %s  (%d→%d, 종 %d)\n", group, out, n0, nrow(clean), n_distinct(clean$species)))
    rm(raw, clean); gc(verbose = FALSE)
  }
  for (g in SERVICE_GROUPS) tryCatch(import_one(g), error = function(e) cat(sprintf("[%s] 오류: %s\n", g, conditionMessage(e))))
  cat("\n=== import 단계 종료 ===\n")
}
