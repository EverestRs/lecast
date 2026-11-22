# -*- coding: utf-8 -*-
"""讲解稿 + TTS 链路（mock chat / synthesize）：生成 / 编辑 / 重生成 / 双密钥回退 / 懒迁移"""
import json
from datetime import datetime
from types import SimpleNamespace

import app.routers.section as section_router
import app.routers.script as script_router
import app.routers.tts as tts_router
from app.models import Tts
from app.services import video as video_svc


def _split_three(client, make_task, wait_job, monkeypatch, name):
    tid = make_task(name)
    split_json = json.dumps({"sections": [{"title": f"c{i}", "content": f"x{i}"} for i in range(1, 4)]})
    monkeypatch.setattr(section_router, "chat", lambda p, k, **kw: split_json)
    client.post(f"/api/section/split?taskId={tid}", headers={"X-API-Key": "sk-t"})
    assert wait_job("split", tid)["state"] == "success"
    return tid


def test_generate_scripts_requires_sections(client, make_task):
    tid = make_task("P6TEST-NOSC")
    r = client.post(f"/api/script/generate-all?taskId={tid}").json()
    assert r["code"] != 200 and "先" in r["message"]


def _gen_scripts(client, tid, monkeypatch):
    """mock chat 生成 3 篇讲解稿并断言全链路结果，返回捕获的 key 列表"""
    seen_keys, counter = [], {"n": 0}

    def fake_chat(p, k, **kw):
        seen_keys.append(k)
        counter["n"] += 1
        return f"讲稿{counter['n']}"

    monkeypatch.setattr(script_router, "chat", fake_chat)

    r = client.post(f"/api/script/generate-all?taskId={tid}", headers={"X-API-Key": "sk-t"}).json()
    assert r["code"] == 200 and r["data"]["jobStep"] == "scripts"
    # wait_job 在调用方注入，这里通过 client 直接轮询
    import time
    deadline = time.time() + 15
    while True:
        snap = client.get(f"/api/task/job/scripts/{tid}").json()["data"]
        if snap.get("state") in ("success", "failed"):
            break
        assert time.time() < deadline
        time.sleep(0.1)
    assert snap["state"] == "success" and "3/3" in snap["result"]

    # key 透传：每个请求携带的 X-API-Key 原样传给 chat
    assert seen_keys and all(k == "sk-t" for k in seen_keys)

    rows = client.get(f"/api/script/by-task-id?taskId={tid}").json()["data"]
    assert [(x["scriptOrder"], x["status"]) for x in rows] == [(1, "ok"), (2, "ok"), (3, "ok")]
    assert [x["title"] for x in rows] == ["c1", "c2", "c3"]
    return tid


def test_scripts_full_flow(client, make_task, wait_job, monkeypatch):
    tid = _split_three(client, make_task, wait_job, monkeypatch, "P6TEST-SCR")
    _gen_scripts(client, tid, monkeypatch)


