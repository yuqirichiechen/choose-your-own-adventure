#!/usr/bin/env python3
"""Write all possible story paths into individual text files.

Reads:
- Mermaid graph file (output/cot-story-graph.mmd)
- Per-page text files (output/cot-pages-ocr-v2/*.txt)

Writes one file per full story path into a separate directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

EDGE_RE = re.compile(r"\bP(\d+)\s*-->\s*P(\d+)\b")
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

    # Guard against accidental captures from normal words.
    if not re.search(r"[0-9IlOoL]", raw):
        return None

    mapped = (
        raw
        .replace("O", "0")
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


def parse_graph(graph_path: Path) -> Tuple[Set[int], Dict[int, List[int]]]:
    nodes: Set[int] = set()
    edges: Dict[int, List[int]] = {}

    for raw_line in graph_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if line.startswith("P") and "[" in line:
            token = line.split("[", 1)[0].strip()
            if token.startswith("P") and token[1:].isdigit():
                nodes.add(int(token[1:]))

        match = EDGE_RE.search(line)
        if not match:
            continue

        src = int(match.group(1))
        dst = int(match.group(2))
        nodes.add(src)
        nodes.add(dst)
        edges.setdefault(src, [])
        if dst not in edges[src]:
            edges[src].append(dst)

    for node in nodes:
        edges.setdefault(node, [])

    return nodes, edges


def parse_page_texts(pages_dir: Path) -> Dict[int, str]:
    page_texts: Dict[int, str] = {}

    for path in sorted(pages_dir.glob("*-CoT.txt")):
        match = PAGE_FILE_RE.match(path.name)
        if not match:
            continue
        page = int(match.group(1))
        text = path.read_text(encoding="utf-8").strip()
        page_texts[page] = text

    return page_texts


def parse_links_from_page_text(text: str) -> List[int]:
    targets: List[int] = []
    for match in TURN_TO_RE.finditer(text):
        page = normalize_page_token(match.group(1))
        if page is None:
            continue
        if page not in targets:
            targets.append(page)
    return targets


def choose_start_nodes(nodes: Set[int], edges: Dict[int, List[int]], explicit_start: List[int]) -> List[int]:
    if explicit_start:
        return sorted({p for p in explicit_start if p in nodes})

    indegree: Dict[int, int] = {n: 0 for n in nodes}
    for src, targets in edges.items():
        for dst in targets:
            indegree[dst] = indegree.get(dst, 0) + 1

    roots_with_choices = [n for n in sorted(nodes) if indegree.get(n, 0) == 0 and len(edges.get(n, [])) > 0]
    if roots_with_choices:
        return roots_with_choices

    # Fallback if the graph is noisy and has no clean roots.
    return sorted(n for n in nodes if len(edges.get(n, [])) > 0)


def enumerate_paths(
    start_nodes: List[int],
    edges: Dict[int, List[int]],
    max_decisions: int,
) -> List[Tuple[List[int], str]]:
    """Return list of (path, reason) where reason is end/cycle/max-depth."""

    results: List[Tuple[List[int], str]] = []

    def dfs(path: List[int], decision_points: int) -> None:
        current = path[-1]
        next_nodes = edges.get(current, [])

        if not next_nodes:
            results.append((path[:], "end"))
            return

        if decision_points > max_decisions:
            results.append((path[:], "max-decisions"))
            return

        next_decision_points = decision_points + (1 if len(next_nodes) > 1 else 0)
        if next_decision_points > max_decisions:
            results.append((path[:], "max-decisions"))
            return

        for nxt in next_nodes:
            if nxt in path:
                results.append((path + [nxt], "cycle"))
                continue
            dfs(path + [nxt], next_decision_points)

    for start in start_nodes:
        dfs([start], 0)

    return results


def render_story(path: List[int], page_texts: Dict[int, str], reason: str) -> str:
    lines: List[str] = []
    lines.append("Path: " + " -> ".join(str(p) for p in path))
    lines.append("")

    for idx, page in enumerate(path, start=1):
        lines.append(f"=== Step {idx}: Page {page} ===")
        lines.append(page_texts.get(page, f"Page {page}\n\n[Missing page text]"))
        lines.append("")

    if reason != "end":
        lines.append(f"[Path terminated by: {reason}]")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    paths: List[Tuple[List[int], str]],
    page_texts: Dict[int, str],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear old generated stories so each run is a clean snapshot.
    for old_story in output_dir.glob("story-*.txt"):
        old_story.unlink()

    manifest: List[dict] = []

    for idx, (path, reason) in enumerate(paths, start=1):
        filename = f"story-{idx:04d}.txt"
        content = render_story(path, page_texts, reason)
        (output_dir / filename).write_text(content, encoding="utf-8")

        manifest.append(
            {
                "file": filename,
                "path": path,
                "end_reason": reason,
                "start_page": path[0],
                "end_page": path[-1],
                "length": len(path),
            }
        )

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate all possible full story texts from page graph.")
    parser.add_argument(
        "--graph",
        type=Path,
        default=Path("output/cot-story-graph.mmd"),
        help="Mermaid graph file path.",
    )
    parser.add_argument(
        "--pages-dir",
        type=Path,
        default=Path("output/cot-pages-ocr-v2"),
        help="Directory containing page text files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/cot-stories"),
        help="Output directory for generated story files.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        action="append",
        default=[],
        help="Optional start page. Repeat for multiple start pages.",
    )
    parser.add_argument(
        "--max-decisions",
        type=int,
        default=20,
        help="Maximum number of decision points before truncating a path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.graph.exists():
        raise FileNotFoundError(f"Graph file not found: {args.graph}")
    if not args.pages_dir.exists():
        raise FileNotFoundError(f"Pages directory not found: {args.pages_dir}")
    if args.max_decisions < 1:
        raise ValueError("--max-decisions must be >= 1")

    nodes, edges = parse_graph(args.graph)
    if not nodes:
        raise RuntimeError("No graph nodes found. Check graph input file.")

    page_texts = parse_page_texts(args.pages_dir)

    # If requested start page is missing from the extracted graph, add it from page text.
    if args.start_page:
        for start_page in args.start_page:
            if start_page not in nodes and start_page in page_texts:
                nodes.add(start_page)
                edges.setdefault(start_page, parse_links_from_page_text(page_texts[start_page]))
            elif start_page in nodes and not edges.get(start_page) and start_page in page_texts:
                edges[start_page] = parse_links_from_page_text(page_texts[start_page])

            for target in edges.get(start_page, []):
                nodes.add(target)
                edges.setdefault(target, [])

    starts = choose_start_nodes(nodes, edges, args.start_page)
    if not starts:
        raise RuntimeError("No valid start pages found.")

    paths = enumerate_paths(starts, edges, args.max_decisions)
    write_outputs(paths, page_texts, args.output_dir)

    print(f"Graph nodes: {len(nodes)}")
    print(f"Start pages: {', '.join(str(s) for s in starts)}")
    print(f"Generated stories: {len(paths)}")
    print(f"Output directory: {args.output_dir}")


if __name__ == "__main__":
    main()
