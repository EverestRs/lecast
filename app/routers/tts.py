"""TTS 音频 API — 对应原 v1 TtsController"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Header
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.jobs import Job, runner as jobs_runner
from app.routers.task import sync_task_status
from app.models import Script, Section, Tts
from app.schemas import Result
from app.services import tts_api, video as video_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["音频"])


@router.post("/generate-all", response_model=Result)
def generate_all_tts(
    task_id: str = Query(..., alias="taskId"),
    api_key: str = Header(None, alias="X-API-Key"),
    tts_key: str = Header(None, alias="X-TTS-Key"),
    db: Session = Depends(get_db),
):
    if not task_id:
        return Result.fail("taskId 不能为空")

    scripts_count = db.query(Script).filter(Script.task_id == task_id).count()
    if not scripts_count:
        return Result.fail(f"taskId={task_id} 下无讲解稿，请先调用 /api/script/generate-all")

    def work(job: Job):
        session = SessionLocal()
        try:
            scripts = session.query(Script).filter(Script.task_id == task_id).order_by(Script.script_order).all()
            if not scripts:
                raise RuntimeError("讲解稿数据不存在，请先生成讲解稿")

            session.query(Tts).filter(Tts.task_id == task_id).delete()

            job.total = len(scripts)
            success_count = 0
            failed_orders = []
            for i, script in enumerate(scripts):
                tts_order = i + 1
                job.current = i
                job.stage = f"正在合成第 {tts_order}/{len(scripts)} 条音频"
                logger.info("正在为 taskId=%s 合成第 %d 条 TTS", task_id, tts_order)

                if not script.content or script.content.strip() == "":
                    logger.warning("第 %d 篇讲解稿为空，记录为生成失败", tts_order)
                    failed_orders.append(tts_order)
                else:
                    try:
                        result = tts_api.synthesize(script.content, tts_key or api_key)
                        rel_path = video_svc.save_tts_audio(task_id, tts_order, result.bytes)
                        session.add(Tts(
                            task_id=task_id,
                            tts_order=tts_order,
                            audio_url=result.audio_url,
                            content=None,  # 大字段停用，音频落盘
                            file_path=rel_path,
                            status="ok",
                            create_time=datetime.now(),
                        ))
                        success_count += 1
                        session.commit()
                        job.current = i + 1
                        logger.info("已生成第 %d 条 TTS（taskId=%s）", tts_order, task_id)
                        continue
                    except Exception as e:
                        logger.error("TTS 生成失败（taskId=%s, order=%d）：%s", task_id, tts_order, e)
                        failed_orders.append(tts_order)

                # 失败也必须落占位记录，保住 speech_N 序号连续（否则导出配对断裂）
                session.add(Tts(
                    task_id=task_id,
                    tts_order=tts_order,
                    audio_url=None,
                    content=None,
                    status="failed",
                    create_time=datetime.now(),
                ))
                session.commit()
                job.current = i + 1

            sync_task_status(task_id, session)
            job.stage = "完成"
            if failed_orders:
                job.result = f"⚠️ 成功 {success_count}/{len(scripts)} 条，失败序号 {failed_orders}，可在列表中逐条重试"
            else:
                job.result = f"✅ 成功生成 {success_count}/{len(scripts)} 条 TTS 音频"
        finally:
            session.close()

    accepted, reject_msg = jobs_runner.submit("tts", task_id, work)
    if not accepted:
        return Result.fail(reject_msg)
    return Result.success({"jobStep": "tts", "taskId": task_id})


@router.get("/by-task-id", response_model=Result)
def list_tts(task_id: str = Query(..., alias="taskId"), db: Session = Depends(get_db)):
    if not task_id:
        return Result.fail("taskId 不能为空")

    tts_list = db.query(Tts).filter(Tts.task_id == task_id).order_by(Tts.tts_order).all()
    sections = db.query(Section).filter(Section.task_id == task_id).all()
    section_map = {s.section_order: s.title for s in sections}

    scripts = db.query(Script).filter(Script.task_id == task_id).all()
    script_map = {s.script_order: s.content for s in scripts}

    result = []
    for t in tts_list:
        result.append({
            "id": t.id,
            "taskId": t.task_id,
            "ttsOrder": t.tts_order,
            "audioUrl": t.audio_url,
            "status": t.status,
            "title": section_map.get(t.tts_order),
            "script": script_map.get(t.tts_order),
            "createTime": t.create_time.isoformat(),
            "updateTime": (t.update_time or t.create_time).isoformat(),
        })
    return Result.success(result)


@router.get("/audio")
def get_tts_audio(task_id: str = Query(..., alias="taskId"), tts_order: int = Query(..., alias="ttsOrder"), db: Session = Depends(get_db)):
    tts = db.query(Tts).filter(
        Tts.task_id == task_id, Tts.tts_order == tts_order
    ).first()
    if not tts:
        return Response(status_code=404, content="音频不存在")

    inline_disposition = {"Content-Disposition": f'inline; filename="{task_id}_tts_{tts_order}.mp3"'}

    # 懒迁移：旧数据只有 blob 时，首次访问落盘并回填 file_path
    if not tts.file_path and tts.content:
        try:
            tts.file_path = video_svc.save_tts_audio(task_id, tts_order, tts.content)
            db.commit()
        except OSError as e:
            logger.error("音频懒迁移落盘失败（taskId=%s, order=%d）：%s", task_id, tts_order, e)

    if tts.file_path:
        fp = video_svc.tts_abs_path(tts.file_path)
        if fp.is_file():
            # FileResponse 由 Starlette 提供 Range/206 分段支持，满足 <audio> seek
            return FileResponse(path=fp, media_type="audio/mpeg", headers=inline_disposition)
        if tts.content:  # 文件意外丢失时回退旧 blob
            return Response(content=tts.content, media_type="audio/mpeg", headers=inline_disposition)
        return Response(status_code=404, content="音频文件不存在")

    return Response(status_code=404, content="音频不存在")


@router.post("/regenerate", response_model=Result)
def regenerate_tts(
    task_id: str = Query(..., alias="taskId"),
    tts_order: int = Query(..., alias="ttsOrder"),
    api_key: str = Header(None, alias="X-API-Key"),
    tts_key: str = Header(None, alias="X-TTS-Key"),
    db: Session = Depends(get_db),
):
    script = db.query(Script).filter(
        Script.task_id == task_id, Script.script_order == tts_order
    ).first()
    if not script or not script.content:
        return Result.fail("未找到对应讲解稿")

    tts = db.query(Tts).filter(
        Tts.task_id == task_id, Tts.tts_order == tts_order
    ).first()
    if not tts:
        return Result.fail("未找到对应音频记录")

    try:
        result = tts_api.synthesize(script.content, tts_key or api_key)
        tts.audio_url = result.audio_url
        tts.file_path = video_svc.save_tts_audio(task_id, tts_order, result.bytes)
        tts.content = None  # 新文件已生成，释放旧 blob 占用
        tts.status = "ok"
        tts.update_time = datetime.now()
        db.commit()
        return Result.success("✅ 重生成成功")
    except Exception as e:
        return Result.fail(f"TTS 重生成失败：{e}")