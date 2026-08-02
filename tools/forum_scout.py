#!/usr/bin/env python3
"""Search forums for Python projects not yet listed in awesome-python.

Sources:
  - Reddit: r/Python, r/learnpython (top posts for a given timeframe)
  - Hacker News: Algolia search API (Show HN / Ask HN posts mentioning Python)

Usage:
    uv run python tools/forum_scout.py
    uv run python tools/forum_scout.py --timeframe week
    uv run python tools/forum_scout.py --subreddits Python django --limit 200
    uv run python tools/forum_scout.py --hn-query "python library" --no-reddit
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

# Make website/ importable for readme_parser
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "website"))

import httpx
from readme_parser import parse_readme

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

GITHUB_REPO_RE = re.compile(
    r"https?://github\.com/([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+?)(?:\.git)?(?:[/#?]|$)"
)

_HEADERS = {"User-Agent": "awesome-python-scout/1.0 (https://github.com/vinta/awesome-python)"}
_TIMEOUT = 15.0


class Candidate(TypedDict):
    name: str
    github_url: str
    source: str
    score: int
    post_url: str
    post_title: str
    suggested_category: str


# ---------------------------------------------------------------------------
# Load existing README entries
# ---------------------------------------------------------------------------


def _normalise_github_url(url: str) -> str:
    """Normalise a GitHub URL to 'github.com/owner/repo' (lowercase, no trailing slash)."""
    m = GITHUB_REPO_RE.match(url)
    if not m:
        return url.rstrip("/").lower()
    return f"github.com/{m.group(1).lower()}"


def load_existing_github_urls(readme_path: Path) -> set[str]:
    """Return normalised GitHub URLs already listed in README.md."""
    text = readme_path.read_text(encoding="utf-8")
    groups = parse_readme(text)
    seen: set[str] = set()
    for group in groups:
        for cat in group["categories"]:
            for entry in cat["entries"]:
                if "github.com" in entry["url"]:
                    seen.add(_normalise_github_url(entry["url"]))
                for also in entry["also_see"]:
                    if "github.com" in also["url"]:
                        seen.add(_normalise_github_url(also["url"]))
    return seen


def load_category_names(readme_path: Path) -> list[str]:
    """Return all category names from README.md for suggested-category matching."""
    text = readme_path.read_text(encoding="utf-8")
    groups = parse_readme(text)
    return [cat["name"] for group in groups for cat in group["categories"]]


# ---------------------------------------------------------------------------
# Suggest a category by keyword matching
# ---------------------------------------------------------------------------

_KEYWORD_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bweb\b|\bhttp\b|\bdjango\b|\bflask\b|\bfastapi\b|\baiohttp\b", re.IGNORECASE), "Web Frameworks"),
    (re.compile(r"\brest\b|\bapi\b", re.IGNORECASE), "RESTful API"),
    (re.compile(r"\bml\b|\bmachine.?learn\b|\bneural\b|\bdeep.?learn\b|\btorch\b|\btensor\b", re.IGNORECASE), "Machine Learning"),
    (re.compile(r"\bdata.?science\b|\bpandas\b|\bnumpy\b|\banalytic\b", re.IGNORECASE), "Data Analysis"),
    (re.compile(r"\bviz\b|\bvisual\b|\bchart\b|\bplot\b|\bgraph\b|\bmatplotlib\b|\bseaborn\b", re.IGNORECASE), "Data Visualization"),
    (re.compile(r"\bdatabas\b|\borm\b|\bsql\b|\bmongo\b|\bpostgres\b|\bmysql\b", re.IGNORECASE), "Database"),
    (re.compile(r"\btest\b|\bpytest\b|\bmock\b|\bfixture\b", re.IGNORECASE), "Testing"),
    (re.compile(r"\bcli\b|\bcommand.?line\b|\bterminal\b|\bshell\b|\brich\b|\btextual\b", re.IGNORECASE), "Command-line Interface Development"),
    (re.compile(r"\basync\b|\basyncio\b|\bconcurren\b|\bthread\b|\bparallel\b", re.IGNORECASE), "Concurrency and Parallelism"),
    (re.compile(r"\bsecur\b|\bcrypt\b|\bauth\b|\bpassword\b|\bjwt\b|\boauth\b", re.IGNORECASE), "Authentication"),
    (re.compile(r"\bscrap\b|\bcrawl\b|\bspider\b|\bbeautiful.?soup\b|\bscrapy\b", re.IGNORECASE), "Web Crawling and Web Scraping"),
    (re.compile(r"\bimage\b|\bvideo\b|\baudio\b|\bmedia\b|\bpillow\b|\bopencv\b", re.IGNORECASE), "Computer Vision"),
    (re.compile(r"\bdevops\b|\bdocker\b|\bkubernetes\b|\bdeploy\b|\bci\b|\bcd\b", re.IGNORECASE), "DevOps Tools"),
    (re.compile(r"\bserializ\b|\bjson\b|\byaml\b|\btoml\b|\bxml\b|\bpars\b", re.IGNORECASE), "Data Formats"),
    (re.compile(r"\blog\b|\bmonitor\b|\bobserv\b|\bmetric\b|\btrac\b", re.IGNORECASE), "Logging"),
    (re.compile(r"\bgame\b|\bpygame\b|\bargame\b", re.IGNORECASE), "Game Development"),
    (re.compile(r"\bnlp\b|\bnatural.?language\b|\btext\b|\bllm\b|\bgpt\b", re.IGNORECASE), "Natural Language Processing"),
    (re.compile(r"\bnetwork\b|\bsocket\b|\btcp\b|\budp\b|\bssh\b|\bftp\b", re.IGNORECASE), "Network"),
    (re.compile(r"\bgui\b|\bdesktop\b|\btkinter\b|\bqt\b|\bwx\b", re.IGNORECASE), "GUI Development"),
]


def suggest_category(title: str, body: str, category_names: list[str]) -> str:
    """Return the most likely category name based on keyword matching."""
    combined = f"{title} {body}"
    for pattern, cat in _KEYWORD_MAP:
        if pattern.search(combined):
            # Confirm the category exists in the README
            for name in category_names:
                if cat.lower() in name.lower() or name.lower() in cat.lower():
                    return name
            return cat
    return "—"


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------


def fetch_reddit(subreddits: list[str], timeframe: str, limit: int) -> list[Candidate]:
    """Fetch top posts from the given subreddits via the Reddit JSON API."""
    candidates: list[Candidate] = []
    with httpx.Client(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        for sub in subreddits:
            url = f"https://www.reddit.com/r/{sub}/top.json?t={timeframe}&limit={min(limit, 100)}"
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"  [reddit] Warning: could not fetch r/{sub}: {exc}", file=sys.stderr)
                continue

            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                p = post.get("data", {})
                title: str = p.get("title", "")
                selftext: str = p.get("selftext", "")
                post_url: str = f"https://www.reddit.com{p.get('permalink', '')}"
                score: int = p.get("score", 0)
                linked_url: str = p.get("url", "")

                # Extract GitHub repos from the post URL, title, and body
                repos = _extract_github_repos(f"{linked_url} {title} {selftext}")
                for repo_url in repos:
                    candidates.append(
                        Candidate(
                            name=_repo_name(repo_url),
                            github_url=repo_url,
                            source=f"r/{sub}",
                            score=score,
                            post_url=post_url,
                            post_title=title,
                            suggested_category="",
                        )
                    )
    return candidates


# ---------------------------------------------------------------------------
# Hacker News (Algolia API)
# ---------------------------------------------------------------------------


def fetch_hn(query: str, limit: int) -> list[Candidate]:
    """Fetch Show HN / Ask HN posts mentioning Python via the Algolia HN API."""
    candidates: list[Candidate] = []
    url = "https://hn.algolia.com/api/v1/search"
    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": min(limit, 100),
    }
    with httpx.Client(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"  [hn] Warning: could not fetch HN results: {exc}", file=sys.stderr)
            return []

        data = resp.json()
        hits = data.get("hits", [])
        for hit in hits:
            title: str = hit.get("title", "")
            story_url: str = hit.get("url", "") or ""
            object_id: str = hit.get("objectID", "")
            score: int = hit.get("points") or 0
            post_url = f"https://news.ycombinator.com/item?id={object_id}"

            repos = _extract_github_repos(f"{story_url} {title}")
            for repo_url in repos:
                candidates.append(
                    Candidate(
                        name=_repo_name(repo_url),
                        github_url=repo_url,
                        source="HN",
                        score=score,
                        post_url=post_url,
                        post_title=title,
                        suggested_category="",
                    )
                )
    return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_github_repos(text: str) -> list[str]:
    """Extract unique canonical GitHub repo URLs from text."""
    seen: set[str] = set()
    results: list[str] = []
    for m in GITHUB_REPO_RE.finditer(text):
        key = m.group(1).lower()
        if key not in seen:
            seen.add(key)
            results.append(f"https://github.com/{m.group(1)}")
    return results


def _repo_name(github_url: str) -> str:
    """Return the 'owner/repo' part of a GitHub URL."""
    parts = urlparse(github_url).path.strip("/").split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else github_url


def _dedup_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Deduplicate by normalised GitHub URL, keeping highest score."""
    best: dict[str, Candidate] = {}
    for c in candidates:
        key = _normalise_github_url(c["github_url"])
        if key not in best or c["score"] > best[key]["score"]:
            best[key] = c
    return sorted(best.values(), key=lambda c: c["score"], reverse=True)


