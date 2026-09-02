"""자산 CRUD / 배정 / 회수 / 상태변경 / 내보내기 (FR-02~FR-05, FR-07~FR-09, FR-12)."""
from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel

from ..auth import require_user
from ..core import (
    AppError, HIST_ASSIGN, HIST_CREATE, HIST_DISPOSE, HIST_RETURN, HIST_STATUS, ST_DISPOSED,
    ST_INUSE, ST_READY, ST_REPAIR, ST_TO_DISPOSE, STATUS_BLOCK_MESSAGE, STATUS_TRANSITIONS,
    clean_str, jdump, now_str, parse_date, today_str,
)
from ..db import get_conn, transaction
from ..services import excel_io
from ..services.assets import (
    EDITABLE_FIELDS, add_history, apply_update, close_assignment, create_assignment,
    current_assignment, get_asset, insert_asset, validate_asset, validate_assignment_input,
)
from ..services.histfmt import format_history
from ..services.lookup import dept_full_label, validate_code
from ..services.query import search

router = APIRouter(prefix="/assets", tags=["assets"])
# `/assets/{asset_id}` 보다 먼저 매칭되어야 하므로 별도 라우터로 분리한다 (main.py에서 먼저 include)
bulk_router = APIRouter(prefix="/assets/bulk", tags=["assets"])

FILTER_KEYS = ["q", "status", "asset_type", "manufacturer", "site", "dept", "os", "manager",
               "emp_no", "purchase_from", "purchase_to", "issue_from", "issue_to",
               "disposal_from", "disposal_to", "quick", "include_disposed"]


def _filters(request: Request) -> dict:
    qp = request.query_params
    f: dict[str, Any] = {}
    for k in FILTER_KEYS:
        vals = qp.getlist(k)
        if not vals:
            continue
        if k == "include_disposed":
            f[k] = vals[0] in ("1", "true", "True", "yes")
        elif k in ("status", "asset_type", "manufacturer", "site", "dept", "os"):
            out: list[str] = []
            for v in vals:
                out += [s for s in v.split(",") if s.strip()]
            f[k] = out
        else:
            f[k] = vals[0]
    return f


def _enrich(conn, item: dict) -> dict:
    item["dept_label"] = dept_full_label(conn, item.get("cur_dept"))
    return item


# ---------------------------------------------------------------- 목록 (FR-03, FR-05)
@router.get("")
def list_assets(request: Request, page: int = 1, size: int = 20,
                sort: str = "created_at", order: str = "desc",
                user: dict = Depends(require_user)):
    with get_conn() as conn:
        result = search(conn, _filters(request), page, size, sort, order)
        result["items"] = [_enrich(conn, i) for i in result["items"]]
    return result


# ---------------------------------------------------------------- 자산번호 채번 제안 (OI-01 잠정)
@router.get("/next-no")
def next_asset_no(prefix: str = "PC", user: dict = Depends(require_user)):
    """`PC-YYYY-NNNN` 형식의 다음 번호를 제안한다. 수기 입력도 그대로 허용한다."""
    year = today_str()[:4]
    head = f"{clean_str(prefix) or 'PC'}-{year}-"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT asset_no FROM asset WHERE asset_no LIKE ? ORDER BY asset_no DESC LIMIT 1",
            (head + "%",)).fetchall()
    seq = 1
    if rows:
        tail = rows[0]["asset_no"][len(head):]
        if tail.isdigit():
            seq = int(tail) + 1
    return {"asset_no": f"{head}{seq:04d}"}


