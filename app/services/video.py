"""视频合成服务：dump + 调用 record.py / compose.py"""

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import (
    COMPOSE_TIMEOUT_FACTOR,
    RECORD_TIMEOUT_PER_PAGE,
    SUBPROCESS_MIN_TIMEOUT,
    TIMEOUT_EXTRA,
    DUMP_ROOT,
    SCRIPTS_DIR,
    FFMPEG_PATH,
)
from app.models import Slide, Tts

logger = logging.getLogger(__name__)

# 安全字符集（用于 taskId → 目录名）
_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _safe_task_id(task_id: str) -> str:
    return "".join(c if c in _SAFE_CHARS else "_" for c in task_id)


def _task_dir(task_id: str) -> Path:
    return DUMP_ROOT / _safe_task_id(task_id)


def tts_audio_path(task_id: str, order: int) -> Path:
    """某任务第 N 条 TTS 音频的绝对存储路径"""
    return DUMP_ROOT / _safe_task_id(task_id) / "audios" / f"tts_{order}.wav"


def save_tts_audio(task_id: str, order: int, data: bytes) -> str:
    """音频落盘并返回相对 DUMP_ROOT 的存储路径（写入 DB 的 file_path）"""
    p = tts_audio_path(task_id, order)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return f"{_safe_task_id(task_id)}/audios/tts_{order}.wav"


def tts_abs_path(file_path: str) -> Path:
    return DUMP_ROOT / file_path


def _tts_row_has_data(tts: Tts) -> bool:
    if tts.file_path and tts_abs_path(tts.file_path).is_file():
        return True
    return bool(tts.content)


def dump_slides_and_audio(task_id: str, db: Session) -> str:
    """将 slides / tts 从数据库写出到磁盘，供 Python 脚本消费。

    目录结构：
        {DUMP_ROOT}/{safeTaskId}/slides/slide_N.html
        {DUMP_ROOT}/{safeTaskId}/audios/speech_N.wav

    存在 failed 记录或序号错位时直接抛错，避免残缺数据流入视频合成。
    """
    slides = db.query(Slide).filter(Slide.task_id == task_id).order_by(Slide.slide_order).all()
    if not slides:
        raise ValueError(f"taskId={task_id} 下无幻灯片数据")

    tts_list = db.query(Tts).filter(Tts.task_id == task_id).order_by(Tts.tts_order).all()
    if not tts_list:
        raise ValueError(f"taskId={task_id} 下无音频数据")

    bad_slides = sorted(s.slide_order for s in slides if s.status == "failed" or not s.content)
    bad_tts = sorted(t.tts_order for t in tts_list if t.status == "failed" or not _tts_row_has_data(t))
    if bad_slides or bad_tts:
        parts = []
        if bad_slides:
            parts.append(f"生成失败的幻灯片序号 {bad_slides}")
        if bad_tts:
            parts.append(f"生成失败或缺失的音频序号 {bad_tts}")
        raise ValueError("存在未完成的生成记录，请先在对应步骤重试后再导出：" + "；".join(parts))

    slide_orders = [s.slide_order for s in slides]
    tts_orders = [t.tts_order for t in tts_list]
    expected = list(range(1, len(slides) + 1))
    if slide_orders != expected:
        raise ValueError(f"幻灯片序号不连续或未从 1 开始：{slide_orders}")
    if tts_orders != list(range(1, len(tts_list) + 1)):
        raise ValueError(f"音频序号不连续或未从 1 开始：{tts_orders}")
    if slide_orders != tts_orders:
        raise ValueError(f"幻灯片({len(slides)} 张)与音频({len(tts_list)} 条)数量不一致，无法配对合成")

    task_path = _task_dir(task_id)
    slides_dir = task_path / "slides"
    audios_dir = task_path / "audios"
    os.makedirs(slides_dir, exist_ok=True)
    os.makedirs(audios_dir, exist_ok=True)

    slide_count = 0
    for slide in slides:
        (slides_dir / f"slide_{slide.slide_order}.html").write_text(slide.content, encoding="utf-8")
        slide_count += 1

    audio_count = 0
    for tts in tts_list:
        dst = audios_dir / f"speech_{tts.tts_order}.wav"
        src = tts_abs_path(tts.file_path) if tts.file_path else None
        if src and src.is_file():
            # 复用已落盘音频，不再读 DB blob
            shutil.copyfile(src, dst)
        else:
            dst.write_bytes(tts.content)
        audio_count += 1

    return f"转储成功：幻灯片 {slide_count} 张 + 音频 {audio_count} 条 → {task_path}"


def _report(progress, stage: str = None, current: int = None, total: int = None):
    """向作业对象回报进度（progress 为 None 时静默，供脚本独立调用）"""
    if progress is None:
        return
    if stage is not None:
        progress.stage = stage
    if current is not None:
        progress.current = current
    if total is not None:
        progress.total = total


def _count_slides(slides_dir: Path) -> int:
    return len(list(slides_dir.glob("slide_*.html")))


def _audio_total_seconds(audios_dir: Path) -> float:
    """用 ffprobe 汇总音频总时长（秒），失败项按 0 计"""
    total = 0.0
    for p in sorted(audios_dir.glob("speech_*.wav")):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                capture_output=True, text=True, check=True, timeout=30,
            )
            total += float(r.stdout.strip())
        except Exception as e:  # noqa: BLE001 —— 单个文件探测失败不阻断
            logger.warning("ffprobe 探测 %s 失败：%s", p.name, e)
    return total


def export_video(task_id: str, progress=None) -> dict:
    """执行 record.py（HTML→截图→MP4）+ compose.py（拼接最终视频）。

    返回: {"success": bool, "message": str, "output_path": str, "duration_ms": int}
    """
    task_path = _task_dir(task_id)
    slides_dir = task_path / "slides"
    audios_dir = task_path / "audios"
    videos_dir = task_path / "videos"
    final_output = task_path / "final.mp4"

    if not slides_dir.is_dir():
        return {"success": False, "message": f"幻灯片目录不存在：{slides_dir}", "output_path": None, "duration_ms": 0}
    if not audios_dir.is_dir():
        return {"success": False, "message": f"音频目录不存在：{audios_dir}", "output_path": None, "duration_ms": 0}

    record_py = SCRIPTS_DIR / "record.py"
    compose_py = SCRIPTS_DIR / "compose.py"
    if not record_py.is_file():
        return {"success": False, "message": f"record.py 未找到：{record_py}", "output_path": None, "duration_ms": 0}
    if not compose_py.is_file():
        return {"success": False, "message": f"compose.py 未找到：{compose_py}", "output_path": None, "duration_ms": 0}
    if not Path(FFMPEG_PATH).is_file() and not shutil.which(FFMPEG_PATH):
        return {"success": False, "message": f"FFmpeg 未找到：{FFMPEG_PATH}，请设置 FFMPEG_PATH", "output_path": None, "duration_ms": 0}

    # 超时按规模动态计算：录制约 90s/页 + 裕量；合成按音频总时长×系数 + 裕量
    n_pages = _count_slides(slides_dir)
    record_timeout = max(SUBPROCESS_MIN_TIMEOUT, RECORD_TIMEOUT_PER_PAGE * n_pages + TIMEOUT_EXTRA)
    compose_timeout = max(
        SUBPROCESS_MIN_TIMEOUT,
        int(_audio_total_seconds(audios_dir) * COMPOSE_TIMEOUT_FACTOR) + TIMEOUT_EXTRA,
    )

    python = sys.executable
    child_env = os.environ.copy()
    child_env["FFMPEG_PATH"] = FFMPEG_PATH
    start = time.monotonic()
    _report(progress, stage="正在录制幻灯片（Playwright 截图 + FFmpeg）", current=0, total=2)

    # Step 1: record.py
    logger.info("运行 record.py ...")
    try:
        proc = subprocess.run(
            [python, str(record_py), "--slides-dir", str(slides_dir),
             "--audio-dir", str(audios_dir), "--out-dir", str(videos_dir)],
            capture_output=True, text=True, timeout=record_timeout, env=child_env,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "无输出").strip()
            return {"success": False, "message": f"record.py 失败：{detail[-2000:]}",
                    "output_path": None, "duration_ms": 0}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"record.py 执行超时（{record_timeout} 秒）", "output_path": None, "duration_ms": 0}

    # Step 2: compose.py
    _report(progress, stage="正在拼接最终视频（FFmpeg concat）", current=1)
    logger.info("运行 compose.py ...")
    try:
        proc = subprocess.run(
            [python, str(compose_py), "--video-dir", str(videos_dir),
             "--audio-dir", str(audios_dir), "--output", str(final_output)],
            capture_output=True, text=True, timeout=compose_timeout, env=child_env,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "无输出").strip()
            return {"success": False, "message": f"compose.py 失败：{detail[-2000:]}",
                    "output_path": None, "duration_ms": 0}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"compose.py 执行超时（{compose_timeout} 秒）", "output_path": None, "duration_ms": 0}

    duration_ms = int((time.monotonic() - start) * 1000)
    _report(progress, stage="完成", current=2)
    return {
        "success": True,
        "message": "success",
        "output_path": str(final_output),
        "duration_ms": duration_ms,
    }


def export_pptx(task_id: str, progress=None) -> dict:
    """执行 screenshot_slides.py（HTML→PNG）+ make_pptx.py（PNG→PPTX）。"""
    task_path = _task_dir(task_id)
    slides_dir = task_path / "slides"
    screenshots_dir = task_path / "screenshots"
    pptx_output = task_path / "presentation.pptx"

    if not slides_dir.is_dir():
        return {"success": False, "message": f"幻灯片目录不存在：{slides_dir}", "output_path": None, "duration_ms": 0}

    screenshot_py = SCRIPTS_DIR / "screenshot_slides.py"
    make_pptx_py = SCRIPTS_DIR / "make_pptx.py"
    if not screenshot_py.is_file():
        return {"success": False, "message": f"screenshot_slides.py 未找到：{screenshot_py}", "output_path": None, "duration_ms": 0}
    if not make_pptx_py.is_file():
        return {"success": False, "message": f"make_pptx.py 未找到：{make_pptx_py}", "output_path": None, "duration_ms": 0}

    n_pages = _count_slides(slides_dir)
    screenshot_timeout = max(SUBPROCESS_MIN_TIMEOUT, 60 * n_pages + TIMEOUT_EXTRA)
    pptx_timeout = SUBPROCESS_MIN_TIMEOUT

    python = sys.executable
    start = time.monotonic()
    _report(progress, stage="正在截图幻灯片（Playwright）", current=0, total=2)

    # Step 1: screenshot_slides.py
    logger.info("运行 screenshot_slides.py ...")
    try:
        proc = subprocess.run(
            [python, str(screenshot_py), "--slides-dir", str(slides_dir), "--out-dir", str(screenshots_dir)],
            capture_output=True, text=True, timeout=screenshot_timeout,
        )
        if proc.returncode != 0:
            return {"success": False, "message": f"screenshot_slides.py 失败：{proc.stderr[:500] or proc.stdout[:500]}",
                    "output_path": None, "duration_ms": 0}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"screenshot_slides.py 执行超时（{screenshot_timeout} 秒）", "output_path": None, "duration_ms": 0}

    # Step 2: make_pptx.py
    _report(progress, stage="正在组装 PPTX", current=1)
    logger.info("运行 make_pptx.py ...")
    try:
        proc = subprocess.run(
            [python, str(make_pptx_py), "--image-dir", str(screenshots_dir), "--output", str(pptx_output)],
            capture_output=True, text=True, timeout=pptx_timeout,
        )
        if proc.returncode != 0:
            return {"success": False, "message": f"make_pptx.py 失败：{proc.stderr[:500] or proc.stdout[:500]}",
                    "output_path": None, "duration_ms": 0}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"make_pptx.py 执行超时（{pptx_timeout} 秒）", "output_path": None, "duration_ms": 0}

    duration_ms = int((time.monotonic() - start) * 1000)
    _report(progress, stage="完成", current=2)
    return {
        "success": True,
        "message": "success",
        "output_path": str(pptx_output),
        "duration_ms": duration_ms,
    }


def has_final_video(task_id: str) -> bool:
    """检查 final.mp4 是否已生成"""
    fp = _task_dir(task_id) / "final.mp4"
    return fp.is_file()


def delete_task_dir(task_id: str) -> None:
    """删除任务的整个磁盘转储目录（任务删除时调用，含 TTS 音频文件）"""
    shutil.rmtree(_task_dir(task_id), ignore_errors=True)


def has_pptx(task_id: str) -> bool:
    """检查 presentation.pptx 是否已生成"""
    fp = _task_dir(task_id) / "presentation.pptx"
    return fp.is_file()


def get_final_video_path(task_id: str) -> Optional[Path]:
    fp = _task_dir(task_id) / "final.mp4"
    return fp if fp.is_file() else None


def get_pptx_path(task_id: str) -> Optional[Path]:
    fp = _task_dir(task_id) / "presentation.pptx"
    return fp if fp.is_file() else None