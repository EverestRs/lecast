# -*- coding: utf-8 -*-
import os
import sys

V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, V2)
os.chdir(V2)
os.environ.pop("APP_ACCESS_TOKEN", None)
os.environ.pop("STEPFUN_API_KEY", None)

import pytest
from fastapi.testclient import TestClient

from app.main import app

# 真实密钥联调脚本，仅手工运行：python tests/test_stepfun_live.py <KEY>
collect_ignore = ["test_stepfun_live.py"]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    from app.database import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def make_task(client):
    created = []

    def _make(name: str = "P6TEST") -> str:
        r = client.post(
            "/api/task/upload",
            files={"file": ("a.md", b"# t\nbody")},
            data={"taskName": name},
        )
        assert r.json()["code"] == 200
        tid = r.json()["data"]
        created.append(tid)
        return tid

    yield _make
    for tid in created:
        client.delete(f"/api/task/{tid}")


@pytest.fixture()
def wait_job(client):
    def _wait(step: str, task_id: str, timeout_s: float = 15.0):
        import time
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            snap = client.get(f"/api/task/job/{step}/{task_id}").json()["data"]
            if snap.get("state") in ("success", "failed"):
                return snap
            time.sleep(0.1)
        raise AssertionError(f"job {step} 超时未完成")
    return _wait
