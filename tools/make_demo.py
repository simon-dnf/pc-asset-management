"""데모 데이터 생성기 — 화면 확인·교육용 샘플을 만든다. 운영 데이터에는 사용하지 않는다."""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import (HIST_ASSIGN, HIST_CREATE, HIST_RETURN, HIST_STATUS, ST_DISPOSED,
                      ST_INUSE, ST_READY, ST_REPAIR, ST_TO_DISPOSE, now_str, today_str)
from app.db import DB_PATH, init_db, transaction
from app.main import bootstrap
from app.seed import DEPT_SEED
from app.services.assets import add_history, create_assignment, insert_asset

SITES = ["서울", "인천", "시화", "판교", "발안", "음성"]
SITE_WEIGHT = [32, 12, 23, 17, 9, 7]
TYPES = [("데스크톱", 62), ("노트북", 35), ("워크스테이션", 3)]
MAKERS = ["삼성", "LG", "Dell", "HP", "Lenovo"]
MODELS = {
    "삼성": ["DM500SFA-A58A", "DB400T7A", "NT750XDA-KC58S", "NT550XDA"],
    "LG": ["24V70N-GR56K", "gram 16Z90R", "gram 17Z90Q"],
    "Dell": ["OptiPlex 7010", "Latitude 5440", "Precision 3660"],
    "HP": ["ProDesk 400 G9", "EliteBook 840 G10", "Z2 Tower G9"],
    "Lenovo": ["ThinkCentre M70q", "ThinkPad E14", "ThinkStation P360"],
}
CPUS = ["Intel i5-12400", "Intel i5-13500", "Intel i7-12700", "Intel i7-13700",
        "Intel i9-13900", "AMD Ryzen 5 5600G", "AMD Ryzen 7 7700"]
SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍"
GIVEN = ["민준", "서연", "도윤", "지우", "예준", "하윤", "시우", "서윤", "주원", "지민",
         "건우", "수아", "우진", "지호", "은우", "다은", "정우", "채원", "성민", "가은"]
POSITIONS = ["사원", "주임", "대리", "과장", "차장", "부장"]
LOCATIONS = ["A동 1층", "A동 2층", "A동 3층", "B동 1층", "B동 2층", "C동 4층", "본관 5층", "연구동 2층"]
MANAGERS = ["김IT", "이인프라", "박전산"]

rnd = random.Random(20260901)


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _pick(pairs):
    vals, weights = zip(*pairs)
    return rnd.choices(vals, weights=weights, k=1)[0]


