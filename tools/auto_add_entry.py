#!/usr/bin/env python3
"""Insert a new entry into README.md at the correct alphabetical position.

Usage (single entry — description fetched from GitHub if omitted):
    uv run python tools/auto_add_entry.py \\
        --github-url https://github.com/owner/repo \\
        --category "Web Frameworks"

    uv run python tools/auto_add_entry.py \\
        --github-url https://github.com/owner/repo \\
        --category "Web Frameworks" \\
        --name mylib --description "A great framework." \\
        --dry-run

Usage (subcategorized section):
    uv run python tools/auto_add_entry.py \\
        --github-url https://github.com/owner/repo \\
        --category "CLI Development" \\
        --subcategory "CLI Development" \\
        --description "A CLI tool."

Usage (batch from forum_scout --json output):
    uv run python tools/forum_scout.py --enrich --min-stars 500 --json \\
        > /tmp/candidates.json
    uv run python tools/auto_add_entry.py \\
        --from-scout /tmp/candidates.json \\
        [--min-stars 500] [--dry-run] [--create-prs]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# README manipulation
# ---------------------------------------------------------------------------

_FLAT_ENTRY_RE = re.compile(r"^- \[([^\]]+)\]")
_SUBCAT_ENTRY_RE = re.compile(r"^  - \[([^\]]+)\]")
_SUBCAT_LABEL_RE = re.compile(r"^- ([^\[(\s].+?)\s*$")
_NEXT_SECTION_RE = re.compile(r"^(#{1,3} |\*\*[A-Z])")


def _find_section_bounds(lines: list[str], category: str) -> tuple[int, int]:
    """Return (first_line_after_heading, first_line_of_next_section)."""
    pat = re.compile(rf"^### {re.escape(category)}\s*$")
    start: int | None = None
    for i, line in enumerate(lines):
        if pat.match(line):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"Section '### {category}' not found in README.md")
    end = len(lines)
    for i in range(start, len(lines)):
        if _NEXT_SECTION_RE.match(lines[i]):
            end = i
            break
    return start, end


def _has_subcategories(lines: list[str], start: int, end: int) -> bool:
    return any(_SUBCAT_LABEL_RE.match(lines[i]) for i in range(start, end))


def _extract_name(line: str) -> str | None:
    """Extract display name from '- [name](...)' (leading whitespace already stripped)."""
    m = re.match(r"^- \[([^\]]+)\]", line)
    return m.group(1) if m else None


def _flat_insert_pos(lines: list[str], start: int, end: int, new_name: str) -> int:
    """Return the line index at which to insert the new flat entry."""
    entries = [
        (i, _FLAT_ENTRY_RE.match(lines[i]).group(1).lower())  # type: ignore[union-attr]
        for i in range(start, end)
        if _FLAT_ENTRY_RE.match(lines[i])
    ]
    if not entries:
        # No entries yet — insert after description/blank lines
        for i in range(start, end):
            s = lines[i].strip()
            if s and not s.startswith("_"):
                return i
        return end
    new_lower = new_name.lower()
    for pos, name in entries:
        if new_lower <= name:
            return pos
    return entries[-1][0] + 1


def _subcategory_insert_pos(
    lines: list[str],
    start: int,
    end: int,
    subcategory: str,
    new_name: str,
) -> int:
    """Return the line index at which to insert the new subcategory entry."""
    label_pat = re.compile(rf"^- {re.escape(subcategory)}\s*$")
    subcat_start: int | None = None
    for i in range(start, end):
        if label_pat.match(lines[i]):
            subcat_start = i + 1
            break
    if subcat_start is None:
        raise ValueError(f"Subcategory '- {subcategory}' not found in section")

    subcat_end = end
    for i in range(subcat_start, end):
        if _SUBCAT_LABEL_RE.match(lines[i]):
            subcat_end = i
            break

    entries = [
        (i, _SUBCAT_ENTRY_RE.match(lines[i]).group(1).lower())  # type: ignore[union-attr]
        for i in range(subcat_start, subcat_end)
        if _SUBCAT_ENTRY_RE.match(lines[i])
    ]
    if not entries:
        return subcat_start
    new_lower = new_name.lower()
    for pos, name in entries:
        if new_lower <= name:
            return pos
    return entries[-1][0] + 1


def insert_entry_into_readme(
    readme_text: str,
    entry_line: str,
    category: str,
    subcategory: str | None = None,
) -> str:
    """Return README text with entry_line inserted alphabetically.

    Raises ValueError if:
    - The category is not found.
    - The entry name already exists in the section.
    - The section has subcategories and *subcategory* is None.
    - The subcategory is specified but not found.
    """
    lines = readme_text.splitlines(keepends=True)
    start, end = _find_section_bounds(lines, category)

    # Duplicate check
    new_name = _extract_name(entry_line.lstrip())
    if new_name:
        for i in range(start, end):
            existing = _extract_name(lines[i].lstrip())
            if existing and existing.lower() == new_name.lower():
                raise ValueError(f"Entry '{new_name}' already exists in '{category}'")

    if subcategory is not None:
        # Ensure proper indentation for subcategory entries
        stripped = entry_line.lstrip()
        if not stripped.startswith("- ["):
            raise ValueError(f"entry_line must start with '- [': {entry_line!r}")
        entry_line = "  " + stripped
        insert_at = _subcategory_insert_pos(lines, start, end, subcategory, new_name or "")
    else:
        if _has_subcategories(lines, start, end):
            raise ValueError(
                f"Section '{category}' uses subcategories. "
                "Use --subcategory to target a specific one."
            )
        insert_at = _flat_insert_pos(lines, start, end, new_name or "")

    if not entry_line.endswith("\n"):
        entry_line += "\n"
    lines.insert(insert_at, entry_line)
    return "".join(lines)


# ---------------------------------------------------------------------------
# Entry formatting
# ---------------------------------------------------------------------------


def format_entry_line(
    github_url: str,
    name: str | None = None,
    description: str | None = None,
) -> str:
    """Return a formatted README entry line."""
    if name is None:
        name = github_url.rstrip("/").split("/")[-1]
    desc = (description or "").strip()
    if desc and not desc.endswith("."):
        desc += "."
    return f"- [{name}]({github_url}) - {desc}" if desc else f"- [{name}]({github_url})"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"
_GH_ACCEPT = "application/vnd.github+json"
_GH_API_VERSION = "2022-11-28"
_TIMEOUT = 30.0


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Accept": _GH_ACCEPT,
        "X-GitHub-Api-Version": _GH_API_VERSION,
    }


def _repo_slug(github_url: str) -> str:
    """Return 'owner/repo' from a GitHub URL."""
    parts = urlparse(github_url).path.strip("/").split("/")
    return "/".join(parts[:2])


def fetch_github_repo_info(github_url: str, token: str | None = None) -> dict[str, str | int]:
    """Return a dict with 'name', 'description', 'stars', 'last_commit_date'."""
    slug = _repo_slug(github_url)
    headers: dict[str, str] = {"Accept": _GH_ACCEPT, "X-GitHub-Api-Version": _GH_API_VERSION}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with httpx.Client(headers=headers, timeout=_TIMEOUT) as client:
            resp = client.get(f"{_GH_API}/repos/{slug}")
            resp.raise_for_status()
            data = resp.json()
            pushed_at: str = data.get("pushed_at") or ""
            return {
                "name": data.get("name", slug.split("/")[-1]),
                "description": (data.get("description") or "").strip(),
                "stars": data.get("stargazers_count", 0),
                "last_commit_date": pushed_at[:10] if pushed_at else "",
            }
    except httpx.HTTPError:
        return {
            "name": slug.split("/")[-1],
            "description": "",
            "stars": 0,
            "last_commit_date": "",
        }


def _detect_github_repo() -> str:
    """Return 'owner/repo' for the current checkout (via env var or git remote)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        return repo
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    url = result.stdout.strip()
    m = re.search(r"github\.com[/:](.+?/.+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def _detect_base_branch() -> str:
    """Return the default/base branch name for this checkout."""
    # In GitHub Actions (push/schedule), GITHUB_REF_NAME is the triggering branch
    name = os.environ.get("GITHUB_REF_NAME", "")
    if name and name not in ("HEAD", ""):
        return name
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    if result.returncode == 0:
        return result.stdout.strip().split("/")[-1]
    return "master"


# ---------------------------------------------------------------------------
# PR creation via GitHub REST API
# ---------------------------------------------------------------------------


def _format_pr_body(
    candidate: dict[str, object],
    entry_line: str,
    category: str,
) -> str:
    github_url = str(candidate.get("github_url", ""))
    stars = int(candidate.get("stars", 0) or 0)
    score = int(candidate.get("score", 0) or 0)
    source = str(candidate.get("source", "") or "")
    post_url = str(candidate.get("post_url", "") or "")
    post_title = str(candidate.get("post_title", "") or "")
    last_commit = str(candidate.get("last_commit_date", "") or "")
    description = str(candidate.get("description", "") or "")
    repo_name = github_url.rstrip("/").split("/")[-1]

    justify_parts = ["Auto-discovered by forum scout."]
    if stars:
        justify_parts.append(f"GitHub stars: {stars:,}.")
    if description:
        justify_parts.append(description if description.endswith(".") else description + ".")
    if source and score:
        justify_parts.append(f"Source: {source} (score: {score}).")
    if post_title and post_url:
        justify_parts.append(f"Post: [{post_title}]({post_url}).")
    if last_commit:
        justify_parts.append(f"Last commit: {last_commit}.")
    justification = " ".join(justify_parts)

    return f"""\
## Project

[{repo_name}]({github_url})

## Checklist

- [x] One project per PR
- [x] PR title format: `Add project-name`
- [x] Entry format: `- [project-name](url) - Description ending with period.`
- [x] Description is concise and short

## Why This Project Is Awesome

Which criterion does it meet? (pick one)

- [ ] **Industry Standard** - The go-to tool for a specific use case
- [ ] **Rising Star** - 5000+ stars in < 2 years, significant adoption
- [ ] **Hidden Gem** - Exceptional quality, solves niche problems elegantly

Explain:
{justification}

Suggested category: **{category}**

Proposed entry:
```
{entry_line.strip()}
```

## How It Differs

_Auto-generated draft PR. Requires human review and approval before merging._
"""


def _create_pr_via_api(
    candidate: dict[str, object],
    entry_line: str,
    new_readme_text: str,
    category: str,
    github_repo: str,
    base_branch: str,
    token: str,
) -> str | None:
    """Create branch + commit + draft PR via GitHub REST API. Returns PR URL or None."""
    github_url = str(candidate.get("github_url", ""))
    slug = _repo_slug(github_url)
    branch_name = "auto-scout/" + slug.replace("/", "-")
    pypi_name = str(candidate.get("pypi_name") or slug.split("/")[-1])

    headers = _gh_headers(token)

    with httpx.Client(headers=headers, timeout=_TIMEOUT) as client:
        # Check the branch doesn't already exist
        r = client.get(f"{_GH_API}/repos/{github_repo}/branches/{branch_name}")
        if r.status_code == 200:
            print(f"  [skip] branch '{branch_name}' already exists", file=sys.stderr)
            return None

        # Get HEAD SHA of the base branch
        r = client.get(f"{_GH_API}/repos/{github_repo}/git/ref/heads/{base_branch}")
        r.raise_for_status()
        head_sha: str = r.json()["object"]["sha"]

        # Create the new branch
        r = client.post(
            f"{_GH_API}/repos/{github_repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": head_sha},
        )
        r.raise_for_status()

        # Get the current README file SHA (required for updates)
        r = client.get(
            f"{_GH_API}/repos/{github_repo}/contents/README.md",
            params={"ref": base_branch},
        )
        r.raise_for_status()
        file_sha: str = r.json()["sha"]

        # Commit the updated README to the new branch
        content_b64 = base64.b64encode(new_readme_text.encode("utf-8")).decode()
        r = client.put(
            f"{_GH_API}/repos/{github_repo}/contents/README.md",
            json={
                "message": f"Add {pypi_name}",
                "content": content_b64,
                "sha": file_sha,
                "branch": branch_name,
            },
        )
        r.raise_for_status()

        # Create the draft PR
        pr_body = _format_pr_body(candidate, entry_line, category)
        r = client.post(
            f"{_GH_API}/repos/{github_repo}/pulls",
            json={
                "title": f"Add {pypi_name}",
                "body": pr_body,
                "head": branch_name,
                "base": base_branch,
                "draft": True,
            },
        )
        r.raise_for_status()
        return str(r.json()["html_url"])


