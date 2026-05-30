# Phase 0 Research: First PyPI Release (v0.1.0)

All open questions in the spec were resolved during the 14-question clarification pass, so this
document records **how those decisions land against the actual codebase** (verified by inspecting
the four `pyproject.toml` files, `Makefile`, `.gitignore`, CI workflows, `uv.lock`, and the
frontend engine path on 2026-05-30). Each entry: Decision / Rationale / Alternatives considered /
Current-state delta.

---

## R1 — Build-time proto stub generation for `vllm-grpc-gen`

- **Decision**: Add a hatchling **build hook** (`packages/gen/hatch_build.py`, a
  `hatch_register_build_hook` / custom `BuildHookInterface`) that runs
  `python -m grpc_tools.protoc -I <repo>/proto --python_out=src --grpc_python_out=src …` into
  `src/vllm_grpc/v1/` immediately before the wheel/sdist is assembled. Declare
  `grpcio-tools` (pinned to the same `1.80.x` line as runtime grpcio) and `protobuf` in
  `[build-system].requires`. Stubs stay gitignored.
- **Rationale**: Constitution Principle I mandates build-time generation, no committed stubs,
  `proto/` as single source of truth. A build hook puts the generated `*_pb2.py` / `*_pb2_grpc.py`
  into the artifact without checking them in, so `uv build` (or `pip install` from sdist) reproduces
  them deterministically. Matches `make proto` invocation already proven in CI.
- **Alternatives considered**:
  - *Commit the stubs* — rejected: violates Principle I and `.gitignore` lines 217–221.
  - *Generate in a separate `setup.py`/`build` step the operator must remember* — rejected: not
    reproducible from a plain `pip install vllm-grpc-gen` sdist.
  - *`hatch-protobuf` plugin* — viable but adds a third-party build dependency; a ~30-line in-repo
    hook is simpler, auditable, and reuses the exact `protoc` invocation from the `Makefile`.
- **Current-state delta**: `gen/pyproject.toml` today has `[build-system] requires = ["hatchling"]`
  and **no** hook → a bare `uv build` of `gen` would ship an empty/`py.typed`-only package. The hook
  + build-system reqs close FR-007a / SC-013. The sdist must also carry `proto/` (or a copy) so the
  hook can run when building *from sdist* in a clean env — include the needed `.proto` files via
  hatch `force-include` / sdist `include`. **Open mechanical detail for /tasks**: whether to copy
  `proto/` into the sdist or vendor a minimal subset; resolved at implementation time, does not
  change the plan shape.

## R2 — Internal `vllm-grpc-gen` dependency must resolve from an index, not the workspace

- **Decision**: In proxy/frontend/client, declare `vllm-grpc-gen~=0.1.0` in `[project.dependencies]`
  (currently the entry is the unversioned `"vllm-grpc-gen"`). Keep `[tool.uv.sources] vllm-grpc-gen
  = { workspace = true }` for local dev — it is a uv-only table that standard build backends ignore
  and that is **not** emitted into wheel/sdist `METADATA`, so it does not leak (closes the
  "stale workspace-only source markers" edge case).
- **Rationale**: `~=0.1.0` (compatible-release) pins the minor line while allowing a patch `gen`
  (e.g. `0.1.1`), exactly the spec's FR-006 requirement. The published `METADATA` then carries
  `Requires-Dist: vllm-grpc-gen~=0.1.0`, which an index install resolves to the published stubs
  package rather than a path.
- **Alternatives considered**: exact pin `==0.1.0` — rejected (blocks a stub-only patch release);
  floor `>=0.1.0` — rejected (could pull a future `0.2.0` with incompatible stubs).
- **Current-state delta**: Verified `[tool.uv.sources]` is present in all three leaf packages and
  the dep is unversioned today. Must add the `~=0.1.0` constraint and confirm via `twine check` +
  a fresh-venv install that `METADATA` shows the versioned, path-free requirement.

## R3 — Console-script entry points (proxy + frontend)

