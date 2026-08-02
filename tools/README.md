# Maintenance Tools

Scripts for curators and maintainers of awesome-python.

---

## `print_tree.py` — Category Tree Viewer

Reads `README.md` via the existing `readme_parser` and prints the full
hierarchy of groups → categories → entries.  Useful for quickly auditing
the structure, checking alphabetical order, or exporting the catalogue as
JSON for other tooling.

### Usage

```bash
# Full ASCII tree (all entries)
uv run python tools/print_tree.py

# Summary statistics only
uv run python tools/print_tree.py --stats

# Groups and categories without individual entries
uv run python tools/print_tree.py --no-entries

# Filter to a single category (by name or slug)
uv run python tools/print_tree.py --category "Web Frameworks"
uv run python tools/print_tree.py --category web-frameworks

# Export the full tree as JSON
uv run python tools/print_tree.py --json > /tmp/tree.json

# Point at a different README
uv run python tools/print_tree.py --readme /path/to/README.md
```

### Output example

```
awesome-python — 14 groups, 72 categories, 573 entries

┌─ Web Development  [web-development]
│  ├─ Web Frameworks  (16)  — Traditional full stack web frameworks.
│  │   ├─ django  [Synchronous]  (+1 also-see)
│  │   │   https://github.com/django/django
│  │   └─ flask  [Synchronous]  (+1 also-see)
│  │       https://github.com/pallets/flask
│  └─ Web APIs  (11)  — Libraries for building RESTful and GraphQL APIs.
│      └─ …
```

---

## `forum_scout.py` — Forum Scout

Searches Reddit and Hacker News for Python projects that are not yet
listed in awesome-python.  It extracts GitHub repository URLs from
highly-voted posts, deduplicates them against the entries already in
`README.md`, and prints a Markdown report of candidates with a suggested
category for each one.

**The script never edits `README.md` automatically.**  All additions
remain a human decision.

### Usage

```bash
# Default: Reddit (r/Python + r/learnpython, last month) + Hacker News
uv run python tools/forum_scout.py

# Shorter timeframe
uv run python tools/forum_scout.py --timeframe week

# Custom subreddits
uv run python tools/forum_scout.py --subreddits Python django asyncio

# Custom HN query
uv run python tools/forum_scout.py --hn-query "python library 2025"

# Reddit only / HN only
uv run python tools/forum_scout.py --no-hn
uv run python tools/forum_scout.py --no-reddit

# Raise the quality bar (only posts with score ≥ 50)
uv run python tools/forum_scout.py --min-score 50

# Save the report to a file
uv run python tools/forum_scout.py > /tmp/scout_report.md

# All options
uv run python tools/forum_scout.py --help
```

### Full workflow

```
1.  Run the scout:
      make scout
    or
      uv run python tools/forum_scout.py --timeframe week > /tmp/report.md

2.  Open the report and review the candidates:
      open /tmp/report.md   # macOS
      xdg-open /tmp/report.md   # Linux

3.  For each project you want to add, check CONTRIBUTING.md:
      - Is it Python-first, active, and documented?
      - Does it meet the star / quality threshold?
      - Is it already listed under a different name?

4.  Add the entry to README.md in the correct category,
    in alphabetical order, following the standard format:
      - [package-name](https://github.com/owner/repo) - One-line description.

5.  Open a PR with the single new entry.
```

### Output example

```
## Forum Scout Report — 5 candidate(s)

#   Score  Source           Repo                        Suggested Category        Title
1    892   r/Python         pallets/click               Command-line Inter...      Show HN: Click 9.0 released
2    541   HN               encode/httpx                HTTP Clients               Show HN: HTTPX — async HTTP client
…

### Details

#### 1. pallets/click
- **GitHub**: https://github.com/pallets/click
- **Source**: r/Python (score: 892)
- **Post**: [Show HN: Click 9.0 released](https://reddit.com/r/…)
- **Suggested category**: Command-line Interface Development
```

---

## Make targets

| Command      | Description                                      |
|-------------|--------------------------------------------------|
| `make tree`  | Print the full category tree from `README.md`    |
| `make scout` | Run the forum scout with default settings        |

---

## Dependencies

Both scripts use only libraries already declared in `pyproject.toml`
(`httpx`, `markdown-it-py`).  Install them with:

```bash
make install
# or
uv sync --locked
```
