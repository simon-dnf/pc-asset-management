"""v1 자체 점검 — PRD의 주요 요구사항을 API 시나리오로 확인한다.

    python tools\\selftest.py

운영 DB(data/assets.db)는 건드리지 않는다. 매 실행마다 data/selftest.db를 새로 만든다.
"""
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 운영 데이터와 분리된 임시 DB에서 실행한다.
TEST_DB = ROOT / "data" / "selftest.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
for suffix in ("", "-wal", "-shm"):
    p = Path(str(TEST_DB) + suffix)
    if p.exists():
        p.unlink()
os.environ["PCAMS_DB"] = str(TEST_DB)
os.environ["PCAMS_ADMIN_PW"] = "admin1234"

from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
ok = fail = 0

def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label} {extra}")

print("== FR-01 로그인 ==")
r = c.get("/api/dashboard"); check("미인증 401", r.status_code == 401, r.status_code)
r = c.post("/api/login", json={"username": "admin", "password": "wrong"})
check("오류 비밀번호 401", r.status_code == 401, r.text)
r = c.post("/api/login", json={"username": "admin", "password": "admin1234"})
check("로그인 성공", r.status_code == 200, r.text)
check("me 조회", c.get("/api/me").status_code == 200)

print("== FR-13 공통코드 ==")
r = c.get("/api/codes/options"); opt = r.json()
check("사업장 6개", len(opt["SITE"]) == 6, opt.get("SITE"))
check("부서 2단계", any(d["parent"] for d in opt["DEPT"]))
r = c.post("/api/codes", json={"group_code": "STATUS", "label": "테스트"})
check("상태코드 추가 차단", r.status_code == 400, r.text)

print("== FR-14 임직원 ==")
r = c.post("/api/employees", json={"emp_no": "20210315", "name": "홍길동",
                                   "dept_code": "생산기술팀", "position_code": "대리", "site_code": "시화"})
check("임직원 등록", r.status_code == 200, r.text)
r = c.post("/api/employees", json={"emp_no": "20210315", "name": "중복"})
check("사번 중복 차단", r.status_code == 400)
r = c.post("/api/employees", json={"emp_no": "20260801", "name": "김신입",
                                   "dept_code": "품질보증팀", "site_code": "시화"})
check("임직원2 등록", r.status_code == 200, r.text)
r = c.get("/api/employees/suggest?q=홍길")
check("자동완성", r.json()["items"][0]["emp_no"] == "20210315", r.text)

print("== FR-02 자산 등록 ==")
base = {"asset_type": "데스크톱", "manufacturer": "삼성", "model_name": "DM500SFA-A58A",
        "purchase_date": "2024-03-05", "site": "시화", "location": "B동 2층",
        "manager_emp_no": "김IT", "ram_gb": "16GB", "disk_gb": "512", "disk_type": "NVMe",
        "os": "Windows 11", "ip_address": "10.20.3.41", "ip_type": "고정",
        "mac_address": "ac-de-48-00-11-22", "serial_no": "SN-A-0001", "useful_life_years": 5}
r = c.post("/api/assets", json={**base, "asset_no": "pc-2026-0001"})
check("등록 성공", r.status_code == 200, r.text)
a1 = r.json()["id"]
check("자산번호 대문자 정규화", r.json()["asset_no"] == "PC-2026-0001", r.json())
r = c.get(f"/api/assets/{a1}")
d = r.json()
check("MAC 정규화", d["mac_address"] == "AC:DE:48:00:11:22", d["mac_address"])
check("RAM 숫자 변환", d["ram_gb"] == 16, d["ram_gb"])
check("기본 상태 대기", d["status"] == "대기", d["status"])
check("CREATE 이력", len(c.get(f"/api/assets/{a1}/history").json()["items"]) == 1)

r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0001", "serial_no": "SN-X"})
check("자산번호 중복 차단", r.status_code == 400 and "이미 등록된 자산번호" in r.text, r.text)
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0002"})
check("시리얼 중복 차단", r.status_code == 400 and "시리얼" in r.text, r.text)
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0002", "serial_no": "SN-B-0002",
                                "purchase_date": "2099-01-01"})
check("미래 구매일 차단", r.status_code == 400, r.text)
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0002", "serial_no": "SN-B-0002",
                                "ip_address": "999.1.1.1"})
check("IP 형식 차단", r.status_code == 400, r.text)
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0002", "serial_no": "SN-B-0002",
                                "asset_type": "데스크탑"})
check("코드 유사값 제안", r.status_code == 400 and "데스크톱" in r.text, r.text)

# hostname 중복은 경고만
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0002", "serial_no": "SN-B-0002",
                                "asset_type": "노트북", "hostname": "SIH-PC-01"})
a2 = r.json()["id"]
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0003", "serial_no": "SN-C-0003",
                                "hostname": "SIH-PC-01", "ip_address": "10.20.3.42"})
check("hostname 중복 경고(등록 허용)", r.status_code == 200 and r.json()["warnings"], r.text)
a3 = r.json()["id"]

print("== FR-08 배정 ==")
r = c.post(f"/api/assets/{a1}/assign", json={"emp_no": "20210315", "issue_date": "2026-03-02",
                                             "reason": "신규 입사자 배정"})
check("배정 성공", r.status_code == 200, r.text)
d = c.get(f"/api/assets/{a1}").json()
check("상태 사용중", d["status"] == "사용중", d["status"])
check("사용자 자동 채움", d["assignment"]["user_name"] == "홍길동", d["assignment"])
check("부서 자동 채움", d["assignment"]["dept_code"] == "생산기술팀", d["assignment"])
check("부서 라벨 2단계", d["dept_label"] == "생산본부 / 생산기술팀", d["dept_label"])
r = c.post(f"/api/assets/{a2}/assign", json={"emp_no": "20210315", "reason": "추가 배정"})
check("1인 다수 자산 배정", r.status_code == 200, r.text)
r = c.post(f"/api/assets/{a1}/assign", json={"emp_no": "20210315", "issue_date": "2020-01-01"})
check("지급일 < 구매일 차단", r.status_code == 400, r.text)

print("== FR-12 상태 전환 ==")
r = c.post(f"/api/assets/{a1}/status", json={"status": "폐기예정", "reason": "노후"})
check("사용중→폐기예정 차단", r.status_code == 400 and "회수" in r.text, r.text)
r = c.post(f"/api/assets/{a1}/status", json={"status": "수리"})
check("사유 없으면 차단", r.status_code == 400, r.text)
r = c.post(f"/api/assets/{a1}/status", json={"status": "수리", "reason": "메인보드 장애"})
check("사용중→수리 허용", r.status_code == 200, r.text)

print("== FR-09 회수 ==")
r = c.post(f"/api/assets/{a1}/return", json={"return_date": "2020-01-01", "return_reason": "퇴사"})
check("회수일 < 지급일 차단", r.status_code == 400, r.text)
r = c.post(f"/api/assets/{a1}/return", json={"return_reason": "퇴사", "after_status": "대기"})
check("회수 성공", r.status_code == 200, r.text)
d = c.get(f"/api/assets/{a1}").json()
check("회수 후 대기", d["status"] == "대기" and d["assignment"] is None, d["status"])
check("사용 이력 보존", d["usage_history"][0]["user_name"] == "홍길동", d["usage_history"])

print("== FR-04 수정 ==")
r = c.put(f"/api/assets/{a1}", json={"ram_gb": 32})
check("사유 없으면 차단", r.status_code == 400, r.text)
r = c.put(f"/api/assets/{a1}", json={"ram_gb": 32, "disk_gb": 1024, "reason": "RAM 증설"})
check("수정 성공", r.status_code == 200, r.text)
check("변경 필드만 기록", set(r.json()["changed"]) == {"ram_gb", "disk_gb"}, r.json()["changed"])
r = c.put(f"/api/assets/{a1}", json={"ram_gb": 32, "reason": "변경 없음"})
check("무변경 시 이력 없음", r.json()["changed"] == {}, r.json())
r = c.put(f"/api/assets/{a1}", json={"asset_no": "PC-9999", "reason": "번호 변경 시도"})
check("자산번호 수정 차단", r.status_code == 400, r.text)
r = c.put(f"/api/assets/{a1}", json={"site": "판교", "reason": "사업장 이동"})
h = c.get(f"/api/assets/{a1}/history").json()["items"]
check("사업장 변경은 MOVE", h[0]["hist_type"] == "MOVE", h[0]["hist_type"])