- **Decision**: Add `[project.scripts]` to proxy and frontend.
  - Frontend already has `main()` at `main.py:69` → `vllm-grpc-frontend = "vllm_grpc_frontend.main:main"`.
  - Proxy exposes an ASGI `app` but **no** callable entry → add a thin `main()` that calls
    `uvicorn.run("vllm_grpc_proxy.main:app", host=…, port=…)` (host/port from env, mirroring the
    `Makefile run-proxy` target) and wire `vllm-grpc-proxy = "vllm_grpc_proxy.main:main"`.
- **Rationale**: FR-004 requires a launchable command per server package without cloning the repo.
  Proxy's new `main()` is console-script wiring explicitly permitted by the scope fence (FR-019).
- **Alternatives considered**: shipping only the ASGI `app` and telling operators to run `uvicorn …`
  — rejected: FR-004/US2 require an actual console command.
- **Current-state delta**: No `[project.scripts]` in any package today; frontend `main()` exists,
  proxy needs a small `main()` addition.

## R4 — Dependency floor bumps (floor-only, no caps)

- **Decision**: Set floors to the versions already resolved in `uv.lock` (verified 2026-05-30):
  `grpcio>=1.80` (lock 1.80.0), `fastapi>=0.136` (lock 0.136.1), `uvicorn>=0.46` (lock 0.46.0),
  and for `gen` `protobuf>=6.33` (lock 6.33.6). All floor-only (`>=`), **no upper caps**.
- **Rationale**: FR-006a/FR-006b/SC-009. Floor-only avoids downstream resolver conflicts (standard
  SDK practice). `grpcio>=1.80` is additionally *mandatory* because the generated gRPC stubs
  hard-require `grpcio>=1.80.0` at runtime. Tests must stay green at these floors (Principle IV).
- **Alternatives considered**: keep current floors (`grpcio>=1.65`, `fastapi>=0.115`,
  `uvicorn>=0.30`) — rejected by FR-006b; add upper caps for safety — rejected by FR-006a.
- **Current-state delta**: proxy = `fastapi>=0.115, uvicorn[standard]>=0.30, grpcio>=1.65`;
  frontend/client = `grpcio>=1.65`; gen = `dependencies = []`. All need bumping; `gen` additionally
  gains `protobuf>=6.33` + `grpcio>=1.80` (FR-006c).

## R5 — Frontend V0→V1 engine remediation

- **Decision**: Replace `AsyncLLMEngine.from_engine_args(AsyncEngineArgs(model=…,
  enable_prompt_embeds=True))` (frontend `main.py:52–56`) with the V1 `AsyncLLM` construction the
  M6.x harness already targets (`from vllm.v1.engine.async_llm import AsyncLLM`; build via
  `AsyncLLM.from_engine_args(EngineArgs(model=…, enable_prompt_embeds=True))` or the V1-equivalent
  constructor). Confirm against the M6.x harness usage as ground truth before finalizing the exact
  symbol/signature.
- **Rationale**: FR-022/SC-010 — eliminate the recurring V0 deprecation warning; uses vLLM's public
  V1 surface (Principle II, no fork). The import is inside `serve()` (lazy), so a vLLM-less platform
  still installs (FR-005 / US2 scenario 3).
- **Alternatives considered**: suppress the warning via `warnings.filterwarnings` — rejected: hides
  the deprecation instead of remediating it, and FR-023 requires the packages' own code to emit no
  such warning.
- **Current-state delta**: Verified V0 path at `main.py:52–56`. The exact V1 entry symbol is the one
  mechanical unknown; resolve from the M6.x benchmark harness (which already runs V1) during /tasks.
  This is a runtime-logic touch explicitly authorized by FR-021–FR-023 within the scope fence.
