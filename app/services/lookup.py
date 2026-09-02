"""공통코드 조회/검증 및 유사값 제안 (FR-13, FR-06 검증)."""
from __future__ import annotations

import difflib

from ..core import AppError, clean_str


def code_labels(conn, group: str, active_only: bool = True) -> list[str]:
    sql = "SELECT label FROM code WHERE group_code = ?"
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order, id"
    return [r["label"] for r in conn.execute(sql, (group,)).fetchall()]


def all_code_labels(conn, group: str) -> list[str]:
    return code_labels(conn, group, active_only=False)


def suggest(value: str, candidates: list[str]) -> str | None:
    """'데스크탑' → '데스크톱' 처럼 가까운 코드값을 제안한다."""
    if not value or not candidates:
        return None
    hit = difflib.get_close_matches(value, candidates, n=1, cutoff=0.6)
    if hit:
        return hit[0]
    norm = value.replace(" ", "").lower()
    for c in candidates:
        if c.replace(" ", "").lower() == norm:
            return c
    return None


def validate_code(conn, group: str, value, field_label: str, required: bool = False,
                  allow_inactive_existing: str | None = None) -> str | None:
    """코드값 검증. 기존 데이터가 이미 비활성 코드를 쓰고 있으면 그대로 허용한다 (13-3)."""
    v = clean_str(value)
    if v is None:
        if required:
            raise AppError(f"{field_label}은(는) 필수입니다.")
        return None
    active = code_labels(conn, group)
    if v in active:
        return v
    if allow_inactive_existing is not None and v == allow_inactive_existing:
        return v
    every = all_code_labels(conn, group)
    if v in every:
        raise AppError(f"{field_label} '{v}'은(는) 비활성 코드입니다. 사용 가능한 값: {', '.join(active)}")
    tip = suggest(v, every)
    hint = f" '{tip}'을(를) 의도하셨나요?" if tip else f" 사용 가능한 값: {', '.join(active)}"
    raise AppError(f"{field_label} '{v}'은(는) 등록되지 않은 코드입니다.{hint}")


def dept_full_label(conn, dept_code: str | None) -> str | None:
    """'품질보증팀' → '생산본부 / 품질보증팀'."""
    v = clean_str(dept_code)
    if not v:
        return None
    row = conn.execute(
        "SELECT label, parent_code FROM code WHERE group_code='DEPT' AND label = ?", (v,)
    ).fetchone()
    if row is None:
        return v
    if row["parent_code"]:
        return f"{row['parent_code']} / {row['label']}"
    return row["label"]


def employee_of(conn, emp_no: str | None):
    v = clean_str(emp_no)
    if not v:
        return None
    row = conn.execute("SELECT * FROM employee WHERE emp_no = ?", (v,)).fetchone()
    return dict(row) if row else None
