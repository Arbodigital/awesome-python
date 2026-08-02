#!/usr/bin/env python3
"""Collect, store, and verify help links for Leiameoffchr."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")


def canonicalize(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def parse_markdown_links(markdown_path: Path) -> list[str]:
    text = markdown_path.read_text(encoding="utf-8")
    links = [canonicalize(match) for match in URL_PATTERN.findall(text)]
    unique_links = sorted(set(links))
    return unique_links


def load_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {"product": "chrome", "version": "v1", "sources": []}
    return json.loads(index_path.read_text(encoding="utf-8"))


def next_id(existing_sources: list[dict], prefix: str = "chrome") -> str:
    numbers = []
    for source in existing_sources:
        source_id = str(source.get("id", ""))
        if source_id.startswith(f"{prefix}-"):
            number = source_id.removeprefix(f"{prefix}-")
            if number.isdigit():
                numbers.append(int(number))
    value = (max(numbers) + 1) if numbers else 1
    return f"{prefix}-{value:04d}"


def sync_sources(links_path: Path, index_path: Path, language: str = "en") -> tuple[int, int]:
    links = parse_markdown_links(links_path)
    index = load_index(index_path)
    sources = index.setdefault("sources", [])

    existing_urls = {canonicalize(str(item.get("url", ""))): item for item in sources}
    added = 0
    for link in links:
        if link in existing_urls:
            continue
        sources.append(
            {
                "id": next_id(sources),
                "url": link,
                "title": "",
                "language": language,
                "topic": "",
                "status": "to_review",
            }
        )
        added += 1

    sorted_sources = sorted(sources, key=lambda item: canonicalize(str(item.get("url", ""))))
    index["sources"] = sorted_sources
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(links), added


def check_missing(links_path: Path, index_path: Path) -> tuple[list[str], list[str]]:
    markdown_links = set(parse_markdown_links(links_path))
    index = load_index(index_path)
    index_links = {canonicalize(str(item.get("url", ""))) for item in index.get("sources", []) if item.get("url")}

    missing_in_index = sorted(markdown_links - index_links)
    stale_in_index = sorted(index_links - markdown_links)
    return missing_in_index, stale_in_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Leiameoffchr source links.")
    parser.add_argument("--links", type=Path, required=True, help="Path to markdown file with source links.")
    parser.add_argument("--index", type=Path, required=True, help="Path to source index JSON file.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync", help="Collect links and store new entries in index.")
    sync_parser.add_argument("--language", default="en", help="Default language for new sources.")

    subparsers.add_parser("check", help="Verify missing/stale links between markdown and index.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "sync":
        total, added = sync_sources(args.links, args.index, language=args.language)
        print(f"Total links found: {total}")
        print(f"New links added to index: {added}")
        return 0

    missing_in_index, stale_in_index = check_missing(args.links, args.index)
    if missing_in_index:
        print("Missing in index:")
        for item in missing_in_index:
            print(f"- {item}")
    if stale_in_index:
        print("Stale in index (not present in links file):")
        for item in stale_in_index:
            print(f"- {item}")
    if not missing_in_index and not stale_in_index:
        print("No gaps found. Links and index are aligned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
