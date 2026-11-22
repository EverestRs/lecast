"""Pydantic 请求/响应模型"""

from pydantic import BaseModel


# ── 通用响应 ──

class Result(BaseModel):
    """统一 API 响应体"""
    code: int = 200
    message: str = "success"
    data: object = None

    @staticmethod
    def success(data: object = None, message: str = "success") -> "Result":
        return Result(code=200, message=message, data=data)

    @staticmethod
    def fail(message: str, code: int = 400) -> "Result":
        return Result(code=code, message=message, data=None)


# ── 任务 ──

class TaskRenameReq(BaseModel):
    task_id: str
    task_name: str


class TaskVoiceReq(BaseModel):
    task_id: str
    voice: str


# ── 内容更新 ──

class SectionUpdateReq(BaseModel):
    task_id: str
    section_order: int
    title: str
    content: str


class SlideUpdateReq(BaseModel):
    task_id: str
    slide_order: int
    content: str


class ScriptUpdateReq(BaseModel):
    task_id: str
    script_order: int
    content: str