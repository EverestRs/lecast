"""讲解稿 API — 对应原 v1 ScriptController"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Body, Header
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.jobs import Job, runner as jobs_runner
from app.routers.task import sync_task_status
from app.models import Section, Script
from app.schemas import Result, ScriptUpdateReq
from app.services.llm import chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/script", tags=["讲解稿"])

SCRIPT_PROMPT_TMPL = """你是一个专业的教学视频讲解稿撰写专家。请根据以下章节内容，生成一篇口语化、自然流畅的讲解稿。

要求：
1. 语言口语化，像老师在课堂上自然讲解
2. 篇幅适中，每分钟约 200-250 字
3. 逻辑清晰，有自然的过渡和衔接
4. 适当使用提问、强调等教学技巧
5. 直接输出讲解稿文本，不要任何额外说明

章节标题：{sec_title}
章节内容：
{sec_content}"""


@router.post("/generate-all", response_model=Result)
def generate_all_scripts(
    task_id: str = Query(..., alias="taskId"),
    api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    if not task_id:
        return Result.fail("taskId 不能为空")

    sections_count = db.query(Section).filter(Section.task_id == task_id).count()
    if not sections_count:
        return Result.fail(f"taskId={task_id} 下无章节，请先调用 /api/section/split")

    def work(job: Job):
        session = SessionLocal()
        try:
            sections = session.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
            if not sections:
                raise RuntimeError("章节数据不存在，请先划分章节")

            session.query(Script).filter(Script.task_id == task_id).delete()

            job.total = len(sections)
            success_count = 0
            failed_orders = []
            for i, sec in enumerate(sections):
                script_order = i + 1
                job.current = i
                job.stage = f"正在生成第 {script_order}/{len(sections)} 篇讲解稿（{sec.title}）"
                logger.info("正在为 taskId=%s 生成第 %d 篇讲解稿（%s）...", task_id, script_order, sec.title)

                prompt = SCRIPT_PROMPT_TMPL.format(sec_title=sec.title, sec_content=sec.content)
                try:
                    script_content = chat(prompt, api_key, max_tokens=4096)
                    session.add(Script(
                        task_id=task_id,
                        script_order=script_order,
                        content=script_content,
                        status="ok",
                        create_time=datetime.now(),
                    ))
                    success_count += 1
                except Exception as e:
                    logger.error("生成第 %d 篇讲解稿失败：%s", script_order, e)
                    failed_orders.append(script_order)
                    # 失败也落占位记录，保住序号连续
                    session.add(Script(
                        task_id=task_id,
                        script_order=script_order,
                        content="",
                        status="failed",
                        create_time=datetime.now(),
                    ))
                session.commit()
                job.current = i + 1

            sync_task_status(task_id, session)
            job.stage = "完成"
            if failed_orders:
                job.result = f"⚠️ 成功 {success_count}/{len(sections)} 篇，失败序号 {failed_orders}，可在列表中逐条重试"
            else:
                job.result = f"✅ 成功生成 {success_count}/{len(sections)} 篇讲解稿"
        finally:
            session.close()

    accepted, reject_msg = jobs_runner.submit("scripts", task_id, work)
    if not accepted:
        return Result.fail(reject_msg)
    return Result.success({"jobStep": "scripts", "taskId": task_id})


@router.get("/by-task-id", response_model=Result)
def list_scripts(task_id: str = Query(..., alias="taskId"), db: Session = Depends(get_db)):
    if not task_id:
        return Result.fail("taskId 不能为空")

    scripts = db.query(Script).filter(Script.task_id == task_id).order_by(Script.script_order).all()
    sections = db.query(Section).filter(Section.task_id == task_id).all()
    section_map = {s.section_order: s.title for s in sections}

    result = []
    for s in scripts:
        result.append({
            "id": s.id,
            "taskId": s.task_id,
            "scriptOrder": s.script_order,
            "content": s.content,
            "status": s.status,
            "title": section_map.get(s.script_order),
            "createTime": s.create_time.isoformat(),
            "updateTime": (s.update_time or s.create_time).isoformat(),
        })
    return Result.success(result)


@router.put("/update", response_model=Result)
def update_script(req: ScriptUpdateReq, db: Session = Depends(get_db)):
    script = db.query(Script).filter(
        Script.task_id == req.task_id,
        Script.script_order == req.script_order,
    ).first()
    if not script:
        return Result.fail("未找到对应讲解稿")
    script.content = req.content.strip()
    script.status = "ok"
    script.update_time = datetime.now()
    db.commit()
    return Result.success("讲解稿更新成功")


@router.post("/regenerate", response_model=Result)
def regenerate_script(
    task_id: str = Query(..., alias="taskId"),
    script_order: int = Query(..., alias="scriptOrder"),
    api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    sections = db.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
    if not sections or script_order > len(sections):
        return Result.fail("章节数据不存在或序号超出范围")

    sec = sections[script_order - 1]
    prompt = f"""你是一个专业的教学视频讲解稿撰写专家。请根据以下章节内容，重新生成一篇口语化、自然流畅的讲解稿。

要求：
1. 语言口语化，像老师在课堂上自然讲解
2. 篇幅适中，每分钟约 200-250 字
3. 逻辑清晰，有自然的过渡和衔接
4. 适当使用提问、强调等教学技巧

章节标题：{sec.title}
章节内容：
{sec.content}"""

    try:
        content = chat(prompt, api_key, max_tokens=4096)
        script = db.query(Script).filter(
            Script.task_id == task_id,
            Script.script_order == script_order,
        ).first()
        if script:
            script.content = content
            script.status = "ok"
            script.update_time = datetime.now()
            db.commit()
        return Result.success("✅ 重生成成功")
    except Exception as e:
        return Result.fail(f"重生成失败：{e}")