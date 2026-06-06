# Implementation Plan: First PyPI Release (v0.1.0)

**Branch**: `chore/pypi-release-v0.1.0` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/030-pypi-release-v0.1.0/spec.md`

## Summary

Bring the four `packages/` workspace members (`vllm-grpc-gen`, `vllm-grpc-proxy`,
`vllm-grpc-frontend`, `vllm-grpc-client`) to a *publish-ready, installable* state and prove it
locally / in CI **without performing any external upload**. The work is mechanical-packaging and
documentation plus one runtime remediation:

1. **Metadata + layout** — fill each `pyproject.toml` (description, keywords, classifiers, authors,
   MIT license, four project URLs), add a per-package `README.md` as the long-description, wire
   console scripts for proxy + frontend, and make the internal `vllm-grpc-gen` dependency resolve
   to a *published* version (`~=0.1.0`) instead of a workspace path.
2. **Build-time stub generation** — give `vllm-grpc-gen` a build hook that runs `protoc`
   (grpcio-tools) so the gitignored stubs are produced into the wheel/sdist; `proto/` stays the
   single source of truth (Constitution Principle I).
3. **Dependency floors** — bump third-party floors to the versions already resolved in `uv.lock`
   (`grpcio>=1.80`, `fastapi>=0.136`, `uvicorn>=0.46`), floor-only/no caps; `gen` declares its own
   `protobuf>=6.33` + `grpcio>=1.80`.
4. **Deprecated-API remediation** — migrate the frontend's V0 `AsyncLLMEngine` /`AsyncEngineArgs`
   path to the V1 `AsyncLLM` surface, eliminating the recurring deprecation warning.
5. **Release pipeline** — author `.github/workflows/release.yml` (tag-triggered, Trusted-Publishing
   OIDC, test-index then gated real-index, gen-first ordering) and *statically validate* it; no
   step runs in this feature.
6. **Documentation** — per-package READMEs with usage snippets, an install matrix in the root
   `README.md`, the release procedure in `CONTRIBUTING.md`, plus new `CHANGELOG.md`
   (Keep-a-Changelog) and `docs/RELEASES.md`; simplify/clarify the top-level docs.

The technical approach is verification-first: every functional requirement maps to a locally
runnable check (`uv build`, install into a fresh `--no-project` venv, `twine check`, console-script
smoke against the existing fake engine, workflow lint). The Definition of Done is reached with
**zero external uploads** — the TestPyPI and real-PyPI uploads are later, operator-triggered
actions.

## Technical Context

**Language/Version**: Python 3.12 (published `requires-python = ">=3.12"`, no upper cap; root
workspace lock keeps its dev-only `<3.13`).
**Primary Dependencies**: hatchling (build backend, all four packages); grpcio-tools / `protoc`
(build-time stub generation for `gen`); grpcio (runtime, all four); fastapi + `uvicorn[standard]`
(proxy); protobuf (runtime, via `gen`); vLLM (frontend **peer prerequisite**, not in
`install_requires`).
**Storage**: N/A (no datastore; artifacts are wheels + sdists under each package's `dist/`).
**Testing**: pytest (existing `packages/*/tests`, must stay green at bumped floors); `twine check`
for metadata/long-description; fresh-venv install smoke + console-script smoke against the existing
fake engine/server fixtures; workflow lint (`actionlint`-style static validation) for the release
pipeline.
**Target Platform**: Linux/macOS dev + Linux CI (GitHub Actions `ubuntu-latest`); published wheels
are pure-Python (`py3-none-any`) so platform-agnostic; vLLM availability is a runtime concern only.
**Project Type**: Multi-package Python workspace (uv workspace, 4 distributable members + 1
internal `tools/benchmark` that stays unpublished).
**Performance Goals**: N/A — packaging/release feature; no latency or throughput targets. The
build-time stub hook must not regress build to an unreasonable duration but no numeric target.
**Constraints**: No external upload of any kind (FR-014a/FR-020); no name claimed on any index;
floor-only dependency constraints with no upper caps; static `version = "0.1.0"` literals (no
VCS-derived versioning); Trusted Publishing (OIDC) — no long-lived token in the repo; scope fence —
no changes to `tools/benchmark/`, `proto/`, or package runtime logic beyond packaging + the named
deprecation remediation.
**Scale/Scope**: 4 published packages → 8 artifacts (wheel + sdist each); ~35 FRs / 13 SCs; one
new CI workflow; ~5 new doc files (4 package READMEs + CHANGELOG + RELEASES) plus edits to root
README/CONTRIBUTING/ANALYSIS.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Proto-First** | ✅ PASS (reinforced) | FR-007a moves stub generation to a **build-time** hook and keeps stubs gitignored — exactly the principle's "produced at build time… MUST NOT be committed" rule. `proto/` stays the single source of truth. The existing `proto.yml` CI no-diff check is preserved. |
| **II. Library Dependency, Not Fork** | ✅ PASS | vLLM is declared as a pinned-range **optional dependency extra** `engine = ["vllm>=0.20"]` in the frontend `pyproject.toml` (FR-005a) — a versioned library-dependency declaration, satisfying II's "depend on vLLM via pyproject, pinned to a compatible range" — while staying out of the default install so vLLM-less platforms still install (FR-005). The V0→V1 remediation (FR-022) uses vLLM's *public* `AsyncLLM` API; no patched/vendored vLLM. *(Resolves the C1 conflict raised in `/speckit-analyze`: the optional-extra form reconciles II's pinned-declaration requirement with the no-force-install peer posture — no constitution amendment required.)* |
| **III. Phase Discipline** | ✅ PASS | `v0.1.0 — First PyPI release` is an explicit PLAN.md deliverable on the parallel semver track; this plan builds only what that section lists. No M7/M8 functionality introduced. |
| **IV. CI is the Merge Gate** | ✅ PASS | lint + `mypy --strict` + tests + proto-check stay green; floor bumps must keep the suite green at the new floors (FR-006b/SC-009). New `release.yml` adds a gate, never bypasses one; `--no-verify` not used. |
| **V. Honest Measurement** | ✅ PASS (N/A) | No benchmark numbers produced or altered; scope fence forbids touching `tools/benchmark/`. |

**Result**: No violations. Complexity Tracking table left empty (no new package added — the four
members already exist; governance's "fourth package" caution does not apply).

## Project Structure

### Documentation (this feature)

```text
specs/030-pypi-release-v0.1.0/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Feature spec (already present)
├── research.md          # Phase 0 output (this command)
├── data-model.md        # Phase 1 output (this command)
├── quickstart.md        # Phase 1 output (this command)
├── contracts/           # Phase 1 output (this command)
│   ├── package-metadata.md      # Required pyproject metadata per package
│   ├── release-workflow.md      # release.yml structural contract
│   └── verification-commands.md # Local/CI checks mapped to FRs/SCs
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
packages/
├── gen/                         # vllm-grpc-gen — owns generated stubs
│   ├── pyproject.toml           # +metadata, +protobuf>=6.33, +grpcio>=1.80,
│   │                            #  +grpcio-tools build-req, +build hook, +readme
│   ├── README.md                # NEW — long-description + usage snippet
│   ├── hatch_build.py           # NEW — build hook: runs protoc into src before build
│   └── src/vllm_grpc/           # py.typed + v1/*_pb2*.py (gitignored, build-generated)
├── proxy/                       # vllm-grpc-proxy — REST proxy (console script)
│   ├── pyproject.toml           # +metadata, floor bumps, gen ~=0.1.0, +[project.scripts]
│   ├── README.md                # NEW
│   └── src/vllm_grpc_proxy/
│       ├── main.py              # +main() console entry calling uvicorn.run(app)
│       └── …
├── frontend/                    # vllm-grpc-frontend — gRPC server (console script)
│   ├── pyproject.toml           # +metadata, floor bumps, gen ~=0.1.0, +[project.scripts]
│   ├── README.md                # NEW
│   └── src/vllm_grpc_frontend/
│       ├── main.py              # V0 AsyncLLMEngine → V1 AsyncLLM remediation (FR-022)
│       └── …
└── client/                      # vllm-grpc-client — lean async client
    ├── pyproject.toml           # +metadata, floor bumps, gen ~=0.1.0
    ├── README.md                # NEW
    └── src/vllm_grpc_client/

.github/workflows/
├── ci.yml                       # unchanged (proto-stub generation already wired)
├── proto.yml                    # unchanged (no-diff stub check preserved)
└── release.yml                  # NEW — tag-triggered, OIDC, test→gated-real, gen-first

proto/                           # UNCHANGED (scope fence) — single source of truth
README.md                        # +install matrix; simplify per FR-025/FR-026
CONTRIBUTING.md                  # +release procedure; consistency review
ANALYSIS.md                      # simplify per FR-025
CHANGELOG.md                     # NEW — Keep-a-Changelog
docs/RELEASES.md                 # NEW — human-readable release history (v0.0.0/v0.0.1/v0.1.0)
```

**Structure Decision**: Existing uv multi-package workspace, retained unchanged in shape. All edits
are confined to the four `packages/*/` members (metadata, READMEs, console-script + remediation
source), one new CI workflow, and top-level documentation files. No new package, no module
relocation, no proto or benchmark-harness change — honoring the scope fence (FR-019) and governance's
no-new-package caution.

## Complexity Tracking

> No Constitution Check violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
