"""자산 도메인 로직: 검증, 등록/수정/삭제, 이력 적재 (FR-02, FR-03, FR-04, FR-10)."""
from __future__ import annotations

from ..core import (
    AppError, HIST_CREATE, HIST_MOVE, HIST_UPDATE, MOVE_FIELDS, ST_DISPOSED, ST_INUSE,
    ST_READY, clean_str, jdump, now_str, parse_asset_no, parse_date, parse_int, parse_ip,
    parse_mac, today_str,
)
from .lookup import employee_of, validate_code

# 화면·엑셀·이력에서 공통으로 쓰는 필드 라벨
FIELD_LABELS: dict[str, str] = {
    "asset_no": "자산번호",
    "asset_type": "자산구분",
    "manufacturer": "제조사",
    "model_name": "모델명",
    "serial_no": "시리얼번호",
    "purchase_date": "구매일",
    "service_start_date": "사용시작일",
    "status": "자산상태",
    "purchase_amount": "취득금액",
    "useful_life_years": "내용연수",
    "remark": "비고",
    "site": "사업장",
    "location": "위치",
    "manager_emp_no": "자산관리 담당자",
    "hostname": "Hostname",
    "ip_address": "IP 주소",
    "ip_type": "IP 구분",
    "mac_address": "MAC 주소",
    "cpu": "CPU",
    "ram_gb": "RAM(GB)",
    "disk_type": "디스크 유형",
    "disk_gb": "디스크 용량(GB)",
    "os": "운영체제",
    "os_eol_date": "OS 지원종료일",
    "disposal_date": "폐기일",
    "disposal_method": "폐기방법",
    # 배정 관련(이력 표시용)
    "user_name": "사용자명",
    "emp_no": "사번",
    "dept_code": "소속부서",
    "position_code": "직급",
    "issue_date": "지급일",
    "due_return_date": "반납예정일",
    "return_date": "회수일",
}

# 수정 가능한 자산 필드 (자산번호·상태·폐기정보 제외 — FR-04-2, FR-12)
EDITABLE_FIELDS = [
    "asset_type", "manufacturer", "model_name", "serial_no", "purchase_date",
    "service_start_date", "purchase_amount", "useful_life_years", "remark",
    "site", "location", "manager_emp_no",
    "hostname", "ip_address", "ip_type", "mac_address", "cpu", "ram_gb",
    "disk_type", "disk_gb", "os", "os_eol_date",
]


# ---------------------------------------------------------------- 이력
def add_history(conn, asset_id: int, asset_no: str, hist_type: str, actor: str,
                reason: str | None = None, before: dict | None = None,
                after: dict | None = None, extra: dict | None = None,
                occurred_at: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO asset_history
           (asset_id, asset_no, hist_type, occurred_at, actor, reason, before_json, after_json, extra_json)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (asset_id, asset_no, hist_type, occurred_at or now_str(), actor, clean_str(reason),
         jdump(before or {}), jdump(after or {}), jdump(extra or {})),
    )
    return cur.lastrowid


