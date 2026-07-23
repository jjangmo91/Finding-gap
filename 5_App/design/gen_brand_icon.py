# -*- coding: utf-8 -*-
"""Finding gap 브랜드 아이콘 생성.
실제 시도 경계(5_App/demo/data/sido.geojson)를 저해상도 격자로 래스터화해
"한국 지도 + 발견공백(격자 결손)" 모티프를 만든다 — 서비스의 1km 격자 발견공백
지도와 같은 시각 언어. 색은 실제 UI의 발견(--accent 녹색)·미발견(러스트) 배지 색을 그대로 사용.

산출(5_App/, docs/ 양쪽에 동일 복사): favicon.svg · favicon.ico · apple-touch-icon.png(180) · icon-512.png
공유(OG) 이미지는 이 스크립트가 아니라 5_App/build_profiles.py 가 생성하는 og.png 를 공용으로 사용
(브랜드 이미지 중복 방지 — 텍스트형 og.png 로 통일, 이 아이콘은 파비콘 전용).

사용: python 5_App/design/gen_brand_icon.py
재실행 시 매번 같은 결과(고정 시드 없음 — 격자 래스터화·틈 선정 모두 결정적 알고리즘).
"""
import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent.parent
APP = ROOT / "5_App"
DOCS = ROOT / "docs"
GEOJSON = APP / "demo" / "data" / "sido.geojson"

GREEN = (47, 111, 94)     # --accent / 발견(found) — index.html discBadge 와 동일
RUST = (181, 72, 47)      # 미발견(undiscovered) — index.html discBadge 와 동일
CREAM = (250, 250, 248)   # --bg

ROWS = 22
N_GAPS = 3


def load_grid():
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    rings = []
    for feat in gj["features"]:
        geom = feat.get("geometry")
        if not geom:
            continue
        if geom["type"] == "Polygon":
            rings.append(geom["coordinates"][0])
        elif geom["type"] == "MultiPolygon":
            for poly in geom["coordinates"]:
                rings.append(poly[0])

    def point_in_ring(x, y, ring):
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > y) != (yj > y):
                xint = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < xint:
                    inside = not inside
            j = i
        return inside

    def point_in_any(x, y):
        return any(point_in_ring(x, y, r) for r in rings)

    lons = [p[0] for r in rings for p in r]
    lats = [p[1] for r in rings for p in r]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)
    mean_lat = (lat_min + lat_max) / 2
    lat_span = lat_max - lat_min
    lon_span = (lon_max - lon_min) * math.cos(math.radians(mean_lat))
    cols = round(ROWS * lon_span / lat_span)

    grid = []
    for r in range(ROWS):
        lat = lat_max - (r + 0.5) / ROWS * lat_span
        row = []
        for c in range(cols):
            lon = lon_min + (c + 0.5) / cols * (lon_max - lon_min)
            row.append(point_in_any(lon, lat))
        grid.append(row)
    return grid


def pick_gaps(grid, n=N_GAPS):
    """내륙 깊은 칸(사방 인접칸도 모두 육지) 중, 육지가 있는 행 범위를 n등분한 밴드마다
    하나씩 골라 전국에 퍼진 것처럼 보이게(북쪽에 몰리지 않도록)."""
    rows, cols = len(grid), len(grid[0])

    def land(r, c):
        return 0 <= r < rows and 0 <= c < cols and grid[r][c]

    interior = [(r, c) for r in range(rows) for c in range(cols)
                if grid[r][c] and all(land(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))]
    if not interior:
        return []
    r_min, r_max = min(rc[0] for rc in interior), max(rc[0] for rc in interior)
    band = max(1, (r_max - r_min + 1) / n)
    picks = []
    for i in range(n):
        lo, hi = r_min + i * band, r_min + (i + 1) * band
        cands = [rc for rc in interior if lo <= rc[0] < hi]
        if not cands:
            continue
        mid_col = sum(c for _, c in cands) / len(cands)
        picks.append(min(cands, key=lambda rc: abs(rc[1] - mid_col)))
    return picks


def render_grid(grid, gaps, cell, radius_ratio=0.22):
    rows, cols = len(grid), len(grid[0])
    w, h = cols * cell, rows * cell
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    gapset = set(gaps)
    radius = cell * radius_ratio
    for r in range(rows):
        for c in range(cols):
            if not grid[r][c]:
                continue
            x0, y0 = c * cell, r * cell
            x1, y1 = x0 + cell - 1, y0 + cell - 1
            color = RUST if (r, c) in gapset else GREEN
            draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=color)
    return img


def square_icon(grid, gaps, size, pad_ratio=0.06):
    rows, cols = len(grid), len(grid[0])
    pad = int(size * pad_ratio)
    cell = min((size - 2 * pad) // cols, (size - 2 * pad) // rows)
    art = render_grid(grid, gaps, cell)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    return canvas


def write_svg(grid, gaps, path, cell=10):
    rows, cols = len(grid), len(grid[0])
    gapset = set(gaps)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cols*cell} {rows*cell}">']
    for r in range(rows):
        for c in range(cols):
            if not grid[r][c]:
                continue
            color = "#b5482f" if (r, c) in gapset else "#2f6f5e"
            parts.append(f'<rect x="{c*cell}" y="{r*cell}" width="{cell-1}" height="{cell-1}" '
                         f'rx="{cell*0.22:.1f}" fill="{color}"/>')
    parts.append("</svg>")
    path.write_text("".join(parts), encoding="utf-8")


def main():
    grid = load_grid()
    gaps = pick_gaps(grid)
    rows, cols = len(grid), len(grid[0])
    print(f"grid {cols}x{rows} · gaps={gaps}")

    icon_512 = square_icon(grid, gaps, 512)
    icon_512.save(APP / "icon-512.png")

    touch = Image.new("RGBA", (180, 180), CREAM + (255,))
    touch.alpha_composite(square_icon(grid, gaps, 164), (8, 8))
    touch.convert("RGB").save(APP / "apple-touch-icon.png")

    fav_master = square_icon(grid, gaps, 256)
    fav_master.save(APP / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

    write_svg(grid, gaps, APP / "favicon.svg")

    names = ("icon-512.png", "apple-touch-icon.png", "favicon.ico", "favicon.svg")
    for name in names:
        shutil.copy2(APP / name, DOCS / name)

    print("생성 완료:", ", ".join(names))


if __name__ == "__main__":
    main()
