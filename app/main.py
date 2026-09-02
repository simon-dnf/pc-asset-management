"""PC 자산관리 시스템 v1 — 애플리케이션 진입점.

정적 프런트엔드(web/)를 이 서버가 그대로 서빙하므로 별도 빌드 도구가 필요 없다.
화면 자체는 외부 CDN 없이 동작한다. 외부 API 연동은 서버 측에서만 하고,
장애가 나도 화면과 자산 CRUD는 그대로 돌아가야 한다 (NFR-15).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import AppError
from .db import init_db
from .routers import (accounts, assets, codes, dashboard, employees, eol, history, imports,
                      session_api)
from . import seed

log = logging.getLogger("pcams")
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

def bootstrap() -> dict:
    """스키마 생성 + 초기 데이터 시딩. 여러 번 호출해도 안전하다."""
    init_db()
    result = seed.run()
    if result["admin_created"]:
        log.warning("최초 관리자 계정 생성: %s / 초기 비밀번호는 첫 로그인 후 변경하세요.",
                    result["admin_created"])
    return result


bootstrap()

app = FastAPI(title="PC 자산관리 시스템", version="1.0.0", docs_url=None, redoc_url=None)


@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "field": exc.field, "detail": exc.detail},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("처리되지 않은 오류: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"error": "서버 오류가 발생했습니다. 관리자에게 문의하세요."})


for r in (session_api.router, accounts.router, assets.bulk_router, assets.router,
          employees.router, codes.router, dashboard.router, history.router, imports.router,
          eol.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- 정적 파일 / SPA
class NoCacheStatic(StaticFiles):
    """화면 파일(js/css)에 `no-cache`를 붙인다.

    브라우저가 이전 버전을 붙잡고 있으면 프로그램을 갱신해도 화면이 그대로여서
    관리자가 매번 Ctrl+F5를 눌러야 한다. `no-cache`는 캐시를 금지하는 게 아니라
    **쓰기 전에 서버에 물어보게** 하는 것이라, 바뀌지 않았으면 304로 끝나 부담이 거의 없다.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


app.mount("/static", NoCacheStatic(directory=WEB_DIR), name="static")


@app.get("/{full_path:path}")
def spa(full_path: str):
    """SPA 라우팅. /api 이외의 모든 경로는 index.html로 넘긴다 (01-5 프런트에서 처리)."""
    candidate = (WEB_DIR / full_path).resolve()
    try:
        candidate.relative_to(WEB_DIR.resolve())
    except ValueError:
        candidate = None
    headers = {"Cache-Control": "no-cache, must-revalidate"}
    if full_path and candidate and candidate.is_file():
        return FileResponse(candidate, headers=headers)
    return FileResponse(WEB_DIR / "index.html", headers=headers)