# ---------------------------------------------------------------- 검증
def validate_asset(conn, data: dict, existing: dict | None = None) -> tuple[dict, list[str]]:
    """자산 입력값을 정규화·검증한다. (정규화 결과, 경고 목록)을 돌려준다.

    경고는 저장을 막지 않는다 (FR-02-5: Hostname/IP 중복은 경고).
    """
    out: dict = {}
    warnings: list[str] = []

    def old(f):
        return existing.get(f) if existing else None

    # --- 자산번호 (신규만)
    if existing is None:
        out["asset_no"] = parse_asset_no(data.get("asset_no"))

    # --- 필수 코드/문자
    out["asset_type"] = validate_code(conn, "ASSET_TYPE", data.get("asset_type"), "자산구분",
                                      required=True, allow_inactive_existing=old("asset_type"))
    out["manufacturer"] = validate_code(conn, "MANUFACTURER", data.get("manufacturer"), "제조사",
                                        required=True, allow_inactive_existing=old("manufacturer"))
    out["model_name"] = clean_str(data.get("model_name"))
    if not out["model_name"]:
        raise AppError("모델명은 필수입니다.", field="model_name")

    out["site"] = validate_code(conn, "SITE", data.get("site"), "사업장",
                                required=True, allow_inactive_existing=old("site"))
    out["location"] = clean_str(data.get("location"))

    out["manager_emp_no"] = clean_str(data.get("manager_emp_no"))
    if not out["manager_emp_no"]:
        raise AppError("자산관리 담당자는 필수입니다.", field="manager_emp_no")

    # --- 날짜
    out["purchase_date"] = parse_date(data.get("purchase_date"), "구매일")
    if not out["purchase_date"]:
        raise AppError("구매일은 필수입니다.", field="purchase_date")
    if out["purchase_date"] > today_str():
        raise AppError(f"구매일은 미래 날짜일 수 없습니다: {out['purchase_date']}", field="purchase_date")

    out["service_start_date"] = parse_date(data.get("service_start_date"), "사용시작일")
    if out["service_start_date"] and out["service_start_date"] < out["purchase_date"]:
        raise AppError("사용시작일은 구매일보다 이전일 수 없습니다.", field="service_start_date")

    out["os_eol_date"] = parse_date(data.get("os_eol_date"), "OS 지원종료일")

    # --- 숫자
    out["purchase_amount"] = parse_int(data.get("purchase_amount"), "취득금액", 0, 9_999_999_999)
    out["useful_life_years"] = parse_int(data.get("useful_life_years"), "내용연수", 1, 50)
    out["ram_gb"] = parse_int(data.get("ram_gb"), "RAM", 1, 1024)
    out["disk_gb"] = parse_int(data.get("disk_gb"), "디스크 용량", 1, 100_000)

    # --- 선택 코드
    out["disk_type"] = validate_code(conn, "DISK_TYPE", data.get("disk_type"), "디스크 유형",
                                     allow_inactive_existing=old("disk_type"))
    out["os"] = validate_code(conn, "OS", data.get("os"), "운영체제",
                              allow_inactive_existing=old("os"))
    ip_type = clean_str(data.get("ip_type"))
    if ip_type and ip_type not in ("고정", "DHCP"):
        raise AppError(f"IP 구분은 '고정' 또는 'DHCP'여야 합니다: '{ip_type}'", field="ip_type")
    out["ip_type"] = ip_type

    # --- 형식 검증
    out["serial_no"] = clean_str(data.get("serial_no"))
    out["hostname"] = clean_str(data.get("hostname"))
    out["ip_address"] = parse_ip(data.get("ip_address"))
    out["mac_address"] = parse_mac(data.get("mac_address"))
    out["cpu"] = clean_str(data.get("cpu"))
    out["remark"] = clean_str(data.get("remark"))

    # --- 유니크 (02-3, 02-4)
    asset_id = existing["id"] if existing else -1
    if existing is None:
        dup = conn.execute("SELECT asset_no FROM asset WHERE asset_no = ?", (out["asset_no"],)).fetchone()
        if dup:
            raise AppError(f"이미 등록된 자산번호입니다 (자산: {dup['asset_no']})", field="asset_no")

    if out["serial_no"]:
        dup = conn.execute(
            "SELECT asset_no FROM asset WHERE serial_no = ? AND id <> ?", (out["serial_no"], asset_id)
        ).fetchone()
        if dup:
            raise AppError(f"이미 등록된 시리얼번호입니다 (자산: {dup['asset_no']})", field="serial_no")

    # --- 중복 경고 (02-5): 차단하지 않는다
    if out["hostname"]:
        dup = conn.execute(
            "SELECT asset_no FROM asset WHERE hostname = ? AND id <> ? AND status <> ?",
            (out["hostname"], asset_id, ST_DISPOSED),
        ).fetchone()
        if dup:
            warnings.append(f"Hostname '{out['hostname']}'이(가) 자산 {dup['asset_no']}에 이미 사용 중입니다.")
    if out["ip_address"]:
        dup = conn.execute(
            "SELECT asset_no FROM asset WHERE ip_address = ? AND id <> ? AND status <> ?",
            (out["ip_address"], asset_id, ST_DISPOSED),
        ).fetchone()
        if dup:
            warnings.append(f"IP 주소 '{out['ip_address']}'이(가) 자산 {dup['asset_no']}에 이미 사용 중입니다.")

    return out, warnings


def validate_assignment_input(conn, data: dict, purchase_date: str, site_fallback: str) -> tuple[dict, list[str]]:
    """배정 입력 검증 (FR-08)."""
    warnings: list[str] = []
    emp_no = clean_str(data.get("emp_no"))
    user_name = clean_str(data.get("user_name"))
    emp = employee_of(conn, emp_no) if emp_no else None

    if emp:
        user_name = user_name or emp["name"]
        if emp["employ_status"] == "퇴사":
            warnings.append(f"{emp['name']}({emp_no})은(는) 퇴사 처리된 임직원입니다.")
    elif emp_no:
        # 08-4 — 마스터에 없는 사번은 경고 후 허용
        warnings.append(f"사번 {emp_no}은(는) 임직원 마스터에 없습니다. 입력한 값으로 저장합니다.")

    if not user_name:
        raise AppError("사용자명은 필수입니다.", field="user_name")
    if not emp_no:
        raise AppError("사번은 필수입니다.", field="emp_no")

    dept = clean_str(data.get("dept_code")) or (emp["dept_code"] if emp else None)
    position = clean_str(data.get("position_code")) or (emp["position_code"] if emp else None)
    if dept:
        dept = validate_code(conn, "DEPT", dept, "소속부서")
    if position:
        position = validate_code(conn, "POSITION", position, "직급")

    site = validate_code(conn, "SITE", data.get("site") or site_fallback, "사업장", required=True)

    issue_date = parse_date(data.get("issue_date"), "지급일") or today_str()
    if issue_date < purchase_date:
        raise AppError(f"지급일({issue_date})은 구매일({purchase_date})보다 이전일 수 없습니다.", field="issue_date")

    due = parse_date(data.get("due_return_date"), "반납예정일")
    if due and due < issue_date:
        raise AppError("반납예정일은 지급일보다 이전일 수 없습니다.", field="due_return_date")

    return {
        "emp_no": emp_no,
        "user_name": user_name,
        "dept_code": dept,
        "position_code": position,
        "site": site,
        "location": clean_str(data.get("location")),
        "issue_date": issue_date,
        "due_return_date": due,
        "assign_reason": clean_str(data.get("reason")),
    }, warnings