def run(reset: bool = False, employees: int = 1000, assets: int = 1400) -> dict:
    if reset:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()
    bootstrap()
    init_db()

    teams = [t for _, ts in DEPT_SEED for t in ts]
    user = {"name": "데모생성기"}

    with transaction() as conn:
        if conn.execute("SELECT COUNT(*) c FROM asset").fetchone()["c"] > 0 and not reset:
            print("  이미 데이터가 있어 데모 생성을 건너뜁니다. (--reset-demo 로 초기화)")
            return {"skipped": True}

        # ---------------- 임직원
        emps = []
        used = set()
        for i in range(employees):
            emp_no = f"20{rnd.randint(15, 26):02d}{rnd.randint(1000, 9999)}"
            if emp_no in used:
                continue
            used.add(emp_no)
            name = rnd.choice(SURNAMES) + rnd.choice(GIVEN)
            dept = rnd.choice(teams)
            site = rnd.choices(SITES, SITE_WEIGHT)[0]
            status = _pick([("재직", 92), ("휴직", 3), ("퇴사", 5)])
            conn.execute(
                """INSERT INTO employee (emp_no, name, dept_code, position_code, site_code,
                                         employ_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (emp_no, name, dept, rnd.choice(POSITIONS), site, status, now_str(), now_str()))
            emps.append({"emp_no": emp_no, "name": name, "dept": dept, "site": site, "status": status})

        # ---------------- 자산
        counters: dict[int, int] = {}
        made = 0
        for i in range(assets):
            year = rnd.choices([2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
                               [4, 6, 9, 13, 16, 20, 22, 10])[0]
            counters[year] = counters.get(year, 0) + 1
            asset_no = f"PC-{year}-{counters[year]:04d}"
            maker = rnd.choice(MAKERS)
            atype = _pick(TYPES)
            site = rnd.choices(SITES, SITE_WEIGHT)[0]
            purchase = date(year, rnd.randint(1, 12), rnd.randint(1, 28))
            if purchase > date.today():
                purchase = date.today() - timedelta(days=rnd.randint(1, 60))

            status = _pick([(ST_INUSE, 76), (ST_READY, 11), (ST_REPAIR, 4),
                            (ST_TO_DISPOSE, 4), (ST_DISPOSED, 5)])
            values = {
                "asset_no": asset_no, "asset_type": atype, "manufacturer": maker,
                "model_name": rnd.choice(MODELS[maker]),
                "serial_no": f"SN{year}{i:06d}",
                "purchase_date": purchase.strftime("%Y-%m-%d"),
                "service_start_date": (purchase + timedelta(days=rnd.randint(1, 20))).strftime("%Y-%m-%d"),
                "purchase_amount": rnd.choice([850000, 1050000, 1250000, 1450000, 1850000, 2400000]),
                "useful_life_years": 5,
                "site": site, "location": rnd.choice(LOCATIONS),
                "manager_emp_no": rnd.choice(MANAGERS),
                "hostname": f"{site[0]}{atype[0]}-{rnd.randint(1000, 9999)}",
                "ip_address": f"10.{SITES.index(site) + 20}.{rnd.randint(1, 40)}.{rnd.randint(2, 250)}",
                "ip_type": _pick([("고정", 70), ("DHCP", 30)]),
                "mac_address": ":".join(f"{rnd.randint(0, 255):02X}" for _ in range(6)),
                "cpu": rnd.choice(CPUS),
                "ram_gb": rnd.choices([8, 16, 32, 64], [22, 52, 22, 4])[0],
                "disk_type": rnd.choices(["NVMe", "SSD", "HDD"], [55, 38, 7])[0],
                "disk_gb": rnd.choices([256, 512, 1024, 2048], [22, 52, 22, 4])[0],
                "os": rnd.choices(["Windows 11", "Windows 10", "기타"], [66, 32, 2])[0],
                "remark": None,
            }
            if status == ST_DISPOSED:
                values["disposal_date"] = _d(rnd.randint(1, 500))
                values["disposal_method"] = rnd.choice(["HDD 물리파기", "완전삭제(디가우징)", "업체 반납", "매각"])

            asset_id = insert_asset(conn, values, user, status=status, method="수동")
            created = min(purchase + timedelta(days=rnd.randint(0, 10)), date.today())
            add_history(conn, asset_id, asset_no, HIST_CREATE, "김IT", "초기 대장 이관",
                        after={"status": ST_READY}, extra={"method": "엑셀", "batch_no": "IMP-DEMO-001"},
                        occurred_at=created.strftime("%Y-%m-%d 09:%M:00").replace("%M", f"{rnd.randint(10,59):02d}"))

            if status == ST_INUSE:
                pool = [e for e in emps if e["site"] == site] or emps
                emp = rnd.choice(pool)
                issue = purchase + timedelta(days=rnd.randint(3, 60))
                if issue > date.today():
                    issue = date.today()
                due = None
                if rnd.random() < 0.10:                    # 반납예정일이 있는 임시 배정
                    due = (date.today() + timedelta(days=rnd.randint(-40, 40))).strftime("%Y-%m-%d")
                create_assignment(conn, asset_id, {
                    "emp_no": emp["emp_no"], "user_name": emp["name"], "dept_code": emp["dept"],
                    "position_code": rnd.choice(POSITIONS), "site": site,
                    "location": values["location"], "issue_date": issue.strftime("%Y-%m-%d"),
                    "due_return_date": due, "assign_reason": rnd.choice(
                        ["신규 입사자 배정", "장비 교체 배정", "부서 전입 배정"]),
                }, user)
                add_history(conn, asset_id, asset_no, HIST_ASSIGN, "김IT", "자산 배정",
                            before={"user_name": None, "status": ST_READY},
                            after={"user_name": emp["name"], "emp_no": emp["emp_no"],
                                   "dept_code": emp["dept"], "status": ST_INUSE},
                            occurred_at=issue.strftime("%Y-%m-%d 10:20:00"))
            elif status in (ST_REPAIR, ST_TO_DISPOSE, ST_DISPOSED):
                add_history(conn, asset_id, asset_no, HIST_STATUS, "김IT",
                            {"수리": "장애 접수", "폐기예정": "노후 장비 교체 대상",
                             "폐기": "폐기 처리 완료"}[status],
                            before={"status": ST_READY}, after={"status": status},
                            occurred_at=_d(rnd.randint(1, 300)) + " 14:30:00")
                if status == ST_REPAIR and rnd.random() < 0.4:
                    conn.execute("UPDATE asset SET updated_at = ? WHERE id = ?",
                                 (_d(rnd.randint(35, 90)) + " 14:30:00", asset_id))
            made += 1

    print(f"  데모 데이터 생성: 임직원 {len(emps)}명 / 자산 {made}대")
    return {"employees": len(emps), "assets": made}


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
