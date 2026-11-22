# -*- coding: utf-8 -*-
"""任务 API：上传校验 / 重命名 / 音色 / 健康检查 / 搜索转义"""


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_gbk_rejected(client):
    r = client.post("/api/task/upload", files={"file": ("a.md", b"\xc4\xe3\xba\xc3")}, data={"taskName": "x"})
    j = r.json()
    assert j["code"] != 200 and "UTF-8" in j["message"]


def test_upload_empty_rejected(client):
    r = client.post("/api/task/upload", files={"file": ("a.md", b"  \n")}, data={"taskName": "x"})
    assert r.json()["code"] != 200


def test_upload_success_and_detail(client, make_task):
    tid = make_task("P6TEST-DETAIL")
    d = client.get(f"/api/task/detail/{tid}").json()["data"]
    assert d["taskName"] == "P6TEST-DETAIL"
    assert d["ttsVoice"]  # 默认音色已下发


def test_rename(client, make_task):
    tid = make_task("P6TEST-RENAME")
    assert client.put("/api/task/rename", json={"task_id": tid, "task_name": "新名字"}).json()["code"] == 200
    assert client.get(f"/api/task/detail/{tid}").json()["data"]["taskName"] == "新名字"

    assert client.put("/api/task/rename", json={"task_id": tid, "task_name": "   "}).json()["code"] != 200
    assert client.put("/api/task/rename", json={"task_id": tid, "task_name": "x" * 51}).json()["code"] != 200
    assert client.put("/api/task/rename", json={"task_id": "no-such", "task_name": "a"}).json()["code"] != 200


def test_voice_validation(client, make_task):
    tid = make_task("P6TEST-VOICE")
    bad = client.put("/api/task/voice", json={"task_id": tid, "voice": "NoSuchVoice"})
    assert bad.json()["code"] != 200

    ok = client.put("/api/task/voice", json={"task_id": tid, "voice": "苏打"})
    assert ok.json()["code"] == 200
    assert client.get(f"/api/task/detail/{tid}").json()["data"]["ttsVoice"] == "苏打"


def test_search_like_escaped(client, make_task):
    tid = make_task("P6TEST-LIKE")
    r = client.get("/api/task/list?current=1&task_name=%").json()["data"]["records"]
    assert all(x["taskId"] != tid for x in r)
    r2 = client.get("/api/task/list?current=1&task_name=P6TEST-LIKE").json()["data"]["records"]
    assert any(x["taskId"] == tid for x in r2)
