"""幻灯片 API — 对应原 v1 SlideController"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Body, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.jobs import Job, runner as jobs_runner
from app.routers.task import sync_task_status
from app.models import Section, Slide
from app.schemas import Result, SlideUpdateReq
from app.services.llm import chat, clean_html_output

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slide", tags=["幻灯片"])

SLIDE_PROMPT_TMPL = """你是一个专业的教学幻灯片制作专家。请根据以下章节内容，生成一张适配 1920×1080 大屏展示的 HTML 幻灯片。

要求：
1. 使用 HTML + CSS 生成，所有样式使用内联样式或 <style> 标签
2. 布局清晰美观，字体大小适合大屏阅读（标题 48px+，正文 28px+）
3. 内容精炼，突出核心知识点
4. 配色专业，背景简洁
5. 生成的 HTML 必须是完整、独立可运行的片段（不要 <html>/<body> 包裹）

当前章节内容：
{sec_content}

上下文（全部章节）：
{full_context}

请直接输出 HTML 代码，不要用 ```html 包裹。"""


def _build_slide_context(sections, slide_order: int) -> str:
    context_parts = []
    for j, s in enumerate(sections, 1):
        prefix = "【当前章节】" if j == slide_order else f"【第{j}章】"
        context_parts.append(f"{prefix} {s.title}\n{s.content}")
    return "\n\n".join(context_parts)


@router.post("/generate-all", response_model=Result)
def generate_all_slides(
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

            session.query(Slide).filter(Slide.task_id == task_id).delete()

            job.total = len(sections)
            success_count = 0
            failed_orders = []
            for i, sec in enumerate(sections):
                slide_order = i + 1
                job.current = i
                job.stage = f"正在生成第 {slide_order}/{len(sections)} 张幻灯片（{sec.title}）"
                logger.info("正在为 taskId=%s 生成第 %d 张幻灯片（%s）...", task_id, slide_order, sec.title)

                prompt = SLIDE_PROMPT_TMPL.format(
                    sec_content=sec.content,
                    full_context=_build_slide_context(sections, slide_order),
                )
                try:
                    html = clean_html_output(chat(prompt, api_key, max_tokens=8192))
                    session.add(Slide(
                        task_id=task_id,
                        slide_order=slide_order,
                        content=html,
                        status="ok",
                        create_time=datetime.now(),
                    ))
                    success_count += 1
                except Exception as e:
                    logger.error("生成第 %d 张幻灯片失败：%s", slide_order, e)
                    failed_orders.append(slide_order)
                    # 失败也落占位记录，保住序号连续
                    session.add(Slide(
                        task_id=task_id,
                        slide_order=slide_order,
                        content="",
                        status="failed",
                        create_time=datetime.now(),
                    ))
                session.commit()
                job.current = i + 1

            sync_task_status(task_id, session)
            job.stage = "完成"
            if failed_orders:
                job.result = f"⚠️ 成功 {success_count}/{len(sections)} 张，失败序号 {failed_orders}，可在列表中逐条重试"
            else:
                job.result = f"✅ 成功生成 {success_count}/{len(sections)} 张幻灯片"
        finally:
            session.close()

    accepted, reject_msg = jobs_runner.submit("slides", task_id, work)
    if not accepted:
        return Result.fail(reject_msg)
    return Result.success({"jobStep": "slides", "taskId": task_id})


@router.get("/by-task-id", response_model=Result)
def list_slides(task_id: str = Query(..., alias="taskId"), db: Session = Depends(get_db)):
    slides = db.query(Slide).filter(Slide.task_id == task_id).order_by(Slide.slide_order).all()
    return Result.success([{
        "id": s.id,
        "taskId": s.task_id,
        "slideOrder": s.slide_order,
        "content": s.content,
        "status": s.status,
        "createTime": s.create_time.isoformat(),
        "updateTime": (s.update_time or s.create_time).isoformat(),
    } for s in slides])


@router.get("/content", response_model=Result)
def get_slide_content(task_id: str = Query(..., alias="taskId"), slide_order: int = Query(..., alias="slideOrder"), db: Session = Depends(get_db)):
    slide = db.query(Slide).filter(
        Slide.task_id == task_id, Slide.slide_order == slide_order
    ).first()
    if not slide or not slide.content:
        return Result.fail("未查找到内容")
    return Result.success(slide.content)


@router.get("/html")
def get_slide_html(task_id: str = Query(..., alias="taskId"), slide_order: int = Query(..., alias="slideOrder"), db: Session = Depends(get_db)):
    slide = db.query(Slide).filter(
        Slide.task_id == task_id, Slide.slide_order == slide_order
    ).first()
    if not slide or not slide.content:
        return HTMLResponse(status_code=404)
    return HTMLResponse(
        content=slide.content,
        # sandbox 不给 allow-same-origin/allow-popups：隔离存储访问并禁止 AI 页弹窗
        headers={"Content-Security-Policy": "sandbox allow-scripts"},
    )


@router.put("/update", response_model=Result)
def update_slide(req: SlideUpdateReq, db: Session = Depends(get_db)):
    slide = db.query(Slide).filter(
        Slide.task_id == req.task_id, Slide.slide_order == req.slide_order
    ).first()
    if not slide:
        return Result.fail("未找到对应幻灯片")
    slide.content = req.content.strip()
    slide.status = "ok"
    slide.update_time = datetime.now()
    db.commit()
    return Result.success("幻灯片更新成功")


@router.post("/regenerate", response_model=Result)
def regenerate_slide(
    task_id: str = Query(..., alias="taskId"),
    slide_order: int = Query(..., alias="slideOrder"),
    api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    sections = db.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
    if not sections or slide_order > len(sections):
        return Result.fail("章节数据不存在或序号超出范围")

    sec = sections[slide_order - 1]
    full_context = _build_slide_context(sections, slide_order)

    prompt = f"""你是一个专业的教学幻灯片制作专家。请根据以下章节内容，重新生成一张适配 1920×1080 大屏展示的 HTML 幻灯片。

要求：
1. 使用 HTML + CSS 生成，所有样式使用内联样式或 <style> 标签
2. 布局清晰美观，字体大小适合大屏阅读（标题 48px+，正文 28px+）
3. 内容精炼，突出核心知识点
4. 配色专业，背景简洁

当前章节内容：
{sec.content}

上下文：
{full_context}

请直接输出 HTML 代码，不要用 ```html 包裹。"""

    try:
        html = chat(prompt, api_key, max_tokens=8192)
        html = clean_html_output(html)
        slide = db.query(Slide).filter(
            Slide.task_id == task_id, Slide.slide_order == slide_order
        ).first()
        if slide:
            slide.content = html
            slide.status = "ok"
            slide.update_time = datetime.now()
            db.commit()
        return Result.success("✅ 重生成成功")
    except Exception as e:
        return Result.fail(f"重生成失败：{e}")