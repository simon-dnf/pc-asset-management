"""SQLite 연결/트랜잭션 헬퍼.

PRD-Master §9.1은 PostgreSQL을 제안하지만 확정이 아니며, 대상 규모(자산 1,500건)와
폐쇄망 단일 서버 배포(NFR-01, NFR-10 단일 파일 백업)를 고려해 SQLite를 사용한다.
SQL은 표준 문법 위주로 작성해 필요 시 PostgreSQL 이관이 가능하도록 유지한다.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# PCAMS_DB 로 DB 파일 위치를 바꿀 수 있다 (자체 점검·테스트용).
DB_PATH = Path(os.environ.get("PCAMS_DB") or (BASE_DIR / "data" / "assets.db")).resolve()
DATA_DIR = DB_PATH.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def get_conn():
    """읽기 전용/단건 조회용 커넥션."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    """쓰기용 커넥션. 예외 발생 시 전체 롤백한다."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def init_db() -> None:
    """스키마를 생성한다. 이미 있으면 아무것도 하지 않는다."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = _connect()
    try:
        conn.executescript(sql)
    finally:
        conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def row_to_dict(row):
    return dict(row) if row is not None else None
