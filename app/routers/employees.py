"""임직원 마스터 (FR-14)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel

from ..auth import require_user
from ..core import AppError, ST_INUSE, clean_str, now_str
from ..db import get_conn, transaction
from ..services.lookup import dept_full_label, validate_code

router = APIRouter(prefix="/employees", tags=["employees"])

VALID_EMPLOY = ("재직", "휴직", "퇴사")


class EmployeeIn(BaseModel):
    emp_no: str
    name: str
    dept_code: str | None = None
    position_code: str | None = None
    site_code: str | None = None
    employ_status: str = "재직"
    email: str | None = None
    phone: str | None = None


@router.get("")
def list_employees(q: str = "", dept: str = "", site: str = "", employ_status: str = "",
                   page: int = 1, size: int = 20, user: dict = Depends(require_user)):
    where, params = [], []
    if clean_str(q):
        where.append("(e.emp_no LIKE ? OR e.name LIKE ?)")
        params += [f"%{q.strip()}%"] * 2
    for value, col in ((dept, "e.dept_code"), (site, "e.site_code"),
                       (employ_status, "e.employ_status")):
        v = clean_str(value)
        if v:
            where.append(f"{col} = ?")
            params.append(v)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    size = max(1, min(int(size), 200))
    page = max(1, int(page))

    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM employee e{clause}", params).fetchone()["c"]
        rows = conn.execute(
            f"""SELECT e.*, (SELECT COUNT(*) FROM assignment g
                              JOIN asset a ON a.id = g.asset_id
                              WHERE g.emp_no = e.emp_no AND g.is_current = 1) AS asset_count
                FROM employee e{clause}
                ORDER BY e.emp_no LIMIT ? OFFSET ?""",
            params + [size, (page - 1) * size]).fetchall()
        items = [dict(r) for r in rows]
        for it in items:
            it["dept_label"] = dept_full_label(conn, it.get("dept_code"))
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/suggest")
def suggest_employee(q: str = "", limit: int = 10, user: dict = Depends(require_user)):
    """08-3 — 사번 또는 이름으로 자동완성."""
    term = clean_str(q)
    if not term:
        return {"items": []}
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT emp_no, name, dept_code, position_code, site_code, employ_status
               FROM employee WHERE emp_no LIKE ? OR name LIKE ?
               ORDER BY (employ_status = '퇴사'), emp_no LIMIT ?""",
            (f"%{term}%", f"%{term}%", max(1, min(int(limit), 30)))).fetchall()
        items = [dict(r) for r in rows]
        for it in items:
            it["dept_label"] = dept_full_label(conn, it.get("dept_code"))
    return {"items": items}


