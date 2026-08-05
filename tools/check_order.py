#!/usr/bin/env python3
"""Validate that entries within every README.md category are in alphabetical order.

Exit code 0 means all categories are correctly sorted.
Exit code 1 means at least one category has out-of-order entries.

Usage:
    uv run python tools/check_order.py
    uv run python tools/check_order.py --fix          # auto-sort and overwrite README.md
    uv run python tools/check_order.py --json         # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "website"))

# ---------------------------------------------------------------------------
# Patterns (mirror auto_add_entry.py conventions)
# ---------------------------------------------------------------------------

_FLAT_ENTRY_RE = re.compile(r"^(- \[([^\]]+)\].*)$")
_SUBCAT_ENTRY_RE = re.compile(r"^(  - \[([^\]]+)\].*)$")
_SUBCAT_LABEL_RE = re.compile(r"^- ([^\[(\s].+?)\s*$")
_SECTION_RE = re.compile(r"^### (.+?)\s*$")
_GROUP_RE = re.compile(r"^\*\*([A-Z].+?)\*\*\s*$")
_NEXT_SECTION_RE = re.compile(r"^(#{1,3} |\*\*[A-Z])")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    category: str
    subcategory: str | None
    entry: str
    expected_before: str
    line_number: int  # 1-based

    def message(self) -> str:
        scope = f"{self.category}" + (f" > {self.subcategory}" if self.subcategory else "")
        return (
            f"Line {self.line_number}: [{self.entry}] should come before [{self.expected_before}]"
            f" in '{scope}'"
        )


@dataclass
class CategoryResult:
    name: str
    violations: list[Violation] = field(default_factory=list)

    def is_sorted(self) -> bool:
        return not self.violations


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _find_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return list of (category_name, first_content_line, last_content_line) — exclusive end."""
    sections: list[tuple[str, int, int]] = []
    i = 0
    while i < len(lines):
        m = _SECTION_RE.match(lines[i])
        if m:
            name = m.group(1)
            start = i + 1
            end = len(lines)
            for j in range(start, len(lines)):
                if _NEXT_SECTION_RE.match(lines[j]) and j != start:
                    end = j
                    break
            sections.append((name, start, end))
        i += 1
    return sections


def _check_flat_entries(lines: list[str], start: int, end: int, category: str) -> list[Violation]:
    """Check flat (non-subcategorized) entries for alphabetical order."""
    violations: list[Violation] = []
    entries: list[tuple[int, str]] = []  # (line_index, name_lower)

    for i in range(start, end):
        m = _FLAT_ENTRY_RE.match(lines[i])
        if m:
            entries.append((i, m.group(2).lower()))

    for idx, (line_i, name) in enumerate(entries):
        if idx > 0 and name < entries[idx - 1][1]:
            violations.append(
                Violation(
                    category=category,
                    subcategory=None,
                    entry=name,
                    expected_before=entries[idx - 1][1],
                    line_number=line_i + 1,
                )
            )
    return violations


def _check_subcategorized_entries(
    lines: list[str], start: int, end: int, category: str
) -> list[Violation]:
    """Check entries within each subcategory block."""
    violations: list[Violation] = []

    # Collect subcategory blocks
    subcat_blocks: list[tuple[str, int, int]] = []
    current_label: str | None = None
    current_start: int | None = None

    for i in range(start, end):
        m = _SUBCAT_LABEL_RE.match(lines[i])
        if m and not _FLAT_ENTRY_RE.match(lines[i]):
            # Close previous block
            if current_label is not None and current_start is not None:
                subcat_blocks.append((current_label, current_start, i))
            current_label = m.group(1)
            current_start = i + 1
    if current_label is not None and current_start is not None:
        subcat_blocks.append((current_label, current_start, end))

    for label, s, e in subcat_blocks:
        entries: list[tuple[int, str]] = []
        for i in range(s, e):
            m = _SUBCAT_ENTRY_RE.match(lines[i])
            if m:
                entries.append((i, m.group(2).lower()))
        for idx, (line_i, name) in enumerate(entries):
            if idx > 0 and name < entries[idx - 1][1]:
                violations.append(
                    Violation(
                        category=category,
                        subcategory=label,
                        entry=name,
                        expected_before=entries[idx - 1][1],
                        line_number=line_i + 1,
                    )
                )
    return violations


def _has_subcategories(lines: list[str], start: int, end: int) -> bool:
    return any(_SUBCAT_LABEL_RE.match(lines[i]) and not _FLAT_ENTRY_RE.match(lines[i]) for i in range(start, end))


