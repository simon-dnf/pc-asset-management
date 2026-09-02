"""통합 이력 조회 및 내보내기 (FR-10-5, FR-10-6)."""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, Response

from ..auth import require_user
from ..core import HIST_LABELS, clean_str
from ..db import get_conn
from ..services import excel_io
from ..services.histfmt import format_history

router = APIRouter(prefix="/history", tags=["history"])


def _build(asset_no: str, hist_type: str, actor: str, date_from: str, date_to: str, q: str):
    where, params = [], []
    if clean_str(asset_no):
        where.append("asset_no LIKE ?")
        params.append(f"%{asset_no.strip()}%")
    types = [t for t in (hist_type or "").split(",") if t.strip()]
    if types:
        where.append(f"hist_type IN ({','.join('?' * len(types))})")
        params += types
    if clean_str(actor):
        where.append("actor LIKE ?")
        params.append(f"%{actor.strip()}%")
    if clean_str(date_from):
        where.append("occurred_at >= ?")
        params.append(date_from.strip() + " 00:00:00")
    if clean_str(date_to):
        where.append("occurred_at <= ?")
        params.append(date_to.strip() + " 23:59:59")
    if clean_str(q):
        where.append("(reason LIKE ? OR before_json LIKE ? OR after_json LIKE ?)")
        params += [f"%{q.strip()}%"] * 3
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


@router.get("/types")
def types(user: dict = Depends(require_user)):
    return {"items": [{"code": k, "label": v} for k, v in HIST_LABELS.items()]}


@router.get("")
def list_history(asset_no: str = "", hist_type: str = "", actor: str = "",
                 date_from: str = "", date_to: str = "", q: str = "",
                 page: int = 1, size: int = 30, user: dict = Depends(require_user)):
    clause, params = _build(asset_no, hist_type, actor, date_from, date_to, q)
    size = max(1, min(int(size), 200))
    page = max(1, int(page))
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM asset_history{clause}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM asset_history{clause} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size]).fetchall()
    return {"total": total, "page": page, "size": size,
            "items": [format_history(r) for r in rows]}


@router.get("/export.xlsx")
def export_history(asset_no: str = "", hist_type: str = "", actor: str = "",
                   date_from: str = "", date_to: str = "", q: str = "",
                   user: dict = Depends(require_user)):
    clause, params = _build(asset_no, hist_type, actor, date_from, date_to, q)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM asset_history{clause} ORDER BY occurred_at DESC, id DESC LIMIT ?",
            params + [excel_io.EXPORT_MAX]).fetchall()
    items = [format_history(r) for r in rows]
    content = excel_io.build_generic_export(
        "변경이력",
        ["발생일시", "자산번호", "이력유형", "변경자", "사유", "변경 내용"],
        [[i["occurred_at"], i["asset_no"], i["hist_type_label"], i["actor"],
          i.get("reason") or "", i["summary"]] for i in items])
    fname = excel_io.export_filename("변경이력")
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{urllib.parse.quote(fname)}"})
