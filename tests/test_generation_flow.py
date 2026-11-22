# -*- coding: utf-8 -*-
"""生成链路（mock Qwen）：split 全链路 / 幻灯片部分失败 / 章节删排级联失效"""
import json

import app.routers.section as section_router
import app.routers.slide as slide_router


def _wait_job(client, wait_job, step, tid):
    return wait_job(step, tid)


def test_split_partial_fail_and_section_ops(client, make_task, wait_job, monkeypatch):
    tid = make_task("P6TEST-FLOW")

    split_json = json.dumps({"sections": [
        {"title": f"c{i}", "content": f"x{i}"} for i in range(1, 4)
    ]})
    monkeypatch.setattr(section_router, "chat", lambda p, k, **kw: split_json)

    # 1. split 异步全链路
    r = client.post(f"/api/section/split?taskId={tid}", headers={"X-API-Key": "sk-t"}).json()
    assert r["code"] == 200 and r["data"]["jobStep"] == "split"
    snap = wait_job("split", tid)
    assert snap["state"] == "success" and "3 个章节" in snap["result"]

    orders = [s["sectionOrder"] for s in client.get(f"/api/section/by-task-id?taskId={tid}").json()["data"]]
    assert orders == [1, 2, 3]

    # 2. slides 生成：第 2 张模拟失败
    calls = {"n": 0}

    def fake_slide_chat(p, k, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("sim fail")
        return "<p>ok</p>"

    monkeypatch.setattr(slide_router, "chat", fake_slide_chat)
    r = client.post(f"/api/slide/generate-all?taskId={tid}", headers={"X-API-Key": "sk-t"}).json()
    assert r["data"]["jobStep"] == "slides"
    snap = wait_job("slides", tid)
    assert snap["state"] == "success" and "失败序号 [2]" in snap["result"]
    statuses = {s["slideOrder"]: s["status"] for s in client.get(f"/api/slide/by-task-id?taskId={tid}").json()["data"]}
    assert statuses == {1: "ok", 2: "failed", 3: "ok"}

    # 3. 章节移动 → 下游幻灯片被清空
    assert client.post(f"/api/section/move?taskId={tid}&sectionOrder=1&direction=down").json()["code"] == 200
    secs = client.get(f"/api/section/by-task-id?taskId={tid}").json()["data"]
    assert [s["title"] for s in secs] == ["c2", "c1", "c3"]
    assert client.get(f"/api/slide/by-task-id?taskId={tid}").json()["data"] == []

    # 边界：第一章不能再上移
    assert "已是第一章" in client.post(f"/api/section/move?taskId={tid}&sectionOrder=1&direction=up").json()["message"]

    # 4. 删除中间章 → 序号前移保持连续
    r = client.delete(f"/api/section/delete?taskId={tid}&sectionOrder=2").json()
    assert r["code"] == 200
    secs = client.get(f"/api/section/by-task-id?taskId={tid}").json()["data"]
    assert [(s["sectionOrder"], s["title"]) for s in secs] == [(1, "c2"), (2, "c3")]

    # 5. 仅剩两章再删一章后，最后一章不可删
    assert client.delete(f"/api/section/delete?taskId={tid}&sectionOrder=1").json()["code"] == 200
    last = client.delete("/api/section/delete", params={"taskId": tid, "sectionOrder": 1})
    assert "至少保留一个章节" in last.json()["message"]

    # 非法 direction
    assert client.post(f"/api/section/move?taskId={tid}&sectionOrder=1&direction=left").json()["code"] != 200


def test_split_requires_existing_task(client):
    r = client.post("/api/section/split?taskId=no-such").json()
    assert r["code"] != 200 and "任务" in r["message"]
