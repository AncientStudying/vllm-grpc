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

Branches follow the `NNN-short-description` convention, where `NNN` is the next sequential spec number:

```
013-contributing-roadmap
012-demo-polish
011-phase-6.1
```

Check `specs/` to find the current highest number. New feature branches should increment from there.

---

## Pull Requests

- CI must pass (all three jobs: lint, tests, proto check).
- The PR description should explain **why** the change is needed, not just what changed. The diff shows the what.
- Keep each PR to one concern. Unrelated fixes belong in a separate branch.
- Reference the relevant spec directory (e.g., `specs/013-contributing-roadmap/`) if the change was planned through the spec-kit workflow.

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

## Spec-Kit Workflow

Planned phases in this project follow a spec-kit cycle before any code is written:

```
/speckit-specify   → create feature specification (spec.md)
/speckit-plan      → generate implementation plan + research
/speckit-tasks     → generate ordered task list
/speckit-implement → execute the task list
```

Artifacts are written to `specs/NNN-feature-name/`. If you are contributing a planned change that spans multiple files, start with `/speckit-specify` and open the spec for review before implementation.

See the [README](README.md#spec-kit) for more detail.
