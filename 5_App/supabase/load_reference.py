# -*- coding: utf-8 -*-
"""
발견공백 MCP SQLite → Supabase Postgres 참고 테이블 벌크 로드.
사용법: python 5_App/supabase/load_reference.py
필요: SUPABASE_DB_URL 환경변수 (Supabase Dashboard → Database → URI)
"""

import os
import re
import sys
import gzip
import csv
import io
import sqlite3
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("pip install psycopg2-binary")
    sys.exit(1)


def env_val(name):
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return ""
    m = re.search(rf"^\s*{name}\s*=\s*(.+?)\s*$", env.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def get_db_url():
    url = (os.environ.get('SUPABASE_DB_URL') or env_val('SUPABASE_DB_URL')).strip()
    if not url:
        print("""SUPABASE_DB_URL이 설정되지 않았습니다.
Supabase Dashboard → Project Settings → Database → Connection string에서
직접 연결(Direct connection) 또는 세션 풀러(Session pooler) URI를 복사하여
환경변수로 설정하세요. (port 6543 제외)""")
        sys.exit(1)
    return url


def ensure_sqlite():
    db_path = Path('7_MCP/data/fg_mcp.sqlite')
    gz_path = Path('7_MCP/data/fg_mcp.sqlite.gz')

    if db_path.exists():
        return db_path

    if gz_path.exists():
        print(f"압축 해제 중: {gz_path}")
        with gzip.open(gz_path, 'rb') as f_in, open(db_path, 'wb') as f_out:
            f_out.write(f_in.read())
        print(f"생성됨: {db_path}")
        return db_path

    print(f"오류: {db_path} 또는 {gz_path}를 찾을 수 없습니다.")
    sys.exit(1)


def load_table(sqlite_conn, pg_cursor, table_name, columns, query):
    """테이블 벌크 로드 — 배치 단위 COPY 로 메모리 억제(590k행 대비)."""
    pg_cursor.execute(f"TRUNCATE public.{table_name};")
    src = sqlite_conn.cursor()
    src.execute(query)
    copy_sql = f"COPY public.{table_name} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv)"
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    while True:
        rows = src.fetchmany(20000)
        if not rows:
            break
        buf.seek(0)
        buf.truncate(0)
        writer.writerows(rows)
        buf.seek(0)
        pg_cursor.copy_expert(copy_sql, buf)


def verify_tables(pg_cursor):
    """로드된 행 수 확인."""
    for table in ['fg_species', 'fg_species_region', 'fg_region', 'fg_taxa']:
        pg_cursor.execute(f"SELECT count(*) FROM public.{table};")
        count = pg_cursor.fetchone()[0]
        print(f"  {table}: {count}행")


def main():
    db_url = get_db_url()
    sqlite_path = ensure_sqlite()

    sqlite_conn = None
    pg_conn = None

    try:
        sqlite_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        sqlite_conn.row_factory = sqlite3.Row

        pg_conn = psycopg2.connect(db_url)
        pg_cursor = pg_conn.cursor()

        print("데이터 로드 중...")

        load_table(sqlite_conn, pg_cursor, 'fg_species',
                   ['ktsn', 'korean_name', 'scientific_name', 'taxon_group',
                    'taxon_group_kor', 'endangered_grade', 'national_redlist_category',
                    'has_media', 'interest'],
                   "SELECT ktsn, korean_name, scientific_name, taxon_group, "
                   "taxon_group_kor, endangered_grade, national_redlist_category, "
                   "has_media, interest FROM species")

        load_table(sqlite_conn, pg_cursor, 'fg_species_region',
                   ['ktsn', 'taxon_group', 'region', 'sido', 'maxyear', 'obs_count'],
                   "SELECT ktsn, taxon_group, region, sido, maxyear, obs_count "
                   "FROM species_region")

        load_table(sqlite_conn, pg_cursor, 'fg_region',
                   ['code', 'name', 'level', 'sido_cd'],
                   "SELECT code, name, level, sido_cd FROM region")

        load_table(sqlite_conn, pg_cursor, 'fg_taxa',
                   ['taxon_group', 'taxon_group_kor', 'n_species'],
                   "SELECT taxon_group, taxon_group_kor, n_species FROM taxa")

        print("검증:")
        verify_tables(pg_cursor)

        pg_conn.commit()
        print("완료!")
        return 0

    except Exception as e:
        if pg_conn:
            pg_conn.rollback()
        print(f"오류: {e}", file=sys.stderr)
        return 1
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if pg_conn:
            pg_conn.close()


if __name__ == "__main__":
    sys.exit(main())
