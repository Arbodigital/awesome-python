-include .env
export

install:
	uv sync --locked

fetch_github_stars:
	uv run python website/fetch_github_stars.py

test:
	uv run pytest website/tests/ -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run ty check website

build:
	uv run python website/build.py

tree:
	uv run python tools/print_tree.py

scout:
	uv run python tools/forum_scout.py

add-entry:
	uv run python tools/auto_add_entry.py $(ARGS)

check-links:
	uv run python tools/check_links.py $(ARGS)

check-order:
	uv run python tools/check_order.py $(ARGS)

fix-order:
	uv run python tools/check_order.py --fix

preview: build
	uv run watchmedo shell-command \
		--patterns='*.md;*.html;*.css;*.js;*.py' \
		--recursive \
		--wait --drop \
		--command='uv run python website/build.py' \
		README.md website/templates website/static website/data & \
	python -m http.server -b 127.0.0.1 -d website/output/ 8000
