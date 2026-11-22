"""
Record Slides: Convert slide_*.html + speech_*.wav → slide_*.mp4

Usage:
  python record.py --slides-dir ./slides --audio-dir ./audios --out-dir ./videos
  python record.py --slides-dir ./slides --audio-dir ./audios --out-dir ./videos --duration-ms 12000
"""

import asyncio
import argparse
import os
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console

from utils import safe_mkdir, get_audio_duration_ms, list_slides_and_audios, log_step, console


async def record_single(
    browser,
    html_path: Path,
    audio_path: Path,
    out_path: Path,
    width: int = 1920,
    height: int = 1080,
    duration_ms: int = None,
):
    console.print(f"[blue][RECORD] 录制 {html_path.name} → {out_path.name}...[/blue]")

    if duration_ms is None:
        duration_ms = get_audio_duration_ms(audio_path) + 1000

    page = await browser.new_page(viewport={"width": width, "height": height})
    try:
        await page.goto(f"file://{html_path.absolute()}", wait_until="networkidle")
        await page.wait_for_timeout(1500)

        # 内容溢出预警：full_page 截图会被等比缩小留黑边
        scroll_height = await page.evaluate("document.documentElement.scrollHeight")
        if scroll_height > height + 50:
            console.print(
                f"[yellow][WARN] {html_path.name} 内容高度 {scroll_height}px 超出视口 {height}px，"
                f"成片将整体缩小并留黑边[/yellow]"
            )

        img_path = out_path.with_suffix(".png")
        await page.screenshot(path=img_path, full_page=True)
    finally:
        await page.close()

    cmd = [
        os.environ.get("FFMPEG_PATH", "ffmpeg"),
        "-y",
        "-loop", "1",
        "-i", str(img_path),
        "-t", str(duration_ms / 1000),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-preset", "veryfast",
        "-crf", "18",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        console.print(f"[green][OK] 已保存: {out_path.name} ({duration_ms//1000}s)[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red][FAIL] FFmpeg 失败: {e}[/red]")
        raise
    finally:
        img_path.unlink(missing_ok=True)


async def main():
    parser = argparse.ArgumentParser(description="Record slides HTML to MP4 videos")
    parser.add_argument("--slides-dir", type=Path, required=True, help="Directory with slide_*.html")
    parser.add_argument("--audio-dir", type=Path, required=True, help="Directory with speech_*.wav")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory for slide_*.mp4")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--duration-ms", type=int, default=None, help="Fixed duration per slide (ms)")

    args = parser.parse_args()

    log_step("RECORD SLIDES")
    console.print(f"Slides: {args.slides_dir}")
    console.print(f"Audio:  {args.audio_dir}")
    console.print(f"Output: {args.out_dir}")

    pairs = list_slides_and_audios(args.slides_dir, args.audio_dir)
    safe_mkdir(args.out_dir)

    # 整批复用同一个浏览器实例，逐页开关 page
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[f"--window-size={args.width},{args.height}"])
        try:
            for html_path, audio_path in pairs:
                i = int(html_path.stem.split("_")[1])
                out_path = args.out_dir / f"slide_{i}.mp4"
                await record_single(browser, html_path, audio_path, out_path, args.width, args.height, args.duration_ms)
        finally:
            await browser.close()

    console.print(f"\n[bold green][DONE] 录制完成！共 {len(pairs)} 个视频 → {args.out_dir}/[/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
