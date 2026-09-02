"""엑셀 가져오기 엔진: 행 단위 검증 → 오류 리포트 → 확정 (FR-06)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..core import (
    AppError, HIST_ASSIGN, HIST_CREATE, HIST_UPDATE, ST_DISPOSED, ST_INUSE, ST_READY,
    clean_str, now_dt, now_str, parse_asset_no, parse_date, parse_int, parse_ip, parse_mac,
    today_str,
)
from ..db import DATA_DIR
from .assets import EDITABLE_FIELDS, add_history, create_assignment, insert_asset
from .excel_io import COLUMNS, parse_file, suggest_mapping
from .lookup import code_labels, suggest

UPLOAD_DIR = DATA_DIR / "uploads"


# ---------------------------------------------------------------- 업로드 임시 보관
def save_upload(filename: str, content: bytes, kind: str) -> dict:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    header, body = parse_file(filename, content)          # 여기서 형식/행수 검증
    token = uuid.uuid4().hex
    (UPLOAD_DIR / f"{token}.bin").write_bytes(content)
    meta = {"token": token, "kind": kind, "filename": filename,
            "uploaded_at": now_str(), "rows": len(body)}
    (UPLOAD_DIR / f"{token}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _cleanup()
    return {"meta": meta, "header": header, "body": body}


def load_upload(token: str) -> tuple[dict, list[str], list[list]]:
    if not token or not token.isalnum():
        raise AppError("업로드 정보를 찾을 수 없습니다. 파일을 다시 올려주세요.", 404)
    mp = UPLOAD_DIR / f"{token}.json"
    bp = UPLOAD_DIR / f"{token}.bin"
    if not mp.exists() or not bp.exists():
        raise AppError("업로드 파일이 만료되었습니다. 처음부터 다시 진행해 주세요.", 404)
    meta = json.loads(mp.read_text(encoding="utf-8"))
    header, body = parse_file(meta["filename"], bp.read_bytes())
    return meta, header, body


def _cleanup(max_age_hours: int = 12) -> None:
    """오래된 임시 업로드 파일을 정리한다."""
    cutoff = now_dt().timestamp() - max_age_hours * 3600
    for p in UPLOAD_DIR.glob("*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- 행 → dict
def row_to_data(header: list[str], row: list, mapping: dict) -> dict:
    data: dict = {}
    for idx, h in enumerate(header):
        field = mapping.get(h)
        if not field:
            continue
        data[field] = row[idx] if idx < len(row) else None
    return data


def _label(kind: str, field: str) -> str:
    for c in COLUMNS[kind]:
        if c.field == field:
            return c.header
    return field


# ---------------------------------------------------------------- 검증
def _check_code(conn, group: str, value, label: str, errs: list, required: bool,
                as_warning: bool = False, warns: list | None = None):
    v = clean_str(value)
    if v is None:
        if required:
            errs.append((label, value, f"{label}은(는) 필수입니다."))
        return None
    active = code_labels(conn, group)
    if v in active:
        return v
    tip = suggest(v, active)
    msg = f"등록되지 않은 {label} 값입니다."
    msg += f" '{tip}'을(를) 의도하셨나요?" if tip else f" 사용 가능한 값: {', '.join(active)}"
    if as_warning:
        (warns if warns is not None else errs).append((label, value, msg + " (입력값 그대로 저장)"))
        return v
    errs.append((label, value, msg))
    return None


def validate_asset_row(conn, data: dict, seen_no: dict, seen_sn: dict, row_no: int,
                       dup_policy: str) -> tuple[dict, list, list, str]:
    """한 행을 검증한다. (정규화값, 오류, 경고, 처리구분)

    처리구분: new / update / skip / error
    """
    errs: list[tuple] = []
    warns: list[tuple] = []
    out: dict = {}

    def try_(label, fn, value):
        try:
            return fn(value)
        except AppError as e:
            errs.append((label, value, e.message))
            return None

    # --- 자산번호
    asset_no = None
    raw_no = data.get("asset_no")
    if clean_str(raw_no) is None:
        errs.append(("자산번호", raw_no, "자산번호는 필수입니다."))
    else:
        asset_no = try_("자산번호", parse_asset_no, raw_no)
    action = "new"
    if asset_no:
        if asset_no in seen_no:
            errs.append(("자산번호", asset_no, f"파일 내 {seen_no[asset_no]}행과 자산번호가 중복됩니다."))
        else:
            seen_no[asset_no] = row_no
        exist = conn.execute("SELECT id, asset_no FROM asset WHERE asset_no = ?", (asset_no,)).fetchone()
        if exist:
            if dup_policy == "update":
                action = "update"
                out["_existing_id"] = exist["id"]
            else:
                action = "skip"
    out["asset_no"] = asset_no

    # --- 코드 필수
    out["asset_type"] = _check_code(conn, "ASSET_TYPE", data.get("asset_type"), "자산구분", errs, True)
    out["manufacturer"] = _check_code(conn, "MANUFACTURER", data.get("manufacturer"), "제조사", errs, True)
    out["site"] = _check_code(conn, "SITE", data.get("site"), "사업장", errs, True)
    status = _check_code(conn, "STATUS", data.get("status"), "자산상태", errs, True) or ST_READY
    out["status"] = status

    # --- 코드 선택
    out["disk_type"] = _check_code(conn, "DISK_TYPE", data.get("disk_type"), "디스크 유형", errs, False)
    out["os"] = _check_code(conn, "OS", data.get("os"), "운영체제", errs, False)
    if status == ST_DISPOSED or clean_str(data.get("disposal_method")):
        out["disposal_method"] = _check_code(conn, "DISPOSAL_METHOD", data.get("disposal_method"),
                                             "폐기방법", errs, status == ST_DISPOSED)
    else:
        out["disposal_method"] = None

    # 부서/직급은 마이그레이션 중 표기 정리 대상이므로 경고로 처리한다 (M-3)
    dept = clean_str(data.get("dept_code"))
    out["dept_code"] = _check_code(conn, "DEPT", dept, "소속부서", errs, False,
                                   as_warning=True, warns=warns) if dept else None
    pos = clean_str(data.get("position_code"))
    out["position_code"] = _check_code(conn, "POSITION", pos, "직급", errs, False,
                                       as_warning=True, warns=warns) if pos else None

    # --- 문자
    out["model_name"] = clean_str(data.get("model_name"))
    if not out["model_name"]:
        errs.append(("모델명", data.get("model_name"), "모델명은 필수입니다."))
    out["manager_emp_no"] = clean_str(data.get("manager_emp_no"))
    if not out["manager_emp_no"]:
        errs.append(("자산관리 담당자", data.get("manager_emp_no"), "자산관리 담당자는 필수입니다."))
    out["location"] = clean_str(data.get("location"))
    out["cpu"] = clean_str(data.get("cpu"))
    out["remark"] = clean_str(data.get("remark"))
    out["hostname"] = clean_str(data.get("hostname"))

    # --- 시리얼
    sn = clean_str(data.get("serial_no"))
    out["serial_no"] = sn
    if sn:
        if sn in seen_sn:
            errs.append(("시리얼번호", sn, f"파일 내 {seen_sn[sn]}행과 시리얼번호가 중복됩니다."))
        else:
            seen_sn[sn] = row_no
        dup = conn.execute(
            "SELECT asset_no FROM asset WHERE serial_no = ? AND (? IS NULL OR asset_no <> ?)",
            (sn, asset_no, asset_no)).fetchone()
        if dup and action != "update":
            errs.append(("시리얼번호", sn, f"이미 등록된 시리얼번호입니다 (자산 {dup['asset_no']})."))

    # --- 날짜
    pd = try_("구매일", lambda v: parse_date(v, "구매일"), data.get("purchase_date"))
    if pd is None and clean_str(data.get("purchase_date")) is None:
        errs.append(("구매일", data.get("purchase_date"), "구매일은 필수입니다."))
    elif pd and pd > today_str():
        errs.append(("구매일", pd, "구매일은 미래 날짜일 수 없습니다."))
    out["purchase_date"] = pd

    ssd = try_("사용시작일", lambda v: parse_date(v, "사용시작일"), data.get("service_start_date"))
    if ssd and pd and ssd < pd:
        errs.append(("사용시작일", ssd, f"사용시작일은 구매일({pd})보다 이전일 수 없습니다."))
    out["service_start_date"] = ssd

    issue = try_("지급일", lambda v: parse_date(v, "지급일"), data.get("issue_date"))
    due = try_("반납예정일", lambda v: parse_date(v, "반납예정일"), data.get("due_return_date"))
    disp = try_("폐기일", lambda v: parse_date(v, "폐기일"), data.get("disposal_date"))
    out["disposal_date"] = disp

    # --- 숫자
    out["purchase_amount"] = try_("취득금액", lambda v: parse_int(v, "취득금액", 0, 9_999_999_999), data.get("purchase_amount"))
    out["useful_life_years"] = try_("내용연수", lambda v: parse_int(v, "내용연수", 1, 50), data.get("useful_life_years"))
    out["ram_gb"] = try_("RAM(GB)", lambda v: parse_int(v, "RAM", 1, 1024), data.get("ram_gb"))
    out["disk_gb"] = try_("디스크 용량(GB)", lambda v: parse_int(v, "디스크 용량", 1, 100_000), data.get("disk_gb"))

    # --- 형식
    out["ip_address"] = try_("IP 주소", parse_ip, data.get("ip_address"))
    out["mac_address"] = try_("MAC 주소", parse_mac, data.get("mac_address"))
    ip_type = clean_str(data.get("ip_type"))
    if ip_type and ip_type not in ("고정", "DHCP"):
        fixed = suggest(ip_type, ["고정", "DHCP"])
        errs.append(("IP 구분", ip_type, f"IP 구분은 '고정' 또는 'DHCP'여야 합니다." + (f" '{fixed}'을(를) 의도하셨나요?" if fixed else "")))
        ip_type = None
    out["ip_type"] = ip_type
    out["os_eol_date"] = try_("OS 지원종료일", lambda v: parse_date(v, "OS 지원종료일"), data.get("os_eol_date"))

    # --- 배정 정보
    emp_no = clean_str(data.get("emp_no"))
    user_name = clean_str(data.get("user_name"))
    emp = None
    if emp_no:
        row = conn.execute("SELECT * FROM employee WHERE emp_no = ?", (emp_no,)).fetchone()
        emp = dict(row) if row else None
        if emp is None:
            warns.append(("사번", emp_no, "임직원 마스터에 없는 사번입니다. 확인 목록에 표시됩니다."))
        else:
            user_name = user_name or emp["name"]
            out["dept_code"] = out["dept_code"] or emp["dept_code"]
            out["position_code"] = out["position_code"] or emp["position_code"]

    # --- 논리 검증
    if status == ST_INUSE:
        if not user_name:
            errs.append(("사용자명", user_name, "상태가 '사용중'이면 사용자명이 필요합니다."))
        if not emp_no:
            errs.append(("사번", emp_no, "상태가 '사용중'이면 사번이 필요합니다."))
        if not issue:
            issue = pd
            warns.append(("지급일", data.get("issue_date"), f"지급일이 없어 구매일({pd})로 채웁니다."))
    elif user_name or emp_no:
        warns.append(("사용자명", user_name or emp_no,
                      f"상태가 '{status}'인데 사용자 정보가 있습니다. 배정 정보는 저장되지 않습니다."))
        user_name, emp_no, issue, due = None, None, None, None

    if issue and pd and issue < pd:
        errs.append(("지급일", issue, f"지급일은 구매일({pd})보다 이전일 수 없습니다."))
    if due and issue and due < issue:
        errs.append(("반납예정일", due, f"반납예정일은 지급일({issue})보다 이전일 수 없습니다."))

    if status == ST_DISPOSED and not disp:
        errs.append(("폐기일", data.get("disposal_date"), "상태가 '폐기'이면 폐기일이 필요합니다."))

    out["_assign"] = {"emp_no": emp_no, "user_name": user_name, "issue_date": issue,
                      "due_return_date": due} if status == ST_INUSE else None

    if errs:
        action = "error"
    return out, errs, warns, action


def validate_employee_row(conn, data: dict, seen: dict, row_no: int, dup_policy: str):
    errs, warns, out = [], [], {}
    emp_no = clean_str(data.get("emp_no"))
    if not emp_no:
        errs.append(("사번", data.get("emp_no"), "사번은 필수입니다."))
    else:
        if emp_no in seen:
            errs.append(("사번", emp_no, f"파일 내 {seen[emp_no]}행과 사번이 중복됩니다."))
        else:
            seen[emp_no] = row_no
    out["emp_no"] = emp_no

    out["name"] = clean_str(data.get("name"))
    if not out["name"]:
        errs.append(("성명", data.get("name"), "성명은 필수입니다."))

    dept = clean_str(data.get("dept_code"))
    out["dept_code"] = _check_code(conn, "DEPT", dept, "소속부서", errs, False, True, warns) if dept else None
    pos = clean_str(data.get("position_code"))
    out["position_code"] = _check_code(conn, "POSITION", pos, "직급", errs, False, True, warns) if pos else None
    site = clean_str(data.get("site_code"))
    out["site_code"] = _check_code(conn, "SITE", site, "사업장", errs, False) if site else None

    st = clean_str(data.get("employ_status")) or "재직"
    if st not in ("재직", "휴직", "퇴사"):
        errs.append(("재직상태", st, "재직상태는 재직 / 휴직 / 퇴사 중 하나여야 합니다."))
    out["employ_status"] = st
    out["email"] = clean_str(data.get("email"))
    out["phone"] = clean_str(data.get("phone"))

    action = "new"
    if emp_no and conn.execute("SELECT 1 FROM employee WHERE emp_no = ?", (emp_no,)).fetchone():
        action = "update" if dup_policy == "update" else "skip"
    if errs:
        action = "error"
    return out, errs, warns, action


# ---------------------------------------------------------------- 전체 검증 (06-6)
def validate_all(conn, kind: str, header: list[str], body: list[list],
                 mapping: dict, dup_policy: str) -> dict:
    required = [c.field for c in COLUMNS[kind] if c.required]
    mapped = {v for v in mapping.values() if v}
    missing = [_label(kind, f) for f in required if f not in mapped]
    if missing:
        raise AppError("필수 컬럼이 매핑되지 않았습니다: " + ", ".join(missing))

    errors: list[dict] = []
    warnings: list[dict] = []
    preview: list[dict] = []
    seen_no: dict = {}
    seen_sn: dict = {}
    seen_emp: dict = {}
    counts = {"total": len(body), "ok": 0, "error": 0, "skip": 0, "update": 0}
    rows_out: list[dict] = []

    for i, raw in enumerate(body):
        row_no = i + 2                            # 엑셀 실제 행번호 (헤더 1행)
        data = row_to_data(header, raw, mapping)
        if kind == "asset":
            norm, errs, warns, action = validate_asset_row(conn, data, seen_no, seen_sn, row_no, dup_policy)
        else:
            norm, errs, warns, action = validate_employee_row(conn, data, seen_emp, row_no, dup_policy)

        for col, val, msg in errs:
            errors.append({"row": row_no, "column": col, "value": val, "message": msg})
        for col, val, msg in warns:
            warnings.append({"row": row_no, "column": col, "value": val, "message": msg})

        if action == "error":
            counts["error"] += 1
        elif action == "skip":
            counts["skip"] += 1
        elif action == "update":
            counts["update"] += 1
            counts["ok"] += 1
        else:
            counts["ok"] += 1

        rows_out.append({"row_no": row_no, "data": norm, "action": action})
        if len(preview) < 20:                     # 06-4 미리보기 20행 (정규화 결과 표시)
            preview.append({"row_no": row_no, "action": action,
                            "values": {k: v for k, v in norm.items() if not k.startswith("_")},
                            "has_error": bool(errs)})

    return {"counts": counts, "errors": errors, "warnings": warnings,
            "preview": preview, "rows": rows_out}


# ---------------------------------------------------------------- 확정 (06-8 ~ 06-11)
def _next_batch_no(conn) -> str:
    today = now_dt().strftime("%Y%m%d")
    n = conn.execute("SELECT COUNT(*) c FROM import_batch WHERE batch_no LIKE ?",
                     (f"IMP-{today}-%",)).fetchone()["c"]
    return f"IMP-{today}-{n + 1:03d}"


def commit_import(conn, kind: str, meta: dict, validated: dict, mode: str,
                  dup_policy: str, user: dict) -> dict:
    counts = validated["counts"]
    if mode == "all_or_nothing" and counts["error"] > 0:
        raise AppError(
            f"오류 {counts['error']}건이 있어 전체 취소되었습니다. "
            f"오류 리포트를 확인해 수정 후 다시 시도하거나, '부분 반영' 모드를 선택하세요.")

    batch_no = _next_batch_no(conn)
    cur = conn.execute(
        """INSERT INTO import_batch (batch_no, kind, file_name, mode, dup_policy, total_rows,
                                     created_at, created_by)
           VALUES (?,?,?,?,?,?,?,?)""",
        (batch_no, kind, meta["filename"], mode, dup_policy, counts["total"], now_str(), user["name"]))
    batch_id = cur.lastrowid

    success = updated = skipped = 0
    for r in validated["rows"]:
        if r["action"] in ("error", "skip"):
            skipped += 1
            continue
        if kind == "asset":
            if r["action"] == "update":
                _update_existing_asset(conn, r["data"], user, batch_no)
                updated += 1
            else:
                _insert_new_asset(conn, r["data"], user, batch_id, batch_no)
            success += 1
        else:
            _upsert_employee(conn, r["data"], r["action"])
            if r["action"] == "update":
                updated += 1
            success += 1

    conn.execute(
        """UPDATE import_batch SET success_rows=?, failed_rows=?, skipped_rows=?, updated_rows=?
           WHERE id=?""",
        (success, counts["error"], skipped - counts["error"], updated, batch_id))

    return {"batch_id": batch_id, "batch_no": batch_no, "total": counts["total"],
            "success": success, "failed": counts["error"],
            "skipped": skipped - counts["error"], "updated": updated}


def _insert_new_asset(conn, d: dict, user: dict, batch_id: int, batch_no: str) -> int:
    values = {k: d.get(k) for k in EDITABLE_FIELDS}
    values["asset_no"] = d["asset_no"]
    values["disposal_date"] = d.get("disposal_date")
    values["disposal_method"] = d.get("disposal_method")
    asset_id = insert_asset(conn, values, user, status=d["status"], method="엑셀", batch_id=batch_id)

    add_history(conn, asset_id, d["asset_no"], HIST_CREATE, user["name"],
                reason="엑셀 일괄 등록",
                after={"status": d["status"]},
                extra={"method": "엑셀", "batch_no": batch_no})

    asg = d.get("_assign")
    if asg and asg.get("user_name"):
        create_assignment(conn, asset_id, {
            "emp_no": asg["emp_no"], "user_name": asg["user_name"],
            "dept_code": d.get("dept_code"), "position_code": d.get("position_code"),
            "site": d.get("site"), "location": d.get("location"),
            "issue_date": asg["issue_date"], "due_return_date": asg["due_return_date"],
            "assign_reason": "엑셀 일괄 등록",
        }, user)
        add_history(conn, asset_id, d["asset_no"], HIST_ASSIGN, user["name"],
                    reason="엑셀 일괄 등록",
                    before={}, after={"user_name": asg["user_name"], "emp_no": asg["emp_no"],
                                      "dept_code": d.get("dept_code"), "issue_date": asg["issue_date"]},
                    extra={"batch_no": batch_no})
    return asset_id


def _update_existing_asset(conn, d: dict, user: dict, batch_no: str) -> None:
    """06-9 기존 정보 갱신. 실제 바뀐 필드만 이력으로 남긴다."""
    row = conn.execute("SELECT * FROM asset WHERE asset_no = ?", (d["asset_no"],)).fetchone()
    if row is None:
        return
    asset = dict(row)
    changed = {}
    for f in EDITABLE_FIELDS:
        new = d.get(f)
        if new is None:
            continue                              # 빈 칸은 기존 값을 지우지 않는다
        if (asset.get(f) or None) != new:
            changed[f] = (asset.get(f), new)
    if not changed:
        return
    sets = ", ".join(f"{f} = ?" for f in changed)
    conn.execute(f"UPDATE asset SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                 [changed[f][1] for f in changed] + [now_str(), user["name"], asset["id"]])
    add_history(conn, asset["id"], asset["asset_no"], HIST_UPDATE, user["name"],
                reason=f"엑셀 일괄 갱신 ({batch_no})",
                before={f: changed[f][0] for f in changed},
                after={f: changed[f][1] for f in changed},
                extra={"batch_no": batch_no})


def _upsert_employee(conn, d: dict, action: str) -> None:
    now = now_str()
    if action == "update":
        conn.execute(
            """UPDATE employee SET name=?, dept_code=COALESCE(?,dept_code),
               position_code=COALESCE(?,position_code), site_code=COALESCE(?,site_code),
               employ_status=?, email=COALESCE(?,email), phone=COALESCE(?,phone), updated_at=?
               WHERE emp_no=?""",
            (d["name"], d["dept_code"], d["position_code"], d["site_code"],
             d["employ_status"], d["email"], d["phone"], now, d["emp_no"]))
    else:
        conn.execute(
            """INSERT INTO employee (emp_no, name, dept_code, position_code, site_code,
                                     employ_status, email, phone, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (d["emp_no"], d["name"], d["dept_code"], d["position_code"], d["site_code"],
             d["employ_status"], d["email"], d["phone"], now, now))


