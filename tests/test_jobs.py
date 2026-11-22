# -*- coding: utf-8 -*-
"""JobRunner：互斥 / 终态 / 失败捕获 / 未知 step"""
import time

from app.jobs import JobRunner


def test_mutual_exclusion_and_rerun():
    runner = JobRunner()

    def slow(job):
        job.total = 1
        time.sleep(0.3)
        job.current = 1
        job.result = "done"

    ok1, _ = runner.submit("video", "jt1", slow)
    assert ok1

    ok2, msg = runner.submit("video", "jt1", slow)
    assert not ok2 and "正在执行" in msg

    snap = None
    for _ in range(100):
        snap = runner.snapshot("video", "jt1")
        if snap["state"] != "running":
            break
        time.sleep(0.05)
    assert snap["state"] == "success" and snap["result"] == "done"

    # 终态后允许再次提交
    ok3, _ = runner.submit("video", "jt1", slow)
    assert ok3


def test_unknown_step_rejected():
    runner = JobRunner()
    ok, msg = runner.submit("nope", "t1", lambda j: None)
    assert not ok


def test_failure_captured():
    runner = JobRunner()

    def boom(job):
        raise RuntimeError("boom-msg")

    runner.submit("split", "ft1", boom)
    snap = None
    for _ in range(100):
        snap = runner.snapshot("split", "ft1")
        if snap["state"] == "failed":
            break
        time.sleep(0.05)
    assert snap["state"] == "failed" and "boom-msg" in snap["error"]


def test_snapshot_none_for_unknown():
    runner = JobRunner()
    assert runner.snapshot("pptx", "never-submitted") is None
