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

#   Score   Stars  Source           Repo                        Suggested Category        Title
1    892    1,234  r/Python         pallets/click               Command-line Inter...      Show HN: Click 9.0 released
2    541    8,900  HN               encode/httpx                HTTP Clients               Show HN: HTTPX — async HTTP client
…

### Details

#### 1. pallets/click
- **GitHub**: https://github.com/pallets/click
- **Stars**: 1,234
- **Last commit**: 2025-06-15
- **Source**: r/Python (score: 892)
- **Post**: [Show HN: Click 9.0 released](https://reddit.com/r/…)
- **Suggested category**: Command-line Interface Development
```

---

## `auto_add_entry.py` — README Entry Inserter

Inserts a new entry into `README.md` at the correct **alphabetical position**
within the target category.  Also supports creating draft PRs automatically
via the GitHub API when paired with `forum_scout --json` output.

### Usage (single entry)

```bash
# Fetch description from GitHub automatically
make add-entry ARGS="--github-url https://github.com/owner/repo --category 'Web Frameworks'"

# Specify everything explicitly
make add-entry ARGS="--github-url https://github.com/owner/repo \
  --category 'Web Frameworks' --name mylib --description 'A great framework.'"

# Preview without writing
make add-entry ARGS="--github-url https://github.com/owner/repo \
  --category 'Web Frameworks' --dry-run"

# Subcategorized section
make add-entry ARGS="--github-url https://github.com/owner/repo \
  --category 'CLI Development' --subcategory 'CLI Development' \
  --description 'A CLI tool.'"
```

### Usage (batch + auto PR)

```bash
# 1. Discover candidates and enrich with GitHub data
uv run python tools/forum_scout.py \
    --timeframe week \
    --enrich --min-stars 500 \
    --json > /tmp/candidates.json

# 2a. Preview candidates (no writes)
uv run python tools/auto_add_entry.py \
    --from-scout /tmp/candidates.json --dry-run

# 2b. Create draft PRs for every qualifying candidate
uv run python tools/auto_add_entry.py \
    --from-scout /tmp/candidates.json \
    --min-stars 500 \
    --create-prs
```

The `--create-prs` flag uses the GitHub REST API (via `GITHUB_TOKEN`) to:
1. Create a new branch `auto-scout/{owner}-{repo}`
2. Commit the README change to that branch
3. Open a **draft pull request** against the default branch

All auto-generated PRs require human review before merging.

---

## `check_links.py` — Link Health Checker

Iterates every URL in `README.md` and checks for broken links and archived
GitHub repositories.  GitHub repos are verified via the API (detecting 404,
archived status, and legal takedowns).  Non-GitHub URLs are checked with HTTP
HEAD/GET requests.

### Usage

```bash
# Check all links (GitHub + generic URLs)
make check-links

# Check only GitHub repo URLs (faster, no rate-limit concerns for other hosts)
make check-links ARGS="--github-only"

# Increase concurrency and reduce timeout for speed
make check-links ARGS="--concurrency 20 --timeout 10"

# Also fail if any archived repos are found
make check-links ARGS="--fail-on-archived"

# Machine-readable JSON output
make check-links ARGS="--json" > /tmp/broken_links.json

# Full options
uv run python tools/check_links.py --help
```

Set `GITHUB_TOKEN` in your environment to increase API rate limits from
60 to 5,000 requests/hour.

### Output example

```
Checking 612 links (concurrency=10, timeout=20.0s)…

  ✗ [BROKEN] awesome-lib (Data Formats)
      https://github.com/old-owner/awesome-lib
      HTTP 404 — repo not found or renamed
  ⚠ [ARCHIVED] legacy-tool (Networking)
      https://github.com/author/legacy-tool
      Repository is archived on GitHub

────────────────────────────────────────────────────────────
  Total checked : 612
  Broken        : 1
  Archived      : 1
  Errors        : 0
  Time          : 14.3s
────────────────────────────────────────────────────────────
```

---

## `check_order.py` — Alphabetical Order Validator

Validates that every entry within each category (and subcategory) of
`README.md` is in strict alphabetical order.  This check runs automatically
in CI on every pull request, so out-of-order entries are caught before merge.

### Usage

```bash
# Validate and report violations
make check-order

# Auto-sort and overwrite README.md
make fix-order

# Machine-readable output
make check-order ARGS="--json"

# Full options
uv run python tools/check_order.py --help
```

### Output example

```
❌ Found 2 ordering violation(s):

  Line 412: [zope] should come before [zxcvbn] in 'Authentication'
  Line 1087: [werkzeug] should come before [whitenoise] in 'Web Frameworks'

Run with --fix to auto-sort the README.
```

---

| Command              | Description                                              |
|----------------------|----------------------------------------------------------|
| `make tree`          | Print the full category tree from `README.md`            |
| `make scout`         | Run the forum scout with default settings                |
| `make add-entry`     | Insert a single entry (pass options via `ARGS=`)         |
| `make check-links`   | Check all URLs for broken links and archived repos       |
| `make check-order`   | Validate alphabetical ordering within every category     |
| `make fix-order`     | Auto-sort entries in place and overwrite `README.md`     |

---

## Automated weekly workflow

`.github/workflows/auto-scout.yml` runs every Monday at 09:00 UTC.  It:

1. Runs `forum_scout.py --enrich --min-stars 500` to collect candidates
2. Calls `auto_add_entry.py --create-prs` to open draft PRs
3. Can also be triggered manually via **Actions → Auto Scout → Run workflow**

---

## Dependencies

All scripts use only libraries already declared in `pyproject.toml`
(`httpx`, `markdown-it-py`).  Install them with:

```bash
make install
# or
uv sync --locked
```
