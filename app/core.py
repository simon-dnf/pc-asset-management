"""공통 상수·유틸리티: 시간, 상태 전이 규칙, 검증 헬퍼."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

# NFR-14 — 시간대 Asia/Seoul 고정
KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------- 자산 상태 (Master §8.3)
ST_READY = "대기"
ST_INUSE = "사용중"
ST_REPAIR = "수리"
ST_TO_DISPOSE = "폐기예정"
ST_DISPOSED = "폐기"

ALL_STATUSES = [ST_READY, ST_INUSE, ST_REPAIR, ST_TO_DISPOSE, ST_DISPOSED]
# 보유 자산 = 폐기 제외 (Master §11 용어)
HOLDING_STATUSES = [ST_READY, ST_INUSE, ST_REPAIR, ST_TO_DISPOSE]

# 상태 변경 화면에서 허용하는 직접 전환 (FR-12-1).
# 배정(FR-08)·회수(FR-09)는 별도 액션이므로 여기에 포함하지 않는다.
STATUS_TRANSITIONS: dict[str, list[str]] = {
    ST_READY:       [ST_REPAIR, ST_TO_DISPOSE],
    ST_INUSE:       [ST_REPAIR],                      # 대기로는 '회수'를 거친다
    ST_REPAIR:      [ST_READY, ST_INUSE, ST_TO_DISPOSE],
    ST_TO_DISPOSE:  [ST_DISPOSED, ST_READY],          # 대기 = 폐기 결정 취소
    ST_DISPOSED:    [],                               # 최종 상태
}

STATUS_BLOCK_MESSAGE = {
    (ST_INUSE, ST_TO_DISPOSE): "먼저 회수 처리가 필요합니다. (사용중 → 폐기예정 직접 전환 불가)",
    (ST_INUSE, ST_READY): "사용중 자산은 회수 처리로만 대기 상태가 됩니다.",
}

# ---------------------------------------------------------------- 이력 유형 (DM-HIST)
HIST_CREATE = "CREATE"
HIST_ASSIGN = "ASSIGN"
HIST_RETURN = "RETURN"
HIST_MOVE = "MOVE"
HIST_UPDATE = "UPDATE"
HIST_STATUS = "STATUS"
HIST_DISPOSE = "DISPOSE"

HIST_LABELS = {
    HIST_CREATE: "등록",
    HIST_ASSIGN: "배정",
    HIST_RETURN: "회수",
    HIST_MOVE: "이동",
    HIST_UPDATE: "정보변경",
    HIST_STATUS: "상태변경",
    HIST_DISPOSE: "폐기",
}

# 사용자/부서/사업장/위치 변경은 MOVE, 그 외는 UPDATE (FR-04-6)
MOVE_FIELDS = {"site", "location"}

# ---------------------------------------------------------------- 코드 그룹
CODE_GROUPS = {
    "ASSET_TYPE": "자산구분",
    "MANUFACTURER": "제조사",
    "STATUS": "자산상태",
    "SITE": "사업장",
    "DEPT": "부서",
    "POSITION": "직급",
    "OS": "운영체제",
    "DISK_TYPE": "디스크유형",
    "DISPOSAL_METHOD": "폐기방법",
    "RETURN_REASON": "회수사유",
}


class AppError(Exception):
    """사용자에게 그대로 보여줄 업무 규칙 위반 오류."""

    def __init__(self, message: str, status_code: int = 400, field: str | None = None, detail=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field
        self.detail = detail


# ---------------------------------------------------------------- 시간
def now_dt() -> datetime:
    return datetime.now(KST)


def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return now_dt().strftime("%Y-%m-%d")


def plus_days(days: int) -> str:
    return (now_dt() + timedelta(days=days)).strftime("%Y-%m-%d")


def dt_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 값 정규화 / 검증
DATE_RE = re.compile(r"^(\d{4})[-./]?(\d{1,2})[-./]?(\d{1,2})$")
IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2})([:\-]?)([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})$")
ASSET_NO_RE = re.compile(r"^[A-Za-z0-9\-]{1,30}$")


def clean_str(v) -> str | None:
    """공백만 있는 값은 None으로 만든다."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    return s or None


def parse_date(v, field_label: str = "날짜") -> str | None:
    """다양한 표기('2024.03.05', '2024/3/5', 엑셀 날짜셀)를 YYYY-MM-DD로 정규화한다."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    if not s:
        return None
    s = s.split(" ")[0]
    m = DATE_RE.match(s)
    if not m:
        raise AppError(f"{field_label} 형식이 올바르지 않습니다: '{v}' (YYYY-MM-DD)")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        raise AppError(f"{field_label}가 존재하지 않는 날짜입니다: '{v}'")


def parse_int(v, field_label: str, lo: int | None = None, hi: int | None = None) -> int | None:
    """'16GB', '512 GB', '1,200,000원' 같은 표기에서 숫자만 뽑아 정수로 만든다."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise AppError(f"{field_label}는 숫자여야 합니다.")
    if isinstance(v, (int, float)):
        n = int(v)
    else:
        s = str(v).strip()
        if not s:
            return None
        digits = re.sub(r"[^0-9\-]", "", s)
        if not digits or digits == "-":
            raise AppError(f"{field_label}는 숫자여야 합니다: '{v}'")
        n = int(digits)
    if lo is not None and n < lo:
        raise AppError(f"{field_label}는 {lo} 이상이어야 합니다: '{v}'")
    if hi is not None and n > hi:
        raise AppError(f"{field_label}는 {hi} 이하여야 합니다: '{v}'")
    return n


def parse_ip(v) -> str | None:
    s = clean_str(v)
    if not s:
        return None
    m = IPV4_RE.match(s)
    if not m or any(int(g) > 255 for g in m.groups()):
        raise AppError(f"IP 주소 형식이 올바르지 않습니다: '{v}' (0.0.0.0 ~ 255.255.255.255)")
    return ".".join(str(int(g)) for g in m.groups())


def parse_mac(v) -> str | None:
    """XX:XX:... / XX-XX-... / 구분자 없음을 받아 대문자 콜론 형식으로 정규화한다. (FR-02 검증)"""
    s = clean_str(v)
    if not s:
        return None
    if not MAC_RE.match(s):
        raise AppError(f"MAC 주소 형식이 올바르지 않습니다: '{v}' (XX:XX:XX:XX:XX:XX)")
    hexonly = re.sub(r"[:\-]", "", s).upper()
    return ":".join(hexonly[i:i + 2] for i in range(0, 12, 2))


def parse_asset_no(v) -> str:
    s = clean_str(v)
    if not s:
        raise AppError("자산번호는 필수입니다.", field="asset_no")
    if not ASSET_NO_RE.match(s):
        raise AppError(f"자산번호는 영문/숫자/하이픈 30자 이내여야 합니다: '{v}'", field="asset_no")
    return s.upper()


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def jload(s: str):
    try:
        return json.loads(s) if s else {}
    except (TypeError, ValueError):
        return {}


def age_years(purchase_date: str | None) -> float | None:
    if not purchase_date:
        return None
    try:
        d = datetime.strptime(purchase_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (now_dt().date() - d).days / 365.25