# ---------------------------------------------------------------------------
# Batch processing (from forum_scout --json output)
# ---------------------------------------------------------------------------


def process_scout_candidates(
    candidates: list[dict[str, object]],
    readme_path: Path,
    min_stars: int = 0,
    dry_run: bool = False,
    create_prs: bool = False,
    github_token: str | None = None,
) -> int:
    """Process a list of scout candidates. Returns exit code (0 = ok, 1 = errors)."""
    readme_text = readme_path.read_text(encoding="utf-8")
    github_repo = _detect_github_repo()
    base_branch = _detect_base_branch()
    exit_code = 0

    added = skipped = errors = 0

    for candidate in candidates:
        github_url = str(candidate.get("github_url", "")).strip()
        if not github_url:
            skipped += 1
            continue

        slug = _repo_slug(github_url)

        stars = int(candidate.get("stars", 0) or 0)
        if min_stars > 0 and stars < min_stars:
            print(f"  [skip] {slug}: {stars} stars < {min_stars}", file=sys.stderr)
            skipped += 1
            continue

        category = str(candidate.get("suggested_category") or "").strip()
        if not category or category == "—":
            print(f"  [skip] {slug}: no suggested category", file=sys.stderr)
            skipped += 1
            continue

        desc = str(candidate.get("description") or "").strip()
        if not desc:
            desc = f"See {github_url}."
        if not desc.endswith("."):
            desc += "."

        pypi_name = slug.split("/")[-1]
        candidate["pypi_name"] = pypi_name
        entry_line = f"- [{pypi_name}]({github_url}) - {desc}"

        try:
            new_readme_text = insert_entry_into_readme(readme_text, entry_line, category)
        except ValueError as exc:
            print(f"  [skip] {slug}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        if dry_run:
            print(f"\n{'='*60}")
            print(f"  [dry-run] {slug} → '{category}'")
            print(f"  {entry_line}")
            added += 1
            continue

        if create_prs:
            if not github_token:
                print("  [error] --create-prs requires GITHUB_TOKEN", file=sys.stderr)
                errors += 1
                exit_code = 1
                continue
            if not github_repo:
                print("  [error] cannot determine GitHub repository", file=sys.stderr)
                errors += 1
                exit_code = 1
                continue
            try:
                pr_url = _create_pr_via_api(
                    candidate=candidate,
                    entry_line=entry_line,
                    new_readme_text=new_readme_text,
                    category=category,
                    github_repo=github_repo,
                    base_branch=base_branch,
                    token=github_token,
                )
                if pr_url:
                    print(f"  [ok] PR created: {pr_url}", file=sys.stderr)
                    added += 1
                else:
                    skipped += 1
            except httpx.HTTPError as exc:
                print(f"  [error] {slug}: {exc}", file=sys.stderr)
                errors += 1
                exit_code = 1
        else:
            # Write directly (manual batch without PR creation)
            readme_path.write_text(new_readme_text, encoding="utf-8")
            readme_text = new_readme_text
            print(f"  [ok] Added '{pypi_name}' to '{category}'", file=sys.stderr)
            added += 1

    print(
        f"\nDone: {added} added, {skipped} skipped, {errors} errors.",
        file=sys.stderr,
    )
    return exit_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Insert a new entry into README.md at the correct alphabetical position.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=_REPO_ROOT / "README.md",
        help="Path to README.md (default: repo root)",
    )

    single = parser.add_argument_group("single-entry mode")
    single.add_argument("--github-url", metavar="URL", help="GitHub URL of the project")
    single.add_argument("--category", metavar="NAME", help="Target category in README.md")
    single.add_argument(
        "--subcategory",
        metavar="NAME",
        help="Target subcategory label (for subcategorized sections)",
    )
    single.add_argument(
        "--name",
        metavar="NAME",
        help="Display/PyPI name (default: GitHub repo name)",
    )
    single.add_argument(
        "--description",
        metavar="TEXT",
        help="Entry description (fetched from GitHub if omitted)",
    )

    batch = parser.add_argument_group("batch mode (from forum_scout --json)")
    batch.add_argument(
        "--from-scout",
        metavar="FILE",
        help="JSON file produced by 'forum_scout --json'",
    )
    batch.add_argument(
        "--min-stars",
        type=int,
        default=0,
        metavar="N",
        help="Minimum stars required (default: 0)",
    )
    batch.add_argument(
        "--create-prs",
        action="store_true",
        help="Create a draft PR for each candidate via GitHub API",
    )
    batch.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN"),
        metavar="TOKEN",
        help="GitHub API token for --create-prs (default: $GITHUB_TOKEN)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without modifying README.md or creating PRs",
    )

    args = parser.parse_args(argv)

    if not args.readme.exists():
        print(f"Error: README not found at {args.readme}", file=sys.stderr)
        return 1

    # ---- Batch mode --------------------------------------------------------
    if args.from_scout:
        scout_path = Path(args.from_scout)
        if not scout_path.exists():
            print(f"Error: scout file not found: {scout_path}", file=sys.stderr)
            return 1
        candidates: list[dict[str, object]] = json.loads(
            scout_path.read_text(encoding="utf-8")
        )
        return process_scout_candidates(
            candidates=candidates,
            readme_path=args.readme,
            min_stars=args.min_stars,
            dry_run=args.dry_run,
            create_prs=args.create_prs,
            github_token=args.github_token,
        )

    # ---- Single-entry mode -------------------------------------------------
    if not args.github_url or not args.category:
        parser.error(
            "--github-url and --category are required "
            "(or use --from-scout for batch mode)"
        )

    description = args.description
    name = args.name
    if description is None or name is None:
        print("Fetching GitHub repo info…", file=sys.stderr)
        info = fetch_github_repo_info(args.github_url, args.github_token)
        if description is None:
            description = str(info.get("description", ""))
        if name is None:
            name = str(info.get("name", ""))

    if not description:
        print(
            "Warning: no description found. Use --description to set one.",
            file=sys.stderr,
        )

    entry_line = format_entry_line(args.github_url, name=name or None, description=description or None)

    readme_text = args.readme.read_text(encoding="utf-8")
    try:
        new_text = insert_entry_into_readme(
            readme_text, entry_line, args.category, args.subcategory
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Would insert into '{args.category}':")
        print(f"  {entry_line}")
        return 0

    args.readme.write_text(new_text, encoding="utf-8")
    print(f"Added '{name}' to '{args.category}' in {args.readme.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
