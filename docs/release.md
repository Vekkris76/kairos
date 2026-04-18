# Releasing Kairos to PyPI

## Primary path — GitHub Actions trusted publishing

Since 2026-04-18 releases publish via GitHub Actions OIDC trusted
publishing. No PyPI token stored on disk, no token handling in any
script. Workflow at `.github/workflows/release.yml`.

### One-time PyPI setup

Done once per repository:

1. Go to https://pypi.org/manage/account/publishing/
2. Add a new trusted publisher:
   - PyPI project name: `kairos-engine`
   - Owner: `Vekkris76`
   - Repository: `kairos`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
3. Save.

Also on GitHub:
- Settings → Environments → **New environment** → name `pypi`.
- (Optional but recommended) Add a required reviewer so tag pushes
  hang pending human approval before publishing.

### Per-release flow

```bash
# 1. Bump pyproject.toml version + add CHANGELOG entry
#    (version string must match the tag exactly, no 'v' prefix in pyproject)
vim pyproject.toml CHANGELOG.md

# 2. Commit + push to main
git add pyproject.toml CHANGELOG.md
git commit -m "vX.Y.Z: <one-line summary>"
git push origin main

# 3. Tag the release + push the tag
git tag vX.Y.Z
git push origin vX.Y.Z
```

GHA kicks in on the tag push:
1. **gate** job — extracts version from tag, cross-checks against
   pyproject, verifies CHANGELOG entry, runs ruff + full pytest,
   builds wheel + sdist, runs `twine check`.
2. **publish** job — downloads the artifacts, publishes to PyPI via
   trusted publishing. Requires the gate job green AND (if
   configured) a human approval on the `pypi` environment.

Verify at https://pypi.org/project/kairos-engine/X.Y.Z/.

### Failure modes + recovery

- **Tag/pyproject mismatch** → gate fails. Delete the tag
  (`git tag -d vX.Y.Z && git push origin :vX.Y.Z`), fix pyproject,
  re-tag, re-push.
- **Missing CHANGELOG entry** → same as above. Add the entry, amend
  the commit, re-tag.
- **Tests fail in CI but pass locally** → investigate CI-specific
  failures; do NOT bypass the gate. The gate exists precisely to
  catch the class of bug that shipped 0.3.2 without `reduce_only`.

## Fallback — `scripts/release.sh` (local)

For emergencies or dev testing, `scripts/release.sh` enforces the
same gates as the GHA workflow but runs locally and can publish
using a token from `~/.pypirc` (legacy twine format) or
`UV_PUBLISH_TOKEN` env var.

```bash
# Dry run (no publish — runs all gates, produces dist/ artifacts)
./scripts/release.sh

# Actually publish to PyPI
./scripts/release.sh --publish

# Publish to TestPyPI instead (useful for dry-run of the flow end-to-end)
./scripts/release.sh --publish --test-pypi
```

This path should NOT be the normal release route once the GHA
workflow is active — the trusted-publishing setup removes any
on-disk token and produces a cleaner audit trail.

## Historical context

The 2026-04-18 incident where Kairos 0.3.2 shipped without the
`reduce_only` kwarg that downstream DCA / EMA strategies pass when
closing positions directly motivated this release gate. A local
`uv build && uv publish` without re-running the test suite against
the working tree missed the kwarg mismatch. Both the GHA workflow
and `scripts/release.sh` now guarantee the test suite runs against
the exact code being packaged before any `publish` step.
