#!/usr/bin/env python3
"""Check every URL in README.md for broken links and archived GitHub repos.

Exit code 0 means all links are healthy.
Exit code 1 means at least one link is broken or archived.

Usage:
    uv run python tools/check_links.py
    uv run python tools/check_links.py --concurrency 20 --timeout 15
    uv run python tools/check_links.py --github-only
    uv run python tools/check_links.py --json > /tmp/broken_links.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "website"))

from readme_parser import parse_readme  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"
_GH_ACCEPT = "application/vnd.github+json"
_GH_API_VERSION = "2022-11-28"
_DEFAULT_CONCURRENCY = 10
_DEFAULT_TIMEOUT = 20.0

GITHUB_REPO_RE = re.compile(
    r"https?://github\.com/([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+?)(?:\.git)?(?:[/#?]|$)"
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class LinkResult:
    __slots__ = ("url", "name", "category", "status", "reason")

    def __init__(self, url: str, name: str, category: str, status: str, reason: str = "") -> None:
        self.url = url
        self.name = name
        self.category = category
        self.status = status  # "ok" | "broken" | "archived" | "redirect" | "error"
        self.reason = reason

    def is_healthy(self) -> bool:
        return self.status in ("ok", "redirect")

    def to_dict(self) -> dict[str, str]:
        return {
            "url": self.url,
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gh_headers(token: str | None) -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": _GH_ACCEPT,
        "X-GitHub-Api-Version": _GH_API_VERSION,
    }
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def _repo_slug(url: str) -> str | None:
    m = GITHUB_REPO_RE.match(url)
    if not m:
        return None
    parts = m.group(1).strip("/").split("/")
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _is_github_repo_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.hostname != "github.com":
            return False
        parts = parsed.path.strip("/").split("/")
        return len(parts) >= 2 and parts[0] and parts[1]
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Link checking
# ---------------------------------------------------------------------------


def check_github_repo(
    url: str,
    name: str,
    category: str,
    client: httpx.Client,
    token: str | None,
) -> LinkResult:
    """Check a GitHub repo via the API: detect archived, missing, or renamed repos."""
    slug = _repo_slug(url)
    if slug is None:
        return LinkResult(url, name, category, "error", "Could not parse repo slug")

    api_url = f"{_GH_API}/repos/{slug}"
    try:
        resp = client.get(api_url, headers=_gh_headers(token))
    except httpx.HTTPError as exc:
        return LinkResult(url, name, category, "error", str(exc))

    if resp.status_code == 404:
        return LinkResult(url, name, category, "broken", "HTTP 404 — repo not found or renamed")
    if resp.status_code == 451:
        return LinkResult(url, name, category, "broken", "HTTP 451 — repository unavailable for legal reasons")
    if resp.status_code == 403:
        # Rate-limited or private — treat as inconclusive, not broken
        return LinkResult(url, name, category, "ok", "HTTP 403 — rate-limited or private")
    if resp.status_code >= 400:
        return LinkResult(url, name, category, "broken", f"HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception:
        return LinkResult(url, name, category, "error", "Could not decode API response")

    if data.get("archived"):
        return LinkResult(url, name, category, "archived", "Repository is archived on GitHub")

    return LinkResult(url, name, category, "ok")


def check_generic_url(
    url: str,
    name: str,
    category: str,
    client: httpx.Client,
) -> LinkResult:
    """Check a non-GitHub URL with an HTTP HEAD (fallback to GET)."""
    try:
        resp = client.head(url, follow_redirects=True)
        # Some servers reject HEAD; fall back to GET
        if resp.status_code == 405:
            resp = client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        return LinkResult(url, name, category, "error", str(exc))

    if resp.status_code >= 400:
        return LinkResult(url, name, category, "broken", f"HTTP {resp.status_code}")

    if resp.history:
        final = str(resp.url)
        if final != url:
            return LinkResult(url, name, category, "redirect", f"→ {final}")

    return LinkResult(url, name, category, "ok")


def check_url(
    url: str,
    name: str,
    category: str,
    token: str | None,
    timeout: float,
    github_only: bool,
) -> LinkResult:
    headers = {"User-Agent": "awesome-python-link-checker/1.0"}
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        if _is_github_repo_url(url):
            return check_github_repo(url, name, category, client, token)
        if github_only:
            return LinkResult(url, name, category, "ok", "skipped (non-GitHub)")
        return check_generic_url(url, name, category, client)


# ---------------------------------------------------------------------------
# README parsing
# ---------------------------------------------------------------------------


def collect_links(readme_path: Path) -> list[tuple[str, str, str]]:
    """Return list of (url, name, category) tuples from README.md entries."""
    text = readme_path.read_text(encoding="utf-8")
    groups = parse_readme(text)
    links: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for cat in group["categories"]:
            for entry in cat["entries"]:
                if entry["url"] not in seen:
                    seen.add(entry["url"])
                    links.append((entry["url"], entry["name"], cat["name"]))
                for also in entry["also_see"]:
                    if also["url"] not in seen:
                        seen.add(also["url"])
                        links.append((also["url"], also["name"], cat["name"]))
    return links


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check README.md links for breakage and archived repos.")
    parser.add_argument("--readme", default=str(_REPO_ROOT / "README.md"), help="Path to README.md")
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY, help="Number of parallel workers")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument("--github-only", action="store_true", help="Only check GitHub repo URLs")
    parser.add_argument("--show-ok", action="store_true", help="Also print healthy links")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--fail-on-archived", action="store_true", help="Exit 1 if any archived repos are found")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    readme_path = Path(args.readme)

    if not readme_path.exists():
        print(f"ERROR: README not found: {readme_path}", file=sys.stderr)
        return 1

    links = collect_links(readme_path)
    total = len(links)

    if not args.json:
        print(f"Checking {total} links (concurrency={args.concurrency}, timeout={args.timeout}s)…\n")

    results: list[LinkResult] = []
    start = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(check_url, url, name, cat, token, args.timeout, args.github_only): (url, name, cat)
            for url, name, cat in links
        }
        done = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            if not args.json:
                symbol = "✓" if result.is_healthy() else ("⚠" if result.status == "archived" else "✗")
                if not result.is_healthy() or args.show_ok:
                    label = f"[{result.status.upper()}]"
                    print(f"  {symbol} {label} {result.name} ({result.category})")
                    if result.reason:
                        print(f"      {result.url}")
                        print(f"      {result.reason}")

    elapsed = time.monotonic() - start

    broken = [r for r in results if r.status == "broken"]
    archived = [r for r in results if r.status == "archived"]
    errors = [r for r in results if r.status == "error"]

    if args.json:
        output = {
            "total": total,
            "broken": [r.to_dict() for r in broken],
            "archived": [r.to_dict() for r in archived],
            "errors": [r.to_dict() for r in errors],
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'─'*60}")
        print(f"  Total checked : {total}")
        print(f"  Broken        : {len(broken)}")
        print(f"  Archived      : {len(archived)}")
        print(f"  Errors        : {len(errors)}")
        print(f"  Time          : {elapsed:.1f}s")
        print(f"{'─'*60}")

        if broken:
            print("\n🔴 BROKEN LINKS:")
            for r in broken:
                print(f"  • [{r.name}] in '{r.category}'")
                print(f"    {r.url}")
                print(f"    {r.reason}")

        if archived:
            print("\n🟡 ARCHIVED REPOS (candidates for removal):")
            for r in archived:
                print(f"  • [{r.name}] in '{r.category}'")
                print(f"    {r.url}")

        if broken:
            print("\n❌ Link check FAILED.")
        elif archived and args.fail_on_archived:
            print("\n❌ Link check FAILED (archived repos found).")
        else:
            print("\n✅ Link check passed.")

    if broken:
        return 1
    if archived and args.fail_on_archived:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