def test_script_update_and_regenerate(client, make_task, wait_job, monkeypatch):
    tid = _split_three(client, make_task, wait_job, monkeypatch, "P6TEST-SCR2")
    _gen_scripts(client, tid, monkeypatch)

    # 编辑
    r = client.put("/api/script/update", json={"task_id": tid, "script_order": 1, "content": "手动改写"})
    assert r.json()["code"] == 200
    rows = client.get(f"/api/script/by-task-id?taskId={tid}").json()["data"]
    assert rows[0]["content"] == "手动改写"
    bad = client.put("/api/script/update", json={"task_id": tid, "script_order": 9, "content": "x"}).json()
    assert bad["code"] != 200 and "未找到" in bad["message"]

    # 重生成失败：原内容不被破坏
    def boom(p, k, **kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(script_router, "chat", boom)
    fail = client.post(f"/api/script/regenerate?taskId={tid}&scriptOrder=1").json()
    assert fail["code"] != 200 and "重生成失败" in fail["message"]
    rows = client.get(f"/api/script/by-task-id?taskId={tid}").json()["data"]
    assert rows[0]["content"] == "手动改写"

    # 重生成成功 + 序号越界
    monkeypatch.setattr(script_router, "chat", lambda p, k, **kw: "重生成稿")
    ok = client.post(f"/api/script/regenerate?taskId={tid}&scriptOrder=1").json()
    assert ok["code"] == 200
    rows = client.get(f"/api/script/by-task-id?taskId={tid}").json()["data"]
    assert rows[0]["content"] == "重生成稿"

    over = client.post(f"/api/script/regenerate?taskId={tid}&scriptOrder=9").json()
    assert over["code"] != 200


def _mock_synthesize(monkeypatch, calls):
    def fake(content, key):
        calls.append((content, key))
        return SimpleNamespace(bytes=f"wav-{len(calls)}".encode(), audio_url="/fake")

    monkeypatch.setattr(tts_router.tts_api, "synthesize", fake)


def test_tts_success_and_key_priority(client, make_task, wait_job, monkeypatch):
    tid = _split_three(client, make_task, wait_job, monkeypatch, "P6TEST-TTS")
    _gen_scripts(client, tid, monkeypatch)
    calls = []
    _mock_synthesize(monkeypatch, calls)

    # 同时带两个头 → TTS Key 优先
    r = client.post(
        f"/api/tts/generate-all?taskId={tid}",
        headers={"X-API-Key": "chat-k", "X-TTS-Key": "mimo-k"},
    ).json()
    assert r["code"] == 200 and r["data"]["jobStep"] == "tts"
    snap = wait_job("tts", tid)
    assert snap["state"] == "success" and "3/3" in snap["result"]
    assert [k for _, k in calls] == ["mimo-k"] * 3

    rows = client.get(f"/api/tts/by-task-id?taskId={tid}").json()["data"]
    assert [x["ttsOrder"] for x in rows] == [1, 2, 3]
    assert all(x["status"] == "ok" for x in rows)

    # 音频端点返回落盘字节 + inline
    audio = client.get(f"/api/tts/audio?taskId={tid}&ttsOrder=1")
    assert audio.status_code == 200 and audio.content == b"wav-1"
    assert "inline" in audio.headers["content-disposition"]

    # 仅 X-API-Key → 回退使用
    calls.clear()
    r2 = client.post(f"/api/tts/regenerate?taskId={tid}&ttsOrder=1", headers={"X-API-Key": "fallback-k"})
    assert r2.json()["code"] == 200
    assert calls and calls[0][1] == "fallback-k"

    # 都不带 → None（由服务端默认密钥兜底）
    calls.clear()
    r3 = client.post(f"/api/tts/regenerate?taskId={tid}&ttsOrder=1")
    assert r3.json()["code"] == 200
    assert calls[0][1] is None

    assert client.get(f"/api/tts/audio?taskId={tid}&ttsOrder=99").status_code == 404


def test_tts_empty_script_fails_with_placeholder(client, make_task, wait_job, monkeypatch):
    tid = _split_three(client, make_task, wait_job, monkeypatch, "P6TEST-TTSEMPTY")

    # 第 2 篇讲解稿生成结果为空串
    state = {"n": 0}

    def fake_chat(p, k, **kw):
        state["n"] += 1
        return "" if state["n"] == 2 else f"讲稿{state['n']}"

    monkeypatch.setattr(script_router, "chat", fake_chat)
    client.post(f"/api/script/generate-all?taskId={tid}", headers={"X-API-Key": "sk-t"})
    wait_job("scripts", tid)

    calls = []
    _mock_synthesize(monkeypatch, calls)
    client.post(f"/api/tts/generate-all?taskId={tid}", headers={"X-TTS-Key": "mimo-k"})
    snap = wait_job("tts", tid)
    assert snap["state"] == "success" and "[2]" in snap["result"]

    statuses = {x["ttsOrder"]: x["status"] for x in client.get(f"/api/tts/by-task-id?taskId={tid}").json()["data"]}
    assert statuses == {1: "ok", 2: "failed", 3: "ok"}
    # 空讲解稿不调用 synthesize，序号仍连续
    assert len(calls) == 2
    missing = client.get(f"/api/tts/audio?taskId={tid}&ttsOrder=2")
    assert missing.status_code == 404


def test_audio_lazy_migration_for_legacy_blob(client, make_task, db):
    tid = make_task("P6TEST-LAZY")
    db.add(Tts(task_id=tid, tts_order=1, content=b"legacy-blob", status="ok", create_time=datetime.now()))
    db.commit()

    r = client.get(f"/api/tts/audio?taskId={tid}&ttsOrder=1")
    assert r.status_code == 200 and r.content == b"legacy-blob"

    row = db.query(Tts).filter(Tts.task_id == tid, Tts.tts_order == 1).first()
    db.refresh(row)
    assert row.file_path
    assert video_svc.tts_abs_path(row.file_path).is_file()
