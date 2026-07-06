# -*- coding: utf-8 -*-
# env_layers.R — 종 페이지 "기후·지형 지위" + 지도 환경변수 레이어용 데이터 산출
# 입력 : observations.sqlite(obs_points)  ·  bioclim bio01/05/06/12(EPSG:5186,30m)  ·  한반도90m DEM(GRS80 TM)
# 산출 :
#   1) species_dem.csv         — 종별 해발고도 5수치(bio='dem', species_bioclim 와 동일 스키마)
#   2) env_national.csv        — 변수별 전국(1km 격자) 분포 분위수 — 비교막대 회색트랙·빨간원 기준
#   3) 5_App/demo/data/env/<var>.png — 저해상 컬러 오버레이(EPSG:3857, NA 투명)
#   4) env_layers_meta.csv     — 변수·png·extent(3857 xmin,ymin,xmax,ymax)·color vmin/vmax
# 방법 : 점추출은 원본 풀해상도, 지도 레이어는 1km로 집계 후 3857 투영(저해상). 고유좌표 1회 추출.
# 실행 : Rscript 3_ETL/R/env_layers.R   (공백경로면 -e "source('3_ETL/R/env_layers.R')")

suppressMessages({library(terra); library(DBI); library(RSQLite); library(png)})

BASE <- "D:/Google_Drive/Finding gap"
PROC <- file.path(BASE, "1_Data", "processed")
BIO  <- "D:/Google_Drive/Paper/Lucanidae/Data/Zonal/bioclim"
DEMP <- "/vsizip/D:/Google_Drive/Finding gap/1_Data/spatial/한반도.zip/한반도90m_GRS80.img"
# NDVI/NDWI: 2024 Sentinel, 30m, 값 -1~1, 남한만(EPSG:5179).
# ⚠ 주의(크래시 회피): ⑴ zip .ovr 오버뷰가 손상돼 /vsizip 직독·대량 read 시 GDAL heap 크래시 →
#   원본 zip(1_Data/spatial)에서 .tif만 로컬 캐시로 추출(.ovr 제외)해 사용. ⑵ 진행로그를 Google Drive
#   폴더에 자주 쓰면 Drive File Stream 필터와 충돌해 heap 크래시 → 로그는 비-Drive(LOCALAPPDATA)로.
CACHE <- file.path(Sys.getenv("LOCALAPPDATA"), "fg_cache")
SENT  <- file.path(CACHE, "sentinel")
NDVI  <- file.path(SENT, "S2_NDVI.tif")
NDWI  <- file.path(SENT, "S2_NDWI.tif")
DBF  <- file.path(PROC, "observations.sqlite")
ENVDIR <- file.path(BASE, "5_App", "demo", "data", "env")
dir.create(ENVDIR, showWarnings = FALSE, recursive = TRUE)

t0 <- Sys.time(); mins <- function() as.numeric(difftime(Sys.time(), t0, units = "mins"))
dir.create(CACHE, showWarnings = FALSE, recursive = TRUE)
LOG <- file.path(CACHE, "env_layers_run.log")   # 비-Drive 진행로그(모니터링·크래시 지점 — Drive에 쓰면 크래시)
cat("", file=LOG)
lg <- function(m){ con <- file(LOG, "a"); writeLines(sprintf("[%s] %s", format(Sys.time(),"%H:%M:%S"), m), con); close(con) }
lg("START")

# 변수 정의: key·래스터·집계계수(≈1km)·색 타입
VARS <- list(
  list(key="bio01", path=file.path(BIO,"bio01.tif"), fact=33, type="temp"),
  list(key="bio05", path=file.path(BIO,"bio05.tif"), fact=33, type="temp"),
  list(key="bio06", path=file.path(BIO,"bio06.tif"), fact=33, type="temp"),
  list(key="bio12", path=file.path(BIO,"bio12.tif"), fact=33, type="precip"),
  list(key="dem",   path=DEMP,                       fact=11, type="elev"),
  list(key="ndvi",  path=NDVI,                       fact=22, type="ndvi"),   # 실효 ~46m→≈1km
  list(key="ndwi",  path=NDWI,                       fact=22, type="ndwi")
)
# 모델용 1km 격자에 실을 변수(display용 bio05 제외). ndwi는 종별 적용여부를 build 단계에서 분기.
GRID_VARS <- c("bio01","bio06","bio12","dem","ndvi","ndwi")
PAL <- list(
  temp   = c("#2c7bb6","#abd9e9","#ffffbf","#fdae61","#d7191c"),
  precip = c("#f7fbff","#c6dbef","#6baed6","#2171b5","#08306b"),
  elev   = c("#2b7a3d","#a6d96a","#ffffbf","#e0a060","#8c510a"),
  ndvi   = c("#a6611a","#dfc27d","#f5f5f5","#a6d96a","#1a9641"),   # 갈색(저)→녹색(고)
  ndwi   = c("#8c510a","#dfc27d","#f5f5f5","#92c5de","#2166ac")    # 갈색(저)→청색(고=물)
)

# ── 1) 5변수 점추출 → 종별 통계(min·Q1·median·Q3·max·mean·sd) ──────────────
con <- dbConnect(SQLite(), DBF)
pts <- dbGetQuery(con, "SELECT ktsn, taxon_group, lon, lat FROM obs_points
                        WHERE lon IS NOT NULL AND lat IS NOT NULL")
dbDisconnect(con)
key   <- paste0(pts$lon, "_", pts$lat)
uc    <- pts[!duplicated(key), c("lon","lat")]
pts$cid <- match(key, paste0(uc$lon, "_", uc$lat))
ucv   <- vect(uc, geom=c("lon","lat"), crs="EPSG:4326")
tx_of <- tapply(pts$taxon_group, pts$ktsn, function(z) z[1])
cat(sprintf("점 %s행 · 고유좌표 %s · 종 %s\n",
            format(nrow(pts),big.mark=","), format(nrow(uc),big.mark=","),
            format(length(unique(pts$ktsn)),big.mark=",")))
lg(sprintf("점 로드 %s · 고유좌표 %s", nrow(pts), nrow(uc)))

statRows <- list()
for(v in VARS){
  lg(paste0("S1 extract 시작: ", v$key))
  r  <- rast(v$path)
  ex <- terra::extract(r, project(ucv, crs(r)), ID=FALSE)[[1]]   # 고유좌표 값(원본 풀해상도)
  pv <- ex[pts$cid]                                              # 관측별 값
  agg <- tapply(pv, pts$ktsn, function(x){
    x <- x[is.finite(x)]; if(!length(x)) return(NULL)
    q <- as.numeric(quantile(x, c(0,.25,.5,.75,1), names=FALSE))
    c(n=length(x), min=q[1], q1=q[2], median=q[3], q3=q[4], max=q[5],
      mean=mean(x), sd=if(length(x) > 1) sd(x) else 0)
  })
  keep <- !vapply(agg, is.null, logical(1))
  for(k in names(agg)[keep]){ a <- agg[[k]]
    statRows[[length(statRows)+1L]] <- data.frame(ktsn=k, taxon_group=tx_of[[k]], var=v$key,
      n=a[["n"]], min=a[["min"]], q1=a[["q1"]], median=a[["median"]], q3=a[["q3"]],
      max=a[["max"]], mean=a[["mean"]], sd=a[["sd"]], stringsAsFactors=FALSE) }
  cat(sprintf("  %s 점추출·집계 종 %s (%.1f분)\n", v$key, format(sum(keep),big.mark=","), mins()))
  lg(sprintf("S1 %s 완료 종 %s", v$key, sum(keep)))
}
stat <- do.call(rbind, statRows)
sc <- c("min","q1","median","q3","max","mean","sd"); stat[sc] <- round(stat[sc], 2)
write.csv(stat, file.path(PROC,"species_env_stats.csv"), row.names=FALSE, fileEncoding="UTF-8")
cat(sprintf("species_env_stats.csv 행 %s · 종 %s (%.1f분)\n",
            format(nrow(stat),big.mark=","), format(length(unique(stat$ktsn)),big.mark=","), mins()))

# ── 2~4) 변수별: 1km 집계 → 전국 분위수 + 3857 PNG + 메타 ──────────────────
val2rgb <- function(m, vmin, vmax, pal){
  ramp <- colorRamp(pal)                       # 0..1 → 0..255
  norm <- (m - vmin)/(vmax - vmin)
  norm[norm<0] <- 0; norm[norm>1] <- 1
  fin <- is.finite(norm)
  rgb <- matrix(0, length(norm), 3)
  if(any(fin)) rgb[fin,] <- ramp(norm[fin])
  a <- ifelse(fin, 1, 0)
  list(r=matrix(rgb[,1]/255, nrow(m)), g=matrix(rgb[,2]/255, nrow(m)),
       b=matrix(rgb[,3]/255, nrow(m)), a=matrix(a, nrow(m)))
}
natl <- list(); meta <- list(); agref <- NULL   # agref = bio01 1km 격자(육지 기준)
grid_cols <- list()                             # agref 셀별 변수값(모델 1km 격자용)
for(v in VARS){
  lg(paste0("S2 aggregate 시작: ", v$key))
  if(v$key=="dem"){                                        # DEM: 바다(0)·북한 제외 → bioclim 육지격자에 투영·마스크
    ag0 <- aggregate(rast(v$path), fact=v$fact, fun="mean", na.rm=TRUE)   # GRS80 ≈1km
    ag  <- mask(project(ag0, agref), agref)                # bio01 격자로 리샘플 후 육지만 남김
  } else {
    ag <- aggregate(rast(v$path), fact=v$fact, fun="mean", na.rm=TRUE)    # 5186/5179 ≈1km(해상·역외=NA)
    if(v$key=="bio01") agref <- ag
  }
  if(v$key %in% GRID_VARS){                                # agref 격자에 정렬된 열 수집(NDVI/NDWI는 투영 필요)
    ag_ref <- if(v$key=="bio01") agref
              else if(crs(ag)==crs(agref) && all(dim(ag)==dim(agref))) mask(ag, agref)
              else mask(project(ag, agref), agref)         # 다른 CRS(NDVI/NDWI)는 agref로 리샘플
    grid_cols[[v$key]] <- values(ag_ref, mat=FALSE)
  }
  vv <- values(ag, mat=FALSE); vv <- vv[is.finite(vv)]
  qs <- as.numeric(quantile(vv, c(.01,.05,.25,.5,.75,.95,.99), names=FALSE))
  natl[[v$key]] <- data.frame(var=v$key, p01=qs[1], p05=qs[2], q1=qs[3], median=qs[4],
                              q3=qs[5], p95=qs[6], p99=qs[7], min=min(vv), max=max(vv),
                              n=length(vv))
  vmin <- qs[1]; vmax <- qs[7]                              # 색 범위 = p01..p99(이상치 둔감)
  ag3 <- project(ag, "EPSG:3857", method="bilinear")
  m   <- as.matrix(ag3, wide=TRUE)                          # [row(top=N), col]
  ch  <- val2rgb(m, vmin, vmax, PAL[[v$type]])
  arr <- array(0, dim=c(nrow(m), ncol(m), 4))
  arr[,,1] <- ch$r; arr[,,2] <- ch$g; arr[,,3] <- ch$b; arr[,,4] <- ch$a
  writePNG(arr, file.path(ENVDIR, paste0(v$key, ".png")))
  e <- as.vector(ext(ag3))                                 # xmin,xmax,ymin,ymax
  meta[[v$key]] <- data.frame(var=v$key, png=paste0("env/",v$key,".png"),
                              xmin=e[1], ymin=e[3], xmax=e[2], ymax=e[4],
                              vmin=vmin, vmax=vmax)
  cat(sprintf("  %s: 격자 %s · 색 %.1f~%.1f · PNG %dx%d (%.1f분)\n",
              v$key, format(length(vv),big.mark=","), vmin, vmax, ncol(m), nrow(m), mins()))
  lg(sprintf("S2 %s 완료(격자 %s)", v$key, length(vv)))
}
lg("S5 env_grid 시작")
nat <- do.call(rbind, natl); nat[,-1] <- round(nat[,-1], 1)
write.csv(nat, file.path(PROC,"env_national.csv"), row.names=FALSE, fileEncoding="UTF-8")
mt <- do.call(rbind, meta)
mt[c("xmin","ymin","xmax","ymax")] <- round(mt[c("xmin","ymin","xmax","ymax")], 1)
mt[c("vmin","vmax")] <- round(mt[c("vmin","vmax")], 1)
write.csv(mt, file.path(PROC,"env_layers_meta.csv"), row.names=FALSE, fileEncoding="UTF-8")

# ── 5) 모델용 1km 환경격자 테이블 — agref(육지) 셀별 변수값 + 셀중심 경위도 ──────────
xy   <- crds(agref, na.rm=FALSE)                            # 5186 셀중심(모든 셀)
land <- is.finite(grid_cols[["bio01"]])                    # bio01 유효 = 육지 격자
ll   <- crds(project(vect(xy[land,,drop=FALSE], type="points", crs=crs(agref)), "EPSG:4326"))  # 육지 셀만 경위도
gc   <- function(k, d) round(grid_cols[[k]][land], d)
grid <- data.frame(cid=which(land),
  lon=round(ll[,1],5), lat=round(ll[,2],5),
  bio01=gc("bio01",1), bio06=gc("bio06",1), bio12=gc("bio12",0),
  dem=gc("dem",0), ndvi=gc("ndvi",3), ndwi=gc("ndwi",3))
write.csv(grid, file.path(PROC,"env_grid.csv"), row.names=FALSE, fileEncoding="UTF-8")
cat(sprintf("env_grid.csv 셀 %s · NDVI값있음 %s · NDWI값있음 %s (%.1f분)\n",
            format(nrow(grid),big.mark=","), format(sum(is.finite(grid$ndvi)),big.mark=","),
            format(sum(is.finite(grid$ndwi)),big.mark=","), mins()))

lg(sprintf("DONE env_grid %s행", nrow(grid)))
cat(sprintf("완료: species_env_stats.csv · env_national.csv · env_layers_meta.csv · env_grid.csv · env/*.png  (%.1f분)\n", mins()))