@router.get("/{emp_no}")
def employee_detail(emp_no: str, user: dict = Depends(require_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM employee WHERE emp_no = ?", (emp_no,)).fetchone()
        if row is None:
            raise AppError("임직원을 찾을 수 없습니다.", 404)
        emp = dict(row)
        emp["dept_label"] = dept_full_label(conn, emp.get("dept_code"))
        # 14-3 배정 자산 목록
        assets = conn.execute(
            """SELECT a.id, a.asset_no, a.asset_type, a.manufacturer, a.model_name, a.status,
                      a.site, a.location, g.issue_date, g.due_return_date, g.dept_code
               FROM assignment g JOIN asset a ON a.id = g.asset_id
               WHERE g.emp_no = ? AND g.is_current = 1 ORDER BY g.issue_date DESC""",
            (emp_no,)).fetchall()
        emp["assets"] = [dict(r) for r in assets]
        # 14-5 부서 불일치 자산
        emp["dept_mismatch"] = [a["asset_no"] for a in emp["assets"]
                                if (a["dept_code"] or None) != (emp.get("dept_code") or None)]
        past = conn.execute(
            """SELECT a.asset_no, a.model_name, g.issue_date, g.return_date, g.return_reason
               FROM assignment g JOIN asset a ON a.id = g.asset_id
               WHERE g.emp_no = ? AND g.is_current = 0 ORDER BY g.issue_date DESC LIMIT 50""",
            (emp_no,)).fetchall()
        emp["past_assets"] = [dict(r) for r in past]
    return emp


def _validate(conn, body: EmployeeIn, creating: bool) -> dict:
    emp_no = clean_str(body.emp_no)
    if not emp_no:
        raise AppError("사번은 필수입니다.", field="emp_no")
    name = clean_str(body.name)
    if not name:
        raise AppError("성명은 필수입니다.", field="name")
    if body.employ_status not in VALID_EMPLOY:
        raise AppError("재직상태는 재직 / 휴직 / 퇴사 중 하나여야 합니다.", field="employ_status")
    dept = validate_code(conn, "DEPT", body.dept_code, "소속부서") if clean_str(body.dept_code) else None
    pos = validate_code(conn, "POSITION", body.position_code, "직급") if clean_str(body.position_code) else None
    site = validate_code(conn, "SITE", body.site_code, "사업장") if clean_str(body.site_code) else None
    return {"emp_no": emp_no, "name": name, "dept_code": dept, "position_code": pos,
            "site_code": site, "employ_status": body.employ_status,
            "email": clean_str(body.email), "phone": clean_str(body.phone)}


@router.post("")
def create_employee(body: EmployeeIn, user: dict = Depends(require_user)):
    with transaction() as conn:
        d = _validate(conn, body, True)
        if conn.execute("SELECT 1 FROM employee WHERE emp_no = ?", (d["emp_no"],)).fetchone():
            raise AppError(f"이미 등록된 사번입니다: {d['emp_no']}", field="emp_no")
        now = now_str()
        conn.execute(
            """INSERT INTO employee (emp_no, name, dept_code, position_code, site_code,
                                     employ_status, email, phone, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (d["emp_no"], d["name"], d["dept_code"], d["position_code"], d["site_code"],
             d["employ_status"], d["email"], d["phone"], now, now))
    return {"ok": True, "emp_no": d["emp_no"]}


@router.put("/{emp_no}")
def update_employee(emp_no: str, body: EmployeeIn, user: dict = Depends(require_user)):
    with transaction() as conn:
        row = conn.execute("SELECT * FROM employee WHERE emp_no = ?", (emp_no,)).fetchone()
        if row is None:
            raise AppError("임직원을 찾을 수 없습니다.", 404)
        d = _validate(conn, body, False)
        warnings = []
        # 14-4 퇴사 전환 시 미회수 자산 경고
        if d["employ_status"] == "퇴사" and row["employ_status"] != "퇴사":
            held = conn.execute(
                """SELECT a.asset_no, a.model_name FROM assignment g JOIN asset a ON a.id = g.asset_id
                   WHERE g.emp_no = ? AND g.is_current = 1""", (emp_no,)).fetchall()
            if held:
                warnings.append(
                    f"배정된 자산 {len(held)}건이 있습니다: "
                    + ", ".join(f"{h['asset_no']}({h['model_name']})" for h in held)
                    + " — 회수 처리가 필요합니다.")
        conn.execute(
            """UPDATE employee SET name=?, dept_code=?, position_code=?, site_code=?,
               employ_status=?, email=?, phone=?, updated_at=? WHERE emp_no=?""",
            (d["name"], d["dept_code"], d["position_code"], d["site_code"],
             d["employ_status"], d["email"], d["phone"], now_str(), emp_no))
    return {"ok": True, "warnings": warnings}


@router.post("/{emp_no}/sync-dept")
def sync_dept(emp_no: str, payload: dict = Body(default={}), user: dict = Depends(require_user)):
    """14-5 — 임직원 부서와 다른 배정 자산의 부서를 이력과 함께 일괄 갱신한다."""
    from ..core import HIST_MOVE
    from ..services.assets import add_history

    reason = clean_str(payload.get("reason")) or "임직원 부서 정보 동기화"
    with transaction() as conn:
        row = conn.execute("SELECT * FROM employee WHERE emp_no = ?", (emp_no,)).fetchone()
        if row is None:
            raise AppError("임직원을 찾을 수 없습니다.", 404)
        emp = dict(row)
        rows = conn.execute(
            """SELECT g.id gid, g.dept_code, a.id aid, a.asset_no
               FROM assignment g JOIN asset a ON a.id = g.asset_id
               WHERE g.emp_no = ? AND g.is_current = 1""", (emp_no,)).fetchall()
        updated = []
        for r in rows:
            if (r["dept_code"] or None) == (emp["dept_code"] or None):
                continue
            conn.execute("UPDATE assignment SET dept_code = ?, position_code = ? WHERE id = ?",
                         (emp["dept_code"], emp["position_code"], r["gid"]))
            add_history(conn, r["aid"], r["asset_no"], HIST_MOVE, user["name"], reason,
                        before={"dept_code": r["dept_code"]}, after={"dept_code": emp["dept_code"]})
            updated.append(r["asset_no"])
    return {"ok": True, "updated": updated}


@router.get("/{emp_no}/assets")
def employee_assets(emp_no: str, user: dict = Depends(require_user)):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.id, a.asset_no, a.model_name, a.status FROM assignment g
               JOIN asset a ON a.id = g.asset_id WHERE g.emp_no = ? AND g.is_current = 1""",
            (emp_no,)).fetchall()
    return {"items": [dict(r) for r in rows]}
