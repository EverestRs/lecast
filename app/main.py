"""FastAPI 应用入口"""

import logging
import logging.handlers
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import text

from app.config import APP_ACCESS_TOKEN
from app.database import engine, init_db
from app.templating import templates
from app.routers import task, section, slide, script, tts, pages

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        ),
    ],
)

app = FastAPI(title="课映 Lecast", version="2.0.0")

# 静态文件
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.middleware("http")
async def access_gate(request: Request, call_next):
    """站点门禁：设置 APP_ACCESS_TOKEN 后，除 /static 与 /login 外均需持有口令 Cookie。"""
    if not APP_ACCESS_TOKEN:
        return await call_next(request)

    path = request.url.path
    if path.startswith("/static") or path in ("/login", "/healthz"):
        return await call_next(request)

    provided = request.cookies.get("app_token") or ""
    if secrets.compare_digest(provided, APP_ACCESS_TOKEN):
        return await call_next(request)

    if path.startswith("/api"):
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "未登录或口令已失效", "data": None},
        )
    next_url = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


@app.get("/healthz")
def healthz():
    """存活与数据库连通性探针（免鉴权）"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001 —— 探针不抛栈，只报状态
        return JSONResponse(status_code=500, content={"status": "db_error", "detail": str(e)[:200]})

# 注册 API 路由
app.include_router(task.router)
app.include_router(section.router)
app.include_router(slide.router)
app.include_router(script.router)
app.include_router(tts.router)

# 注册页面路由
app.include_router(pages.router)


@app.on_event("startup")
def on_startup():
    """启动时初始化数据库"""
    init_db()
    logging.info("✅ 数据库初始化完成")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": 404, "message": "页面未找到"},
        status_code=404,
    )


@app.exception_handler(Exception)
async def server_error(request: Request, exc):
    logging.getLogger(__name__).exception("服务器内部错误: %s %s", request.method, request.url.path)
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": 500, "message": "服务器内部错误，请稍后重试"},
        status_code=500,
    )