# ---------------------------------------------------------------- 내보내기 (FR-07)
@router.get("/export.xlsx")
def export_assets(request: Request, scope: str = "basic", columns: str = "",
                  sort: str = "created_at", order: str = "desc",
                  with_history: bool = False, user: dict = Depends(require_user)):
    if scope == "custom":
        fields = [c for c in columns.split(",") if c.strip() and c in excel_io.EXPORT_ALL]
        if not fields:
            raise AppError("내보낼 항목을 1개 이상 선택하세요.")
    elif scope == "full":
        fields = excel_io.EXPORT_ALL
    else:
        fields = excel_io.EXPORT_BASIC

    f = _filters(request)
    with get_conn() as conn:
        result = search(conn, f, sort=sort, order=order, limit_all=excel_io.EXPORT_MAX + 1)
        items = result["items"]
        if len(items) > excel_io.EXPORT_MAX:
            raise AppError(
                f"내보내기는 최대 {excel_io.EXPORT_MAX:,}행까지 가능합니다. "
                f"(조건에 해당하는 자산 {result['total']:,}건) 검색 조건을 좁혀 주세요.")
        items = [_enrich(conn, i) for i in items]

        hist = None
        if with_history and items:                # 07-6
            ids = [i["id"] for i in items]
            rows = conn.execute(
                f"SELECT * FROM asset_history WHERE asset_id IN ({','.join('?' * len(ids))})"
                " ORDER BY asset_no, occurred_at DESC", ids).fetchall()
            hist = [format_history(r) for r in rows]

    content = excel_io.build_asset_export(items, fields, hist)
    with transaction() as conn:                   # 07-7 내보내기 로그
        conn.execute(
            "INSERT INTO export_log (actor, executed_at, scope, row_count, filter_json) VALUES (?,?,?,?,?)",
            (user["name"], now_str(), scope, len(items), jdump(f)))

    fname = excel_io.export_filename()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{urllib.parse.quote(fname)}"},
    )


# ---------------------------------------------------------------- 등록 (FR-02)
@router.post("")
def create_asset(payload: dict = Body(...), user: dict = Depends(require_user)):
    assign_payload = payload.get("assignment") or {}
    do_assign = bool(clean_str(assign_payload.get("emp_no")) or clean_str(assign_payload.get("user_name")))

    with transaction() as conn:
        values, warnings = validate_asset(conn, payload)
        status = ST_READY                          # 02-6 신규 기본 상태는 대기
        asg = None
        if do_assign:                              # 02-7
            asg, aw = validate_assignment_input(conn, assign_payload, values["purchase_date"], values["site"])
            warnings += aw
            status = ST_INUSE

        asset_id = insert_asset(conn, values, user, status=status, method="수동")
        add_history(conn, asset_id, values["asset_no"], HIST_CREATE, user["name"],
                    reason=clean_str(payload.get("reason")) or "신규 등록",
                    after={"status": status}, extra={"method": "수동"})

        if asg:
            create_assignment(conn, asset_id, asg, user)
            add_history(conn, asset_id, values["asset_no"], HIST_ASSIGN, user["name"],
                        reason=asg.get("assign_reason") or "등록 시 배정",
                        before={"user_name": None, "status": ST_READY},
                        after={"user_name": asg["user_name"], "emp_no": asg["emp_no"],
                               "dept_code": asg["dept_code"], "issue_date": asg["issue_date"],
                               "status": ST_INUSE})

    return {"id": asset_id, "asset_no": values["asset_no"], "warnings": warnings}


# ---------------------------------------------------------------- 상세 (FR-03)
@router.get("/{asset_id}")
def asset_detail(asset_id: int, user: dict = Depends(require_user)):
    with get_conn() as conn:
        asset = get_asset(conn, asset_id)
        asg = current_assignment(conn, asset_id)
        asset["assignment"] = asg
        asset["dept_label"] = dept_full_label(conn, asg["dept_code"]) if asg else None
        if asg and asg.get("emp_no"):
            emp = conn.execute("SELECT * FROM employee WHERE emp_no = ?", (asg["emp_no"],)).fetchone()
            asset["employee"] = dict(emp) if emp else None
        # 사용 이력 요약 (10-7)
        rows = conn.execute(
            """SELECT emp_no, user_name, dept_code, issue_date, return_date, return_reason
               FROM assignment WHERE asset_id = ? ORDER BY issue_date DESC, id DESC""",
            (asset_id,)).fetchall()
        asset["usage_history"] = [dict(r) for r in rows]
        # 삭제 가능 여부 (04-7)
        hist = conn.execute("SELECT hist_type FROM asset_history WHERE asset_id = ?", (asset_id,)).fetchall()
        only_create = len(hist) == 1 and hist[0]["hist_type"] == HIST_CREATE
        fresh = conn.execute(
            "SELECT (julianday('now','localtime') - julianday(created_at)) * 24 AS hrs FROM asset WHERE id = ?",
            (asset_id,)).fetchone()["hrs"]
        asset["can_delete"] = bool(only_create and fresh is not None and fresh <= 24)
        asset["allowed_status"] = STATUS_TRANSITIONS.get(asset["status"], [])
    return asset


