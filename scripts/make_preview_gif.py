#!/usr/bin/env python3
"""生成 README 效果预览 GIF：应用页面截图 + 演示任务成片片段 → assets/preview.gif

前提：
  1. 应用已启动（默认 http://127.0.0.1:8000）
  2. 已用 assets/demo_lesson.md 创建演示任务并走完 6 步（状态「已完成」）
  3. data/ 中只有演示任务（原数据目录已隔离改名，见 README/工作流说明）

用法：
  python scripts/make_preview_gif.py --task-id <演示任务ID>

隐私说明：截图仅捕获应用页面视口（无浏览器外壳/任务栏/桌面元素），
视频段仅取 --task-id 指定的演示任务成片，绝不触碰其他任务数据。

依赖：playwright(chromium)、ffmpeg（项目运行环境已具备）。
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent


def find_ffmpeg() -> str:
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"


def run(cmd: list) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"命令失败：{' '.join(cmd)}\n{proc.stderr[-800:]}")


def encode_segment(src: list, dst: Path, ffmpeg: str, width: int, fps: int) -> None:
    """把图片序列或视频片段编码为统一规格的 mp4 段。src 为 ffmpeg 输入参数。"""
    run([ffmpeg, "-y", *src,
         "-vf", f"scale={width}:-2,fps={fps},format=yuv420p",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         str(dst)])


def main() -> None:
    ap = argparse.ArgumentParser(description="生成效果预览 GIF")
    ap.add_argument("--task-id", required=True, help="演示任务 ID（必须是演示任务）")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(BASE / "assets" / "preview.gif"))
    ap.add_argument("--width", type=int, default=800, help="GIF 宽度，高度自适应")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--still-seconds", type=float, default=1.6, help="每张页面截图停留秒数")
    ap.add_argument("--video-seconds", type=float, default=6.0, help="成片片段秒数")
    ap.add_argument("--keep-temp", action="store_true", help="保留中间文件便于排查")
    args = ap.parse_args()

    ffmpeg = find_ffmpeg()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="preview_gif_"))

    try:
        # ── 1. 应用页面截图（Playwright 无头：只截视口，无浏览器外壳） ──
        pages = [
            f"{args.base_url}/taskList",
            f"{args.base_url}/taskCreate?taskId={args.task_id}",
        ]
        stills = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            for i, url in enumerate(pages):
                page.goto(url, wait_until="load")
                page.wait_for_timeout(1200)  # 等待 JS 渲染
                f = work / f"still_{i}.png"
                page.screenshot(path=str(f))
                stills.append(f)
            browser.close()
        print(f"[1/4] 页面截图 {len(stills)} 张完成")

        # ── 2. 静帧 → 统一规格 mp4 段 ──
        segs = []
        for i, f in enumerate(stills):
            seg = work / f"seg_{i}.mp4"
            encode_segment(["-loop", "1", "-i", str(f), "-t", str(args.still_seconds)], seg, ffmpeg,
                           args.width, args.fps)
            segs.append(seg)

        # ── 3. 演示任务成片片段 ──
        video_src = BASE / "data" / args.task_id / "final.mp4"
        if video_src.exists():
            seg = work / "seg_video.mp4"
            encode_segment(["-ss", "0", "-t", str(args.video_seconds), "-i", str(video_src)],
                           seg, ffmpeg, args.width, args.fps)
            segs.append(seg)
            print(f"[2/4] 成片片段 {args.video_seconds}s 已截取")
        else:
            print(f"[2/4] 未找到 {video_src}，仅用页面截图合成")

        # ── 4. 拼接 → 调色板 GIF（两遍法画质最佳） ──
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
        merged = work / "merged.mp4"
        run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(merged)])

        palette = work / "palette.png"
        run([ffmpeg, "-y", "-i", str(merged),
             "-vf", f"fps={args.fps},scale={args.width}:-2:flags=lanczos,palettegen=max_colors=128",
             str(palette)])
        run([ffmpeg, "-y", "-i", str(merged), "-i", str(palette),
             "-filter_complex",
             f"[0:v]fps={args.fps},scale={args.width}:-2:flags=lanczos[x];[x][1:v]paletteuse",
             "-loop", "0", str(out)])
        print(f"[3/4] GIF 已生成：{out}")

        size_kb = out.stat().st_size / 1024
        print(f"[4/4] 大小 {size_kb:.0f} KB" + ("（GitHub 建议控制在 10MB 内）" if size_kb > 10240 else ""))
    finally:
        if args.keep_temp:
            print(f"中间文件保留在：{work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
