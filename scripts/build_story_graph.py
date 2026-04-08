#!/usr/bin/env python3
"""Build a Mermaid story graph from extracted Cave of Time page files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Set

PAGE_FILE_RE = re.compile(r"^(\d+)-CoT\.txt$")
TURN_TO_RE = re.compile(
    r"\b(?:turn|tum|go|follow|take|return)\b[^\n]{0,120}?\b(?:to|ta|io)\b[^\n]{0,20}?"
    r"(?:page|poge|p\.)\s*([0-9IlOoSsZz]{1,3})",
    flags=re.IGNORECASE,
)


def normalize_page_token(token: str) -> int | None:
    raw = token.strip()
    if raw.lower() in {"s", "z"}:
        return None
    if not re.search(r"[0-9IlOoL]", raw):
        return None

    mapped = (
        raw.replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("l", "1")
        .replace("L", "1")
        .replace("S", "5")
        .replace("s", "5")
        .replace("Z", "2")
        .replace("z", "2")
    )
    if not mapped.isdigit():
        return None
    value = int(mapped)
    if value <= 0 or value > 300:
        return None
    return value


def parse_pages(pages_dir: Path) -> Dict[int, str]:
    pages: Dict[int, str] = {}
    for path in sorted(pages_dir.glob("*-CoT.txt")):
        match = PAGE_FILE_RE.match(path.name)
        if not match:
            continue
        page = int(match.group(1))
        pages[page] = path.read_text(encoding="utf-8", errors="ignore")
    return pages


def extract_links(text: str) -> List[int]:
    links: List[int] = []
    for match in TURN_TO_RE.finditer(text):
        page = normalize_page_token(match.group(1))
        if page is None:
            continue
        if page not in links:
            links.append(page)
    return links


def build_graph_lines(pages: Dict[int, str]) -> List[str]:
    nodes: Set[int] = set(pages.keys())
    edges: Dict[int, List[int]] = {}
    sorted_pages = sorted(pages)
    page_set = set(sorted_pages)

    for page, text in pages.items():
        targets = [target for target in extract_links(text) if target in pages and target != page]
        if targets:
            edges[page] = targets
            nodes.update(targets)
            continue

        # Some pages simply continue onto the next numbered page before choices appear.
        if re.search(r"\bthe\s+end\b", text, flags=re.IGNORECASE):
            continue

        next_page = page + 1
        if next_page in page_set:
            edges[page] = [next_page]
            nodes.add(next_page)

    lines = ["graph TD"]
    for node in sorted(nodes):
        lines.append(f'  P{node}["{node}"]')
    for src in sorted(edges):
        for dst in edges[src]:
            lines.append(f"  P{src} --> P{dst}")
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Mermaid story graph from extracted page files.")
    parser.add_argument("--pages-dir", type=Path, default=Path("output/cot-pages-ocr-v2"))
    parser.add_argument("--output", type=Path, default=Path("output/cot-story-graph.mmd"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.pages_dir.exists():
        raise FileNotFoundError(f"Pages directory not found: {args.pages_dir}")

    pages = parse_pages(args.pages_dir)
    if not pages:
        raise RuntimeError("No page files found.")

    lines = build_graph_lines(pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    edge_count = sum(1 for line in lines if "-->" in line)
    print(f"Pages loaded: {len(pages)}")
    print(f"Graph edges: {edge_count}")
    print(f"Graph file: {args.output}")


if __name__ == "__main__":
    main()
