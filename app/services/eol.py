"""OS 지원종료일(EOL) 외부 연동.

PRD-Master §7.3 `os_eol_date`("Windows 10 EOL 대응 등 교체 계획용")를 채우기 위해
공개 API [endoflife.date](https://endoflife.date)에서 OS 릴리스별 지원종료일을 받아온다.

NFR-15 (외부 연동 장애 격리)
  - 짧은 타임아웃을 두고, 실패하면 예외 대신 캐시를 돌려준다.
  - 외부 호출은 이 화면에서 관리자가 [갱신]을 누를 때만 일어난다.
    대시보드·자산 목록은 DB에 저장된 `os_eol_date`만 읽으므로 외부가 죽어도 영향이 없다.

NFR-16 (외부 전송 시 개인정보 제외)
  - 공개 JSON을 GET 으로 내려받기만 한다. 사번·성명 등 사내 데이터는 일절 전송하지 않는다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from ..core import AppError, HIST_UPDATE, jdump, jload, now_str, today_str
from .assets import add_history

API_BASE = "https://endoflife.date/api"
TIMEOUT_SEC = 8
USER_AGENT = "PC-Asset-Management/1.0 (+internal tool)"

CACHE_KEY = "eol_cycles_cache"
MAPPING_KEY = "eol_os_mapping"

# 공통코드 [운영체제] 값 → endoflife.date 제품 슬러그
# 여기에 없는 코드(예: '기타')는 연동 대상이 아니다.
OS_PRODUCTS: dict[str, str] = {
    "Windows 11": "windows",
    "Windows 10": "windows",
    "Windows Server": "windows-server",
    "macOS": "macos",
    "Linux": "ubuntu",
}

# 제품별로 "일반적으로 쓰는 릴리스"의 기준이 다르다. 여기서 걸러낸 뒤 가장 최신 릴리스를 추천한다.
#   windows        : LTSC/IoT는 특수 목적이라 제외
#   windows-server : LTSC가 표준 배포판이므로 포함하고, 반기채널(SAC/AC)만 제외
#   ubuntu         : 사내 배포는 보통 LTS
_EXCLUDE = {
    "windows": lambda c: c["lts"] or "iot" in c["cycle"],
    "windows-server": lambda c: c["cycle"].endswith(("-sac", "-ac")),
    "ubuntu": lambda c: not c["lts"],
}


# ---------------------------------------------------------------- 설정 저장소
def get_setting(conn, key: str, fallback=None):
    row = conn.execute("SELECT value_json FROM app_setting WHERE setting_key = ?", (key,)).fetchone()
    return jload(row["value_json"]) if row else fallback


def set_setting(conn, key: str, value, actor: str | None = None) -> None:
    conn.execute(
        """INSERT INTO app_setting (setting_key, value_json, updated_at, updated_by) VALUES (?,?,?,?)
           ON CONFLICT(setting_key) DO UPDATE SET
             value_json = excluded.value_json, updated_at = excluded.updated_at,
             updated_by = excluded.updated_by""",
        (key, jdump(value), now_str(), actor))


# ---------------------------------------------------------------- 외부 호출
def _fetch_product(product: str) -> list[dict]:
    req = urllib.request.Request(f"{API_BASE}/{product}.json", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
        data = json.load(res)
    if not isinstance(data, list):
        raise ValueError("응답 형식이 예상과 다릅니다.")
    # API는 최신 릴리스를 앞에 준다. 이 순서를 그대로 유지해 "가장 최신"을 뽑는 데 쓴다.
    # eol이 날짜가 아닌 항목(false = 아직 지원 중이고 종료일 미발표)도 버리지 않고 남긴다.
    # 애플처럼 종료일을 예고하지 않는 제품은 "미정"으로 보여주는 것이 맞다.
    out = []
    for c in data:
        eol = c.get("eol")
        out.append({
            "cycle": str(c.get("cycle")),
            "eol": eol if isinstance(eol, str) else None,
            "lts": bool(c.get("lts")),
            "latest": c.get("latest"),
            "release": c.get("releaseDate"),
        })
    return out


def fetch_cycles(conn, force: bool = False) -> dict:
    """제품별 릴리스 목록을 받아온다. 실패해도 예외를 던지지 않고 캐시로 폴백한다."""
    cache = get_setting(conn, CACHE_KEY) or {}
    products = sorted(set(OS_PRODUCTS.values()))

    if not force and cache.get("products"):
        return {"products": cache["products"], "fetched_at": cache.get("fetched_at"),
                "source": "cache", "errors": {}}

    result: dict[str, list] = {}
    errors: dict[str, str] = {}
    for product in products:
        try:
            result[product] = _fetch_product(product)
        except urllib.error.HTTPError as e:
            errors[product] = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            errors[product] = f"연결 실패 ({e.reason})"
        except Exception as e:                       # 형식 변경·타임아웃 등
            errors[product] = f"{type(e).__name__}: {e}"

    if not result:
        # 전부 실패했다면 이전 캐시라도 돌려준다 (NFR-15)
        if cache.get("products"):
            return {"products": cache["products"], "fetched_at": cache.get("fetched_at"),
                    "source": "cache_fallback", "errors": errors}
        return {"products": {}, "fetched_at": None, "source": "failed", "errors": errors}

    merged = {**(cache.get("products") or {}), **result}
    set_setting(conn, CACHE_KEY, {"products": merged, "fetched_at": now_str()})
    return {"products": merged, "fetched_at": now_str(), "source": "live", "errors": errors}


# ---------------------------------------------------------------- 자동 추천
def candidates(os_label: str, cycles: list[dict]) -> list[dict]:
    """해당 OS 코드에 실제로 해당하는 릴리스만 남긴다.

    windows.json 하나에 Windows 10과 11이 섞여 있으므로 이름 접두사로 갈라야
    'Windows 11' 선택지에 Windows 10 릴리스가 끼지 않는다.
    """
    product = OS_PRODUCTS.get(os_label)
    if not product or not cycles:
        return []
    if product == "windows":
        prefix = os_label.split()[-1] + "-"           # 'Windows 11' → '11-'
        return [c for c in cycles if c["cycle"].startswith(prefix)]
    return list(cycles)


def suggest_cycle(os_label: str, cycles: list[dict]) -> str | None:
    """이 OS를 최신 상태로 유지했을 때 기준이 되는 릴리스를 고른다.

    "가장 늦게 끝나는 릴리스"가 아니라 **가장 최신 릴리스**를 고른다.
    전자로 하면 특수 목적 LTSC(예: Windows 10 IoT LTSC 2032)가 뽑혀 위험을 실제보다 낮게 보여준다.
    """
    cands = candidates(os_label, cycles)
    if not cands:
        return None
    exclude = _EXCLUDE.get(OS_PRODUCTS.get(os_label))
    if exclude:
        filtered = [c for c in cands if not exclude(c)]
        if filtered:
            cands = filtered
    return cands[0]["cycle"]                          # API 순서상 맨 앞이 최신


def build_view(conn, force: bool = False) -> dict:
    """화면에 필요한 것을 한 번에 만든다: OS 코드별 현재 매핑·추천·적용 대상 건수."""
    fetched = fetch_cycles(conn, force=force)
    mapping = get_setting(conn, MAPPING_KEY) or {}
    today = today_str()

    items = []
    for os_label, product in OS_PRODUCTS.items():
        all_cycles = fetched["products"].get(product, [])
        cycles = [{**c, "expired": bool(c["eol"] and c["eol"] < today)}
                  for c in candidates(os_label, all_cycles)]
        chosen = mapping.get(os_label) or suggest_cycle(os_label, all_cycles)
        eol = next((c["eol"] for c in cycles if c["cycle"] == chosen), None)
        counts = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN os_eol_date IS NULL THEN 1 ELSE 0 END) missing,
                      SUM(CASE WHEN os_eol_date IS NOT NULL AND os_eol_date <> ? THEN 1 ELSE 0 END) differs
               FROM asset WHERE os = ? AND status <> '폐기'""",
            (eol or "", os_label)).fetchone()
        items.append({
            "os": os_label,
            "product": product,
            "cycle": chosen,
            "eol": eol,
            "expired": bool(eol and eol < today),
            "is_manual": os_label in mapping,
            "suggested": suggest_cycle(os_label, all_cycles),
            "asset_count": counts["total"] or 0,
            "need_update": (counts["missing"] or 0) + (counts["differs"] or 0),
            "cycles": cycles,
        })

    return {
        "items": items,
        "fetched_at": fetched["fetched_at"],
        "source": fetched["source"],
        "errors": fetched["errors"],
        "api": API_BASE,
        "unmapped_os": [r["label"] for r in conn.execute(
            "SELECT label FROM code WHERE group_code='OS' AND is_active=1").fetchall()
            if r["label"] not in OS_PRODUCTS],
    }