print("== FR-05 검색 ==")
check("통합검색 자산번호", c.get("/api/assets?q=PC-2026-0001").json()["total"] == 1)
check("통합검색 hostname", c.get("/api/assets?q=SIH-PC-01").json()["total"] == 2)
check("상태 복수선택", c.get("/api/assets?status=대기,사용중").json()["total"] >= 2)
# 05-4 동일 필터 내 복수 선택은 OR, 서로 다른 필터는 AND
only_nb = c.get("/api/assets?asset_type=노트북").json()["total"]
only_dt = c.get("/api/assets?asset_type=데스크톱").json()["total"]
both = c.get("/api/assets?asset_type=노트북,데스크톱").json()["total"]
check("동일 필터 복수선택 OR", both == only_nb + only_dt, f"{both} vs {only_nb}+{only_dt}")
and_hit = c.get("/api/assets?asset_type=노트북,데스크톱&site=판교").json()["total"]
check("다른 필터끼리 AND", and_hit <= both, f"{and_hit} <= {both}")
check("사업장 필터", c.get("/api/assets?site=판교").json()["total"] == 1)
check("빠른필터 대기", c.get("/api/assets?quick=to_dispose").json()["total"] == 0)

print("== FR-11 대시보드 ==")
dash = c.get("/api/dashboard").json()
check("보유 집계", dash["summary"]["holding"] == 3, dash["summary"])
check("사업장별 집계", len(dash["sites"]) >= 1, dash["sites"])
check("조치필요 키", set(dash["actions"]) >= {"overdue", "unassigned", "long_repair", "to_dispose", "aged"})
# 11-8 기간 필터 — 구매일 기준으로 집계 대상을 좁힌다
narrow = c.get("/api/dashboard?date_from=2030-01-01").json()
check("기간 필터 집계 축소", narrow["summary"]["holding"] == 0, narrow["summary"])
check("기간 필터 조치필요는 전체 유지",
      narrow["actions"]["to_dispose"]["count"] == dash["actions"]["to_dispose"]["count"],
      narrow["actions"]["to_dispose"]["count"])
wide = c.get("/api/dashboard?date_from=2000-01-01&date_to=2030-12-31").json()
check("기간 필터 전체 범위", wide["summary"]["holding"] == dash["summary"]["holding"], wide["summary"])

print("== FR-06 엑셀 가져오기 ==")
from openpyxl import Workbook
wb = Workbook(); ws = wb.active
ws.append(["자산번호", "자산구분", "제조사", "모델명", "구매일", "자산상태", "사업장", "담당자",
           "사번", "사용자", "지급일", "RAM", "시리얼번호"])
ws.append(["PC-2026-0101", "노트북", "LG", "gram 16", "2025-01-10", "사용중", "판교", "김IT",
           "20260801", "", "2025-01-15", "16GB", "SN-101"])
ws.append(["PC-2026-0102", "데스크탑", "삼성", "DM500", "2025-02-10", "대기", "서울", "김IT",
           "", "", "", "8GB", "SN-102"])       # 자산구분 오타 → 오류
ws.append(["PC-2026-0103", "노트북", "삼성", "NT550", "2025-03-10", "사용중", "인천", "김IT",
           "", "", "", "16", "SN-103"])        # 사용중인데 사번 없음 → 오류
ws.append(["PC-2026-0101", "노트북", "LG", "gram 17", "2025-04-10", "대기", "서울", "김IT",
           "", "", "", "16", "SN-104"])        # 파일 내 중복 → 오류
buf = io.BytesIO(); wb.save(buf)

