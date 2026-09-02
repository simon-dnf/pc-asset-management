"""인증/세션 (FR-01, NFR-07, NFR-08)."""
from __future__ import annotations

import re
import secrets
from datetime import timedelta

import bcrypt
from fastapi import Request

from .core import AppError, KST, dt_str, now_dt, now_str
from .db import get_conn, transaction

SESSION_COOKIE = "pcams_session"
SESSION_HOURS = 8          # NFR-08 세션 타임아웃 8시간
MAX_FAILED = 5             # NFR-08 5회 실패 시 잠금
LOCK_MINUTES = 10


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_password_policy(raw: str) -> None:
    """01-8 — 8자 이상, 영문+숫자 조합."""
    if raw is None or len(raw) < 8:
        raise AppError("비밀번호는 8자 이상이어야 합니다.", field="password")
    if not re.search(r"[A-Za-z]", raw) or not re.search(r"[0-9]", raw):
        raise AppError("비밀번호는 영문과 숫자를 모두 포함해야 합니다.", field="password")


def _parse(ts: str):
    from datetime import datetime
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)


def login(username: str, password: str) -> tuple[str, dict]:
    username = (username or "").strip()
    if not username or not password:
        raise AppError("아이디와 비밀번호를 입력하세요.", 400)

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM admin_user WHERE username = ?", (username,)).fetchone()
    if row is None:
        raise AppError("아이디 또는 비밀번호가 올바르지 않습니다.", 401)
    user = dict(row)

    if not user["is_active"]:
        raise AppError("비활성화된 계정입니다. 관리자에게 문의하세요.", 403)

    if user["locked_until"]:
        until = _parse(user["locked_until"])
        if until > now_dt():
            mins = max(1, int((until - now_dt()).total_seconds() // 60) + 1)
            raise AppError(f"로그인 {MAX_FAILED}회 실패로 계정이 잠겼습니다. {mins}분 후 다시 시도하세요.", 423)

    if not verify_password(password, user["password_hash"]):
        # 실패 카운터는 예외와 함께 롤백되면 안 되므로 별도 트랜잭션에서 먼저 확정한다.
        failed = user["failed_count"] + 1
        locked_until = None
        if failed >= MAX_FAILED:
            locked_until = dt_str(now_dt() + timedelta(minutes=LOCK_MINUTES))
            failed = 0
        with transaction() as conn:
            conn.execute(
                "UPDATE admin_user SET failed_count = ?, locked_until = ? WHERE id = ?",
                (failed, locked_until, user["id"]),
            )
        if locked_until:
            raise AppError(f"로그인 {MAX_FAILED}회 실패로 계정이 {LOCK_MINUTES}분간 잠겼습니다.", 423)
        raise AppError(f"아이디 또는 비밀번호가 올바르지 않습니다. ({MAX_FAILED - failed}회 남음)", 401)

    with transaction() as conn:
        token = secrets.token_urlsafe(32)
        expires = dt_str(now_dt() + timedelta(hours=SESSION_HOURS))
        conn.execute(
            "INSERT INTO session (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user["id"], now_str(), expires),
        )
        conn.execute(
            "UPDATE admin_user SET failed_count = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
            (now_str(), user["id"]),
        )
        conn.execute("DELETE FROM session WHERE expires_at < ?", (now_str(),))
        return token, _public(user)


def logout(token: str | None) -> None:
    if not token:
        return
    with transaction() as conn:
        conn.execute("DELETE FROM session WHERE token = ?", (token,))


def _public(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "name": user["name"],
        "role": user["role"],
        "must_change_pw": bool(user["must_change_pw"]),
        "last_login_at": user.get("last_login_at"),
    }


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """SELECT u.*, s.expires_at FROM session s
               JOIN admin_user u ON u.id = s.user_id
               WHERE s.token = ?""",
            (token,),
        ).fetchone()
    if row is None:
        return None
    user = dict(row)
    if _parse(user["expires_at"]) <= now_dt() or not user["is_active"]:
        return None
    return _public(user)


def require_user(request: Request) -> dict:
    """FastAPI 의존성. 미인증 시 401 → 프런트가 로그인 화면으로 보낸다 (01-5)."""
    user = current_user(request)
    if user is None:
        raise AppError("로그인이 필요합니다.", 401)
    return user


def change_own_password(user_id: int, current_pw: str, new_pw: str) -> None:
    validate_password_policy(new_pw)
    with transaction() as conn:
        row = conn.execute("SELECT * FROM admin_user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise AppError("계정을 찾을 수 없습니다.", 404)
        if not verify_password(current_pw or "", row["password_hash"]):
            raise AppError("현재 비밀번호가 올바르지 않습니다.", 400, field="current_password")
        if verify_password(new_pw, row["password_hash"]):
            raise AppError("이전과 다른 비밀번호를 입력하세요.", 400, field="new_password")
        conn.execute(
            "UPDATE admin_user SET password_hash = ?, must_change_pw = 0 WHERE id = ?",
            (hash_password(new_pw), user_id),
        )
        # 비밀번호 변경 시 다른 세션은 만료시킨다.
        conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
