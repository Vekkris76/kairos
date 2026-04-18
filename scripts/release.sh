#!/usr/bin/env bash
# release.sh — Kairos pre-release gate + local publish fallback.
#
# This script exists because manually running `uv publish` led to the
# 0.3.2 → 0.3.3 double-release on 2026-04-18: a kwarg the downstream
# needed shipped without me catching it pre-publish. This script
# enforces the pre-ship invariants before any `uv publish` call.
#
# Primary path for future releases is GitHub Actions trusted
# publishing (see .github/workflows/release.yml). This script remains
# as the manual fallback + local dry-run tool.
#
# Usage:
#   scripts/release.sh                         # full gate + build (no publish)
#   scripts/release.sh --publish               # full gate + build + publish to PyPI
#   scripts/release.sh --publish --test-pypi   # publish to TestPyPI instead
#
# Environment:
#   UV_PUBLISH_TOKEN    — PyPI token (or TestPyPI if --test-pypi). When
#                         unset and `~/.pypirc` exists, this script
#                         extracts the token from the appropriate
#                         section. Prefer exporting the env var
#                         yourself for stronger auditability.

set -euo pipefail

PUBLISH=false
PUBLISH_INDEX="pypi"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --publish)
            PUBLISH=true
            shift
            ;;
        --test-pypi)
            PUBLISH_INDEX="testpypi"
            shift
            ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

red()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# ── 1. Extract version from pyproject.toml ──────────────────────

VERSION=$(uv run --quiet python -c '
import tomllib
with open("pyproject.toml", "rb") as f:
    print(tomllib.load(f)["project"]["version"])
')
echo "→ version: $VERSION"

# ── 2. CHANGELOG gate — an entry for this version must exist ────

if ! grep -qE "^## \[$VERSION\]" CHANGELOG.md; then
    red "✗ CHANGELOG.md has no '## [$VERSION]' entry"
    red "   Add one before releasing. Example: '## [$VERSION] — $(date +%Y-%m-%d) — *summary*'"
    exit 1
fi
green "✓ CHANGELOG entry present for $VERSION"

# ── 3. Working tree clean (don't ship uncommitted changes) ──────

if ! git diff --quiet || ! git diff --cached --quiet; then
    red "✗ Working tree has uncommitted changes. Commit or stash first."
    git status --short
    exit 1
fi
green "✓ working tree clean"

# ── 4. Full test suite green ────────────────────────────────────

echo "→ running pytest (full suite)"
if ! uv run pytest -q; then
    red "✗ test suite failed. Fix before shipping $VERSION."
    exit 1
fi
green "✓ test suite green"

# ── 5. Build wheel + sdist ──────────────────────────────────────

rm -rf dist/
echo "→ building distribution artifacts"
uv build >/dev/null
WHEEL=$(ls dist/kairos_engine-"$VERSION"-*.whl 2>/dev/null | head -1)
SDIST=$(ls dist/kairos_engine-"$VERSION"*.tar.gz 2>/dev/null | head -1)
if [[ -z "$WHEEL" || -z "$SDIST" ]]; then
    red "✗ Expected kairos_engine-$VERSION{.whl,.tar.gz} in dist/"
    ls dist/
    exit 1
fi
green "✓ built $(basename "$WHEEL") + $(basename "$SDIST")"

# ── 6. twine check — validate metadata ──────────────────────────

echo "→ twine check"
if ! uv run --with twine twine check "$WHEEL" "$SDIST"; then
    red "✗ twine check failed. Fix metadata before publishing."
    exit 1
fi
green "✓ twine check passed"

# ── 7. Publish (opt-in) ─────────────────────────────────────────

if [[ "$PUBLISH" != "true" ]]; then
    green "All gates passed. Dry run complete."
    echo
    echo "To publish to PyPI:      scripts/release.sh --publish"
    echo "To publish to TestPyPI:  scripts/release.sh --publish --test-pypi"
    exit 0
fi

# Resolve the token
if [[ -z "${UV_PUBLISH_TOKEN:-}" ]]; then
    if [[ -f "$HOME/.pypirc" ]]; then
        SECTION="pypi"
        if [[ "$PUBLISH_INDEX" == "testpypi" ]]; then
            SECTION="testpypi"
        fi
        # Extract password line from the [pypi] / [testpypi] section
        TOKEN=$(awk -v sec="[$SECTION]" '
            $0 == sec { f=1; next }
            /^\[/ { f=0 }
            f && $1 == "password" { print $3; exit }
        ' "$HOME/.pypirc")
        if [[ -n "$TOKEN" ]]; then
            export UV_PUBLISH_TOKEN="$TOKEN"
            echo "→ using token from ~/.pypirc [$SECTION]"
        fi
    fi
fi

if [[ -z "${UV_PUBLISH_TOKEN:-}" ]]; then
    red "✗ No PyPI token available."
    red "   Set UV_PUBLISH_TOKEN env var or add a [$SECTION] section to ~/.pypirc."
    exit 1
fi

# Tag gate — the current commit must be tagged v<version>
if ! git rev-parse "v$VERSION" >/dev/null 2>&1; then
    red "✗ No tag 'v$VERSION' exists. Tag the release first:"
    red "     git tag v$VERSION && git push origin v$VERSION"
    exit 1
fi
TAG_COMMIT=$(git rev-parse "v$VERSION")
HEAD_COMMIT=$(git rev-parse HEAD)
if [[ "$TAG_COMMIT" != "$HEAD_COMMIT" ]]; then
    red "✗ Tag v$VERSION points at $TAG_COMMIT but HEAD is $HEAD_COMMIT."
    red "   Re-tag or checkout the tagged commit before publishing."
    exit 1
fi
green "✓ tag v$VERSION matches HEAD"

# Publish
echo "→ publishing to $PUBLISH_INDEX"
if [[ "$PUBLISH_INDEX" == "testpypi" ]]; then
    uv publish --publish-url "https://test.pypi.org/legacy/" "$WHEEL" "$SDIST"
else
    uv publish "$WHEEL" "$SDIST"
fi

green "✓ published kairos-engine $VERSION to $PUBLISH_INDEX"
echo
echo "Verify at: https://pypi.org/project/kairos-engine/$VERSION/"
