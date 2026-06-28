# -*- coding: utf-8 -*-
# bioclim_points.R — 관측 점 좌표에서 WorldClim 계열 bio01~19 점 추출 → 종별 분포 통계(박스플롯용)
# 입력 : 1_Data/processed/observations.sqlite (obs_points: ktsn,taxon_group,source,year,sido,lon,lat)
#        D:/Google_Drive/Paper/Lucanidae/Data/Zonal/bioclim/bio01..19.tif  (EPSG:5186, 30m)
# 출력 : 1_Data/processed/species_bioclim.csv  (ktsn, taxon_group, bio, n, min, q1, median, q3, max, mean)
# 방법 : 고유 좌표 1회 추출(성능) → 관측을 좌표 id로 매핑 → 종별 5수치 요약 + 평균. 좌표 4326 → 5186 투영.
# 표시 방식(박스플롯 등)은 별도 — 여기서는 데이터만 산출.
# 실행 : Rscript 3_ETL/R/bioclim_points.R

suppressMessages({library(terra); library(DBI); library(RSQLite)})

BASE <- "D:/Google_Drive/Finding gap"
PROC <- file.path(BASE, "1_Data", "processed")
BIO  <- "D:/Google_Drive/Paper/Lucanidae/Data/Zonal/bioclim"
DBF  <- file.path(PROC, "observations.sqlite")
OUT  <- file.path(PROC, "species_bioclim.csv")
bios <- sprintf("bio%02d", 1:19)

t0 <- Sys.time()
mins <- function() as.numeric(difftime(Sys.time(), t0, units = "mins"))

# 1) 점 DB에서 좌표 보유 관측 읽기
con <- dbConnect(SQLite(), DBF)
pts <- dbGetQuery(con, "SELECT ktsn, taxon_group, lon, lat FROM obs_points
                        WHERE lon IS NOT NULL AND lat IS NOT NULL")
dbDisconnect(con)
cat(sprintf("관측 점(좌표보유) %s 행 · 종 %s\n",
            format(nrow(pts), big.mark = ","), format(length(unique(pts$ktsn)), big.mark = ",")))

# 2) 고유 좌표 → 추출 1회
key   <- paste0(pts$lon, "_", pts$lat)
uc    <- pts[!duplicated(key), c("lon", "lat")]
ucKey <- paste0(uc$lon, "_", uc$lat)
pts$cid <- match(key, ucKey)
cat(sprintf("고유 좌표 %s\n", format(nrow(uc), big.mark = ",")))

# 3) bio01~19 스택(지연; 메모리 적재 안 함) + 점 4326 → 래스터 CRS(5186) 투영 후 추출
rs <- rast(file.path(BIO, paste0(bios, ".tif"))); names(rs) <- bios
v  <- project(vect(uc, geom = c("lon", "lat"), crs = "EPSG:4326"), crs(rs))
ex <- terra::extract(rs, v, ID = FALSE)            # nrow(uc) × 19
cat(sprintf("추출 %s × %d  (%.1f분)\n", format(nrow(ex), big.mark = ","), ncol(ex), mins()))

# 4) 종별 × bio 5수치 요약(min·Q1·median·Q3·max) + mean + n
tx_of <- tapply(pts$taxon_group, pts$ktsn, function(z) z[1])
rows  <- vector("list", 0L)
for (b in bios) {
  pv  <- ex[[b]][pts$cid]                          # 관측별 bio 값(좌표 id로 매핑)
  agg <- tapply(pv, pts$ktsn, function(x) {
    x <- x[is.finite(x)]
    if (!length(x)) return(NULL)
    q <- as.numeric(quantile(x, c(0, .25, .5, .75, 1), names = FALSE))
    c(n = length(x), min = q[1], q1 = q[2], median = q[3], q3 = q[4], max = q[5], mean = mean(x))
  })
  keep <- !vapply(agg, is.null, logical(1))
  for (k in names(agg)[keep]) {
    a <- agg[[k]]
    rows[[length(rows) + 1L]] <- data.frame(
      ktsn = k, taxon_group = tx_of[[k]], bio = b,
      n = a[["n"]], min = a[["min"]], q1 = a[["q1"]], median = a[["median"]],
      q3 = a[["q3"]], max = a[["max"]], mean = a[["mean"]], stringsAsFactors = FALSE)
  }
  cat(sprintf("  %s 집계 종 %s\n", b, format(sum(keep), big.mark = ",")))
}
out <- do.call(rbind, rows)
num <- c("min", "q1", "median", "q3", "max", "mean")
out[num] <- round(out[num], 3)
write.csv(out, OUT, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("저장 %s — 종×bio %s행  (%.1f분)\n", basename(OUT), format(nrow(out), big.mark = ","), mins()))
