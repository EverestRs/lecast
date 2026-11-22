"""页面路由（Jinja2 模板）"""

import secrets

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.config import APP_ACCESS_TOKEN
from app.templating import templates

router = APIRouter(tags=["页面"])


def _safe_next(next_url: str) -> str:
    """防开放重定向：仅允许站内绝对路径"""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/taskList"
    return next_url


@router.get("/")
def index():
    return RedirectResponse(url="/taskList")


@router.get("/login")
async def login_page(request: Request, next: str = "/taskList", error: str = ""):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next": _safe_next(next), "error": error},
        status_code=401 if error else 200,
    )


@router.post("/login")
async def login_submit(request: Request, token: str = Form(""), next: str = Form("/taskList")):
    target = _safe_next(next)
    provided = (token or "").strip()
    if not APP_ACCESS_TOKEN or not secrets.compare_digest(provided, APP_ACCESS_TOKEN):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "next": target, "error": "口令错误，请重新输入"},
            status_code=401,
        )
    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(
        "app_token", provided,
        max_age=30 * 24 * 3600, httponly=True, samesite="lax",
    )
    return resp


@router.get("/taskList")
async def task_list_page(request: Request):
    return templates.TemplateResponse("task_list.html", {"request": request})


@router.get("/taskCreate")
async def task_create_page(request: Request, task_id: str = ""):
    return templates.TemplateResponse("task_create.html", {"request": request, "task_id": task_id})


@router.get("/error")
async def error_page(request: Request):
    return templates.TemplateResponse("error.html", {"request": request})