r = c.post("/api/imports/upload", data={"kind": "asset"},
           files={"file": ("대장.xlsx", buf.getvalue(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
check("업로드", r.status_code == 200, r.text)
up = r.json()
check("자동 매핑(사용자→사용자명)", up["mapping"].get("사용자") == "user_name", up["mapping"])
check("자동 매핑(RAM)", up["mapping"].get("RAM") == "ram_gb", up["mapping"])
check("자동 매핑(담당자)", up["mapping"].get("담당자") == "manager_emp_no", up["mapping"])
check("미리보기 4행", len(up["preview"]) == 4, len(up["preview"]))

r = c.post("/api/imports/validate", json={"token": up["token"], "mapping": up["mapping"],
                                          "dup_policy": "skip"})
v = r.json()
check("검증 실행", r.status_code == 200, r.text)
check("오류 3건 행", v["counts"]["error"] == 3, v["counts"])
check("정상 1건", v["counts"]["ok"] == 1, v["counts"])
msgs = " | ".join(e["message"] for e in v["errors"])
check("오타 제안", "데스크톱" in msgs, msgs)
check("논리검증(사용중 사번)", "사번이 필요" in msgs, msgs)
check("파일 내 중복", "중복" in msgs, msgs)
check("오류리포트 다운로드", c.get(f"/api/imports/errors.xlsx?token={up['token']}").status_code == 200)

r = c.post("/api/imports/commit", json={"token": up["token"], "mapping": up["mapping"],
                                        "dup_policy": "skip", "mode": "all_or_nothing"})
check("All-or-Nothing 전체 취소", r.status_code == 400 and "전체 취소" in r.text, r.text)
r = c.post("/api/imports/commit", json={"token": up["token"], "mapping": up["mapping"],
                                        "dup_policy": "skip", "mode": "partial"})
check("부분 반영 성공", r.status_code == 200 and r.json()["success"] == 1, r.text)
batch = r.json()
r = c.get("/api/assets?q=PC-2026-0101").json()
check("가져온 자산 배정됨", r["items"][0]["cur_user_name"] == "김신입", r["items"])
hh = c.get(f"/api/assets/{r['items'][0]['id']}/history").json()["items"]
check("배치ID 이력", any(h["extra"].get("batch_no") for h in hh), hh)

r = c.post(f"/api/imports/batches/{batch['batch_id']}/revert")
check("배치 되돌리기", r.status_code == 200 and len(r.json()["removed"]) == 1, r.text)
check("되돌린 후 자산 없음", c.get("/api/assets?q=PC-2026-0101").json()["total"] == 0)

print("== FR-07 엑셀 내보내기 ==")
r = c.get("/api/assets/export.xlsx?scope=full&with_history=true")
check("내보내기", r.status_code == 200 and len(r.content) > 3000, r.status_code)
check("파일명 규칙", "%EC%9E%90%EC%82%B0%ED%98%84%ED%99%A9" in r.headers.get("content-disposition", ""),
      r.headers.get("content-disposition"))
check("템플릿 다운로드", c.get("/api/imports/template.xlsx?kind=asset").status_code == 200)

print("== FR-10 통합 이력 ==")
r = c.get("/api/history?hist_type=MOVE")
check("이력 유형 필터", r.json()["total"] >= 1, r.json()["total"])
check("이력 내보내기", c.get("/api/history/export.xlsx").status_code == 200)

print("== FR-04 삭제 제한 ==")
r = c.request("DELETE", f"/api/assets/{a1}?reason=오등록")
check("이력 있는 자산 삭제 차단", r.status_code == 400, r.text)
r = c.post("/api/assets", json={**base, "asset_no": "PC-2026-0900", "serial_no": "SN-900"})
tmp = r.json()["id"]
r = c.request("DELETE", f"/api/assets/{tmp}?reason=오등록 취소")
check("신규 자산 삭제 허용", r.status_code == 200, r.text)

print("== FR-14 퇴사 경고 / 부서 동기화 ==")
r = c.put("/api/employees/20210315", json={"emp_no": "20210315", "name": "홍길동",
                                           "dept_code": "품질보증팀", "site_code": "시화",
                                           "employ_status": "퇴사"})
check("퇴사 시 미회수 경고", r.status_code == 200 and r.json()["warnings"], r.text)
d = c.get("/api/employees/20210315").json()
check("부서 불일치 감지", len(d["dept_mismatch"]) == 1, d["dept_mismatch"])
r = c.post("/api/employees/20210315/sync-dept", json={"reason": "부서 이동 반영"})
check("부서 일괄 동기화", len(r.json()["updated"]) == 1, r.text)
check("퇴사자 미회수 대시보드", c.get("/api/dashboard").json()["actions"]["resigned"]["count"] == 1)

print("== 일괄 처리 ==")
r = c.post("/api/assets/bulk/return", json={"ids": [a2], "payload": {"return_reason": "퇴사"}})
check("일괄 회수", r.status_code == 200 and r.json()["success"] == 1, r.text)
r = c.post("/api/assets/bulk/status", json={"ids": [a1, a2],
                                            "payload": {"status": "폐기예정", "reason": "노후 교체"}})
check("일괄 상태변경", r.json()["success"] == 2, r.text)
r = c.post("/api/assets/bulk/status", json={"ids": [a1], "payload": {
    "status": "폐기", "reason": "파기 완료", "disposal_date": "2026-08-30",
    "disposal_method": "HDD 물리파기"}})
check("폐기 처리", r.json()["success"] == 1, r.text)
check("폐기 자산 목록 제외", c.get("/api/assets?q=PC-2026-0001").json()["total"] == 0)
check("폐기 포함 조회", c.get("/api/assets?q=PC-2026-0001&include_disposed=1").json()["total"] == 1)
r = c.put(f"/api/assets/{a1}", json={"ram_gb": 64, "reason": "폐기 후 수정"})
check("폐기 자산 수정 차단", r.status_code == 400, r.text)
r = c.post(f"/api/assets/{a1}/status", json={"status": "대기", "reason": "되돌리기"})
check("폐기 최종상태", r.status_code == 400, r.text)

print("== 계정 / 비밀번호 ==")
r = c.post("/api/accounts", json={"username": "kimit", "name": "김IT", "password": "short"})
check("비밀번호 정책", r.status_code == 400, r.text)
r = c.post("/api/accounts", json={"username": "kimit", "name": "김IT", "password": "pass1234"})
check("계정 생성", r.status_code == 200, r.text)
r = c.post("/api/me/password", json={"current_password": "wrong", "new_password": "newpass123"})
check("현재 비번 불일치", r.status_code == 400, r.text)
r = c.post("/api/me/password", json={"current_password": "admin1234", "new_password": "newpass123"})
check("비밀번호 변경", r.status_code == 200, r.text)
check("변경 후 세션 만료", c.get("/api/me").status_code == 401)
check("새 비번 로그인", c.post("/api/login", json={"username": "admin", "password": "newpass123"}).status_code == 200)

print("== 03-8 / 05-8 계정별 화면 설정 ==")
check("초기 설정 비어 있음", c.get("/api/me/prefs").json()["prefs"] == {}, c.get("/api/me/prefs").text)
cols = ["asset_no", "status", "purchase_date"]
r = c.put("/api/me/prefs/asset_columns", json={"value": cols})
check("표시 컬럼 저장", r.status_code == 200, r.text)
r = c.put("/api/me/prefs/saved_searches",
          json={"value": [{"name": "판교 대기", "filters": {"status": "대기", "site": "판교"}}]})
check("검색 조건 저장", r.status_code == 200, r.text)
p_ = c.get("/api/me/prefs").json()["prefs"]
check("설정 재조회", p_["asset_columns"] == cols, p_)
check("검색 조건 재조회", p_["saved_searches"][0]["name"] == "판교 대기", p_)
r = c.put("/api/me/prefs/asset_columns", json={"value": ["asset_no", "site"]})
check("설정 덮어쓰기", c.get("/api/me/prefs").json()["prefs"]["asset_columns"] == ["asset_no", "site"])
r = c.put("/api/me/prefs/evil_key", json={"value": 1})
check("허용되지 않은 키 차단", r.status_code == 400, r.text)
r = c.put("/api/me/prefs/asset_columns", json={"value": ["x" * 70000]})
check("과대 설정 차단", r.status_code == 400, r.text)
r = c.delete("/api/me/prefs/saved_searches")
check("설정 초기화", r.status_code == 200 and "saved_searches" not in c.get("/api/me/prefs").json()["prefs"], r.text)

# 계정이 다르면 설정도 분리된다
c.post("/api/accounts", json={"username": "prefuser", "name": "설정테스트", "password": "pass1234"})
c3 = TestClient(app)
c3.post("/api/login", json={"username": "prefuser", "password": "pass1234"})
check("계정별로 설정 분리", c3.get("/api/me/prefs").json()["prefs"] == {}, c3.get("/api/me/prefs").text)
check("미인증 설정 접근 차단", TestClient(app).get("/api/me/prefs").status_code == 401)

print("== NFR-08 계정 잠금 ==")
c2 = TestClient(app)
for i in range(5):
    c2.post("/api/login", json={"username": "kimit", "password": "wrong123"})
r = c2.post("/api/login", json={"username": "kimit", "password": "pass1234"})
check("5회 실패 후 잠금", r.status_code == 423, r.text)

print("== NFR-13 이력 불변 ==")
from app.db import transaction
import sqlite3
try:
    with transaction() as conn:
        conn.execute("UPDATE asset_history SET reason='변조' WHERE id=1")
    check("이력 수정 차단", False, "예외 없음")
except sqlite3.IntegrityError as e:
    check("이력 수정 차단", "수정할 수 없습니다" in str(e), str(e))
except Exception as e:
    check("이력 수정 차단", "수정할 수 없습니다" in str(e), repr(e))

print(f"\n===== PASS {ok} / FAIL {fail} =====")
sys.exit(1 if fail else 0)
