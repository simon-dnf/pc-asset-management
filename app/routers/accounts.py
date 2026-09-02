"""관리자 계정 관리 (FR-01 01-7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import hash_password, require_user, validate_password_policy
from ..core import AppError, clean_str, now_str
from ..db import get_conn, transaction

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountIn(BaseModel):
    username: str
    name: str
    password: str


class ResetIn(BaseModel):
    new_password: str


@router.get("")
def list_accounts(user: dict = Depends(require_user)):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, username, name, role, is_active, must_change_pw,
                      last_login_at, locked_until, created_at, created_by
               FROM admin_user ORDER BY id"""
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("")
def create_account(body: AccountIn, user: dict = Depends(require_user)):
    username = clean_str(body.username)
    name = clean_str(body.name)
    if not username or not username.isalnum():
        raise AppError("아이디는 영문/숫자 조합이어야 합니다.", field="username")
    if not name:
        raise AppError("이름은 필수입니다.", field="name")
    validate_password_policy(body.password)
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM admin_user WHERE username = ?", (username,)).fetchone():
            raise AppError("이미 사용 중인 아이디입니다.", field="username")
        conn.execute(
            """INSERT INTO admin_user (username, password_hash, name, role, is_active,
                                       must_change_pw, created_at, created_by)
               VALUES (?,?,?,'ADMIN',1,1,?,?)""",
            (username, hash_password(body.password), name, now_str(), user["name"]))
    return {"ok": True}


@router.post("/{account_id}/active")
def toggle_active(account_id: int, active: bool, user: dict = Depends(require_user)):
    if account_id == user["id"] and not active:
        raise AppError("본인 계정은 비활성화할 수 없습니다.")
    with transaction() as conn:
        row = conn.execute("SELECT id FROM admin_user WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            raise AppError("계정을 찾을 수 없습니다.", 404)
        if not active:
            remaining = conn.execute(
                "SELECT COUNT(*) c FROM admin_user WHERE is_active = 1 AND id <> ?", (account_id,)
            ).fetchone()["c"]
            if remaining == 0:
                raise AppError("활성 관리자 계정이 최소 1개는 있어야 합니다.")
        conn.execute("UPDATE admin_user SET is_active = ? WHERE id = ?", (1 if active else 0, account_id))
        if not active:
            conn.execute("DELETE FROM session WHERE user_id = ?", (account_id,))
    return {"ok": True}


@router.post("/{account_id}/reset-password")
def reset_password(account_id: int, body: ResetIn, user: dict = Depends(require_user)):
    """다른 관리자가 임시 비밀번호로 재설정한다 (메일 발송 없음)."""
    validate_password_policy(body.new_password)
    with transaction() as conn:
        row = conn.execute("SELECT id FROM admin_user WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            raise AppError("계정을 찾을 수 없습니다.", 404)
        conn.execute(
            """UPDATE admin_user SET password_hash = ?, must_change_pw = 1,
               failed_count = 0, locked_until = NULL WHERE id = ?""",
            (hash_password(body.new_password), account_id))
        conn.execute("DELETE FROM session WHERE user_id = ?", (account_id,))
    return {"ok": True, "message": "임시 비밀번호로 재설정했습니다. 최초 로그인 후 변경하도록 안내하세요."}


@router.post("/{account_id}/unlock")
def unlock(account_id: int, user: dict = Depends(require_user)):
    with transaction() as conn:
        conn.execute("UPDATE admin_user SET failed_count = 0, locked_until = NULL WHERE id = ?",
                     (account_id,))
    return {"ok": True}
