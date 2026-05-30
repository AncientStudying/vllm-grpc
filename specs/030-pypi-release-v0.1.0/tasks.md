---

description: "Task list for First PyPI Release (v0.1.0)"
---

# Tasks: First PyPI Release (v0.1.0)

**Input**: Design documents from `specs/030-pypi-release-v0.1.0/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: No new TDD unit tests are requested. The existing `packages/*/tests` suite MUST stay
green at the bumped dependency floors (SC-009). Tasks below therefore include packaging
**verification** steps (build, `twine check`, clean-venv install, console-script smoke) rather than
new unit-test files.

**Organization**: Tasks are grouped by user story. The shared `vllm-grpc-gen` package is
foundational — every leaf package's build/install resolves it — so it is published-ready first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US4, mapping to spec.md user stories
- Exact file paths are included in each task

## Path Conventions

Multi-package uv workspace (per plan.md). Each distributable lives under `packages/<name>/` with
`src/<module>/`. Top-level docs at repo root; release workflow under `.github/workflows/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Tooling and a clean baseline before any packaging change.

- [ ] T001 Add `twine` to the `dev` dependency group in `pyproject.toml` (root) so metadata
  validation (`uv run twine check` / `uvx twine`) is available; run `uv sync --all-packages` to
  resolve it.
- [ ] T002 Capture the green baseline: run `make proto` then
  `uv run pytest packages/proxy/tests packages/frontend/tests packages/client/tests tools/benchmark/tests -q`
  and record that the suite passes BEFORE changes, as the comparison point for SC-009.

---

## Phase 2: Foundational — `vllm-grpc-gen` (Blocking Prerequisites)

**Purpose**: Make the shared stubs package publish-ready and index-resolvable. Every leaf package
(proxy, frontend, client) depends on `vllm-grpc-gen~=0.1.0` resolving to a built distribution, and
FR-015 requires gen to be available first.

**⚠️ CRITICAL**: No user story (US1–US4) build/install verification can pass until this phase is
complete.

- [ ] T003 Fill complete `[project]` metadata in `packages/gen/pyproject.toml` per
  `contracts/package-metadata.md`: description, keywords, classifiers (AI topic + Python 3.12 +
  MIT + Development Status), authors, `license = "MIT"`, `readme = "README.md"`, and all four
  `[project.urls]` (Homepage, Repository, Issues, Changelog). Add runtime
  `dependencies = ["protobuf>=6.33", "grpcio>=1.80"]` (FR-006c). Keep `version = "0.1.0"` static
  (FR-003b) and `requires-python = ">=3.12"` (FR-003a).
- [ ] T004 Add the build-time stub generation hook for gen (FR-007a): create
  `packages/gen/hatch_build.py` implementing a hatchling `BuildHookInterface` that runs
  `python -m grpc_tools.protoc -I proto --python_out=src --grpc_python_out=src` for
  `proto/vllm_grpc/v1/{health,chat,completions}.proto` into `packages/gen/src/`; wire
  `[tool.hatch.build.hooks.custom]` and add `grpcio-tools>=1.80` + `protobuf>=6.33` to
  `[build-system].requires` in `packages/gen/pyproject.toml`; configure the sdist to force-include
  the needed `proto/` sources so the hook reproduces stubs when building from sdist. Keep generated
  stubs gitignored (`.gitignore` lines 217–221 unchanged).
- [ ] T005 [P] Author `packages/gen/README.md` (long-description): purpose (generated protobuf/gRPC
  stubs), `pip install vllm-grpc-gen`, a short usage snippet importing `vllm_grpc.v1`, repo link,
  and changelog link — held to the FR-024 clarity bar.
- [ ] T006 Build gen and validate: `uv build --package vllm-grpc-gen`; assert the wheel AND sdist
  contain `vllm_grpc/v1/*_pb2.py` + `*_pb2_grpc.py` (`python -m zipfile -l …`) (SC-013); run
  `uvx twine check packages/gen/dist/*` with zero errors/warnings (FR-008a); confirm no
  `[tool.uv.sources]` leaks into built `METADATA` (C-D5).
- [ ] T007 Install gen alone into a fresh isolated env (`uv venv` + `uv pip install --no-project`)
  and confirm `import vllm_grpc.v1.chat_pb2_grpc` succeeds with only its declared protobuf/grpcio
  deps resolved (SC-013 / FR-007a).

**Checkpoint**: `vllm-grpc-gen` builds with embedded stubs, validates, and imports standalone — leaf
packages can now resolve it.

---

## Phase 3: User Story 1 — SDK consumer installs a lean client (Priority: P1) 🎯 MVP

**Goal**: `pip install vllm-grpc-client` yields the client + generated stubs and **nothing** from
the web-server stack.

**Independent Test**: Build the client wheel, install it into a clean env (resolving gen from the
local dist), confirm the client + `vllm_grpc.v1` import, and assert no `fastapi`/`uvicorn` present.

- [ ] T008 [P] [US1] Fill complete metadata in `packages/client/pyproject.toml` per
  `contracts/package-metadata.md` (description, keywords, classifiers, authors, MIT license,
  `readme`, four project URLs). Bump deps to floor-only/no-caps: `grpcio>=1.80` and internal
  `vllm-grpc-gen~=0.1.0` (FR-006/FR-006a/FR-006b). Keep the `[tool.uv.sources]` workspace entry for
  dev. Keep `version = "0.1.0"` / `requires-python = ">=3.12"`.
- [ ] T009 [P] [US1] Author `packages/client/README.md`: purpose (lean async gRPC client),
  `pip install vllm-grpc-client`, a copy-pasteable usage snippet exercising the client, repo +
  changelog links (FR-002).
- [ ] T010 [US1] Build the client and validate metadata: `uv build --package vllm-grpc-client`;
  `uvx twine check packages/client/dist/*` (zero errors/warnings); confirm `METADATA` shows
  `Requires-Dist: vllm-grpc-gen~=0.1.0` with no workspace path (C-D3/C-D5). Depends on T008, T009.
- [ ] T011 [US1] Clean-env install + leanness check: install the client wheel into a fresh venv with
  `--find-links packages/gen/dist`, confirm the client + `vllm_grpc.v1` import, and assert
  `pip freeze | grep -Ei 'fastapi|uvicorn'` returns nothing (FR-009/SC-003). Run
  `uv run pytest packages/client/tests -q` green at the bumped floor (SC-009 slice).

**Checkpoint**: Client distribution is lean, installable, and validated — MVP deliverable complete.

---

## Phase 4: User Story 2 — Operator installs and launches a server package (Priority: P1)

**Goal**: `pip install vllm-grpc-proxy` / `vllm-grpc-frontend` each expose a console script that
launches and serves; frontend stays installable without vLLM and emits no deprecation warning.

**Independent Test**: Install proxy + frontend into clean envs, launch each console script against
the existing fake engine (no GPU/model), and confirm they serve; confirm frontend installs on a
vLLM-less env and surfaces missing vLLM only at runtime.

- [ ] T012 [P] [US2] Fill complete metadata in `packages/proxy/pyproject.toml` per
  `contracts/package-metadata.md`. Bump deps floor-only/no-caps: `fastapi>=0.136`,
  `uvicorn[standard]>=0.46`, `grpcio>=1.80`, internal `vllm-grpc-gen~=0.1.0`
  (FR-006/FR-006a/FR-006b). Add `[project.scripts]` → `vllm-grpc-proxy = "vllm_grpc_proxy.main:main"`
  (FR-004).
- [ ] T013 [US2] Add a `main()` console entry to `packages/proxy/src/vllm_grpc_proxy/main.py` that
  calls `uvicorn.run("vllm_grpc_proxy.main:app", host=…, port=…)` reading host/port from env
  (mirroring the `Makefile run-proxy` target) so the `vllm-grpc-proxy` script launches the REST
  surface (FR-004). Depends on T012.
- [ ] T014 [P] [US2] Author `packages/proxy/README.md`: purpose (REST proxy), `pip install
  vllm-grpc-proxy`, how to run the `vllm-grpc-proxy` console script, a usage snippet, repo +
  changelog links (FR-002).
- [ ] T015 [P] [US2] Fill complete metadata in `packages/frontend/pyproject.toml` per
  `contracts/package-metadata.md`. Bump deps floor-only/no-caps: `grpcio>=1.80`, internal
  `vllm-grpc-gen~=0.1.0`. Add `[project.scripts]` →
  `vllm-grpc-frontend = "vllm_grpc_frontend.main:main"` (FR-004). Add
  `[project.optional-dependencies] engine = ["vllm>=0.20"]` (FR-005a) — vLLM MUST NOT be in the
  default `dependencies` (base install stays vLLM-free), only in the `engine` extra (FR-005).
- [ ] T016 [US2] Remediate the deprecated V0 engine path in
  `packages/frontend/src/vllm_grpc_frontend/main.py:52–56`: replace
  `AsyncLLMEngine.from_engine_args(AsyncEngineArgs(model=…, enable_prompt_embeds=True))` with the V1
  `AsyncLLM` construction used by the M6.x benchmark harness (read the exact symbol/signature from
  `tools/benchmark/src/vllm_grpc_bench/`); keep the `vllm` import lazy/inside `serve()` so install
  succeeds on a vLLM-less platform (FR-022/FR-005). Verify
  `grep -rn 'AsyncLLMEngine\|AsyncEngineArgs' packages/frontend/src` returns nothing.
- [ ] T017 [P] [US2] Author `packages/frontend/README.md`: purpose (gRPC frontend), `pip install
  vllm-grpc-frontend`, how to run the `vllm-grpc-frontend` console script, a usage snippet, repo +
  changelog links, AND a prerequisite note that the frontend requires vLLM's V1 engine API
  (`AsyncLLM`), floor `vllm>=0.20` — installed either via the extra
  `pip install "vllm-grpc-frontend[engine]"` or separately by the operator for their platform
  (FR-002/FR-005a).
- [ ] T018 [US2] Build + validate the server packages: `uv build --package vllm-grpc-proxy` and
  `uv build --package vllm-grpc-frontend`; `uvx twine check` both with zero errors/warnings; assert
  the frontend wheel `METADATA` declares vLLM **only** under the `engine` extra
  (`Provides-Extra: engine` + `Requires-Dist: vllm>=0.20; extra == "engine"`) and has **no**
  unconditional `Requires-Dist: vllm` (FR-005/FR-005a/SC-007a/C-D4). Depends on T012–T017.
- [ ] T019 [US2] Clean-env install + console-script smoke (no GPU/model): install proxy and frontend
  into fresh venvs with `--find-links packages/gen/dist`; run `vllm-grpc-proxy` and curl `/healthz`;
  run `vllm-grpc-frontend` against the existing fake-engine fixture and confirm the gRPC server
  starts (FR-010/SC-004); confirm the **base** `pip install vllm-grpc-frontend` pulls no vLLM
  (`pip freeze | grep -i '^vllm'` empty) and missing vLLM surfaces as a runtime error, not an install
  failure (FR-005, US2 scenario 3); assert no `DeprecationWarning`
  originates from `vllm_grpc_frontend.*` (`python -W error::DeprecationWarning`) (FR-023/SC-010).
  Run `uv run pytest packages/proxy/tests packages/frontend/tests -q` green at floors.
- [ ] T019a [US2] Run the Constitution §IV merge-gate checks after the source edits in T013
  (proxy `main()`) and T016 (frontend V0→V1): `make proto` then
  `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict packages/proxy/src
  packages/frontend/src packages/client/src tools/benchmark/src`. Must pass with zero errors —
  every runtime module of proxy/frontend MUST satisfy `mypy --strict` (Quality Standards). Depends
  on T013, T016.

**Checkpoint**: Both server packages install, launch via console script, pass lint + `mypy
--strict`, and the frontend is deprecation-free and vLLM-peer-safe.

---

## Phase 5: User Story 3 — Ready, credential-safe release pipeline (Priority: P2)

**Goal**: A tag-triggered pipeline that builds all four distributions and is configured to publish
via OIDC — authored and statically validated, executing **no** upload in this feature.

**Independent Test**: Statically validate `release.yml` (actionlint + review): builds all four,
OIDC only, test-index then gated real-index, gen-first ordering, no job fires.

- [ ] T020 [US3] Author `.github/workflows/release.yml` per `contracts/release-workflow.md`:
  `on: push: tags: ['v*']`; a `build` job running `uv build` for all four members (gen first); a
  `publish-testpypi` job using `pypa/gh-action-pypi-publish` with `repository-url:
  https://test.pypi.org/legacy/` and `permissions: id-token: write` (no token); a `publish-pypi`
  job gated behind a protected `environment:` with required reviewers; `needs:` ordering so gen
  publishes before the leaf packages (FR-011–FR-015). Add a comment documenting the re-run strategy
  for the "version already on index" edge case (e.g. dev-suffix for TestPyPI).
- [ ] T021 [US3] Statically validate the workflow with zero execution: run
  `uvx actionlint .github/workflows/release.yml`; assert `grep -nE 'password:|PYPI_API_TOKEN'`
  returns nothing and `id-token: write` is present (FR-012); confirm by review that both publish
  steps exist, fire only on `v*`, the real step is approval-gated, and no job runs within this
  feature — no `v0.1.0` tag pushed (FR-013/FR-014/FR-014a/SC-005/SC-008).

**Checkpoint**: Release pipeline is authored, OIDC-only, gated, and statically valid — no upload
performed.

---

## Phase 6: User Story 4 — Discoverable install matrix & release history (Priority: P3)

**Goal**: Docs let a newcomer pick the right package per role and let a maintainer cut the next
release; release history is recorded.

**Independent Test**: Read the docs and confirm the per-persona install command, the release
procedure, and the v0.1.0 history entry are all present and consistent.

- [ ] T022 [P] [US4] Update the root `README.md` install matrix: `pip install vllm-grpc-client` for
  SDK consumers, `vllm-grpc-proxy` / `vllm-grpc-frontend` for operator roles, a note that
  `vllm-grpc-gen` installs transitively, and — for the frontend row — the vLLM V1-API prerequisite,
  the opt-in `pip install "vllm-grpc-frontend[engine]"` form, and the `>=0.20` floor
  (FR-016/FR-005a/SC-007/SC-007a).
- [ ] T023 [P] [US4] Update `CONTRIBUTING.md` with the release procedure: version bump (all four in
  lockstep) → tag (`v*`) → pipeline publish (test index then gated real index) → release-notes draft
  (FR-017).
- [ ] T024 [P] [US4] Create `CHANGELOG.md` in Keep-a-Changelog format with a `v0.1.0` entry
  summarizing this release; this is the target each package's `changelog` project URL points to
  (FR-018a).
- [ ] T025 [P] [US4] Create `docs/RELEASES.md` listing the prior codebase-state tags (`v0.0.0`,
  `v0.0.1`) and the `v0.1.0` entry as human-readable release notes (FR-018).
- [ ] T026 [US4] Verify every package's `changelog` `[project.urls]` value resolves to the
  `CHANGELOG.md` target created in T024 (consistent path/branch across all four `pyproject.toml`)
  (SC-011). Depends on T003/T008/T012/T015 and T024.

**Checkpoint**: Install matrix, release procedure, changelog, and release history are present and
cross-consistent.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Clarity pass, lockfile refresh, ADRs, consolidated verification, and the global
no-upload / green-suite gates.

- [ ] T026a Regenerate and commit `uv.lock` after the dependency-declaration changes (T003 gen
  deps + build-system reqs, T008 client floors, T012 proxy floors, T015 frontend floors + `engine`
  extra): run `uv lock` from repo root and commit the updated `uv.lock`. This keeps `uv.lock`
  consistent with the bumped `pyproject.toml` constraints so CI's `uv sync --frozen --all-packages`
  (ci.yml / proto.yml) does not fail on a stale lock. If delivering incrementally, re-run after each
  phase that changes a `pyproject.toml`. Depends on T003, T008, T012, T015. Run before T029/T030.
- [ ] T026b Commit the v0.1.0 packaging ADR `docs/decisions/0009-pypi-packaging-v0.1.0.md` (the
  non-obvious architectural choices: build-time stub generation hook, vLLM declared as an opt-in
  `engine` extra reconciling Constitution §II, and static literal versioning) as required by the
  constitution's Development Workflow; add a follow-up ADR for any further non-obvious decision
  surfaced during implementation.
- [ ] T027 [P] Simplify `README.md` and `ANALYSIS.md` section-by-section per FR-025: rewrite dense
  or jargon-heavy passages in plainer terms, gloss/link undefined acronyms and milestone shorthand
  (M5.2, TTFT, OIDC, …) on first use, keep a reader-facing summary near the top of each section —
  without removing technical accuracy or published results.
- [ ] T028 [P] Consistency review across `README.md`, `ANALYSIS.md`, `CONTRIBUTING.md` (FR-026):
  consistent package names, install commands, terminology, heading style, and cross-references; each
  acronym/milestone shorthand defined or linked on first use within each file (SC-012).
- [ ] T029 Run the full test suite green at the bumped floors: `make proto` then
  `uv run pytest packages/proxy/tests packages/frontend/tests packages/client/tests tools/benchmark/tests -q`
  — confirm parity with the T002 baseline (SC-009).
- [ ] T030 Build all four and final-validate: `for p in gen proxy frontend client; do uv build
  --package vllm-grpc-$p; done` (8 artifacts, SC-001); `uvx twine check packages/*/dist/*` (SC-005);
  grep all four `pyproject.toml` to confirm no third-party constraint carries an upper cap
  (FR-006a).
- [ ] T031 Execute `quickstart.md` end-to-end (steps 1–8) and confirm the no-upload invariant: no
  `twine upload` / `uv publish` / publish job ran, and no distribution name was claimed on any
  external index (FR-014a/FR-020/SC-008).
- [ ] T032 Run `graphify update .` to refresh the code graph after the source edits in
  `packages/proxy/src/vllm_grpc_proxy/main.py` and `packages/frontend/src/vllm_grpc_frontend/main.py`
  (per CLAUDE.md AST-only update rule).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2, gen)**: Depends on Setup — **BLOCKS all user stories** (leaf builds
  resolve gen; FR-015).
- **User Stories (Phase 3–6)**: All depend on Foundational completion.
  - US1 (P1) and US2 (P1) are independent of each other and can run in parallel after Phase 2.
  - US3 (P2) builds on having valid artifacts (US1/US2) but its *static* validation can be authored
    in parallel; its build job references all four packages.
  - US4 (P3) docs reference the package names/URLs finalized in US1/US2 metadata and the CHANGELOG.
- **Polish (Phase 7)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: After Phase 2. Independent.
- **US2 (P1)**: After Phase 2. Independent of US1.
- **US3 (P2)**: After Phase 2; the build job covers all four packages, so most useful once US1/US2
  metadata is final, but the workflow file is independently authorable.
- **US4 (P3)**: After US1/US2 metadata exists (for accurate names/URLs) and T024 CHANGELOG (for
  T026 URL check).

### Within Each Story

- Metadata (`pyproject.toml`) + README before that package's build.
- Build before `twine check` before clean-env install/smoke.
- Proxy `main()` (T013) before proxy smoke (T019); frontend V0→V1 remediation (T016) before
  frontend smoke (T019); both source edits before the lint + `mypy --strict` gate (T019a).
- All four `pyproject.toml` dependency edits (T003, T008, T012, T015) before the `uv.lock` refresh
  (T026a); the lock refresh before the consolidated suite/build gates (T029, T030).

### Parallel Opportunities

- Setup T001/T002 are quick and sequential-ish (T001 before T002 sync not required, but keep order).
- Foundational: T005 (README) ∥ T003/T004 (pyproject/hook) — different files.
- US1: T008 ∥ T009; US2: T012 ∥ T014 ∥ T015 ∥ T017 (distinct files); T013/T016 edit source after
  their pyproject tasks.
- US4: T022 ∥ T023 ∥ T024 ∥ T025 (distinct files).
- Polish: T027 ∥ T028.
- After Phase 2, **US1 and US2 can be developed fully in parallel by different people**.

---

## Parallel Example: User Story 2

```bash
# Author the three independent server-package files together:
Task: "Fill metadata + scripts in packages/proxy/pyproject.toml"        # T012
Task: "Author packages/proxy/README.md"                                 # T014
Task: "Fill metadata + scripts in packages/frontend/pyproject.toml"     # T015
Task: "Author packages/frontend/README.md (incl. vLLM V1 floor note)"   # T017
# Then the source edits (depend on their pyprojects):
Task: "Add main() to packages/proxy/src/vllm_grpc_proxy/main.py"        # T013
Task: "Migrate frontend main.py V0->V1 AsyncLLM"                         # T016
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup (T001–T002).
2. Phase 2: Foundational gen package (T003–T007) — CRITICAL, blocks everything.
3. Phase 3: US1 client (T008–T011).
4. **STOP and VALIDATE**: lean client builds, installs clean, pulls no web-server deps.

### Incremental Delivery

1. Setup + Foundational → gen publish-ready.
2. US1 (lean client) → validate → MVP.
3. US2 (server packages + V0→V1 remediation) → validate console scripts.
4. US3 (release pipeline) → static validation, no upload.
5. US4 (docs/history) → readable install matrix + changelog.
6. Polish → clarity pass, full-suite green, 8-artifact build, no-upload gate, graph refresh.

### Definition of Done (no external upload)

All four packages build (8 artifacts), install clean, pass `twine check`; client is lean; proxy +
frontend console scripts serve; frontend is deprecation-free and vLLM-peer-safe with a documented
V1 floor; `release.yml` is statically valid and OIDC-only; docs + changelog present and consistent;
full suite green at bumped floors — with **zero** uploads and **no** name claimed (FR-014a/FR-020).

---

## Notes

- [P] = different files, no dependency on an incomplete task.
- No new TDD test files are created; existing tests must stay green at bumped floors (SC-009).
- Scope fence (FR-019): do not touch `tools/benchmark/`, `proto/` schema, or package runtime logic
  beyond packaging metadata, console-script wiring, READMEs, the dependency floor bumps, and the
  V0→V1 remediation.
- Commit after each task or logical group; do not push a `v0.1.0` tag (would trigger the pipeline).