# ---------------------------------------------------------------- 수정 (FR-04)
@router.put("/{asset_id}")
def update_asset(asset_id: int, payload: dict = Body(...), user: dict = Depends(require_user)):
    reason = clean_str(payload.get("reason"))
    if not reason:
        raise AppError("변경 사유를 입력하세요.", field="reason")     # 04-3
    if len(reason) > 200:
        raise AppError("변경 사유는 200자 이내로 입력하세요.", field="reason")

    with transaction() as conn:
        asset = get_asset(conn, asset_id)
        if asset["status"] == ST_DISPOSED:
            raise AppError("폐기 자산은 수정할 수 없습니다. (조회 전용)")   # 12-5
        if clean_str(payload.get("asset_no")) and payload["asset_no"] != asset["asset_no"]:
            raise AppError("자산번호는 수정할 수 없습니다. 오등록이면 삭제 후 재등록하세요.",
                           field="asset_no")                              # 04-2

        merged = {**{f: asset.get(f) for f in EDITABLE_FIELDS}, **{k: v for k, v in payload.items() if k in EDITABLE_FIELDS}}
        values, warnings = validate_asset(conn, merged, existing=asset)
        result = apply_update(conn, asset, values, reason, user)

    return {"ok": True, "changed": result["changed"], "warnings": warnings}


@router.post("/{asset_id}/preview-changes")
def preview_changes(asset_id: int, payload: dict = Body(...), user: dict = Depends(require_user)):
    """04-5 — 저장 전 변경 내용 요약."""
    from ..services.assets import FIELD_LABELS
    with get_conn() as conn:
        asset = get_asset(conn, asset_id)
        merged = {**{f: asset.get(f) for f in EDITABLE_FIELDS},
                  **{k: v for k, v in payload.items() if k in EDITABLE_FIELDS}}
        values, warnings = validate_asset(conn, merged, existing=asset)
    changes = []
    for f in EDITABLE_FIELDS:
        b, a = asset.get(f), values.get(f)
        if (b or None) != (a or None):
            changes.append({"field": f, "label": FIELD_LABELS.get(f, f), "before": b, "after": a})
    return {"changes": changes, "warnings": warnings}


# ---------------------------------------------------------------- 삭제 (FR-04-7~9)
@router.delete("/{asset_id}")
def delete_asset(asset_id: int, reason: str = "", user: dict = Depends(require_user)):
    reason = clean_str(reason)
    if not reason:
        raise AppError("삭제 사유를 입력하세요.", field="reason")
    with transaction() as conn:
        asset = get_asset(conn, asset_id)
        hist = conn.execute("SELECT hist_type FROM asset_history WHERE asset_id = ?", (asset_id,)).fetchall()
        hrs = conn.execute(
            "SELECT (julianday('now','localtime') - julianday(created_at)) * 24 AS hrs FROM asset WHERE id = ?",
            (asset_id,)).fetchone()["hrs"]
        if not (len(hist) == 1 and hist[0]["hist_type"] == HIST_CREATE) or (hrs or 999) > 24:
            raise AppError("등록 후 24시간이 지났거나 변경 이력이 있어 삭제할 수 없습니다. "
                           "대신 '폐기' 상태로 전환하세요.")                 # 04-8
        conn.execute(
            "INSERT INTO delete_log (asset_no, snapshot_json, reason, deleted_by, deleted_at) VALUES (?,?,?,?,?)",
            (asset["asset_no"], jdump(asset), reason, user["name"], now_str()))
        conn.execute("DELETE FROM asset_history WHERE asset_id = ?", (asset_id,))
        conn.execute("DELETE FROM assignment WHERE asset_id = ?", (asset_id,))
        conn.execute("DELETE FROM asset WHERE id = ?", (asset_id,))
    return {"ok": True}


