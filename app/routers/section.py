"""章节 API — 对应原 v1 SectionController"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Body, Header
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.jobs import Job, runner as jobs_runner
from app.routers.task import sync_task_status
from app.models import Task, Section, Slide, Script, Tts
from app.schemas import Result, SectionUpdateReq
from app.services.llm import chat, clean_json_response, parse_json_str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/section", tags=["章节"])


def _build_split_prompt(content: str) -> str:
    return f"""请分析以下Markdown格式的课件内容，将其划分为合理的章节，并为每个章节生成一个标题。
要求如下：
1. 每个章节应逻辑清晰、内容连贯；
2. 后续将基于每章内容生成独立 HTML 页面（一页一章），需适配屏幕尺寸 1920×1080；
3. 单章内容不宜过多：文字密集、代码块、图表等建议单独成章，确保单页 HTML 可完整展示；
4. 若某节内容过长，请主动拆分为多个章节（宁细勿粗）；
5. 每个章节的 content 只保留要点摘要，最多 800 个汉字，不要复述整份课件；

待分析内容：
```markdown
{content}
```

请严格按以下 JSON 格式返回结果（仅输出 JSON，不要思考过程、代码解释、额外说明、注释或 Markdown 代码块包裹）：
{{"sections": [{{"title": "章节标题", "content": "章节内容"}}]}}"""


@router.post("/split", response_model=Result)
def split_sections(
    task_id: str = Query(..., alias="taskId"),
    # 密钥可选：未携带时由服务层回退 STEPFUN_API_KEY
    api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    if not task_id or not task_id.strip():
        return Result.fail("taskId 不能为空")

    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task or not task.content:
        return Result.fail("未找到对应 taskId 的有效任务或内容为空")

    def work(job: Job):
        job.stage = "正在调用 AI 划分章节"
        job.total = 1
        session = SessionLocal()
        try:
            # 后台线程自建会话，不复用请求作用域的 db
            task_row = session.query(Task).filter(Task.task_id == task_id).first()
            if not task_row or not task_row.content:
                raise RuntimeError("任务不存在或内容为空")

            json_str = chat(
                _build_split_prompt(task_row.content), api_key,
                max_tokens=8192,  # 推理模型需为思维链和最终 JSON 预留足够预算
                # json_mode 不显式传：跟随 LLM_JSON_MODE 配置（StepFun 支持实测后再开启）
            )
            cleaned = clean_json_response(json_str)
            root = parse_json_str(cleaned)

            sections_list = root.get("sections")
            if not isinstance(sections_list, list):
                raise RuntimeError("对话模型返回 JSON 缺少 'sections' 字段或类型错误")

            saved = []
            job.total = max(len(sections_list), 1)
            for i, item in enumerate(sections_list):
                if isinstance(item, dict):
                    title = (item.get("title") or "").strip()
                    content = (item.get("content") or "").strip()
                    if title and content:
                        saved.append(Section(
                            task_id=task_id,
                            section_order=len(saved) + 1,
                            title=title,
                            content=content,
                            create_time=datetime.now(),
                        ))
                job.current = i + 1
            if not saved:
                raise RuntimeError("对话模型未返回任何有效章节，请检查 prompt 或重试")

            job.stage = "正在保存章节并清除下游数据"
            removed_slides = session.query(Slide).filter(Slide.task_id == task_id).delete()
            removed_scripts = session.query(Script).filter(Script.task_id == task_id).delete()
            removed_tts = session.query(Tts).filter(Tts.task_id == task_id).delete()
            session.query(Section).filter(Section.task_id == task_id).delete()
            session.add_all(saved)
            session.commit()
            sync_task_status(task_id, session)

            suffix = "（已同步清除下游幻灯片/讲解稿/音频）" if (removed_slides or removed_scripts or removed_tts) else ""
            logger.info("成功为 taskId=%s 划分 %d 个章节", task_id, len(saved))
            job.stage = "完成"
            job.result = f"✅ 成功划分并保存 {len(saved)} 个章节{suffix}"
        finally:
            session.close()

    accepted, reject_msg = jobs_runner.submit("split", task_id, work)
    if not accepted:
        return Result.fail(reject_msg)
    return Result.success({"jobStep": "split", "taskId": task_id})


@router.get("/by-task-id", response_model=Result)
def list_sections(task_id: str = Query(..., alias="taskId"), db: Session = Depends(get_db)):
    if not task_id:
        return Result.fail("taskId 不能为空")
    sections = db.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
    return Result.success([{
        "id": s.id,
        "taskId": s.task_id,
        "sectionOrder": s.section_order,
        "title": s.title,
        "content": s.content,
        "createTime": s.create_time.isoformat(),
    } for s in sections])


def _clear_downstream(task_id: str, db: Session) -> int:
    """章节结构变化后级联清空下游幻灯片/讲解稿/音频，返回清除条数"""
    total = 0
    for model in (Slide, Script, Tts):
        total += db.query(model).filter(model.task_id == task_id).delete()
    return total


@router.post("/move", response_model=Result)
def move_section(
    task_id: str = Query(..., alias="taskId"),
    section_order: int = Query(..., alias="sectionOrder"),
    direction: str = Query(...),
    db: Session = Depends(get_db),
):
    if not task_id:
        return Result.fail("taskId 不能为空")
    if direction not in ("up", "down"):
        return Result.fail("direction 仅支持 up/down")

    sections = db.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
    idx = next((i for i, s in enumerate(sections) if s.section_order == section_order), None)
    if idx is None:
        return Result.fail("未找到对应章节")
    if direction == "up" and idx == 0:
        return Result.fail("已是第一章，不能再上移")
    if direction == "down" and idx == len(sections) - 1:
        return Result.fail("已是最后一章，不能再下移")

    # 相邻交换后按列表顺序重排序号，保证 1..N 连续
    swap = idx - 1 if direction == "up" else idx + 1
    sections[idx], sections[swap] = sections[swap], sections[idx]
    for i, s in enumerate(sections):
        s.section_order = i + 1
        s.update_time = datetime.now()

    cleared = _clear_downstream(task_id, db)
    db.commit()
    sync_task_status(task_id, db)
    suffix = f"，已同步清除下游幻灯片/讲解稿/音频 {cleared} 条" if cleared else ""
    return Result.success(f"章节移动成功{suffix}")


@router.delete("/delete", response_model=Result)
def delete_section(
    task_id: str = Query(..., alias="taskId"),
    section_order: int = Query(..., alias="sectionOrder"),
    db: Session = Depends(get_db),
):
    if not task_id:
        return Result.fail("taskId 不能为空")

    sections = db.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
    if len(sections) <= 1:
        return Result.fail("至少保留一个章节")
    target = next((s for s in sections if s.section_order == section_order), None)
    if not target:
        return Result.fail("未找到对应章节")

    db.delete(target)
    remaining = [s for s in sections if s.id != target.id]
    for i, s in enumerate(remaining):
        s.section_order = i + 1
        s.update_time = datetime.now()

    cleared = _clear_downstream(task_id, db)
    db.commit()
    sync_task_status(task_id, db)
    suffix = f"，已同步清除下游幻灯片/讲解稿/音频 {cleared} 条" if cleared else ""
    return Result.success(f"章节删除成功{suffix}")


@router.put("/update", response_model=Result)
def update_section(req: SectionUpdateReq, db: Session = Depends(get_db)):
    section = db.query(Section).filter(
        Section.task_id == req.task_id,
        Section.section_order == req.section_order,
    ).first()
    if not section:
        return Result.fail("未找到对应章节")
    section.title = req.title.strip()
    section.content = req.content.strip()
    section.update_time = datetime.now()
    db.commit()
    return Result.success("章节更新成功")


@router.post("/regenerate", response_model=Result)
def regenerate_section(
    task_id: str = Query(..., alias="taskId"),
    section_order: int = Query(..., alias="sectionOrder"),
    api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
):
    """基于原始课件全文 + 当前全部章节上下文，重新生成单章标题与内容"""
    if not task_id:
        return Result.fail("taskId 不能为空")
    if section_order <= 0:
        return Result.fail("sectionOrder 必须为正整数")

    target = db.query(Section).filter(
        Section.task_id == task_id, Section.section_order == section_order
    ).first()
    if not target:
        return Result.fail(f"未找到 taskId={task_id} 且 sectionOrder={section_order} 的章节")

    all_sections = db.query(Section).filter(Section.task_id == task_id).order_by(Section.section_order).all()
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task or not task.content:
        return Result.fail("未找到对应任务或原始内容为空")

    full_context = f"""【原始课件全文】（请以此为准还原/校准知识点）：
