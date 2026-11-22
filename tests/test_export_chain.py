# -*- coding: utf-8 -*-
"""导出链路与任务管理：上传限额 / 分页 / 删任务清盘 / dump 校验矩阵 / 产物新鲜度 / 幻灯片 CSP"""
import time
from datetime import datetime, timedelta

import app.routers.task as task_router
from app.config import DUMP_ROOT, PAGE_SIZE
from app.models import Section, Slide, Tts
from app.services import video as video_svc


def _add_slide(db, tid, order=1, content="<html>ok</html>", status="ok"):
    db.add(Slide(task_id=tid, slide_order=order, content=content, status=status, create_time=datetime.now()))


def _add_tts(db, tid, order=1):
    rel = video_svc.save_tts_audio(tid, order, f"wav-{order}".encode())
    db.add(Tts(task_id=tid, tts_order=order, file_path=rel, status="ok", create_time=datetime.now()))


def test_upload_oversize_rejected(client, make_task, monkeypatch):
    monkeypatch.setattr(task_router, "MAX_UPLOAD_BYTES", 16)
    r = client.post(
        "/api/task/upload",
        files={"file": ("big.md", b"x" * 64)},
        data={"taskName": "P6TEST-BIG"},
    ).json()
    assert r["code"] != 200 and "不能超过" in r["message"]


def test_task_list_pagination_and_order(client, make_task):
    names = [f"P6TEST-PAGE-{i}" for i in range(1, 13)]
    for n in names:
        make_task(n)
        time.sleep(0.03)  # 让 create_time 可区分，验证降序

    p1 = client.get("/api/task/list?current=1&task_name=P6TEST-PAGE").json()["data"]
    assert p1["total"] == 12 and len(p1["records"]) == PAGE_SIZE
    assert [x["taskName"] for x in p1["records"]][0] == "P6TEST-PAGE-12"

    p2 = client.get("/api/task/list?current=2&task_name=P6TEST-PAGE").json()["data"]
    assert len(p2["records"]) == 12 - PAGE_SIZE
    assert {x["taskName"] for x in p1["records"] + p2["records"]} == set(names)


def test_delete_task_removes_disk_dir(client, make_task):
    tid = make_task("P6TEST-RMDIR")
    task_dir = video_svc._task_dir(tid)
    (task_dir / "audios").mkdir(parents=True, exist_ok=True)
    (task_dir / "audios" / "tts_1.wav").write_bytes(b"x")
    assert task_dir.exists()

    assert client.delete(f"/api/task/{tid}").json()["code"] == 200
    assert not task_dir.exists()


def test_dump_validations(client, make_task, db):
    # ① 无幻灯片
    tid = make_task("P6TEST-D1")
    msg = client.post(f"/api/task/dump/{tid}").json()
    assert msg["code"] != 200 and "无幻灯片数据" in msg["message"]

    # ② 有幻灯片无音频
    _add_slide(db, tid)
    db.commit()
    msg = client.post(f"/api/task/dump/{tid}").json()
    assert msg["code"] != 200 and "无音频数据" in msg["message"]

    # ③ 失败幻灯片被点名（dump 先查音频存在，需配一条合法音频）
    tid = make_task("P6TEST-D2")
    _add_slide(db, tid, order=1, status="failed", content="")
    _add_tts(db, tid, order=1)
    db.commit()
    msg = client.post(f"/api/task/dump/{tid}").json()
    assert msg["code"] != 200 and "生成失败的幻灯片序号 [1]" in msg["message"]

    # ④ 失败音频被点名
    tid = make_task("P6TEST-D3")
    _add_slide(db, tid)
    db.add(Tts(task_id=tid, tts_order=1, status="failed", content=None, file_path=None, create_time=datetime.now()))
    db.commit()
    msg = client.post(f"/api/task/dump/{tid}").json()
    assert msg["code"] != 200 and "生成失败或缺失的音频序号 [1]" in msg["message"]

    # ⑤ 数量不配对
    tid = make_task("P6TEST-D4")
    _add_slide(db, tid, order=1)
    _add_slide(db, tid, order=2)
    _add_tts(db, tid, order=1)
    db.commit()
    msg = client.post(f"/api/task/dump/{tid}").json()
    assert msg["code"] != 200 and "数量不一致" in msg["message"]


def test_dump_success_writes_files(client, make_task, db):
    tid = make_task("P6TEST-DUMPOK")
    _add_slide(db, tid, order=1, content="<html>dump-ok</html>")
    _add_tts(db, tid, order=1)
    db.commit()

    r = client.post(f"/api/task/dump/{tid}").json()
    assert r["code"] == 200 and "转储成功" in r["data"]

    task_dir = video_svc._task_dir(tid)
    assert (task_dir / "slides" / "slide_1.html").read_text(encoding="utf-8") == "<html>dump-ok</html>"
    assert (task_dir / "audios" / "speech_1.wav").read_bytes() == b"wav-1"


def test_artifact_freshness_and_downloads(client, make_task, db):
    tid = make_task("P6TEST-STALE")

    info = client.get(f"/api/task/has-final/{tid}").json()["data"]
    assert info == {"exists": False, "stale": False}
    assert client.get("/api/task/has-pptx/" + tid).json()["data"]["exists"] is False
    assert client.get(f"/api/task/download-final/{tid}").status_code == 404
    assert client.get(f"/api/task/download-pptx/{tid}").status_code == 404

    final_fp = video_svc._task_dir(tid) / "final.mp4"
    final_fp.parent.mkdir(parents=True, exist_ok=True)
    final_fp.write_bytes(b"\x00\x00\x00ftypisom")

    info = client.get(f"/api/task/has-final/{tid}").json()["data"]
    assert info == {"exists": True, "stale": False}

    # 内容更新时间晚于产物 mtime → 过期
    future = datetime.now() + timedelta(minutes=5)
    db.add(Section(task_id=tid, section_order=1, title="t", update_time=future))
    db.commit()
    info = client.get(f"/api/task/has-final/{tid}").json()["data"]
    assert info["exists"] is True and info["stale"] is True

    dl = client.get(f"/api/task/download-final/{tid}")
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("video/mp4")


def test_slide_html_csp_sandbox(client, make_task, db):
    tid = make_task("P6TEST-CSP")
    _add_slide(db, tid, order=1)
    db.commit()

    r = client.get(f"/api/slide/html?taskId={tid}&slideOrder=1")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert csp == "sandbox allow-scripts"
    assert "allow-popups" not in csp and "allow-same-origin" not in csp

    assert client.get(f"/api/slide/html?taskId={tid}&slideOrder=9").status_code == 404


def test_dump_root_exists():
    assert DUMP_ROOT.is_dir()
