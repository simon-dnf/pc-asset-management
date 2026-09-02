"""자산 검색/필터 (FR-05) 및 목록 조회 (FR-03)."""
from __future__ import annotations

from ..core import ST_DISPOSED, ST_INUSE, ST_REPAIR, ST_TO_DISPOSE, clean_str, plus_days, today_str

# 03-5 정렬 허용 컬럼 (임의 컬럼명 주입 차단)
SORT_COLUMNS = {
    "asset_no": "a.asset_no",
    "asset_type": "a.asset_type",
    "manufacturer": "a.manufacturer",
    "model_name": "a.model_name",
    "status": "a.status",
    "purchase_date": "a.purchase_date",
    "issue_date": "g.issue_date",
    "user_name": "g.user_name",
    "dept": "g.dept_code",
    "site": "a.site",
    "created_at": "a.created_at",
    "id": "a.id",
}

BASE_SELECT = """
SELECT a.*,
       g.emp_no        AS cur_emp_no,
       g.user_name     AS cur_user_name,
       g.dept_code     AS cur_dept,
       g.position_code AS cur_position,
       g.issue_date    AS cur_issue_date,
       g.due_return_date AS cur_due_date,
       e.employ_status AS cur_employ_status
FROM asset a
LEFT JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
LEFT JOIN employee   e ON e.emp_no = g.emp_no
"""


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [p for p in v.split(",")]
    return [s.strip() for s in v if s and str(s).strip()]


def build_where(f: dict) -> tuple[str, list]:
    """필터 dict → (WHERE 절, 파라미터). 필터 간 AND, 동일 필터 내 OR (05-4)."""
    where: list[str] = []
    params: list = []

    # 03-3 — 기본적으로 폐기 제외
    statuses = _as_list(f.get("status"))
    if statuses:
        where.append(f"a.status IN ({','.join('?' * len(statuses))})")
        params += statuses
    elif not f.get("include_disposed"):
        where.append("a.status <> ?")
        params.append(ST_DISPOSED)

    # 05-1 통합 검색
    q = clean_str(f.get("q"))
    if q:
        like = f"%{q}%"
        where.append(
            "(a.asset_no LIKE ? OR a.serial_no LIKE ? OR a.hostname LIKE ? OR a.ip_address LIKE ?"
            " OR a.model_name LIKE ? OR a.mac_address LIKE ?"
            " OR g.user_name LIKE ? OR g.emp_no LIKE ?)"
        )
        params += [like] * 8

    for key, col in (("asset_type", "a.asset_type"), ("manufacturer", "a.manufacturer"),
                     ("site", "a.site"), ("os", "a.os"), ("dept", "g.dept_code")):
        vals = _as_list(f.get(key))
        if vals:
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            params += vals

    manager = clean_str(f.get("manager"))
    if manager:
        where.append("a.manager_emp_no LIKE ?")
        params.append(f"%{manager}%")

    emp_no = clean_str(f.get("emp_no"))
    if emp_no:
        where.append("g.emp_no = ?")
        params.append(emp_no)

    # 05-3 기간 필터
    for key, col in (("purchase_from", "a.purchase_date"), ("issue_from", "g.issue_date"),
                     ("disposal_from", "a.disposal_date")):
        v = clean_str(f.get(key))
        if v:
            where.append(f"{col} >= ?")
            params.append(v)
    for key, col in (("purchase_to", "a.purchase_date"), ("issue_to", "g.issue_date"),
                     ("disposal_to", "a.disposal_date")):
        v = clean_str(f.get(key))
        if v:
            where.append(f"{col} <= ?")
            params.append(v)

    # 빠른 필터 (FR-05 빠른 필터 / FR-11-5 조치 필요)
    quick = clean_str(f.get("quick"))
    if quick == "overdue":                       # 반납예정일 초과
        where.append("a.status = ? AND g.due_return_date IS NOT NULL AND g.due_return_date < ?")
        params += [ST_INUSE, today_str()]
    elif quick == "due_soon":                    # 7일 이내 반납 예정 (15-2)
        where.append("a.status = ? AND g.due_return_date BETWEEN ? AND ?")
        params += [ST_INUSE, today_str(), plus_days(7)]
    elif quick == "unassigned":                  # 사용중인데 사용자 미지정
        where.append("a.status = ? AND g.id IS NULL")
        params.append(ST_INUSE)
    elif quick == "resigned":                    # 퇴사자 미회수 자산 (15-3)
        where.append("a.status = ? AND e.employ_status = ?")
        params += [ST_INUSE, "퇴사"]
    elif quick == "long_repair":                 # 30일 이상 수리
        where.append("a.status = ? AND a.updated_at <= ?")
        params += [ST_REPAIR, plus_days(-30) + " 23:59:59"]
    elif quick == "to_dispose":
        where.append("a.status = ?")
        params.append(ST_TO_DISPOSE)
    elif quick == "os_eol_expired":              # OS 지원종료 (외부 EOL 연동)
        where.append("a.status <> ? AND a.os_eol_date IS NOT NULL AND a.os_eol_date < ?")
        params += [ST_DISPOSED, today_str()]
    elif quick == "os_eol_soon":                 # 1년 내 OS 지원종료
        where.append("a.status <> ? AND a.os_eol_date BETWEEN ? AND ?")
        params += [ST_DISPOSED, today_str(), plus_days(365)]
    elif quick == "aged":                        # 내용연수 초과 (11-6)
        where.append(
            "a.status <> ? AND a.purchase_date <= date('now','localtime','-' || "
            "(CASE WHEN a.useful_life_years IS NULL THEN 5 ELSE a.useful_life_years END) || ' years')"
        )
        params.append(ST_DISPOSED)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


def search(conn, f: dict, page: int = 1, size: int = 20, sort: str = "created_at",
           order: str = "desc", limit_all: int | None = None) -> dict:
    clause, params = build_where(f)
    total = conn.execute(f"SELECT COUNT(*) c FROM asset a "
                         f"LEFT JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1 "
                         f"LEFT JOIN employee e ON e.emp_no = g.emp_no {clause}",
                         params).fetchone()["c"]

    col = SORT_COLUMNS.get(sort, SORT_COLUMNS["created_at"])
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    sql = f"{BASE_SELECT}{clause} ORDER BY {col} {direction}, a.id {direction}"

    if limit_all is not None:                     # 내보내기: 페이징 무시 (07-1)
        sql += " LIMIT ?"
        rows = conn.execute(sql, params + [limit_all]).fetchall()
    else:
        size = max(1, min(int(size), 200))
        page = max(1, int(page))
        sql += " LIMIT ? OFFSET ?"
        rows = conn.execute(sql, params + [size, (page - 1) * size]).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }
