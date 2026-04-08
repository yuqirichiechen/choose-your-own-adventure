#!/usr/bin/env python3
"""Re-extract story pages using image OCR with deterministic spread mapping.

Mapping model:
- PDF page 8 contains story pages 2 (left) and 3 (right)
- PDF page 9 contains story pages 4 (left) and 5 (right)
- and so on
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def run_capture(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def clean_ocr_text(text: str, story_page: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]

    # Remove obvious page-number/header artifacts at the top.
    while lines and not lines[0].strip():
        lines.pop(0)

    if lines:
        first = lines[0].strip().lstrip("_").strip()
        if first == str(story_page) or re.fullmatch(r"[0-9_ ]{1,4}", lines[0].strip()):
            lines.pop(0)

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines).strip()


def ocr_half_page(
    source_png: Path,
    side: str,
    tmp_dir: Path,
    base_name: str,
) -> str:
    size = run_capture(["magick", "identify", "-format", "%w %h", str(source_png)])
    width, height = [int(x) for x in size.split()]
    half = width // 2

    cropped_png = tmp_dir / f"{base_name}-{side}.png"
    ocr_base = tmp_dir / f"{base_name}-{side}"

    if side == "left":
        geometry = f"{half}x{height}+0+0"
    else:
        geometry = f"{half}x{height}+{half}+0"

    run(["magick", str(source_png), "-crop", geometry, "+repage", str(cropped_png)])
    run(["tesseract", str(cropped_png), str(ocr_base), "--psm", "4"])

    txt_path = ocr_base.with_suffix(".txt")
    return txt_path.read_text(encoding="utf-8", errors="ignore").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCR re-extract COT pages from spread-scanned PDF.")
    parser.add_argument("--pdf", type=Path, default=Path("samples/the-cave-of-time.pdf"))
    parser.add_argument("--pdf-start-page", type=int, default=8)
    parser.add_argument("--pdf-end-page", type=int, default=66)
    parser.add_argument("--story-start-page", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=Path("output/cot-pages-ocr-v2"))
    parser.add_argument("--tmp-dir", type=Path, default=Path("output/tmp/ocr-v2"))
    parser.add_argument("--name-width", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    for required in ("pdftoppm", "magick", "tesseract"):
        if shutil.which(required) is None:
            raise RuntimeError(f"{required} is required in PATH")

    if not args.pdf.exists():
        raise FileNotFoundError(f"PDF not found: {args.pdf}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    spread_index = 0
    written = 0

    for pdf_page in range(args.pdf_start_page, args.pdf_end_page + 1):
        page_png = args.tmp_dir / f"pdf-{pdf_page}.png"
        run(["pdftoppm", "-f", str(pdf_page), "-singlefile", "-png", str(args.pdf), str(page_png.with_suffix(""))])

        left_story_page = args.story_start_page + (spread_index * 2)
        right_story_page = left_story_page + 1

        left_text = ocr_half_page(page_png, "left", args.tmp_dir, f"pdf-{pdf_page}")
        right_text = ocr_half_page(page_png, "right", args.tmp_dir, f"pdf-{pdf_page}")

        left_text = clean_ocr_text(left_text, left_story_page)
        right_text = clean_ocr_text(right_text, right_story_page)

        if len("".join(left_text.split())) >= 30:
            left_name = f"{str(left_story_page).zfill(args.name_width)}-CoT.txt"
            write_text(args.output_dir / left_name, f"Page {left_story_page}\n\n{left_text}")
            written += 1

        if len("".join(right_text.split())) >= 30:
            right_name = f"{str(right_story_page).zfill(args.name_width)}-CoT.txt"
            write_text(args.output_dir / right_name, f"Page {right_story_page}\n\n{right_text}")
            written += 1

        spread_index += 1

    print(f"Processed PDF pages: {args.pdf_start_page}-{args.pdf_end_page}")
    print(f"Story pages written: {written}")
    print(f"Output directory: {args.output_dir}")


if __name__ == "__main__":
    main()