# ---------------------------------------------------------------- 배정 (FR-08)
def _do_assign(conn, asset: dict, payload: dict, user: dict) -> list[str]:
    warnings: list[str] = []
    if asset["status"] == ST_DISPOSED:
        raise AppError("폐기 자산은 배정할 수 없습니다.")
    asg, w = validate_assignment_input(conn, payload, asset["purchase_date"], asset["site"])
    warnings += w

    prev = current_assignment(conn, asset["id"])
    if prev:
        # 사용자 교체: 회수 → 배정 두 이력을 자동 생성 (FR-08 배정 변경)
        if asg["issue_date"] < prev["issue_date"]:
            raise AppError(f"지급일은 이전 사용자의 지급일({prev['issue_date']})보다 이전일 수 없습니다.",
                           field="issue_date")
        close_assignment(conn, asset["id"], asg["issue_date"], "장비교체")
        add_history(conn, asset["id"], asset["asset_no"], HIST_RETURN, user["name"],
                    reason="사용자 교체에 따른 자동 회수",
                    before={"user_name": prev["user_name"], "emp_no": prev["emp_no"]},
                    after={"user_name": None, "emp_no": None, "return_date": asg["issue_date"]})
    elif asset["status"] != ST_READY:
        raise AppError(f"'{asset['status']}' 상태의 자산은 배정할 수 없습니다. "
                       f"대기 상태로 전환 후 배정하세요.")                    # 08-1

    create_assignment(conn, asset["id"], asg, user)
    conn.execute("UPDATE asset SET status = ?, location = COALESCE(?, location), site = ?,"
                 " updated_at = ?, updated_by = ? WHERE id = ?",
                 (ST_INUSE, asg["location"], asg["site"], now_str(), user["name"], asset["id"]))
    add_history(conn, asset["id"], asset["asset_no"], HIST_ASSIGN, user["name"],
                reason=asg.get("assign_reason") or "자산 배정",
                before={"user_name": prev["user_name"] if prev else None,
                        "emp_no": prev["emp_no"] if prev else None,
                        "status": asset["status"]},
                after={"user_name": asg["user_name"], "emp_no": asg["emp_no"],
                       "dept_code": asg["dept_code"], "issue_date": asg["issue_date"],
                       "status": ST_INUSE})
    return warnings


@router.post("/{asset_id}/assign")
def assign(asset_id: int, payload: dict = Body(...), user: dict = Depends(require_user)):
    with transaction() as conn:
        asset = get_asset(conn, asset_id)
        warnings = _do_assign(conn, asset, payload, user)
    return {"ok": True, "warnings": warnings}