# ---------------------------------------------------------------- 되돌리기 (06-12)
def revert_batch(conn, batch_id: int, user: dict) -> dict:
    row = conn.execute("SELECT * FROM import_batch WHERE id = ?", (batch_id,)).fetchone()
    if row is None:
        raise AppError("가져오기 배치를 찾을 수 없습니다.", 404)
    batch = dict(row)
    if batch["reverted_at"]:
        raise AppError(f"이미 되돌린 배치입니다. ({batch['reverted_at']})")
    if batch["kind"] != "asset":
        raise AppError("자산 가져오기 배치만 되돌릴 수 있습니다.")

    assets = conn.execute("SELECT id, asset_no FROM asset WHERE import_batch_id = ?", (batch_id,)).fetchall()
    removed, kept = [], []
    for a in assets:
        types = {r["hist_type"] for r in conn.execute(
            "SELECT DISTINCT hist_type FROM asset_history WHERE asset_id = ?", (a["id"],)).fetchall()}
        # 이후 변경 이력이 있으면 되돌리지 않는다
        if types - {HIST_CREATE, HIST_ASSIGN}:
            kept.append(a["asset_no"])
            continue
        conn.execute("DELETE FROM asset_history WHERE asset_id = ?", (a["id"],))
        conn.execute("DELETE FROM assignment WHERE asset_id = ?", (a["id"],))
        conn.execute("DELETE FROM asset WHERE id = ?", (a["id"],))
        removed.append(a["asset_no"])

    note = f"삭제 {len(removed)}건 / 이후 변경 이력이 있어 유지 {len(kept)}건"
    conn.execute("UPDATE import_batch SET reverted_at=?, reverted_by=?, revert_note=? WHERE id=?",
                 (now_str(), user["name"], note, batch_id))
    return {"removed": removed, "kept": kept, "note": note}
