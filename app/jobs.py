"""进程内长任务作业模型：提交 / 互斥 / 进度快照。

单 worker 进程假设；作业在 daemon 线程中执行，内部自建数据库会话，
禁止复用请求作用域的 session（请求返回后即关闭）。
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

JOB_STEPS = ("split", "slides", "scripts", "tts", "video", "pptx")

# 终态保留时长（秒），供前端刷新后查询最后一次执行结果
TERMINAL_TTL_SECONDS = 600


@dataclass
class Job:
    step: str
    task_id: str
    state: str = "running"          # running | success | failed
    stage: str = ""                 # 阶段描述，如「正在生成第 3/12 张幻灯片」
    current: int = 0
    total: int = 0
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    result: Optional[str] = None    # 成功时的提示文案（对应原同步接口的 data）


def _snapshot_of(job: Job) -> dict:
    return {
        "step": job.step,
        "taskId": job.task_id,
        "state": job.state,
        "stage": job.stage,
        "current": job.current,
        "total": job.total,
        "error": job.error,
        "elapsedMs": int(((job.finished_at or time.time()) - job.started_at) * 1000),
        "result": job.result,
    }


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(step: str, task_id: str) -> str:
        return f"{step}:{task_id}"

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [
            k for k, j in self._jobs.items()
            if j.state != "running" and j.finished_at and now - j.finished_at > TERMINAL_TTL_SECONDS
        ]
        for k in expired:
            self._jobs.pop(k, None)
            self._threads.pop(k, None)

    def submit(self, step: str, task_id: str, work: Callable[[Job], None]) -> tuple[bool, str]:
        """提交作业；同一 step+task 已在运行则拒绝。返回 (是否受理, 拒绝原因)。"""
        if step not in JOB_STEPS:
            return False, f"未知的作业类型：{step}"
        k = self.key(step, task_id)
        with self._lock:
            self._purge_expired_locked()
            existing = self._jobs.get(k)
            if existing and existing.state == "running":
                return False, "该步骤正在执行中，请勿重复提交"
            job = Job(step=step, task_id=task_id)
            self._jobs[k] = job
            t = threading.Thread(target=self._execute, args=(k, job, work), daemon=True)
            self._threads[k] = t
        t.start()
        logger.info("作业已提交：%s", k)
        return True, ""

    def _execute(self, key: str, job: Job, work: Callable[[Job], None]) -> None:
        try:
            work(job)
            if job.state == "running":
                job.state = "success"
        except Exception as e:  # noqa: BLE001 —— 统一落为 failed 态
            logger.exception("作业执行失败：%s", key)
            job.state = "failed"
            job.error = str(e) or e.__class__.__name__
        finally:
            job.finished_at = time.time()

    def snapshot(self, step: str, task_id: str) -> Optional[dict]:
        with self._lock:
            self._purge_expired_locked()
            job = self._jobs.get(self.key(step, task_id))
            return _snapshot_of(job) if job else None


runner = JobRunner()
