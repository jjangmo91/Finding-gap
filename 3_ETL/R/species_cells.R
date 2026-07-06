# -*- coding: utf-8 -*-
# species_cells.R — 종별 1km 격자 점유 + 최종관측연도(신규후보/재발견후보 판정용)
# 산출 : 1_Data/processed/species_cells.csv  (ktsn, cid, maxyear)
#   cid     = agref(bio01 1km) 선형 셀 인덱스 = env_grid.csv 의 cid 와 동일(육지 셀만).
#   maxyear = 그 종이 그 셀에서 발견된 최종 연도(연도 미상=0 → 휴면 처리, species_state 관례와 동일).
# 방법 : bio01 을 env_layers.R §2 와 '동일하게' aggregate(fact=33) 해 agref 재구성 → cid 일치 보장.
#        obs_points 좌표를 agref CRS 로 투영 후 cellFromXY → 셀 매핑, (ktsn,cid)별 max(year).
# ⚠ 크래시 회피: NDVI/NDWI 등 대형 Sentinel 은 건드리지 않는다(bio01 read 만). 진행로그는
#   비-Drive(LOCALAPPDATA/fg_cache/species_cells_run.log) — Drive 폴더 잦은 쓰기 heap 크래시 회피.
# 실행 : Rscript -e "source('3_ETL/R/species_cells.R')"   (공백경로 직접실행은 exit 127)

suppressMessages({library(terra); library(DBI); library(RSQLite); library(data.table)})

BASE  <- "D:/Google_Drive/Finding gap"
PROC  <- file.path(BASE, "1_Data", "processed")
BIO   <- "D:/Google_Drive/Paper/Lucanidae/Data/Zonal/bioclim"
DBF   <- file.path(PROC, "observations.sqlite")
CACHE <- file.path(Sys.getenv("LOCALAPPDATA"), "fg_cache")
dir.create(CACHE, showWarnings = FALSE, recursive = TRUE)
LOG <- file.path(CACHE, "species_cells_run.log"); cat("", file = LOG)
lg  <- function(m){ con <- file(LOG, "a"); writeLines(sprintf("[%s] %s", format(Sys.time(),"%H:%M:%S"), m), con); close(con) }
t0  <- Sys.time(); mins <- function() as.numeric(difftime(Sys.time(), t0, units = "mins"))
lg("START")

# agref = bio01 1km (env_layers.R §2 와 동일 재구성 → env_grid.csv cid 와 일치)
agref <- aggregate(rast(file.path(BIO, "bio01.tif")), fact = 33, fun = "mean", na.rm = TRUE)
av <- values(agref, mat = FALSE)
lg(sprintf("agref %dx%d ncell=%d land=%d", nrow(agref), ncol(agref), ncell(agref), sum(is.finite(av))))
cat(sprintf("agref %dx%d · 육지셀 %s (%.1f분)\n", nrow(agref), ncol(agref),
            format(sum(is.finite(av)), big.mark = ","), mins()))

# obs_points 좌표 + 연도
con <- dbConnect(SQLite(), DBF)
pts <- dbGetQuery(con, "SELECT ktsn, year, lon, lat FROM obs_points
                        WHERE lon IS NOT NULL AND lat IS NOT NULL")
dbDisconnect(con)
lg(sprintf("pts %d", nrow(pts)))

# 고유좌표 → agref 셀 인덱스(cid). 4326 → agref CRS 투영 후 cellFromXY(고유좌표 1회).
key <- paste0(pts$lon, "_", pts$lat)
uc  <- pts[!duplicated(key), c("lon", "lat")]
uci <- match(key, paste0(uc$lon, "_", uc$lat))
ucv <- vect(uc, geom = c("lon", "lat"), crs = "EPSG:4326")
xy  <- crds(project(ucv, crs(agref)))
cid <- cellFromXY(agref, xy)[uci]                    # 관측별 셀 선형인덱스(범위밖=NA)
lg("cellFromXY done")

# 육지 셀만(cid 가 bio01 유효 = env_grid 수록 셀). year 정수화(미상=0).
yr <- suppressWarnings(as.integer(pts$year)); yr[is.na(yr)] <- 0L
ok <- !is.na(cid) & is.finite(av[cid])
DT <- data.table(ktsn = pts$ktsn[ok], cid = cid[ok], yr = yr[ok])
lg(sprintf("land pts %d / %d", nrow(DT), nrow(pts)))
cat(sprintf("셀매핑 점 %s / %s (%.1f분)\n",
            format(nrow(DT), big.mark = ","), format(nrow(pts), big.mark = ","), mins()))

# (ktsn, cid) → maxYear
res <- DT[, .(maxyear = max(yr)), by = .(ktsn, cid)][order(ktsn, cid)]
fwrite(res, file.path(PROC, "species_cells.csv"))
lg(sprintf("DONE species_cells %d rows (종 %d)", nrow(res), uniqueN(res$ktsn)))
cat(sprintf("species_cells.csv: %s (ktsn,cid) 행 · 종 %s (%.1f분)\n",
            format(nrow(res), big.mark = ","), format(uniqueN(res$ktsn), big.mark = ","), mins()))
