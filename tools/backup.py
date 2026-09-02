"""DB 백업 (NFR-10: 일 1회 자동 백업, 30일 보관).

    python tools\\backup.py                    # data/backup/ 에 백업 생성 + 30일 초과분 정리
    python tools\\backup.py --dir D:\\백업       # 다른 위치에 보관
    python tools\\backup.py --keep-days 90

Windows 작업 스케줄러에 매일 1회 등록해서 사용한다.
SQLite 온라인 백업 API를 쓰므로 서비스를 멈추지 않아도 안전하다.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import DB_PATH


def run(dest_dir: Path, keep_days: int = 30) -> Path:
    if not DB_PATH.exists():
        raise SystemExit(f"DB 파일이 없습니다: {DB_PATH}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = dest_dir / f"assets_{stamp}.db"

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"백업 생성: {target}  ({size_mb:.1f} MB)")

    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for old in dest_dir.glob("assets_*.db"):
        if datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
            old.unlink()
            removed += 1
    if removed:
        print(f"{keep_days}일 초과 백업 {removed}개 삭제")
    return target


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="PC 자산관리 시스템 DB 백업")
    p.add_argument("--dir", default=str(ROOT / "data" / "backup"), help="백업 보관 위치")
    p.add_argument("--keep-days", type=int, default=30, help="보관 기간 (기본 30일)")
    a = p.parse_args()
    run(Path(a.dir), a.keep_days)
