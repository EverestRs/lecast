"""
Make PowerPoint (.pptx): Convert slide_*.png/jpg → presentation.pptx

Usage:
  python make_pptx.py --image-dir ./screenshots
  python make_pptx.py --image-dir ./screenshots --output mytalk.pptx --ext png

Requirements:
  pip install python-pptx
"""

from pptx import Presentation
from pptx.util import Inches
from pathlib import Path
import argparse
import re

def parse_slide_number(filename: str) -> int:
    m = re.match(r"slide_(\d+)\.([a-zA-Z]+)", filename)
    return int(m.group(1)) if m else -1

def main():
    parser = argparse.ArgumentParser(description="Convert slide images to PowerPoint (.pptx)")
    parser.add_argument("--image-dir", type=Path, required=True, help="Directory containing slide images (e.g., ./screenshots)")
    parser.add_argument("--output", type=Path, default=Path("presentation.pptx"), help="Output .pptx file path")
    parser.add_argument("--ext", type=str, default="png", choices=["png", "jpg", "jpeg"], help="Image extension to include (default: png)")
    parser.add_argument("--width", type=int, default=1920, help="Slide width in pixels (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Slide height in pixels (default: 1080)")
    args = parser.parse_args()

    image_dir = args.image_dir.resolve()
    output_path = args.output.resolve()

    if not image_dir.exists() or not image_dir.is_dir():
        raise SystemExit(f"[FAIL] Image directory not found: {image_dir}")

    ext = args.ext.lower()
    image_files = sorted(
        [p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() == f".{ext}" and p.name.startswith("slide_")],
        key=lambda p: parse_slide_number(p.name)
    )

    if not image_files:
        raise SystemExit(f"[FAIL] No slide_*.{ext} files found in {image_dir}")

    dpi = 96
    prs = Presentation()
    prs.slide_width = Inches(args.width / dpi)
    prs.slide_height = Inches(args.height / dpi)

    print(f"[OK] Found {len(image_files)} slide images ({ext.upper()}) — generating {output_path}...")

    for i, img_path in enumerate(image_files, 1):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        try:
            slide.shapes.add_picture(str(img_path), Inches(0), Inches(0), prs.slide_width, prs.slide_height)
            print(f"[OK] Page {i:3d}: {img_path.name}")
        except Exception as e:
            print(f"[WARN] Page {i:3d}: {img_path.name} → {e}")

    prs.save(output_path)
    print(f"\n[DONE] Done: {output_path} ({len(image_files)} slides)")

if __name__ == "__main__":
    main()
