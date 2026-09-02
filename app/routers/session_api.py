"""로그인/로그아웃/비밀번호 변경 (FR-01) 및 계정별 화면 설정 (03-8, 05-8)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel

from .. import auth
from ..core import AppError, jdump, jload, now_str
from ..db import get_conn, transaction

router = APIRouter(tags=["session"])

# 저장을 허용하는 설정 키. 임의 키로 서버를 저장소처럼 쓰지 못하게 막는다.
PREF_KEYS = {
    "asset_columns":  "자산 목록 표시 컬럼",      # 03-8
    "saved_searches": "저장된 검색 조건",         # 05-8
}
PREF_MAX_BYTES = 64 * 1024


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
def do_login(body: LoginIn, response: Response):
    token, user = auth.login(body.username, body.password)
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        httponly=True, samesite="lax", path="/",
        max_age=auth.SESSION_HOURS * 3600,
    )
    return {"user": user}


@router.post("/logout")
def do_logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = auth.current_user(request)
    if user is None:
        raise AppError("로그인이 필요합니다.", 401)
    return {"user": user}


@router.post("/me/password")
def change_password(body: PasswordIn, request: Request, response: Response,
                    user: dict = Depends(auth.require_user)):
    auth.change_own_password(user["id"], body.current_password, body.new_password)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True, "message": "비밀번호가 변경되었습니다. 다시 로그인해 주세요."}


# ---------------------------------------------------------------- 계정별 화면 설정
def _check_key(key: str) -> str:
    if key not in PREF_KEYS:
        raise AppError(f"저장할 수 없는 설정 항목입니다: {key}", 400)
    return key


@router.get("/me/prefs")
def get_prefs(user: dict = Depends(auth.require_user)):
    """현재 계정의 화면 설정을 한 번에 내려준다. 화면 진입 시 1회 호출한다."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT pref_key, value_json FROM user_pref WHERE user_id = ?", (user["id"],)
        ).fetchall()
    prefs = {r["pref_key"]: jload(r["value_json"]) for r in rows if r["pref_key"] in PREF_KEYS}
    return {"prefs": prefs}


@router.put("/me/prefs/{key}")
def set_pref(key: str, payload: dict = Body(...), user: dict = Depends(auth.require_user)):
    _check_key(key)
    if "value" not in payload:
        raise AppError("저장할 값(value)이 없습니다.", 400)
    encoded = jdump(payload["value"])
    if len(encoded.encode("utf-8")) > PREF_MAX_BYTES:
        raise AppError(f"{PREF_KEYS[key]} 설정이 너무 큽니다. 항목을 줄여 주세요.", 400)

    with transaction() as conn:
        conn.execute(
            """INSERT INTO user_pref (user_id, pref_key, value_json, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(user_id, pref_key)
               DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
            (user["id"], key, encoded, now_str()))
    return {"ok": True}


@router.delete("/me/prefs/{key}")
def reset_pref(key: str, user: dict = Depends(auth.require_user)):
    """설정을 지워 기본값으로 되돌린다."""
    _check_key(key)
    with transaction() as conn:
        conn.execute("DELETE FROM user_pref WHERE user_id = ? AND pref_key = ?", (user["id"], key))
    return {"ok": True}
