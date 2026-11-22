"""
Compose Final Video: Merge slide_*.mp4 + speech_*.wav → output.mp4

Usage:
  python compose.py --video-dir ./videos --audio-dir ./audios --output final.mp4
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from utils import safe_mkdir, log_step, console
except ImportError:  # 作为模块被导入（如测试）时补脚本目录到 sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils import safe_mkdir, log_step, console


def build_pairs(video_dir: Path, audio_dir: Path):
    """按序号配对视频与音频，缺失/空音频直接报错（纯校验逻辑，便于测试）"""
    videos = sorted(
        video_dir.glob("slide_*.mp4"),
        key=lambda p: int(p.stem.split("_")[1])  # 提取数字部分转 int
    )
    if not videos:
        raise ValueError(f"[FAIL] video_dir 无 slide_*.mp4: {video_dir}")

    pairs = []
    for v in videos:
        i = int(v.stem.split("_")[1])
        a = audio_dir / f"speech_{i}.wav"
        if not a.exists():
            raise ValueError(f"[FAIL] 缺失音频: {a}（对应 {v.name}）")
        if a.stat().st_size == 0:
            raise ValueError(f"[FAIL] 音频为空: {a}")
        pairs.append((v, a))
    return pairs


def compose_final(
    video_dir: Path,
    audio_dir: Path,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
):
    console.print(f"[blue][COMPOSE] 合成最终视频 → {output_path}...[/blue]")

    pairs = build_pairs(video_dir, audio_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        processed_videos = []

        for v, a in pairs:
            i = int(v.stem.split("_")[1])
            out_with_audio = tmpdir / f"slide_{i}_with_audio.mp4"
            cmd_mux = [
                os.environ.get("FFMPEG_PATH", "ffmpeg"),
                "-y",
                "-i", str(v),
                "-i", str(a),
                "-c:v", "copy",
                "-c:a", "aac",
                "-ar", "44100",
                "-ac", "2",
                # 不加 -shortest：视频比音频长 1s 作为尾部缓冲，需完整保留
                "-pix_fmt", "yuv420p",
                str(out_with_audio),
            ]
            try:
                result = subprocess.run(cmd_mux, check=True, capture_output=True)
                processed_videos.append(out_with_audio)
            except subprocess.CalledProcessError as e:
                stderr_str = e.stderr.decode("utf-8", errors="replace").strip()
                stdout_str = e.stdout.decode("utf-8", errors="replace").strip()
                err_msg = f"[FAIL] mux 失败 {v.name}+{a.name}"
                if stderr_str:
                    err_msg += f"\n  [stderr] {stderr_str}"
                if stdout_str:
                    err_msg += f"\n  [stdout] {stdout_str}"
                console.print(f"[red]{err_msg}[/red]")
                raise

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            for p in processed_videos:
                f.write(f"file '{p.absolute()}'\n")
            list_file = Path(f.name)

        try:
            cmd_concat = [
                os.environ.get("FFMPEG_PATH", "ffmpeg"),
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c:v", "copy",
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ]
            subprocess.run(cmd_concat, check=True, capture_output=True)
            console.print(f"[green][OK] 合成完成: {output_path}[/green]")
        except subprocess.CalledProcessError as e:
            stderr_str = e.stderr.decode("utf-8", errors="replace").strip()
            stdout_str = e.stdout.decode("utf-8", errors="replace").strip()
            err_msg = f"[red][FAIL] concat 失败"
            if stderr_str:
                err_msg += f"\n  [stderr] {stderr_str}"
            if stdout_str:
                err_msg += f"\n  [stdout] {stdout_str}"
            console.print(err_msg)
            raise
        finally:
            list_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Compose slide videos and audios into final MP4")
    parser.add_argument("--video-dir", type=Path, required=True, help="Directory with slide_*.mp4")
    parser.add_argument("--audio-dir", type=Path, required=True, help="Directory with speech_*.wav")
    parser.add_argument("--output", type=Path, required=True, help="Final output video path (e.g., final.mp4)")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=60)

    args = parser.parse_args()

    log_step("COMPOSE FINAL VIDEO")
    console.print(f"Video:  {args.video_dir}")
    console.print(f"Audio:  {args.audio_dir}")
    console.print(f"Output: {args.output}")

    safe_mkdir(args.output.parent)
    compose_final(args.video_dir, args.audio_dir, args.output, args.width, args.height, args.fps)

    console.print(f"\n[bold green][DONE] 合成完成！→ {args.output}[/bold green]")


if __name__ == "__main__":
    main()
