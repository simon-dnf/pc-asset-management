"""대시보드 집계 및 조치 필요 목록 (FR-11, FR-15)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import require_user
from ..core import (
    ALL_STATUSES, HOLDING_STATUSES, ST_DISPOSED, ST_INUSE, ST_REPAIR, ST_TO_DISPOSE,
    clean_str, plus_days, today_str,
)
from ..db import get_conn
from ..services.histfmt import format_history

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ACTION_SQL = {
    # 반납예정일 초과 (11-5 ①, 15-1)
    "overdue": ("""SELECT a.id, a.asset_no, a.model_name, a.site, g.user_name, g.emp_no,
                          g.due_return_date AS info
                   FROM asset a JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                   WHERE a.status = ? AND g.due_return_date IS NOT NULL AND g.due_return_date < ?
                   ORDER BY g.due_return_date""", lambda: [ST_INUSE, today_str()]),
    # 7일 이내 반납 예정 (15-2)
    "due_soon": ("""SELECT a.id, a.asset_no, a.model_name, a.site, g.user_name, g.emp_no,
                           g.due_return_date AS info
                    FROM asset a JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                    WHERE a.status = ? AND g.due_return_date BETWEEN ? AND ?
                    ORDER BY g.due_return_date""", lambda: [ST_INUSE, today_str(), plus_days(7)]),
    # 사용중인데 사용자 미지정 (11-5 ②)
    "unassigned": ("""SELECT a.id, a.asset_no, a.model_name, a.site, NULL AS user_name,
                             NULL AS emp_no, a.updated_at AS info
                      FROM asset a LEFT JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                      WHERE a.status = ? AND g.id IS NULL ORDER BY a.updated_at""",
                   lambda: [ST_INUSE]),
    # 30일 이상 수리 (11-5 ③)
    "long_repair": ("""SELECT a.id, a.asset_no, a.model_name, a.site, g.user_name, g.emp_no,
                              a.updated_at AS info
                       FROM asset a LEFT JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                       WHERE a.status = ? AND a.updated_at <= ? ORDER BY a.updated_at""",
                    lambda: [ST_REPAIR, plus_days(-30) + " 23:59:59"]),
    # 폐기예정 미처리 (11-5 ④)
    "to_dispose": ("""SELECT a.id, a.asset_no, a.model_name, a.site, NULL AS user_name,
                             NULL AS emp_no, a.updated_at AS info
                      FROM asset a WHERE a.status = ? ORDER BY a.updated_at""",
                   lambda: [ST_TO_DISPOSE]),
    # 퇴사자 미회수 자산 (15-3)
    "resigned": ("""SELECT a.id, a.asset_no, a.model_name, a.site, g.user_name, g.emp_no,
                           e.employ_status AS info
                    FROM asset a JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                    JOIN employee e ON e.emp_no = g.emp_no
                    WHERE a.status = ? AND e.employ_status = '퇴사' ORDER BY g.issue_date""",
                 lambda: [ST_INUSE]),
    # 내용연수 초과 (11-6)
    "aged": ("""SELECT a.id, a.asset_no, a.model_name, a.site, g.user_name, g.emp_no,
                       a.purchase_date AS info
                FROM asset a LEFT JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                WHERE a.status <> ?
                  AND a.purchase_date <= date('now','localtime','-' ||
                      (CASE WHEN a.useful_life_years IS NULL THEN 5 ELSE a.useful_life_years END)
                      || ' years')
                ORDER BY a.purchase_date""", lambda: [ST_DISPOSED]),
}


def _period(date_from: str, date_to: str) -> tuple[str, list]:
    """11-8 기간 필터 — 자산의 '구매일'을 기준으로 집계 대상을 좁힌다.

    조치 필요 목록(11-5)은 '지금 처리해야 할 일'이므로 기간과 무관하게 항상 전체를 본다.
    """
    clause, params = "", []
    if clean_str(date_from):
        clause += " AND a.purchase_date >= ?"
        params.append(date_from.strip())
    if clean_str(date_to):
        clause += " AND a.purchase_date <= ?"
        params.append(date_to.strip())
    return clause, params


@router.get("")
def dashboard(date_from: str = "", date_to: str = "", user: dict = Depends(require_user)):
    period, pp = _period(date_from, date_to)

    with get_conn() as conn:
        # 11-1 요약 카드
        counts = {s: 0 for s in ALL_STATUSES}
        for r in conn.execute(
                f"SELECT a.status, COUNT(*) c FROM asset a WHERE 1=1{period} GROUP BY a.status",
                pp).fetchall():
            counts[r["status"]] = r["c"]
        summary = {
            "holding": sum(counts[s] for s in HOLDING_STATUSES),
            **{s: counts[s] for s in ALL_STATUSES},
        }

        # 11-2 사업장 × 상태 교차 집계
        site_rows = conn.execute(
            f"""SELECT a.site, a.status, COUNT(*) c FROM asset a
                WHERE a.status <> ?{period} GROUP BY a.site, a.status""",
            [ST_DISPOSED] + pp).fetchall()
        sites: dict[str, dict] = {}
        for r in site_rows:
            entry = sites.setdefault(r["site"], {"site": r["site"], "total": 0,
                                                 **{s: 0 for s in HOLDING_STATUSES}})
            entry[r["status"]] = r["c"]
            entry["total"] += r["c"]
        site_list = sorted(sites.values(), key=lambda x: -x["total"])

        # 11-3 부서별 보유 대수
        dept_rows = conn.execute(
            f"""SELECT COALESCE(g.dept_code, '(미지정)') dept, COUNT(*) c
                FROM asset a LEFT JOIN assignment g ON g.asset_id = a.id AND g.is_current = 1
                WHERE a.status <> ?{period} GROUP BY dept ORDER BY c DESC""",
            [ST_DISPOSED] + pp).fetchall()
        depts = [{"dept": r["dept"], "count": r["c"]} for r in dept_rows]

        # 11-4 자산구분별 비율
        type_rows = conn.execute(
            f"""SELECT a.asset_type, COUNT(*) c FROM asset a
                WHERE a.status <> ?{period} GROUP BY a.asset_type ORDER BY c DESC""",
            [ST_DISPOSED] + pp).fetchall()
        total_holding = summary["holding"] or 1
        types = [{"type": r["asset_type"], "count": r["c"],
                  "ratio": round(r["c"] * 100 / total_holding, 1)} for r in type_rows]

        # 11-5 / 11-6 / 15-x 조치 필요
        actions = {}
        for key, (sql, params_fn) in ACTION_SQL.items():
            rows = conn.execute(sql, params_fn()).fetchall()
            actions[key] = {"count": len(rows), "items": [dict(r) for r in rows[:20]]}

        # 11-7 최근 7일 변경 이력 10건
        recent = conn.execute(
            """SELECT * FROM asset_history WHERE occurred_at >= ?
               ORDER BY occurred_at DESC, id DESC LIMIT 10""",
            (plus_days(-7) + " 00:00:00",)).fetchall()

    return {
        "summary": summary,
        "sites": site_list,
        "depts": depts,
        "types": types,
        "actions": actions,
        "recent_history": [format_history(r) for r in recent],
        "generated_at": today_str(),
        "period": {"date_from": clean_str(date_from), "date_to": clean_str(date_to)},
    }
