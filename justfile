default: install lint test

# Install/refresh deps: upgrade the lockfile, sync every extra + the lint group.
install:
    uv lock --upgrade
    uv sync --all-extras --frozen --group lint

# Autofix lint: eof-fixer, ruff format, ruff check --fix, ty type-check.
lint:
    uv run eof-fixer .
    uv run ruff format
    uv run ruff check --fix
    uv run ty check

# CI lint (no autofix): same checks as `lint` without mutating the tree.
lint-ci:
    uv run eof-fixer . --check
    uv run ruff format --check
    uv run ruff check --no-fix
    uv run ty check

adr_check_source := "https://raw.githubusercontent.com/modern-python/.github/main/tests/test_adr_citations.py"

# Tracks main on purpose: the shared check is unpinned.
adr-check:
    #!/usr/bin/env sh
    set -eu
    dir="$(mktemp -d .adr-check.XXXXXX)"
    trap 'rm -rf "$dir"' EXIT
    curl -fsSL "{{ adr_check_source }}" -o "$dir/test_adr_citations.py"
    uv run --no-sync pytest --rootdir=. --noconftest -o addopts= "$dir/test_adr_citations.py"

# Run pytest with NO coverage (targeted runs won't trip the gate). Passes args through.
test *args:
    uv run --no-sync pytest {{ args }}

# The gated full run: 100% line coverage required. CI runs this.
test-ci:
    uv run --no-sync pytest --cov=release_scope --cov-report term-missing --cov-report xml

# Browser smoke test of the page against a report from the CLI scenario; installs Chromium on first run.
test-smoke *args:
    uv run --no-sync playwright install chromium
    uv run --no-sync pytest -m smoke {{ args }}

# Build the demo site into site/: the real CLI collects the made-up scenario in demo/scenario.py.
demo:
    uv run --no-sync python -m demo.build site

# Build the demo and save site/screenshot.png, the image the README shows; installs Chromium on first run.
demo-screenshot: demo
    uv run --no-sync playwright install chromium
    uv run --no-sync python -m demo.screenshot site

# Build the demo and serve it at http://127.0.0.1:8000.
demo-serve: demo
    uv run --no-sync python -m http.server 8000 --bind 127.0.0.1 --directory site

# Branch-coverage run (diagnostic; line coverage is the enforced gate, not branch).
test-branch:
    uv run --no-sync pytest --cov=release_scope --cov-branch

# Build + publish to PyPI. Version comes from the git tag ($GITHUB_REF_NAME); no pyproject bump.
# Auth via PyPI Trusted Publishing (OIDC); uv publish auto-detects the CI id-token.
publish:
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish
