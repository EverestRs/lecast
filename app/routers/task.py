"""任务 API — 对应原 v1 TaskController"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import PAGE_SIZE, TTS_VOICE_CHOICES, UPLOAD_MAX_MB
from app.database import get_db, SessionLocal
from app.jobs import JOB_STEPS, Job, runner as jobs_runner
from app.models import Task, Section, Slide, Script, Tts
from app.schemas import Result, TaskRenameReq, TaskVoiceReq
from app.services import video as video_svc

# ── 状态标签（中文）──
STATUS_LABELS = {
    "uploaded": "已上传",
    "sections_done": "已分章",
    "slides_done": "已生成幻灯片",
    "scripts_done": "已生成讲解稿",
    "tts_done": "已合成音频",
    "video_done": "已完成",
}
STATUS_STEPS = ["uploaded", "sections_done", "slides_done", "scripts_done", "tts_done", "video_done"]

MAX_UPLOAD_BYTES = UPLOAD_MAX_MB * 1024 * 1024


def sync_task_status(task_id: str, db: Session) -> str:
    """根据各子表数据量计算任务进度，并持久化到 task.status 字段。

    供各生成步骤（section/slide/script/tts/export）完成后调用。
    """
    # 按优先顺序计算当前最高状态
    if video_svc.has_final_video(task_id):
        status = "video_done"
    elif db.query(Tts).filter(Tts.task_id == task_id).count() > 0:
        status = "tts_done"
    elif db.query(Script).filter(Script.task_id == task_id).count() > 0:
        status = "scripts_done"
    elif db.query(Slide).filter(Slide.task_id == task_id).count() > 0:
        status = "slides_done"
    elif db.query(Section).filter(Section.task_id == task_id).count() > 0:
        status = "sections_done"
    else:
        status = "uploaded"

    task = db.query(Task).filter(Task.task_id == task_id).first()
    if task and task.status != status:
        task.status = status
        task.update_time = datetime.now()
        db.commit()
    return status


def get_task_status(task_id: str, db: Session) -> str:
    """读取任务当前状态（优先用持久化字段，兼容旧数据回退计算）"""
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if task and task.status:
        return task.status
    # 旧数据无 status 时回退计算
    return sync_task_status(task_id, db)

def _escape_like(keyword: str) -> str:
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _latest_content_time(task_id: str, db: Session) -> Optional[datetime]:
    """该任务全部生成内容的最后更新时间（用于产物新鲜度判断）"""
    latest = None
    for model in (Section, Slide, Script, Tts):
        val = db.query(func.max(func.coalesce(model.update_time, model.create_time))).filter(
            model.task_id == task_id
        ).scalar()
        if val and (latest is None or val > latest):
            latest = val
    return latest


def _artifact_info(path: Optional[Path], task_id: str, db: Session) -> dict:
    """产物存在性与新鲜度：内容更新晚于产物 mtime 则视为过期"""
    if not path:
        return {"exists": False, "stale": False}
    latest = _latest_content_time(task_id, db)
    stale = bool(latest) and latest.timestamp() > path.stat().st_mtime
    return {"exists": True, "stale": stale}


router = APIRouter(prefix="/api/task", tags=["任务"])


@router.post("/upload", response_model=Result)
async def upload_markdown(
    file: UploadFile = File(...),
    # 前端 FormData 字段名为 taskName，需显式 alias 匹配
    task_name: str = Form(..., alias="taskName"),
    db: Session = Depends(get_db),
):
    if not file or not file.filename:
        return Result.fail("文件不能为空")
    if not file.filename.lower().endswith(".md"):
        return Result.fail("仅支持 .md 文件上传")
    if not task_name or not task_name.strip():
        return Result.fail("任务名称不能为空")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return Result.fail(f"文件大小不能超过 {UPLOAD_MAX_MB}MB")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return Result.fail("文件必须是 UTF-8 编码，请转换编码后重新上传")
    if not content.strip():
        return Result.fail("文件内容为空")

    now = datetime.now()
    task_id = str(uuid.uuid4())

    task = Task(
        task_id=task_id,
        task_name=task_name.strip(),
        content=content,
        status="uploaded",
        create_time=now,
        update_time=now,
    )
    db.add(task)
    db.commit()
    return Result.success(task_id)


@router.get("/list", response_model=Result)
def list_tasks(
    current: int = Query(1, ge=1),
    task_name: str = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Task)
    if task_name:
        keyword = task_name.strip()
        if keyword:
            query = query.filter(Task.task_name.like(f"%{_escape_like(keyword)}%", escape="\\"))
    total = query.count()
    tasks = (
        query.order_by(Task.create_time.desc())
        .offset((current - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    # 批量聚合各子表计数，替代逐行 get_task_status 的 N+1 查询
    page_ids = [t.task_id for t in tasks]

    def _count_map(model):
        if not page_ids:
            return {}
        rows = (
            db.query(model.task_id, func.count())
            .filter(model.task_id.in_(page_ids))
            .group_by(model.task_id)
            .all()
        )
        return {r[0]: r[1] for r in rows}

    sec_n, sld_n, scr_n, tts_n = map(_count_map, (Section, Slide, Script, Tts))

    def _status_of(task_id: str) -> str:
        if video_svc.has_final_video(task_id):
            return "video_done"
        if tts_n.get(task_id):
            return "tts_done"
        if scr_n.get(task_id):
            return "scripts_done"
        if sld_n.get(task_id):
            return "slides_done"
        if sec_n.get(task_id):
            return "sections_done"
        return "uploaded"

    records = []
    for t in tasks:
        status = _status_of(t.task_id)
        records.append({
            "id": t.id,
            "taskId": t.task_id,
            "taskName": t.task_name,
            "createTime": t.create_time.isoformat(),
            "updateTime": (t.update_time or t.create_time).isoformat(),
            "status": status,
            "statusLabel": STATUS_LABELS[status],
        })

    data = {
        "records": records,
        "total": total,
        "current": current,
        "size": PAGE_SIZE,
    }
    return Result.success(data)


@router.get("/status/{task_id}", response_model=Result)
def query_task_status(task_id: str, db: Session = Depends(get_db)):
    """查询任务当前进度状态"""
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        return Result.fail("任务不存在")
    status = get_task_status(task_id, db)
    return Result.success({
        "taskId": task_id,
        "status": status,
        "statusLabel": STATUS_LABELS[status],
        "stepIndex": STATUS_STEPS.index(status),
    })


@router.get("/detail/{task_id}", response_model=Result)
def get_task_detail(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        return Result.fail(f"未找到 taskId={task_id} 对应的任务")
    return Result.success({
        "taskName": task.task_name,
        "content": task.content or "",
        "ttsVoice": task.tts_voice,
    })


@router.put("/rename", response_model=Result)
def rename_task(req: TaskRenameReq, db: Session = Depends(get_db)):
    name = req.task_name.strip()
    if not name:
        return Result.fail("任务名称不能为空")
    if len(name) > 50:
        return Result.fail("任务名称不能超过 50 字")
    task = db.query(Task).filter(Task.task_id == req.task_id).first()
    if not task:
        return Result.fail("未找到对应任务")
    task.task_name = name
    task.update_time = datetime.now()
    db.commit()
    return Result.success("任务已重命名")


@router.put("/voice", response_model=Result)
def set_task_voice(req: TaskVoiceReq, db: Session = Depends(get_db)):
    if req.voice not in TTS_VOICE_CHOICES:
        return Result.fail(f"不支持的音色，可选：{TTS_VOICE_CHOICES}")
    task = db.query(Task).filter(Task.task_id == req.task_id).first()
    if not task:
        return Result.fail("未找到对应任务")
    task.tts_voice = req.voice
    task.update_time = datetime.now()
    db.commit()
    return Result.success(f"音色已保存为 {req.voice}，重新生成音频时生效")


@router.post("/dump/{task_id}", response_model=Result)
def dump_task(task_id: str, db: Session = Depends(get_db)):
    try:
        msg = video_svc.dump_slides_and_audio(task_id, db)
        return Result.success(msg)
    except ValueError as e:
        return Result.fail(str(e))


@router.post("/export-final/{task_id}", response_model=Result)
def export_final_video(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        return Result.fail("任务不存在")

    def work(job: Job):
        result = video_svc.export_video(task_id, progress=job)
        if not result["success"]:
            raise RuntimeError(result["message"])
        session = SessionLocal()
        try:
            sync_task_status(task_id, session)
        finally:
            session.close()
        job.stage = "完成"
        job.result = "🎉 视频导出完成"

    accepted, reject_msg = jobs_runner.submit("video", task_id, work)
    if not accepted:
        return Result.fail(reject_msg)
    return Result.success({"jobStep": "video", "taskId": task_id})


@router.get("/download-final/{task_id}")
def download_final_video(task_id: str):
    path = video_svc.get_final_video_path(task_id)
    if not path:
        return Response(status_code=404, content="final.mp4 不存在")
    return FileResponse(
        path=path,
        media_type="video/mp4",
        filename=f"{task_id}_final.mp4",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/has-final/{task_id}", response_model=Result)
def has_final_video(task_id: str, db: Session = Depends(get_db)):
    return Result.success(_artifact_info(video_svc.get_final_video_path(task_id), task_id, db))


@router.post("/export-pptx/{task_id}", response_model=Result)
def export_pptx(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        return Result.fail("任务不存在")

    def work(job: Job):
        result = video_svc.export_pptx(task_id, progress=job)
        if not result["success"]:
            raise RuntimeError(result["message"])
        job.stage = "完成"
        job.result = "PPTX 导出完成"

    accepted, reject_msg = jobs_runner.submit("pptx", task_id, work)
    if not accepted:
        return Result.fail(reject_msg)
    return Result.success({"jobStep": "pptx", "taskId": task_id})


@router.get("/job/{step}/{task_id}", response_model=Result)
def get_job_status(step: str, task_id: str):
    """查询后台作业进度；无记录时返回 state=none"""
    if step not in JOB_STEPS:
        return Result.fail(f"未知的步骤类型：{step}")
    snap = jobs_runner.snapshot(step, task_id)
    return Result.success(snap or {"step": step, "taskId": task_id, "state": "none"})


@router.get("/download-pptx/{task_id}")
def download_pptx(task_id: str):
    path = video_svc.get_pptx_path(task_id)
    if not path:
        return Response(status_code=404, content="presentation.pptx 不存在")
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{task_id}_presentation.pptx",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/has-pptx/{task_id}", response_model=Result)
def has_pptx(task_id: str, db: Session = Depends(get_db)):
    return Result.success(_artifact_info(video_svc.get_pptx_path(task_id), task_id, db))


@router.delete("/{task_id}", response_model=Result)
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        return Result.success(None, "任务不存在，视为已删除")

    # 级联删除关联数据
    db.query(Section).filter(Section.task_id == task_id).delete()
    db.query(Slide).filter(Slide.task_id == task_id).delete()
    db.query(Script).filter(Script.task_id == task_id).delete()
    db.query(Tts).filter(Tts.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    # 同步清理磁盘转储目录（slides/audios/videos/screenshots/final.mp4/pptx）
    video_svc.delete_task_dir(task_id)
    return Result.success(None, "删除成功")