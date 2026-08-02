#!/usr/bin/env python3
"""Print the awesome-python category tree from README.md.

Usage:
    uv run python tools/print_tree.py
    uv run python tools/print_tree.py --json
    uv run python tools/print_tree.py --category web-frameworks
    uv run python tools/print_tree.py --stats
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make website/ importable for readme_parser
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "website"))

from readme_parser import ParsedGroup, parse_readme


def _load_groups(readme_path: Path) -> list[ParsedGroup]:
    text = readme_path.read_text(encoding="utf-8")
    return parse_readme(text)


def _print_tree(groups: list[ParsedGroup], *, show_entries: bool = True) -> None:
    total_cats = sum(len(g["categories"]) for g in groups)
    total_entries = sum(c["entry_count"] for g in groups for c in g["categories"])
    print(f"awesome-python — {len(groups)} groups, {total_cats} categories, {total_entries} entries\n")

    for group in groups:
        print(f"┌─ {group['name']}  [{group['slug']}]")
        cats = group["categories"]
        for ci, cat in enumerate(cats):
            is_last_cat = ci == len(cats) - 1
            cat_prefix = "└─" if is_last_cat else "├─"
            child_indent = "   " if is_last_cat else "│  "
            desc = f"  — {cat['description']}" if cat["description"] else ""
            print(f"│  {cat_prefix} {cat['name']}  ({cat['entry_count']}){desc}")
            if show_entries:
                entries = cat["entries"]
                for ei, entry in enumerate(entries):
                    is_last_entry = ei == len(entries) - 1
                    entry_prefix = "└─" if is_last_entry else "├─"
                    subcat = f"  [{entry['subcategory']}]" if entry["subcategory"] else ""
                    also = f"  (+{len(entry['also_see'])} also-see)" if entry["also_see"] else ""
                    print(f"│  {child_indent} {entry_prefix} {entry['name']}{subcat}{also}")
                    print(f"│  {child_indent} {'   ' if is_last_entry else '│  '} {entry['url']}")
        print("│")


def _print_stats(groups: list[ParsedGroup]) -> None:
    total_entries = sum(c["entry_count"] for g in groups for c in g["categories"])
    total_cats = sum(len(g["categories"]) for g in groups)
    print(f"Groups    : {len(groups)}")
    print(f"Categories: {total_cats}")
    print(f"Entries   : {total_entries}")
    print()
    for group in groups:
        group_entries = sum(c["entry_count"] for c in group["categories"])
        print(f"  {group['name']}  ({len(group['categories'])} cats, {group_entries} entries)")
        for cat in group["categories"]:
            print(f"    {cat['name']:40s}  {cat['entry_count']:4d} entries")


def _filter_category(groups: list[ParsedGroup], slug: str) -> list[ParsedGroup]:
    result: list[ParsedGroup] = []
    for group in groups:
        matched = [c for c in group["categories"] if c["slug"] == slug or c["name"].lower() == slug.lower()]
        if matched:
            result.append(ParsedGroup(name=group["name"], slug=group["slug"], categories=matched))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the awesome-python category tree.")
    parser.add_argument(
        "--readme",
        type=Path,
        default=_REPO_ROOT / "README.md",
        help="Path to README.md (default: repo root)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output the full tree as JSON",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print summary statistics only",
    )
    parser.add_argument(
        "--category",
        metavar="SLUG_OR_NAME",
        help="Filter output to a single category by slug or name",
    )
    parser.add_argument(
        "--no-entries",
        action="store_true",
        help="Show only groups and categories, not individual entries",
    )
    args = parser.parse_args(argv)

    if not args.readme.exists():
        print(f"Error: README not found at {args.readme}", file=sys.stderr)
        return 1

    groups = _load_groups(args.readme)

    if args.category:
        groups = _filter_category(groups, args.category)
        if not groups:
            print(f"Error: no category matching '{args.category}' found.", file=sys.stderr)
            return 1

    if args.as_json:
        print(json.dumps(groups, indent=2, ensure_ascii=False))
        return 0

    if args.stats:
        _print_stats(groups)
        return 0

    _print_tree(groups, show_entries=not args.no_entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
