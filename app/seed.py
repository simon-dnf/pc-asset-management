"""초기 데이터 시딩: 공통코드, 최초 관리자 계정 (PRD-v1 §2, FR-13 초기 코드값)."""
from __future__ import annotations

import os

from .auth import hash_password
from .core import now_str
from .db import transaction

DEFAULT_ADMIN_ID = os.environ.get("PCAMS_ADMIN_ID", "admin")
DEFAULT_ADMIN_PW = os.environ.get("PCAMS_ADMIN_PW", "admin1234")

CODE_SEED: dict[str, list] = {
    "ASSET_TYPE": ["데스크톱", "노트북", "워크스테이션"],
    "STATUS": ["대기", "사용중", "수리", "폐기예정", "폐기"],
    "SITE": ["서울", "인천", "시화", "판교", "발안", "음성"],
    "MANUFACTURER": ["삼성", "LG", "Dell", "HP", "Lenovo", "ASUS", "Apple", "조립", "기타"],
    "OS": ["Windows 11", "Windows 10", "Windows Server", "macOS", "Linux", "기타"],
    "DISK_TYPE": ["HDD", "SSD", "NVMe"],
    "DISPOSAL_METHOD": ["HDD 물리파기", "완전삭제(디가우징)", "업체 반납", "매각", "기타"],
    "RETURN_REASON": ["퇴사", "부서이동", "장비교체", "수리", "반납", "기타"],
    "POSITION": ["사원", "주임", "대리", "과장", "차장", "부장", "이사", "상무", "전무", "대표이사"],
}

# 부서는 사업부 > 팀 2단계 (13-4). (사업부, 팀들)
DEPT_SEED: list[tuple[str, list[str]]] = [
    ("경영지원본부", ["인사팀", "총무팀", "재무회계팀", "IT인프라팀"]),
    ("영업본부", ["국내영업팀", "해외영업팀", "영업지원팀"]),
    ("연구개발본부", ["선행연구팀", "제품개발팀", "설계팀"]),
    ("생산본부", ["생산관리팀", "생산기술팀", "품질보증팀", "설비팀"]),
    ("구매본부", ["구매1팀", "구매2팀"]),
]

SYSTEM_GROUPS = {"STATUS"}          # 로직이 의존하므로 비활성화 금지


def seed_codes(conn) -> int:
    added = 0
    for group, labels in CODE_SEED.items():
        for i, label in enumerate(labels):
            cur = conn.execute(
                """INSERT OR IGNORE INTO code (group_code, code, label, sort_order, is_active, is_system)
                   VALUES (?,?,?,?,1,?)""",
                (group, label, label, (i + 1) * 10, 1 if group in SYSTEM_GROUPS else 0))
            added += cur.rowcount
    order = 0
    for div, teams in DEPT_SEED:
        order += 10
        added += conn.execute(
            """INSERT OR IGNORE INTO code (group_code, code, label, parent_code, sort_order, is_active)
               VALUES ('DEPT',?,?,NULL,?,1)""", (div, div, order)).rowcount
        for t in teams:
            order += 10
            added += conn.execute(
                """INSERT OR IGNORE INTO code (group_code, code, label, parent_code, sort_order, is_active)
                   VALUES ('DEPT',?,?,?,?,1)""", (t, t, div, order)).rowcount
    return added


def seed_admin(conn) -> str | None:
    exists = conn.execute("SELECT COUNT(*) c FROM admin_user").fetchone()["c"]
    if exists:
        return None
    conn.execute(
        """INSERT INTO admin_user (username, password_hash, name, role, is_active,
                                   must_change_pw, created_at, created_by)
           VALUES (?,?,?,'ADMIN',1,1,?,'system')""",
        (DEFAULT_ADMIN_ID, hash_password(DEFAULT_ADMIN_PW), "시스템 관리자", now_str()))
    return DEFAULT_ADMIN_ID


def run() -> dict:
    with transaction() as conn:
        codes = seed_codes(conn)
        admin = seed_admin(conn)
    return {"codes_added": codes, "admin_created": admin}
