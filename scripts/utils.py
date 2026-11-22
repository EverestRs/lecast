import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

from rich.console import Console
from rich.text import Text

console = Console()


def safe_mkdir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def get_audio_duration_ms(audio_path: Path) -> int:
    """Return duration in milliseconds; raise instead of guessing (avoids silent A/V desync)"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        duration_sec = float(result.stdout.strip())
        return int(duration_sec * 1000)
    except Exception as e:
        raise RuntimeError(f"获取音频时长失败: {audio_path.name}: {e}") from e


def list_slides_and_audios(
    slides_dir: Path, audio_dir: Path
) -> List[Tuple[Path, Path]]:
    htmls = sorted(slides_dir.glob("slide_*.html"))
    if not htmls:
        raise ValueError(f"[FAIL] slides_dir 为空: {slides_dir}")

    html_indices = []
    for p in htmls:
        match = __import__("re").search(r"slide_(\d+)\.html", p.name)
        if not match:
            raise ValueError(f"[FAIL] HTML 文件名格式错误（需 slide_N.html）: {p.name}")
        html_indices.append(int(match.group(1)))
    html_indices.sort()

    if not html_indices:
        raise ValueError("[FAIL] 未找到 slide_*.html 文件")
    if html_indices != list(range(1, len(html_indices) + 1)):
        raise ValueError(
            f"[FAIL] HTML 文件索引不连续或未从 1 开始: "
            f"found {html_indices}, expected [1, 2, ..., {len(html_indices)}]"
        )

    pairs = []
    for i in html_indices:
        html_path = slides_dir / f"slide_{i}.html"
        audio_path = audio_dir / f"speech_{i}.wav"

        if not audio_path.exists():
            raise ValueError(f"[FAIL] 缺失音频文件: {audio_path}（对应 {html_path.name}）\n[HINT] 请确保 audios/ 下有 speech_{i}.wav")

        if audio_path.stat().st_size == 0:
            raise ValueError(f"[FAIL] 音频文件为空: {audio_path}")

        pairs.append((html_path, audio_path))

    return pairs


def log_step(name: str):
    console.print(f"\n[bold blue]━━━━━━━━ {name} ━━━━━━━━[/bold blue]")
