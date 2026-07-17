# -*- coding: utf-8 -*-
"""웹 클라이언트용 관심도 자산 — MCP sqlite(단일 소스)의 species.interest 를
`5_App/demo/data/species_interest.js`(window.__SPINT__={ktsn:0~1000})로 export.
관심도 정의·산식은 7_MCP(build_mcp_data.py) 한 곳에서만 계산 → 웹·MCP 동일값 보장.
정수(0~1000) 인코딩으로 크기 절감(소비 측에서 /1000). 사용: python 5_App/build_species_interest.py
"""
import gzip
import json
import shutil
import sqlite3
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent          # 5_App
BASE = APP.parent                              # repo root
DB = BASE / "7_MCP" / "data" / "fg_mcp.sqlite"
GZ = BASE / "7_MCP" / "data" / "fg_mcp.sqlite.gz"
OUT = APP / "demo" / "data" / "species_interest.js"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not DB.exists():
        if not GZ.exists():
            raise FileNotFoundError(f"MCP 데이터 없음: {DB} / {GZ}. 먼저 python 7_MCP/build_mcp_data.py 실행.")
        with gzip.open(GZ, "rb") as f, open(DB, "wb") as o:
            shutil.copyfileobj(f, o)
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT ktsn, interest FROM species WHERE interest IS NOT NULL").fetchall()
    con.close()
    m = {k: int(round(float(v) * 1000)) for k, v in rows}     # 0~1 → 0~1000 정수
    OUT.write_text("window.__SPINT__=" + json.dumps(m, separators=(",", ":")) + ";", encoding="utf-8")
    print(f"species_interest.js: {len(m)}종 · {OUT.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