# ---------------------------------------------------------------- 회수 (FR-09)
def _do_return(conn, asset: dict, payload: dict, user: dict) -> None:
    if asset["status"] not in (ST_INUSE, ST_REPAIR):
        raise AppError(f"'{asset['status']}' 상태의 자산은 회수할 수 없습니다.")   # 09-1

    return_date = parse_date(payload.get("return_date"), "회수일") or today_str()
    reason = validate_code(conn, "RETURN_REASON", payload.get("return_reason"), "회수 사유", required=True)
    after_status = clean_str(payload.get("after_status")) or ST_READY
    if after_status not in (ST_READY, ST_REPAIR, ST_TO_DISPOSE):
        raise AppError("회수 후 상태는 대기 / 수리 / 폐기예정 중 하나여야 합니다.", field="after_status")

    prev = current_assignment(conn, asset["id"])
    if prev and return_date < prev["issue_date"]:
        raise AppError(f"회수일({return_date})은 지급일({prev['issue_date']})보다 이전일 수 없습니다.",
                       field="return_date")                                   # 09-7

    close_assignment(conn, asset["id"], return_date, reason)
    conn.execute("UPDATE asset SET status = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                 (after_status, now_str(), user["name"], asset["id"]))

    note = clean_str(payload.get("remark"))
    add_history(conn, asset["id"], asset["asset_no"], HIST_RETURN, user["name"],
                reason=reason + (f" — {note}" if note else ""),
                before={"user_name": prev["user_name"] if prev else None,
                        "emp_no": prev["emp_no"] if prev else None,
                        "status": asset["status"]},
                after={"user_name": None, "emp_no": None,
                       "return_date": return_date, "status": after_status})


@router.post("/{asset_id}/return")
def do_return(asset_id: int, payload: dict = Body(...), user: dict = Depends(require_user)):
    with transaction() as conn:
        asset = get_asset(conn, asset_id)
        _do_return(conn, asset, payload, user)
    return {"ok": True}


# ---------------------------------------------------------------- 상태 변경 (FR-12)
def _do_status(conn, asset: dict, payload: dict, user: dict) -> None:
    new_status = validate_code(conn, "STATUS", payload.get("status"), "자산상태", required=True)
    cur = asset["status"]
    if new_status == cur:
        raise AppError(f"이미 '{cur}' 상태입니다.")
    allowed = STATUS_TRANSITIONS.get(cur, [])
    if new_status not in allowed:
        msg = STATUS_BLOCK_MESSAGE.get((cur, new_status))
        if not msg:
            msg = (f"'{cur}' → '{new_status}' 전환은 허용되지 않습니다."
                   + (f" 가능한 전환: {', '.join(allowed)}" if allowed else " 폐기는 최종 상태입니다."))
        raise AppError(msg)                                                   # 12-1, 12-6

    reason = clean_str(payload.get("reason"))
    if not reason:
        raise AppError("상태 변경 사유를 입력하세요.", field="reason")          # 12-2

    fields, after = {}, {"status": new_status}
    if new_status == ST_DISPOSED:                                             # 12-3
        d = parse_date(payload.get("disposal_date"), "폐기일") or today_str()
        m = validate_code(conn, "DISPOSAL_METHOD", payload.get("disposal_method"), "폐기방법", required=True)
        if d < asset["purchase_date"]:
            raise AppError("폐기일은 구매일보다 이전일 수 없습니다.", field="disposal_date")
        fields = {"disposal_date": d, "disposal_method": m}
        after.update(fields)
    elif cur == ST_TO_DISPOSE and new_status == ST_READY:
        fields = {"disposal_date": None, "disposal_method": None}

    if new_status == ST_INUSE and not current_assignment(conn, asset["id"]):
        raise AppError("배정된 사용자가 없어 '사용중'으로 전환할 수 없습니다. 배정 처리를 먼저 하세요.")

    sets = "".join(f", {k} = ?" for k in fields)
    conn.execute(f"UPDATE asset SET status = ?{sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                 [new_status] + list(fields.values()) + [now_str(), user["name"], asset["id"]])

    add_history(conn, asset["id"], asset["asset_no"],
                HIST_DISPOSE if new_status == ST_DISPOSED else HIST_STATUS,
                user["name"], reason=reason, before={"status": cur}, after=after)


@router.post("/{asset_id}/status")
def change_status(asset_id: int, payload: dict = Body(...), user: dict = Depends(require_user)):
    with transaction() as conn:
        asset = get_asset(conn, asset_id)
        _do_status(conn, asset, payload, user)
    return {"ok": True}


# ---------------------------------------------------------------- 일괄 처리 (08-10, 09-6, 12-7)
class BulkIn(BaseModel):
    ids: list[int]
    payload: dict = {}


def _bulk(ids: list[int], fn, user: dict) -> dict:
    if not ids:
        raise AppError("대상 자산을 선택하세요.")
    if len(ids) > 500:
        raise AppError("한 번에 최대 500건까지 처리할 수 있습니다.")
    ok, failed = [], []
    for aid in ids:
        try:
            with transaction() as conn:
                asset = get_asset(conn, aid)
                fn(conn, asset, user)
            ok.append(aid)
        except AppError as e:
            failed.append({"id": aid, "asset_no": _asset_no(aid), "error": e.message})
        except Exception:                     # 개별 실패가 나머지를 막지 않는다
            failed.append({"id": aid, "asset_no": _asset_no(aid), "error": "처리 중 오류가 발생했습니다."})
    return {"success": len(ok), "failed": failed}


def _asset_no(asset_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT asset_no FROM asset WHERE id = ?", (asset_id,)).fetchone()
    return row["asset_no"] if row else str(asset_id)


@bulk_router.post("/return")
def bulk_return(body: BulkIn, user: dict = Depends(require_user)):
    return _bulk(body.ids, lambda c, a, u: _do_return(c, a, body.payload, u), user)


@bulk_router.post("/status")
def bulk_status(body: BulkIn, user: dict = Depends(require_user)):
    return _bulk(body.ids, lambda c, a, u: _do_status(c, a, body.payload, u), user)


@bulk_router.post("/assign")
def bulk_assign(body: BulkIn, user: dict = Depends(require_user)):
    return _bulk(body.ids, lambda c, a, u: _do_assign(c, a, body.payload, u), user)


# ---------------------------------------------------------------- 자산별 이력 (FR-10)
@router.get("/{asset_id}/history")
def asset_history(asset_id: int, hist_type: str = "", user: dict = Depends(require_user)):
    sql = "SELECT * FROM asset_history WHERE asset_id = ?"
    params: list = [asset_id]
    types = [t for t in (hist_type or "").split(",") if t.strip()]
    if types:
        sql += f" AND hist_type IN ({','.join('?' * len(types))})"
        params += types
    sql += " ORDER BY occurred_at DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"items": [format_history(r) for r in rows]}