# ---------------------------------------------------------------- 자산에 반영
def apply_eol(conn, mapping: dict, user: dict) -> dict:
    """선택한 릴리스의 지원종료일을 해당 OS 자산에 일괄 반영하고 이력을 남긴다."""
    fetched = fetch_cycles(conn)
    if not fetched["products"]:
        raise AppError("지원종료일 정보를 아직 받아오지 못했습니다. [갱신]을 먼저 실행하세요.")

    set_setting(conn, MAPPING_KEY, mapping, user["name"])

    updated, per_os = 0, []
    for os_label, cycle in mapping.items():
        product = OS_PRODUCTS.get(os_label)
        if not product or not cycle:
            continue
        cycles = fetched["products"].get(product, [])
        eol = next((c["eol"] for c in cycles if c["cycle"] == cycle), None)
        if not eol:
            # 아직 지원종료일이 발표되지 않은 릴리스(예: 최신 macOS)는 날짜를 쓸 수 없다
            per_os.append({"os": os_label, "cycle": cycle, "eol": None, "updated": 0,
                           "skipped": "지원종료일이 발표되지 않은 릴리스입니다."})
            continue

        rows = conn.execute(
            """SELECT id, asset_no, os_eol_date FROM asset
               WHERE os = ? AND status <> '폐기'
                 AND (os_eol_date IS NULL OR os_eol_date <> ?)""",
            (os_label, eol)).fetchall()

        for r in rows:
            conn.execute("UPDATE asset SET os_eol_date = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                         (eol, now_str(), user["name"], r["id"]))
            add_history(conn, r["id"], r["asset_no"], HIST_UPDATE, user["name"],
                        reason=f"OS 지원종료일 자동 반영 ({os_label} {cycle})",
                        before={"os_eol_date": r["os_eol_date"]}, after={"os_eol_date": eol},
                        extra={"source": "endoflife.date", "cycle": cycle})
        updated += len(rows)
        per_os.append({"os": os_label, "cycle": cycle, "eol": eol, "updated": len(rows)})

    return {"updated": updated, "detail": per_os}
