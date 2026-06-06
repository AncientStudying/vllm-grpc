# Contributing to vllm-grpc

Thank you for your interest in contributing. This guide covers local setup, how to run the test suite, the branch and PR conventions, and how to report issues.

---

## Development Setup

**Supported platforms**: macOS (M2/M3) and Linux x86-64. Windows is not supported.

**Prerequisites** — same as the [README quickstart](README.md#prerequisites):

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` — macOS: `xcode-select --install`; Linux: pre-installed

Once prerequisites are in place:

```bash
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap   # install all dependencies + generate protobuf stubs
```

`make bootstrap` is idempotent — safe to re-run after pulling new commits.

---

## Running the Test Suite

The CI gate is `make check`. Run it before opening a PR:

```bash
make check       # ruff (lint + format) + mypy --strict + pytest
```

For the benchmark smoke test (no live model required):

```bash
make bench-ci    # runs the harness against stub servers
```

To regenerate protobuf stubs after editing `.proto` files:

```bash
make proto
```

All three CI jobs must pass before any PR is merged: lint/type-check, unit tests, and the proto stub compile check.

---

## Branch Naming

Use a short, descriptive branch name that conveys the change — there's no required format. Common prefixes like `fix/`, `feat/`, `docs/`, or `chore/` are welcome but optional:

```
fix/proxy-timeout
feat/streaming-embeds
docs/contributing-cleanup
```

> **Note:** You may see existing branches and `specs/` directories that use a `NNN-short-description` numbering scheme (e.g. `013-contributing-roadmap`). That convention comes from the maintainers' internal spec-kit workflow (see below) and is **not** required for outside contributions.

---

## Pull Requests

- CI must pass (all three jobs: lint, tests, proto check).
- The PR description should explain **why** the change is needed, not just what changed. The diff shows the what.
- Keep each PR to one concern. Unrelated fixes belong in a separate branch.
- If your change happens to be planned through the spec-kit workflow, feel free to reference the relevant spec directory (e.g., `specs/013-contributing-roadmap/`) — but this is optional and not expected for most contributions.

---

## Reporting Issues

Open a [GitHub Issue](../../issues) with:

- A short, descriptive title.
- Steps to reproduce (minimal example preferred).
- Your OS and Python version (`python --version`).
- Output of `make check` if the issue involves a test or lint failure.
- Expected vs actual behaviour.

For feature requests, describe the use case and how it fits the project's wire-overhead measurement focus.

---

## Spec-Kit Workflow (optional)

The maintainers use a spec-kit cycle to plan larger phases of work, and you'll find its artifacts under `specs/NNN-feature-name/`. **This is entirely optional and not a prerequisite for contributing** — most fixes, docs changes, and self-contained features need nothing more than a branch, a passing `make check`, and a PR.

If you *want* to use it for a large, multi-file change (and you have the spec-kit tooling installed), the cycle is:

```
/speckit-specify   → create feature specification (spec.md)
/speckit-plan      → generate implementation plan + research
/speckit-tasks     → generate ordered task list
/speckit-implement → execute the task list
```

See the [README](README.md#spec-kit) for more detail.

---

## Releasing to PyPI

The four packages (`vllm-grpc-gen`, `vllm-grpc-proxy`, `vllm-grpc-frontend`,
`vllm-grpc-client`) are versioned and released **in lockstep**. The publish
pipeline is `.github/workflows/release.yml` (tag-triggered, Trusted Publishing /
OIDC — no API token in the repo).

1. **Bump the version in all four packages** to the new release, e.g. `0.1.0`:
   edit `version = "X.Y.Z"` in each `packages/*/pyproject.toml`. Keep them
   identical — versions are static literals (no VCS-derived versioning). Run
   `uv lock` and commit the updated `uv.lock`.
2. **Update release history**: add a `CHANGELOG.md` entry for the version and a
   matching `docs/RELEASES.md` note. Open a PR and merge once CI is green.
3. **Tag and push** the release on `main`: `git tag vX.Y.Z && git push origin vX.Y.Z`.
   The `v*` tag triggers the pipeline: it builds all four distributions
   (`gen` first) and publishes them to **TestPyPI**.
4. **Approve the real-index publish**: the `publish-pypi` job is gated behind the
   protected `pypi-release` GitHub Environment. Review the TestPyPI artifacts,
   then approve the deployment to publish to **PyPI**.
5. **Draft release notes** on GitHub for the tag, summarising the CHANGELOG entry.

**Version already on the index?** PyPI/TestPyPI versions are immutable. If a run
fails partway, bump the version (all four, in lockstep) and push a new tag; for
TestPyPI dry-runs you can append a `.devN` suffix so the index accepts the
re-upload. One-time operator prerequisites: configure the Trusted Publisher for
each package on both indexes and create the `pypi-release` environment with
required reviewers.
