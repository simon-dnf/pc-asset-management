"""공통코드 관리 (FR-13)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_user
from ..core import CODE_GROUPS, AppError, clean_str
from ..db import get_conn, transaction

router = APIRouter(prefix="/codes", tags=["codes"])

# 코드가 실제로 참조되는 위치 (13-3 사용 중 여부 판정)
USAGE = {
    "ASSET_TYPE": [("asset", "asset_type")],
    "MANUFACTURER": [("asset", "manufacturer")],
    "STATUS": [("asset", "status")],
    "SITE": [("asset", "site"), ("employee", "site_code"), ("assignment", "site")],
    "DEPT": [("employee", "dept_code"), ("assignment", "dept_code")],
    "POSITION": [("employee", "position_code"), ("assignment", "position_code")],
    "OS": [("asset", "os")],
    "DISK_TYPE": [("asset", "disk_type")],
    "DISPOSAL_METHOD": [("asset", "disposal_method")],
    "RETURN_REASON": [("assignment", "return_reason")],
}


class CodeIn(BaseModel):
    group_code: str
    label: str
    parent_code: str | None = None
    sort_order: int = 0


class CodeUpdateIn(BaseModel):
    label: str | None = None
    parent_code: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


def _usage_count(conn, group: str, label: str) -> int:
    total = 0
    for table, col in USAGE.get(group, []):
        total += conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE {col} = ?", (label,)).fetchone()["c"]
    return total


@router.get("/groups")
def groups(user: dict = Depends(require_user)):
    return {"items": [{"group_code": g, "label": l} for g, l in CODE_GROUPS.items()]}


@router.get("")
def list_codes(group: str = "", active_only: bool = False, user: dict = Depends(require_user)):
    where, params = [], []
    if clean_str(group):
        where.append("group_code = ?")
        params.append(group)
    if active_only:
        where.append("is_active = 1")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM code{clause} ORDER BY group_code, sort_order, id", params).fetchall()
        items = [dict(r) for r in rows]
        if clean_str(group):
            for it in items:
                it["usage_count"] = _usage_count(conn, it["group_code"], it["label"])
    return {"items": items}


@router.get("/options")
def options(user: dict = Depends(require_user)):
    """화면 셀렉트 박스용 — 활성 코드만 그룹별로 묶어 한 번에 내려준다."""
    out: dict[str, list] = {g: [] for g in CODE_GROUPS}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT group_code, label, parent_code FROM code WHERE is_active = 1"
            " ORDER BY group_code, sort_order, id").fetchall()
    for r in rows:
        out.setdefault(r["group_code"], []).append(
            {"label": r["label"], "parent": r["parent_code"]})
    return out


@router.post("")
def create_code(body: CodeIn, user: dict = Depends(require_user)):
    group = clean_str(body.group_code)
    label = clean_str(body.label)
    if group not in CODE_GROUPS:
        raise AppError(f"알 수 없는 코드 그룹입니다: {group}", field="group_code")
    if not label:
        raise AppError("코드값을 입력하세요.", field="label")
    parent = clean_str(body.parent_code)
    with transaction() as conn:
        if group == "STATUS":
            raise AppError("자산상태는 시스템이 사용하는 코드라 추가할 수 없습니다.")
        if conn.execute("SELECT 1 FROM code WHERE group_code=? AND code=?", (group, label)).fetchone():
            raise AppError(f"이미 등록된 코드값입니다: {label}", field="label")
        if group == "DEPT" and parent:                                  # 13-4 2단계
            p = conn.execute(
                "SELECT parent_code FROM code WHERE group_code='DEPT' AND label=?", (parent,)).fetchone()
            if p is None:
                raise AppError(f"상위 부서 '{parent}'을(를) 찾을 수 없습니다.", field="parent_code")
            if p["parent_code"]:
                raise AppError("부서는 사업부 > 팀 2단계까지만 지원합니다.", field="parent_code")
        elif parent and group != "DEPT":
            parent = None
        order = body.sort_order
        if not order:
            m = conn.execute("SELECT COALESCE(MAX(sort_order),0) m FROM code WHERE group_code=?",
                             (group,)).fetchone()["m"]
            order = m + 10
        conn.execute(
            "INSERT INTO code (group_code, code, label, parent_code, sort_order, is_active)"
            " VALUES (?,?,?,?,?,1)", (group, label, label, parent, order))
    return {"ok": True}


@router.put("/{code_id}")
def update_code(code_id: int, body: CodeUpdateIn, user: dict = Depends(require_user)):
    with transaction() as conn:
        row = conn.execute("SELECT * FROM code WHERE id = ?", (code_id,)).fetchone()
        if row is None:
            raise AppError("코드를 찾을 수 없습니다.", 404)
        code = dict(row)

        if body.is_active is not None and not body.is_active:
            if code["is_system"]:
                raise AppError("시스템 코드는 비활성화할 수 없습니다.")
            used = _usage_count(conn, code["group_code"], code["label"])
            if code["group_code"] == "DEPT":
                kids = conn.execute(
                    "SELECT COUNT(*) c FROM code WHERE group_code='DEPT' AND parent_code=? AND is_active=1",
                    (code["label"],)).fetchone()["c"]
                if kids:
                    raise AppError(f"하위 팀 {kids}개가 활성 상태입니다. 하위 항목을 먼저 비활성화하세요.")
            # 13-3 사용 중이어도 비활성화는 가능 (신규 선택지에서만 제외)
            code["_used"] = used

        new_label = clean_str(body.label)
        if new_label and new_label != code["label"]:
            used = _usage_count(conn, code["group_code"], code["label"])
            if used:
                raise AppError(
                    f"이 코드값을 사용 중인 데이터가 {used}건 있어 이름을 바꿀 수 없습니다. "
                    f"비활성화 후 새 코드를 추가하세요.")
            if conn.execute("SELECT 1 FROM code WHERE group_code=? AND code=? AND id<>?",
                            (code["group_code"], new_label, code_id)).fetchone():
                raise AppError(f"이미 등록된 코드값입니다: {new_label}")

        conn.execute(
            """UPDATE code SET label = COALESCE(?, label), code = COALESCE(?, code),
                               parent_code = CASE WHEN ? IS NULL THEN parent_code ELSE ? END,
                               sort_order = COALESCE(?, sort_order),
                               is_active = COALESCE(?, is_active)
               WHERE id = ?""",
            (new_label, new_label, clean_str(body.parent_code), clean_str(body.parent_code),
             body.sort_order, None if body.is_active is None else int(body.is_active), code_id))
    return {"ok": True}


@router.delete("/{code_id}")
def delete_code(code_id: int, user: dict = Depends(require_user)):
    """13-3 — 사용 중인 코드는 삭제 불가, 비활성화만 가능."""
    with transaction() as conn:
        row = conn.execute("SELECT * FROM code WHERE id = ?", (code_id,)).fetchone()
        if row is None:
            raise AppError("코드를 찾을 수 없습니다.", 404)
        if row["is_system"]:
            raise AppError("시스템 코드는 삭제할 수 없습니다.")
        used = _usage_count(conn, row["group_code"], row["label"])
        if used:
            raise AppError(f"사용 중인 코드는 삭제할 수 없습니다. ({used}건 사용) 비활성화를 이용하세요.")
        if row["group_code"] == "DEPT":
            kids = conn.execute("SELECT COUNT(*) c FROM code WHERE group_code='DEPT' AND parent_code=?",
                                (row["label"],)).fetchone()["c"]
            if kids:
                raise AppError(f"하위 팀 {kids}개가 있어 삭제할 수 없습니다.")
        conn.execute("DELETE FROM code WHERE id = ?", (code_id,))
    return {"ok": True}