def _filter_known(candidates: list[Candidate], known: set[str]) -> list[Candidate]:
    return [c for c in candidates if _normalise_github_url(c["github_url"]) not in known]


def _skip_repo(github_url: str) -> bool:
    """Return True for URLs that are clearly not library/tool repos."""
    path = urlparse(github_url).path.strip("/").lower()
    parts = path.split("/")
    if len(parts) < 2:
        return True
    # Skip awesome-lists, .github meta-repos
    repo = parts[1]
    return repo.startswith("awesome-") or repo == ".github"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _print_report(candidates: list[Candidate]) -> None:
    if not candidates:
        print("No new candidates found.")
        return

    print(f"## Forum Scout Report — {len(candidates)} candidate(s)\n")
    print(f"{'#':<3}  {'Score':>5}  {'Source':<15}  {'Repo':<40}  {'Suggested Category':<30}  Title")
    print("-" * 140)
    for i, c in enumerate(candidates, 1):
        repo = _repo_name(c["github_url"])
        title = c["post_title"][:60] + ("…" if len(c["post_title"]) > 60 else "")
        cat = c["suggested_category"] or "—"
        print(f"{i:<3}  {c['score']:>5}  {c['source']:<15}  {repo:<40}  {cat:<30}  {title}")
    print()
    print("### Details\n")
    for i, c in enumerate(candidates, 1):
        print(f"#### {i}. {c['name']}")
        print(f"- **GitHub**: {c['github_url']}")
        print(f"- **Source**: {c['source']} (score: {c['score']})")
        print(f"- **Post**: [{c['post_title']}]({c['post_url']})")
        print(f"- **Suggested category**: {c['suggested_category'] or '—'}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scout Reddit and Hacker News for Python projects not yet in awesome-python."
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=_REPO_ROOT / "README.md",
        help="Path to README.md (default: repo root)",
    )
    parser.add_argument(
        "--subreddits",
        nargs="+",
        default=["Python", "learnpython"],
        metavar="SUB",
        help="Subreddits to search (default: Python learnpython)",
    )
    parser.add_argument(
        "--timeframe",
        choices=["hour", "day", "week", "month", "year", "all"],
        default="month",
        help="Reddit timeframe for top posts (default: month)",
    )
    parser.add_argument(
        "--hn-query",
        default="show hn python",
        metavar="QUERY",
        help="Hacker News search query (default: 'show hn python')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum posts to fetch per source (default: 100)",
    )
    parser.add_argument(
        "--no-reddit",
        action="store_true",
        help="Skip Reddit sources",
    )
    parser.add_argument(
        "--no-hn",
        action="store_true",
        help="Skip Hacker News source",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=10,
        help="Minimum post score to include (default: 10)",
    )
    args = parser.parse_args(argv)

    if not args.readme.exists():
        print(f"Error: README not found at {args.readme}", file=sys.stderr)
        return 1

    print("Loading existing entries from README.md…", file=sys.stderr)
    known_urls = load_existing_github_urls(args.readme)
    category_names = load_category_names(args.readme)
    print(f"  {len(known_urls)} existing GitHub URLs loaded.", file=sys.stderr)

    candidates: list[Candidate] = []

    if not args.no_reddit:
        print(f"Fetching Reddit ({', '.join('r/' + s for s in args.subreddits)}, timeframe={args.timeframe})…", file=sys.stderr)
        candidates.extend(fetch_reddit(args.subreddits, args.timeframe, args.limit))

    if not args.no_hn:
        print(f"Fetching Hacker News (query='{args.hn_query}')…", file=sys.stderr)
        candidates.extend(fetch_hn(args.hn_query, args.limit))

    print(f"Raw candidates: {len(candidates)}", file=sys.stderr)

    # Filter and deduplicate
    candidates = [c for c in candidates if not _skip_repo(c["github_url"])]
    candidates = _filter_known(candidates, known_urls)
    candidates = _dedup_candidates(candidates)
    candidates = [c for c in candidates if c["score"] >= args.min_score]

    # Suggest categories
    for c in candidates:
        c["suggested_category"] = suggest_category(c["post_title"], "", category_names)

    print(f"New candidates after filtering: {len(candidates)}", file=sys.stderr)
    print(file=sys.stderr)

    _print_report(candidates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