def check_readme_order(readme_path: Path) -> list[CategoryResult]:
    """Return list of CategoryResult for every section in README.md."""
    lines = readme_path.read_text(encoding="utf-8").splitlines()
    sections = _find_sections(lines)
    results: list[CategoryResult] = []

    for name, start, end in sections:
        result = CategoryResult(name=name)
        if _has_subcategories(lines, start, end):
            result.violations = _check_subcategorized_entries(lines, start, end, name)
        else:
            result.violations = _check_flat_entries(lines, start, end, name)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Auto-fix: sort entries in place
# ---------------------------------------------------------------------------


def _sort_flat_section(lines: list[str], start: int, end: int) -> list[str]:
    """Return lines with flat entries sorted alphabetically within [start, end)."""
    entry_indices = [i for i in range(start, end) if _FLAT_ENTRY_RE.match(lines[i])]
    if not entry_indices:
        return lines

    sorted_entries = sorted(entry_indices, key=lambda i: re.match(r"- \[([^\]]+)\]", lines[i]).group(1).lower())  # type: ignore[union-attr]

    new_lines = list(lines)
    for new_idx, old_idx in zip(entry_indices, sorted_entries):
        new_lines[new_idx] = lines[old_idx]
    return new_lines


def _sort_subcategorized_section(lines: list[str], start: int, end: int) -> list[str]:
    """Return lines with each subcategory's entries sorted alphabetically."""
    subcat_blocks: list[tuple[int, int]] = []
    current_start: int | None = None

    for i in range(start, end):
        m = _SUBCAT_LABEL_RE.match(lines[i])
        if m and not _FLAT_ENTRY_RE.match(lines[i]):
            if current_start is not None:
                subcat_blocks.append((current_start, i))
            current_start = i + 1
    if current_start is not None:
        subcat_blocks.append((current_start, end))

    new_lines = list(lines)
    for s, e in subcat_blocks:
        entry_indices = [i for i in range(s, e) if _SUBCAT_ENTRY_RE.match(new_lines[i])]
        if not entry_indices:
            continue
        sorted_entries = sorted(
            entry_indices,
            key=lambda i: re.match(r"  - \[([^\]]+)\]", new_lines[i]).group(1).lower(),  # type: ignore[union-attr]
        )
        orig_entries = list(entry_indices)
        for new_idx, old_idx in zip(orig_entries, sorted_entries):
            new_lines[new_idx] = lines[old_idx]
    return new_lines


def fix_readme_order(readme_path: Path) -> int:
    """Sort entries in every section. Return number of sections fixed."""
    text = readme_path.read_text(encoding="utf-8")
    # Detect and preserve the original line-ending style.
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    sections = _find_sections(lines)
    fixed = 0

    for name, start, end in sections:
        if _has_subcategories(lines, start, end):
            new_lines = _sort_subcategorized_section(lines, start, end)
        else:
            new_lines = _sort_flat_section(lines, start, end)

        if new_lines != lines:
            lines = new_lines
            fixed += 1

    readme_path.write_text(newline.join(lines) + newline, encoding="utf-8")
    return fixed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate alphabetical order of README.md entries.")
    parser.add_argument("--readme", default=str(_REPO_ROOT / "README.md"), help="Path to README.md")
    parser.add_argument("--fix", action="store_true", help="Auto-sort entries and overwrite README.md")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args(argv)

    readme_path = Path(args.readme)
    if not readme_path.exists():
        print(f"ERROR: README not found: {readme_path}", file=sys.stderr)
        return 1

    if args.fix:
        fixed = fix_readme_order(readme_path)
        if args.json:
            print(json.dumps({"fixed_sections": fixed}))
        else:
            print(f"✅ Fixed ordering in {fixed} section(s).")
        return 0

    results = check_readme_order(readme_path)
    all_violations = [v for r in results for v in r.violations]

    if args.json:
        output = [
            {
                "category": r.name,
                "violations": [
                    {
                        "entry": v.entry,
                        "expected_before": v.expected_before,
                        "subcategory": v.subcategory,
                        "line": v.line_number,
                    }
                    for v in r.violations
                ],
            }
            for r in results
            if not r.is_sorted()
        ]
        print(json.dumps(output, indent=2))
    else:
        if all_violations:
            print(f"❌ Found {len(all_violations)} ordering violation(s):\n")
            for r in results:
                if not r.is_sorted():
                    for v in r.violations:
                        print(f"  {v.message()}")
            print("\nRun with --fix to auto-sort the README.")
        else:
            print("✅ All categories are correctly sorted.")

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())