```markdown
{task.content}
```

【当前章节划分】（共 {len(all_sections)} 章，仅作参考，请勿照搬结构）：
""" + "\n---\n".join(
        f"第 {s.section_order} 章：\n标题：{s.title}\n内容：\n```\n{s.content}\n```"
        for s in all_sections
    )

    prompt = f"""你是一名专业的课程设计师，请基于以下两部分信息，重新优化第 {section_order} 章的标题与内容：
1. 【原始课件全文】——这是唯一权威的知识来源，请严格依据其内容还原、提炼本章知识点；
2. 【当前章节划分】——这是人工/模型初步划分的结果，仅用于参考风格、粒度与上下文衔接，不强制沿用。

优化要求：
• 标题需精准概括本章核心，简明有力，避免模糊泛化；
• 正文需逻辑清晰、重点突出、语言规范，适合 PPT 展示；
• 严格忠实于原始课件全文，不得新增/删减知识点，不得曲解技术细节；
• 单章内容需适配 HTML 页面（1920×1080），若过长请主动拆分（但本次只输出第 {section_order} 章）；
• 注意与前后章节自然衔接。

请严格按以下 JSON 格式返回结果（仅输出 JSON，不要任何额外说明、注释或 Markdown 代码块包裹）：
{{"sections": [{{"title": "章节标题", "content": "章节内容"}}]}}

输入数据如下：
```markdown
{full_context}
```"""

    try:
        json_str = chat(prompt, api_key, max_tokens=4096)
        cleaned = clean_json_response(json_str)
        root = parse_json_str(cleaned)
        sections_list = root.get("sections")
        if not isinstance(sections_list, list) or not sections_list:
            return Result.fail("对话模型返回格式不正确")
        item = sections_list[0]
        new_title = (item.get("title") or "").strip()
        new_content = (item.get("content") or "").strip()
        if not new_title or not new_content:
            return Result.fail("对话模型返回的标题或内容为空")

        target.title = new_title
        target.content = new_content
        target.update_time = datetime.now()
        db.commit()
        sync_task_status(task_id, db)
        return Result.success("✅ 本章已重新生成")
    except RuntimeError as e:
        return Result.fail(str(e))
    except Exception as e:
        return Result.fail(f"对话模型调用失败：{e}")