- **vLLM floor via optional extra (FR-005a)**: The V1 dependency is a real functional floor, so it
  is expressed **machine-readably** as an optional dependency extra
  `[project.optional-dependencies] engine = ["vllm>=0.20"]` (installed via `pip install
  "vllm-grpc-frontend[engine]"`) **and** in documentation (frontend README + root install matrix).
  The base `pip install vllm-grpc-frontend` pulls **no** vLLM, preserving the peer posture on
  vLLM-less platforms (FR-005). The project locks/tests against vLLM `0.20.1` (root `graph-targets`
  pin + `uv.lock`; macOS uses the `vllm-metal 0.2.0` build), so `>=0.20` is "the line this project is
  built and tested against," not a bisected absolute minimum.
  - *Decision history*: an earlier pass chose "no vLLM in any metadata, doc-only floor." The
    `/speckit-analyze` C1 finding showed that conflicted with Constitution Principle II (which
    requires a pinned vLLM declaration in `pyproject.toml`) and hid a real floor. The optional-extra
    form resolves C1 at the source — vLLM is a versioned library dependency (II satisfied) that is
    never force-installed (FR-005 satisfied) — so **no constitution amendment is needed**.

## R6 — Release pipeline (Trusted Publishing, no upload in-feature)

- **Decision**: New `.github/workflows/release.yml` triggered on `v*` tags with:
  a `build` job (`uv build` each member → upload artifacts), a `publish-testpypi` job
  (`pypa/gh-action-pypi-publish` with `repository-url: https://test.pypi.org/legacy/`,
  `permissions: id-token: write`, **no** password/token), and a `publish-pypi` job gated behind a
  GitHub **Environment with required reviewers** (manual approval). Job ordering / `needs:` makes
  `gen` publish before the leaf packages (FR-015). Every upload step is gated so none fires within
  this feature (FR-013/FR-014/FR-014a).
- **Rationale**: FR-011–FR-015, FR-012 OIDC. `gh-action-pypi-publish` is the canonical
  Trusted-Publishing action; `id-token: write` + a configured PyPI/TestPyPI publisher means no
  stored secret (Principle: no long-lived token). Static validation = workflow lint + review (no run).
- **Alternatives considered**: `uv publish` with an API token in repo secrets — rejected by FR-012
  (long-lived token) and the OIDC clarification; a single combined publish job — rejected: cannot
  gate the real-index step independently (FR-014).
- **Current-state delta**: Only `ci.yml` + `proto.yml` exist. `release.yml` is net-new. Validation
  in-feature is `actionlint`-style static check + reviewer inspection; **no job is executed**.
  Re-runnability for the version-exists edge case is documented (e.g. dev-suffix for test-index) in
  the workflow/CONTRIBUTING, since no upload happens now.

## R7 — Metadata, classifiers, license, URLs, requires-python, version sourcing

- **Decision**: Each package declares description, `keywords`, `classifiers`
  (`Topic :: Scientific/Engineering :: Artificial Intelligence`,
  `Programming Language :: Python :: 3.12`, `License :: OSI Approved :: MIT License`, an
  appropriate `Development Status`), `authors`, `license = "MIT"` (SPDX, matching root `LICENSE`),
  `readme = "README.md"`, and four `[project.urls]` — Homepage, Repository, Issues, Changelog.
  `requires-python = ">=3.12"` (already present, no upper cap — FR-003a). `version = "0.1.0"` stays
  a **static literal** in each file (FR-003b) — no `dynamic = ["version"]`, no VCS plugin.
- **Rationale**: FR-001/FR-003/FR-003a/FR-003b/SC-006. Static literals avoid coupling to the dual
  `v*` / `milestone/*` tag environment and keep versioning auditable; the release procedure bumps
  all four in lockstep (FR-017).
- **Alternatives considered**: `hatch-vcs` dynamic version from tags — rejected by FR-003b (the repo
  carries two independent tag namespaces; a VCS version would be ambiguous). Single shared README —
  rejected by FR-002 (per-package README is the long-description).
