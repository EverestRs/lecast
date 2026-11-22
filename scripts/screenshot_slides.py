"""
Screenshot Slides: Convert slide_*.html → slide_*.png (full-page PNG)

Usage:
  python screenshot_slides.py --slides-dir ./slides --out-dir ./screenshots
  python screenshot_slides.py --slides-dir ./slides  # defaults to ./screenshots

Requirements:
  pip install playwright rich
  playwright install chromium
"""

import asyncio
import argparse
import re
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()


def parse_slide_number(filename: str) -> int:
    """Extract number from slide_NNN.html (e.g., slide_5.html → 5)"""
    m = re.match(r"slide_(\d+)\.html", filename)
    if not m:
        raise ValueError(f"Invalid slide filename: {filename}")
    return int(m.group(1))


async def screenshot_single(browser, html_path: Path, out_path: Path, width: int = 1920, height: int = 1080):
    """Take full-page screenshot of a single HTML file (browser is reused across pages)."""
    page = await browser.new_page(viewport={"width": width, "height": height})
    try:
        await page.goto(f"file://{html_path.absolute()}", wait_until="networkidle")
        await page.wait_for_timeout(1500)  # brief pause for JS/rendering
        await page.screenshot(path=out_path, full_page=True)
        return True
    except Exception as e:
        console.print(f"[red][FAIL] Failed {html_path.name} → {out_path.name}: {e}[/red]")
        return False
    finally:
        await page.close()


async def main():
    parser = argparse.ArgumentParser(description="Generate PNG screenshots from slide_*.html files")
    parser.add_argument("--slides-dir", type=Path, required=True, help="Directory containing slide_*.html files")
    parser.add_argument("--out-dir", type=Path, default=Path("./screenshots"), help="Output directory for PNGs (default: ./screenshots)")
    parser.add_argument("--width", type=int, default=1920, help="Browser viewport width (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Browser viewport height (default: 1080)")

    args = parser.parse_args()

    slides_dir = args.slides_dir.resolve()
    out_dir = args.out_dir.resolve()

    if not slides_dir.exists() or not slides_dir.is_dir():
        console.print(f"[red][FAIL] Slides dir not found: {slides_dir}[/red]")
        exit(1)

    html_files = sorted(list(slides_dir.glob("slide_*.html")))
    if not html_files:
        console.print(f"[yellow][WARN]  No slide_*.html found in {slides_dir}[/yellow]")
        exit(0)

    console.print(f"[bold blue] Screenshot Slides[/bold blue]")
    console.print(f"Slides:   {slides_dir}")
    console.print(f"Output:   {out_dir}")
    console.print(f"Size:     {args.width}×{args.height}")
    console.print(f"Count:    {len(html_files)} files\n")

    # Ensure output dir exists
    out_dir.mkdir(parents=True, exist_ok=True)

    # 整批复用同一个浏览器实例
    success_count = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[f"--window-size={args.width},{args.height}"])
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Capturing screenshots...", total=len(html_files))

                for html_path in html_files:
                    try:
                        num = parse_slide_number(html_path.name)
                        out_path = out_dir / f"slide_{num}.png"

                        ok = await screenshot_single(browser, html_path, out_path, args.width, args.height)
                        if ok:
                            success_count += 1
                        progress.update(task, advance=1)
                    except Exception as e:
                        console.print(f"[red][WARN]  Skip {html_path.name}: {e}[/red]")
                        progress.update(task, advance=1)
        finally:
            await browser.close()

    console.print("\n[bold green][OK] Done![/bold green]")
    console.print(f"  Generated {success_count}/{len(html_files)} PNGs → {out_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
