# -*- coding: utf-8 -*-
"""访问门禁与登录安全（Phase 3 回归）：拦截 / 豁免 / Cookie / 防开放重定向"""
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.routers.pages as pages_module
from app.routers.pages import _safe_next


@pytest.fixture()
def gated_client(monkeypatch):
    """启用门禁：config 在 import 时读取，这里直接替换两个模块级绑定"""
    monkeypatch.setattr(main_module, "APP_ACCESS_TOKEN", "secret123")
    monkeypatch.setattr(pages_module, "APP_ACCESS_TOKEN", "secret123")
    with TestClient(main_module.app) as c:
        yield c


def test_safe_next_whitelist():
    assert _safe_next("") == "/taskList"
    assert _safe_next("//evil.com") == "/taskList"
    assert _safe_next("http://evil.com/x") == "/taskList"
    assert _safe_next("/taskCreate") == "/taskCreate"


def test_gate_disabled_allows_direct_access():
    with TestClient(main_module.app) as c:
        r = c.get("/taskList")
        assert r.status_code == 200
        assert c.get("/api/task/list?current=1").json()["code"] == 200


def test_page_blocked_redirects_to_login(gated_client):
    r = gated_client.get("/taskList", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=")


def test_api_blocked_returns_401_json(gated_client):
    r = gated_client.get("/api/task/list", follow_redirects=False)
    assert r.status_code == 401
    assert r.json() == {"code": 401, "message": "未登录或口令已失效", "data": None}


def test_exempt_paths_pass_through(gated_client):
    assert gated_client.get("/healthz").json()["status"] == "ok"
    assert gated_client.get("/static/css/style.css").status_code == 200
    assert gated_client.get("/login").status_code == 200


def test_login_wrong_token(gated_client):
    r = gated_client.post("/login", data={"token": "wrong", "next": "/taskList"})
    assert r.status_code == 401
    assert "口令错误" in r.text


def test_login_success_sets_httponly_cookie_and_next(gated_client):
    r = gated_client.post(
        "/login", data={"token": "secret123", "next": "/taskCreate"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/taskCreate"

    set_cookies = r.headers.get_list("set-cookie")
    token_cookie = next(x for x in set_cookies if x.startswith("app_token="))
    assert "app_token=secret123" in token_cookie and "httponly" in token_cookie.lower()

    # 持 Cookie 后受保护页面直通
    assert gated_client.get("/taskList").status_code == 200


def test_forged_cookie_still_blocked(gated_client):
    r = gated_client.get("/taskList", cookies={"app_token": "forged"}, follow_redirects=False)
    assert r.status_code == 303