- **Current-state delta**: `version = "0.1.0"` and `requires-python = ">=3.12"` already correct in
  all four; everything else (URLs, classifiers, authors, keywords, license, readme, per-package
  README files) is missing and must be added. The author literal value is a plan-level detail
  deferred to /tasks.

## R8 — Documentation set (Option C) and clarity bar

- **Decision**: Ship per-package `README.md` files (purpose, install command, repo link, **usage
  snippet** — FR-002), an install matrix in root `README.md` (FR-016), the release procedure in
  `CONTRIBUTING.md` (FR-017), a new Keep-a-Changelog `CHANGELOG.md` (FR-018a) and a human-readable
  `docs/RELEASES.md` listing `v0.0.0` / `v0.0.1` / `v0.1.0` (FR-018). All docs held to the
  simplicity/clarity bar (FR-024); top-level `README.md` + `ANALYSIS.md` simplified section-by-
  section (FR-025); `README.md` / `ANALYSIS.md` / `CONTRIBUTING.md` reviewed for consistency
  (FR-026).
- **Rationale**: FR-016–FR-018a, FR-024–FR-026, SC-007/SC-011/SC-012. Each package's `changelog`
  project URL must resolve to a valid target → point it at `CHANGELOG.md` on the default branch.
- **Alternatives considered**: docs-site generator (mkdocs) — rejected: out of scope, heavier than
  the clarity goal needs; single CHANGELOG only — rejected by the dual-changelog clarification.
- **Current-state delta**: Verified no per-package READMEs, no `CHANGELOG.md`, no `docs/RELEASES.md`
  today; `v0.0.0` + `v0.0.1` tags exist to seed history. Root `README.md`, `ANALYSIS.md`,
  `CONTRIBUTING.md` all present and need the simplify/consistency pass.

## R9 — Build & install verification tooling

- **Decision**: Use `uv build` per package (wheel + sdist → 8 artifacts, SC-001); `twine check`
  for metadata/long-description (FR-008a/SC-005); install each wheel into a fresh isolated venv
  (`uv venv` + `uv pip install --no-project <wheel>`, or `pip install` in a throwaway venv) to prove
  clean install (FR-008/SC-002) and the client's lean dependency set — assert no `fastapi`/`uvicorn`
  present after a client-only install (FR-009/SC-003); run the proxy/frontend console scripts
  against the existing fake-engine fixtures for the smoke check (FR-010/SC-004, no GPU/model).
- **Rationale**: Each FR/SC has a concrete, scriptable check; these become the verification tasks.
- **Alternatives considered**: rely on CI only — rejected: local reproducibility is needed for the
  /tasks acceptance gates; `pip wheel` instead of `uv build` — rejected: project standardizes on uv.
- **Current-state delta**: `uv 0.9.18` available; `twine` is not yet a dev dependency — add it to the
  `dev` group (or invoke via `uvx twine`). Fake-engine fixtures already exist under
  `packages/frontend/tests` and `packages/proxy/tests`.

---

### Resolved unknowns summary

| Spec area | Status |
|-----------|--------|
| Publish scope (no upload) | Resolved — DoD excludes all uploads (FR-014a/FR-020) |
| Auth mode | Resolved — Trusted Publishing OIDC (FR-012) |
| Stub generation timing | Resolved — build hook (FR-007a) |
| Runtime dep declaration | Resolved — gen owns protobuf+grpcio (FR-006c) |
| Dep floors | Resolved — lock-resolved floors, no caps (FR-006b) |
| requires-python | Resolved — `>=3.12`, classifier-advertised (FR-003a) |
| Version sourcing | Resolved — static literals (FR-003b) |
| vLLM posture | Resolved — peer prerequisite (FR-005) |
| Doc set + clarity | Resolved — Option C + clarity bar (FR-024–FR-026) |

**Remaining mechanical unknowns** (do not affect plan shape; settled during /tasks):
exact V1 `AsyncLLM` entry symbol (read from M6.x harness), author-string literal, precise classifier
strings, and whether the `gen` sdist copies `proto/` wholesale or a minimal subset for the build hook.
