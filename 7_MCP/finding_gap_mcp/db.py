# -*- coding: utf-8 -*-
"""발견공백 MCP 데이터 접근 — 커밋된 gzip(fg_mcp.sqlite.gz)을 최초 실행 시 로컬로 해제하고
읽기전용 SQLite 커넥션을 제공. 원시 좌표점은 데이터에 없음(집계만).
"""
import gzip
import os
import shutil
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GZ = DATA_DIR / "fg_mcp.sqlite.gz"
DB = DATA_DIR / "fg_mcp.sqlite"          # 해제본(캐시) — .gitignore 대상, gz만 커밋

_conn = None


def _ensure_db():
    """커밋된 gz를 필요 시 sqlite로 해제. 이미 최신 해제본이 있으면 재사용."""
    if DB.exists() and (not GZ.exists() or DB.stat().st_mtime >= GZ.stat().st_mtime):
        return DB
    if not GZ.exists():
        if DB.exists():
            return DB
        raise FileNotFoundError(
            f"데이터 없음: {GZ} 도 {DB} 도 없습니다. "
            f"먼저 `python 7_MCP/build_mcp_data.py` 로 데이터를 생성하세요.")
    tmp = DB.with_name(DB.name + ".tmp")
    with gzip.open(GZ, "rb") as fin, open(tmp, "wb") as fout:
        shutil.copyfileobj(fin, fout, length=1 << 20)
    os.replace(tmp, DB)
    return DB


def conn():
    """모듈 단일 읽기전용 커넥션(지연 초기화)."""
    global _conn
    if _conn is None:
        _ensure_db()
        _conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def rows(sql, params=()):
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def one(sql, params=()):
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def meta():
    return {r["key"]: r["value"] for r in conn().execute("SELECT key,value FROM meta")}
