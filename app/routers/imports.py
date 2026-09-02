"""엑셀 가져오기 마법사 API (FR-06)."""
from __future__ import annotations

import json
import urllib.parse

from fastapi import APIRouter, Body, Depends, File, Form, Response, UploadFile

from ..auth import require_user
from ..core import AppError, clean_str
from ..db import get_conn, transaction
from ..services import excel_io, importer

router = APIRouter(prefix="/imports", tags=["imports"])

VALID_KIND = ("asset", "employee")


def _check_kind(kind: str) -> str:
    if kind not in VALID_KIND:
        raise AppError("가져오기 종류는 asset 또는 employee여야 합니다.")
    return kind


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"})


# ---------------------------------------------------------------- 템플릿 (06-1)
@router.get("/template.xlsx")
def template(kind: str = "asset", user: dict = Depends(require_user)):
    _check_kind(kind)
    name = "자산등록_템플릿.xlsx" if kind == "asset" else "임직원_템플릿.xlsx"
    return _xlsx(excel_io.build_template(kind), name)


@router.get("/columns")
def columns(kind: str = "asset", user: dict = Depends(require_user)):
    _check_kind(kind)
    return {"items": [{"header": c.header, "field": c.field, "required": c.required,
                       "desc": c.desc} for c in excel_io.COLUMNS[kind]]}


# ---------------------------------------------------------------- 1단계: 업로드 (06-2~06-5)
@router.post("/upload")
async def upload(kind: str = Form("asset"), file: UploadFile = File(...),
                 user: dict = Depends(require_user)):
    _check_kind(kind)
    content = await file.read()
    if not content:
        raise AppError("빈 파일입니다.")
    result = importer.save_upload(file.filename or "upload.xlsx", content, kind)
    header, body = result["header"], result["body"]
    mapping = excel_io.suggest_mapping(kind, header)
    preview = [[("" if v is None else str(v)) for v in row] for row in body[:20]]
    unmapped = [h for h, f in mapping.items() if not f]
    return {
        "token": result["meta"]["token"],
        "filename": result["meta"]["filename"],
        "total_rows": len(body),
        "header": header,
        "mapping": mapping,
        "preview": preview,
        "unmapped": unmapped,
        "fields": [{"field": c.field, "header": c.header, "required": c.required}
                   for c in excel_io.COLUMNS[kind]],
    }


# ---------------------------------------------------------------- 2·3단계: 검증 (06-6, 06-7)
@router.post("/validate")
def validate(payload: dict = Body(...), user: dict = Depends(require_user)):
    token = clean_str(payload.get("token"))
    dup_policy = clean_str(payload.get("dup_policy")) or "skip"
    if dup_policy not in ("skip", "update"):
        raise AppError("중복 처리 방식은 '건너뛰기' 또는 '갱신'이어야 합니다.")
    mapping = payload.get("mapping") or {}

    meta, header, body = importer.load_upload(token)
    with get_conn() as conn:
        result = importer.validate_all(conn, meta["kind"], header, body, mapping, dup_policy)

    # 검증 결과를 3단계 확정에서 재사용할 수 있도록 캐시한다
    (importer.UPLOAD_DIR / f"{token}.val.json").write_text(
        json.dumps({"mapping": mapping, "dup_policy": dup_policy,
                    "counts": result["counts"], "errors": result["errors"]},
                   ensure_ascii=False), encoding="utf-8")

    return {
        "counts": result["counts"],
        "errors": result["errors"][:500],
        "error_total": len(result["errors"]),
        "warnings": result["warnings"][:200],
        "warning_total": len(result["warnings"]),
        "preview": result["preview"],
    }


@router.get("/errors.xlsx")
def error_report(token: str, user: dict = Depends(require_user)):
    p = importer.UPLOAD_DIR / f"{token}.val.json"
    if not token.isalnum() or not p.exists():
        raise AppError("검증 결과를 찾을 수 없습니다. 검증을 다시 실행해 주세요.", 404)
    data = json.loads(p.read_text(encoding="utf-8"))
    return _xlsx(excel_io.build_error_report(data.get("errors") or []),
                 excel_io.export_filename("가져오기_오류리포트"))


# ---------------------------------------------------------------- 확정 (06-8 ~ 06-11)
@router.post("/commit")
def commit(payload: dict = Body(...), user: dict = Depends(require_user)):
    token = clean_str(payload.get("token"))
    mode = clean_str(payload.get("mode")) or "all_or_nothing"
    if mode not in ("all_or_nothing", "partial"):
        raise AppError("반영 모드가 올바르지 않습니다.")
    dup_policy = clean_str(payload.get("dup_policy")) or "skip"
    mapping = payload.get("mapping") or {}

    meta, header, body = importer.load_upload(token)
    with transaction() as conn:
        validated = importer.validate_all(conn, meta["kind"], header, body, mapping, dup_policy)
        result = importer.commit_import(conn, meta["kind"], meta, validated, mode, dup_policy, user)
    return result


# ---------------------------------------------------------------- 배치 이력 / 되돌리기 (06-12)
@router.get("/batches")
def batches(limit: int = 30, user: dict = Depends(require_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM import_batch ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/batches/{batch_id}/revert")
def revert(batch_id: int, user: dict = Depends(require_user)):
    with transaction() as conn:
        return importer.revert_batch(conn, batch_id, user)