# ---------------------------------------------------------------- 등록
def insert_asset(conn, values: dict, user: dict, status: str = ST_READY,
                 method: str = "수동", batch_id: int | None = None) -> int:
    cols = ["asset_no"] + EDITABLE_FIELDS + [
        "status", "disposal_date", "disposal_method",
        "created_at", "created_by", "created_method", "import_batch_id", "updated_at", "updated_by",
    ]
    now = now_str()
    row = {c: values.get(c) for c in cols}
    row["status"] = status
    row["disposal_date"] = values.get("disposal_date")
    row["disposal_method"] = values.get("disposal_method")
    row["created_at"] = now
    row["created_by"] = user["name"]
    row["created_method"] = method
    row["import_batch_id"] = batch_id
    row["updated_at"] = now
    row["updated_by"] = user["name"]

    placeholders = ",".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO asset ({','.join(cols)}) VALUES ({placeholders})",
        tuple(row[c] for c in cols),
    )
    return cur.lastrowid


def create_assignment(conn, asset_id: int, asg: dict, user: dict) -> int:
    cur = conn.execute(
        """INSERT INTO assignment
           (asset_id, emp_no, user_name, dept_code, position_code, site, location,
            issue_date, due_return_date, assign_reason, is_current, created_at, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
        (asset_id, asg["emp_no"], asg["user_name"], asg["dept_code"], asg["position_code"],
         asg["site"], asg["location"], asg["issue_date"], asg["due_return_date"],
         asg.get("assign_reason"), now_str(), user["name"]),
    )
    aid = cur.lastrowid
    conn.execute("UPDATE asset SET current_assignment_id = ? WHERE id = ?", (aid, asset_id))
    return aid


def close_assignment(conn, asset_id: int, return_date: str, reason: str | None) -> dict | None:
    row = conn.execute(
        "SELECT * FROM assignment WHERE asset_id = ? AND is_current = 1", (asset_id,)
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE assignment SET is_current = 0, return_date = ?, return_reason = ? WHERE id = ?",
        (return_date, reason, row["id"]),
    )
    conn.execute("UPDATE asset SET current_assignment_id = NULL WHERE id = ?", (asset_id,))
    return dict(row)


def get_asset(conn, asset_id: int) -> dict:
    row = conn.execute("SELECT * FROM asset WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        raise AppError("자산을 찾을 수 없습니다.", 404)
    return dict(row)


def current_assignment(conn, asset_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM assignment WHERE asset_id = ? AND is_current = 1", (asset_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- 수정
def apply_update(conn, asset: dict, new_values: dict, reason: str, user: dict) -> dict:
    """실제로 바뀐 필드만 골라 UPDATE 하고 이력을 남긴다 (FR-04-4, FR-04-6)."""
    changed: dict[str, tuple] = {}
    for f in EDITABLE_FIELDS:
        if f not in new_values:
            continue
        before, after = asset.get(f), new_values.get(f)
        if (before or None) != (after or None):
            changed[f] = (before, after)

    if not changed:
        return {"changed": {}, "history_ids": []}

    sets = ", ".join(f"{f} = ?" for f in changed)
    params = [changed[f][1] for f in changed] + [now_str(), user["name"], asset["id"]]
    conn.execute(f"UPDATE asset SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?", params)

    # 배정이 살아있으면 사업장/위치 변경을 현재 배정에도 반영한다
    if changed.keys() & MOVE_FIELDS:
        conn.execute(
            "UPDATE assignment SET site = ?, location = ? WHERE asset_id = ? AND is_current = 1",
            (new_values.get("site", asset["site"]), new_values.get("location", asset["location"]), asset["id"]),
        )

    hist_ids = []
    move = {f: v for f, v in changed.items() if f in MOVE_FIELDS}
    upd = {f: v for f, v in changed.items() if f not in MOVE_FIELDS}
    for htype, group in ((HIST_MOVE, move), (HIST_UPDATE, upd)):
        if group:
            hist_ids.append(add_history(
                conn, asset["id"], asset["asset_no"], htype, user["name"], reason,
                before={f: group[f][0] for f in group},
                after={f: group[f][1] for f in group},
            ))
    return {"changed": {f: {"before": v[0], "after": v[1]} for f, v in changed.items()},
            "history_ids": hist_ids}


def update_assignment_dept(conn, asset_id: int, dept_code: str | None, position_code: str | None) -> None:
    conn.execute(
        "UPDATE assignment SET dept_code = COALESCE(?, dept_code), position_code = COALESCE(?, position_code)"
        " WHERE asset_id = ? AND is_current = 1",
        (dept_code, position_code, asset_id),
    )
