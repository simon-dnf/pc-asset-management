"""OS 지원종료일(EOL) 외부 연동 API."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..auth import require_user
from ..core import AppError, ST_DISPOSED, clean_str, plus_days, today_str
from ..db import get_conn, transaction
from ..services import eol as eol_svc

router = APIRouter(prefix="/eol", tags=["eol"])


@router.get("")
def view(refresh: bool = False, user: dict = Depends(require_user)):
    """OS별 매핑·추천·반영 대상 건수. `refresh=true`일 때만 외부 API를 호출한다."""
    with transaction() as conn:          # 캐시를 갱신할 수 있으므로 쓰기 커넥션
        return eol_svc.build_view(conn, force=refresh)


@router.post("/apply")
def apply(payload: dict = Body(...), user: dict = Depends(require_user)):
    mapping = payload.get("mapping") or {}
    if not isinstance(mapping, dict) or not mapping:
        raise AppError("반영할 OS를 하나 이상 선택하세요.")
    clean = {str(k): clean_str(v) for k, v in mapping.items() if clean_str(v)}
    if not clean:
        raise AppError("반영할 OS를 하나 이상 선택하세요.")
    with transaction() as conn:
        return eol_svc.apply_eol(conn, clean, user)


@router.get("/summary")
def summary(user: dict = Depends(require_user)):
    """대시보드·목록에서 쓰는 집계. 외부 호출 없이 DB만 읽는다 (NFR-15)."""
    today = today_str()
    soon = plus_days(365)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT os,
                      COUNT(*) total,
                      SUM(CASE WHEN os_eol_date IS NOT NULL AND os_eol_date < ? THEN 1 ELSE 0 END) expired,
                      SUM(CASE WHEN os_eol_date IS NOT NULL AND os_eol_date >= ? AND os_eol_date <= ?
                               THEN 1 ELSE 0 END) soon,
                      MIN(os_eol_date) earliest_eol
               FROM asset WHERE status <> ? AND os IS NOT NULL
               GROUP BY os ORDER BY expired DESC, soon DESC""",
            (today, today, soon, ST_DISPOSED)).fetchall()
    items = [dict(r) for r in rows]
    return {
        "items": items,
        "expired_total": sum(i["expired"] or 0 for i in items),
        "soon_total": sum(i["soon"] or 0 for i in items),
        "as_of": today,
    }
