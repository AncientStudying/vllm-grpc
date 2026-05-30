# Feature Specification: First PyPI Release (v0.1.0)

**Feature Branch**: `chore/pypi-release-v0.1.0`
**Created**: 2026-05-30
**Status**: Draft
**Input**: User description: "v0.1.0 as described in docs/PLAN.md" (§ v0.1.0 — First PyPI release)

## Overview

Bring the four `packages/` workspace members — `vllm-grpc-gen`, `vllm-grpc-proxy`,
`vllm-grpc-frontend`, `vllm-grpc-client` — to a publishable, installable state and
prove they are publish-ready, without performing any external upload in this feature.
The deliverable is a *publish-ready* repository: complete package metadata, per-package
READMEs, console scripts, and a tag-triggered release pipeline that authenticates via
Trusted Publishing — all validated locally / in CI without uploading anywhere. No upload
occurs in this feature, not even to TestPyPI: the TestPyPI upload is the operator's first
manual trigger of the authored pipeline, and the real public PyPI upload is a later,
separately gated operator action.

Four packages rather than one umbrella package is a deliberate choice (PLAN.md): the
workspace already enforces clean dependency boundaries (`proxy → gen`, `frontend → gen`,
`client → gen`, no cycles), so an SDK consumer who wants only the client never pulls a
web server's dependencies into their environment.

## Clarifications

### Session 2026-05-30

- Q: How far should v0.1.0 go on publishing? → A: Stop publish-ready — **no external upload
  occurs in this feature** (not even to TestPyPI). The TestPyPI upload is the operator's first
  manual trigger of the authored pipeline; the real public PyPI upload is a later, separately
  gated operator action.
- Q: Where exactly is the Definition of Done boundary for the completion goal? → A: Done =
  all four packages build, install cleanly in a fresh isolated environment, and pass
  metadata/long-description validation (e.g. a `twine check`-style check), AND the
  tag-triggered release workflow is authored and statically validated (e.g. workflow lint +
  reviewable publish steps). The TestPyPI upload and the real PyPI upload are both
  operator-triggered and outside DoD.
- Q: How should the release pipeline authenticate to PyPI/TestPyPI? → A: Trusted Publishing
  (OIDC) — no long-lived API token stored in the repository.
- Q: How should `vllm-grpc-frontend` declare its vLLM runtime requirement? → A: As a peer /
  documented prerequisite — vLLM is NOT in `install_requires`; the operator installs it
  separately for their platform.
- Q: How should each package's PyPI long-description be sourced? → A: Author a short,
  dedicated `README.md` inside each `packages/*/` directory.
- Q: What dependency version-constraint policy should the published packages use? → A:
  Floor-only (`>=`) on third-party dependencies with **no upper caps** (standard SDK practice
  to avoid downstream resolver conflicts); the internal `vllm-grpc-gen` cross-dependency
  pinned compatible-release `~=0.1.0` (pins the minor line, allows a patch gen).
- Q: Should the floors stay at their current values? → A: No — bump each third-party floor to
  the latest released version currently resolved in `uv.lock` (`grpcio>=1.80`,
  `fastapi>=0.136`, `uvicorn>=0.46`; protobuf runtime `6.33.x` via transitive resolution),
  still floor-only.
- Q: Any code hygiene to fold into this release? → A: Yes — scan the four published packages
  for deprecated-API usage and remediate. The known recurring warning is the frontend's use
  of the deprecated V0 `AsyncLLMEngine` / `AsyncEngineArgs` engine path
  (`packages/frontend/src/vllm_grpc_frontend/main.py`); migrate it to the V1 `AsyncLLM`
  surface the M6.x harness already targets.
- Q: What documentation deliverable set should v0.1.0 ship? → A: Expanded (Option C) —
  per-package READMEs include a dedicated usage/examples section, AND the project keeps both a
  Keep-a-Changelog `CHANGELOG.md` and a human-readable `docs/RELEASES.md`.
- Q: Any documentation-quality bar to encode? → A: Yes — all documentation MUST favor
  simplicity and clarity (plain language, minimal jargon, acronyms defined on first use).
  Additionally, simplify the language in the top-level `README.md` and `ANALYSIS.md` sections,
  and scan/review all top-level documentary files (`README.md`, `ANALYSIS.md`,
  `CONTRIBUTING.md`) for simplicity, clarity, and consistency.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - SDK consumer installs a lean client (Priority: P1)

A Python developer wants to call the gRPC frontend directly from their own application.
They install just the client distribution and get the client library plus the generated
protobuf stubs — and nothing else (no FastAPI, no uvicorn, no server-side dependencies).

**Why this priority**: The surgical-install promise is the core reason the project ships
four packages instead of one. If a client install drags in the proxy's web-server stack,
the whole packaging rationale collapses. This is the headline consumer-facing value.

**Independent Test**: Build the client distribution, install it into a clean, empty
environment, confirm the client package and the generated-stubs package import
successfully, and confirm that no proxy/frontend-only dependencies (e.g. a web server
framework) were pulled in.

**Acceptance Scenarios**:

1. **Given** a clean environment with nothing installed, **When** the client distribution
   is installed, **Then** the client library and the generated-stubs dependency resolve and
   import, and the installed dependency set contains no web-server framework.
2. **Given** the client distribution's metadata, **When** a packaging tool reads it,
   **Then** it shows a populated description, project URLs (homepage, repository, issues,
   changelog), license, classifiers, and a rendered long-description from the package's own
   README.

---

### User Story 2 - Operator installs and launches a server package (Priority: P1)

An operator deploying the REST proxy or the gRPC frontend installs the corresponding
distribution and launches it via a console-script command, without cloning the repo.

**Why this priority**: The proxy and frontend are operator-facing executables; a published
package that cannot be launched as a command is not usable as a release artifact. Equal in
importance to US1 because together they cover both consumer personas.

**Independent Test**: Install the proxy distribution into a clean environment and confirm
its console-script entry point launches and serves; do the same for the frontend
distribution against a local fake engine, with vLLM treated as a separately-installed
prerequisite.

**Acceptance Scenarios**:

1. **Given** the proxy distribution installed in a clean environment, **When** the operator
   runs the proxy console-script command, **Then** the proxy process starts and serves its
   REST surface.
2. **Given** the frontend distribution installed in a clean environment **and** vLLM
   available as a prerequisite, **When** the operator runs the frontend console-script
   command, **Then** the frontend gRPC server starts.
3. **Given** the frontend distribution installed on a platform where vLLM is absent,
   **When** the operator attempts to start it, **Then** installation of the package itself
   still succeeds and the missing-vLLM condition surfaces as a clear runtime error, not a
   failed install.

---

### User Story 3 - Maintainer has a ready, credential-safe release pipeline (Priority: P2)

A maintainer needs a tag-triggered pipeline that, when they later choose to trigger it,
builds all four distributions and publishes them, authenticating without any stored
long-lived secret. Within this feature the pipeline is authored and validated, but it
performs no upload — the maintainer's first trigger (to the test index) happens later, as
a deliberate operator action.

**Why this priority**: Repeatable, credential-safe publishing is what makes the release
durable, but it builds on US1/US2 (there must be valid artifacts to publish first), and the
upload itself is intentionally left to the operator.

**Independent Test**: Inspect and statically validate the pipeline definition — confirm it
builds all four distributions, targets the test index first and the real index second, uses
short-lived OIDC credentials (no stored token), and that every upload step is gated/manual
so that none fires as part of this feature.

**Acceptance Scenarios**:

1. **Given** the release pipeline definition, **When** it is statically validated (workflow
   lint + review), **Then** it builds all four distributions and is configured to upload via
   short-lived OIDC credentials with no long-lived token stored in the repository.
2. **Given** the release pipeline, **When** a reviewer inspects its upload steps, **Then**
   both the test-index and the real-index publish steps are present, fire only on a version
   tag, and are gated such that neither executes within this feature.
3. **Given** the merged feature, **When** the operator later triggers the pipeline, **Then**
   the test-index upload is the first external upload that occurs — nothing was uploaded
   during this feature's implementation.

---

### User Story 4 - Newcomer discovers the install matrix and release history (Priority: P3)

A new user reads the project's documentation to learn which package to install for their
role, and a maintainer reads the documented procedure to learn how to cut the next release.

**Why this priority**: Documentation makes the release usable and maintainable, but the
artifacts and pipeline deliver value even before the docs are perfect.

**Independent Test**: Read the documentation and confirm it states the correct install
command per persona (consumer vs. each operator role), the release procedure, and a release
history listing the version line.

**Acceptance Scenarios**:

1. **Given** the project README, **When** a reader looks for installation guidance, **Then**
   it states the install command for SDK consumers and for each operator role, and notes that
   the generated-stubs package installs transitively.
2. **Given** the contributing guide, **When** a maintainer looks for the release procedure,
   **Then** it documents the version-bump → tag → pipeline-publish → release-notes sequence.
3. **Given** the release-history document, **When** a reader opens it, **Then** it lists the
   prior codebase-state tags and the v0.1.0 entry.

### Edge Cases

- **Name already claimed**: One or more of the four distribution names is already taken on
  the public or test index by a third party. The feature must detect this during metadata/name
  verification and escalate (rename or reserve), rather than leaving a colliding name baked
  into the publish-ready state.
- **Version already exists on an index (operator-time)**: A given version can never be
  re-uploaded to the same index. When the operator later triggers the pipeline, a re-run after
  a prior upload of the same version must be handled deterministically (e.g. a re-runnable
  strategy such as a pre-release/dev suffix for test-index uploads, or documented deletion)
  rather than failing opaquely. The authored pipeline must account for this even though no
  upload occurs within this feature.
- **Inter-package dependency resolution at install time**: The three leaf packages depend on
  the generated-stubs package. When installed from an index (not the local workspace), that
  dependency must resolve to a published version of the stubs package — not a workspace path
  — or the install fails. Publish ordering must guarantee the stubs package is available
  first.
- **Frontend on a vLLM-less platform**: Installing the frontend where vLLM has no available
  build must still succeed at install time (vLLM is a peer prerequisite, not a hard
  dependency); the absence only manifests when the engine path is exercised at runtime.
- **Stale workspace-only source markers**: Workspace-only source declarations that make the
  packages resolve locally during development must not leak into published artifacts in a way
  that makes them uninstallable from an index.

## Requirements *(mandatory)*

### Functional Requirements

#### Package metadata & layout

- **FR-001**: Each of the four packages MUST declare complete distribution metadata:
  description, keywords, trove classifiers (including an AI/scientific topic and the
  supported Python version), authors, an MIT license consistent with the repository's root
  license, and project URLs for homepage, repository, issues, and changelog.
- **FR-002**: Each package MUST carry its own dedicated README within its package directory,
  used as the published long-description, describing the package's purpose, its install
  command, a link back to the repository, **and a dedicated usage/examples section with a
  short, copy-pasteable snippet** (per the Option C documentation set).
- **FR-003**: All four packages MUST be versioned at `0.1.0` for this release.
- **FR-004**: The proxy and the frontend packages MUST each expose a console-script entry
  point that launches the respective server process.
- **FR-005**: The frontend package MUST treat vLLM as a peer / documented prerequisite —
  vLLM MUST NOT appear in the frontend's hard install requirements, and the frontend MUST
  remain installable on platforms where vLLM has no available build.
- **FR-006**: The three leaf packages (proxy, frontend, client) MUST depend on the
  generated-stubs package such that, when installed from a package index, the dependency
  resolves to a published version of the stubs package rather than a local workspace path.
  The internal `vllm-grpc-gen` dependency MUST use a compatible-release constraint `~=0.1.0`.
- **FR-006a**: Third-party dependency constraints MUST be floor-only (`>=`) with no upper
  version caps.
- **FR-006b**: Each third-party dependency floor MUST be bumped to the latest released
  version currently resolved in `uv.lock` — at minimum `grpcio>=1.80`, `fastapi>=0.136`,
  `uvicorn>=0.46` — and the published packages MUST remain installable and pass their tests
  at those floors.

#### Build & install verification

- **FR-007**: The build process MUST produce both a wheel and a source distribution for each
  of the four packages.
- **FR-008**: Each produced wheel MUST install successfully into a clean, isolated
  environment.
- **FR-008a**: Each produced distribution's metadata and rendered long-description MUST pass
  a packaging-metadata validation check (e.g. a `twine check`-style check) with no errors or
  warnings.
- **FR-009**: After installing the client distribution into a clean environment, the
  installed dependency set MUST NOT include any proxy- or frontend-only dependency (e.g. the
  proxy's web-server framework).
- **FR-010**: After installation into a clean environment, the proxy and frontend console
  scripts MUST launch and serve against a local fake engine/server (no GPU or real model
  required).

#### Release pipeline

- **FR-011**: The repository MUST define an automated release pipeline that triggers on a
  version tag and builds all four distributions.
- **FR-012**: The release pipeline MUST authenticate to the package indexes via Trusted
  Publishing (short-lived OIDC credentials); it MUST NOT rely on a long-lived API token
  stored in the repository.
- **FR-013**: The release pipeline MUST include a publish step targeting the test index for
  all four packages. This step MUST be authored and statically validated within this feature,
  but MUST NOT be executed during this feature — the actual test-index upload is the
  operator's first manual trigger after merge.
- **FR-014**: The release pipeline MUST include a real public-index publish step that is
  present but gated behind an explicit manual approval; this step MUST NOT be executed as
  part of this feature (no irreversible public upload occurs).
- **FR-014a**: No step of the release pipeline MUST execute (upload to any external index)
  as part of this feature; the Definition of Done is reached without any external upload.
- **FR-015**: The release pipeline MUST publish the generated-stubs package before, or in an
  order that satisfies, the leaf packages' dependency on it.

#### Documentation

- **FR-016**: The project README MUST document the install matrix: the install command for
  SDK consumers, the command for each operator role, and a note that the generated-stubs
  package installs transitively.
- **FR-017**: The contributing guide MUST document the release procedure: version bump → tag
  → pipeline publish → release-notes draft.
- **FR-018**: A release-history document `docs/RELEASES.md` MUST exist and list the prior
  codebase-state tags (`v0.0.0`, `v0.0.1`) and the `v0.1.0` entry, written as
  human-readable release notes.
- **FR-018a**: A `CHANGELOG.md` in Keep-a-Changelog format MUST exist alongside
  `docs/RELEASES.md`; the `changelog` project URL declared by each package (FR-001) MUST
  point to a valid changelog target.

<!--
  Documentation principle for this feature: every doc artifact below is held to a
  simplicity-and-clarity bar. Prefer plain language and short sentences; define acronyms and
  milestone shorthand (M5.2, TTFT, OIDC, …) on first use; cut redundancy; keep terminology,
  package names, and install commands consistent across all docs. Clarity for a first-time
  reader outranks exhaustiveness.
-->

- **FR-024**: All documentation produced or edited in this feature MUST favor simplicity and
  clarity — plain language, minimal jargon, acronyms/milestone shorthand defined on first
  use, and short, scannable sections.
- **FR-025**: The language in the top-level `README.md` and `ANALYSIS.md` MUST be simplified
  section-by-section: dense or jargon-heavy passages rewritten in plainer terms, undefined
  acronyms/milestone references given a brief gloss or link, and reader-facing summaries kept
  near the top of each section — without removing technical accuracy or published results.
- **FR-026**: All top-level documentary files (`README.md`, `ANALYSIS.md`, `CONTRIBUTING.md`)
  MUST be scanned and reviewed for simplicity, clarity, and consistency — consistent package
  names, install commands, terminology, heading style, and cross-references across the set.

#### Release hygiene

- **FR-021**: The four published packages MUST be scanned for deprecated-API usage, and any
  deprecated calls within them MUST be remediated as part of this release.
- **FR-022**: The frontend's deprecated V0 engine path —
  `AsyncLLMEngine.from_engine_args(AsyncEngineArgs(...))` in
  `packages/frontend/src/vllm_grpc_frontend/main.py` — MUST be migrated to the V1 `AsyncLLM`
  engine surface already targeted by the M6.x harness, eliminating the recurring vLLM
  deprecation warning.
- **FR-023**: After remediation, exercising the four packages' own code paths (e.g. the
  console-script smoke checks of FR-010) MUST NOT emit deprecation warnings originating from
  those packages' own source.

#### Scope fence

- **FR-019**: This feature MUST NOT modify the benchmark harness under `tools/benchmark/`,
  the proto schema under `proto/`, or the runtime behavior/source logic of the four packages
  beyond what packaging metadata, console-script wiring, per-package READMEs, the dependency
  version bumps (FR-006b), and the deprecated-API remediation (FR-021–FR-023) require.
- **FR-020**: This feature MUST NOT perform any external upload — neither to the public index
  nor to the test index — and MUST NOT claim any distribution name on an external index.

### Key Entities

- **Distributable package**: One of the four workspace members (`vllm-grpc-gen`,
  `vllm-grpc-proxy`, `vllm-grpc-frontend`, `vllm-grpc-client`). Attributes: name, version,
  metadata, dependencies, optional console script, own README. Relationships: the three leaf
  packages depend on `vllm-grpc-gen`.
- **Release pipeline**: The automated tag-triggered process that builds and publishes the
  packages. Attributes: trigger condition (version tag), authentication mode (OIDC), target
  indexes (test + real), approval gate on the real-index step.
- **Install matrix**: The documented mapping from a user's role (SDK consumer, proxy
  operator, frontend operator) to the package they install.
- **Release-history document**: The record of codebase-state version tags and their notes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All four packages build into a wheel and a source distribution (8 artifacts
  total) with zero build errors.
- **SC-002**: Each of the four wheels installs into a clean, isolated environment with zero
  install errors.
- **SC-003**: Installing the client package into a clean environment results in zero
  proxy/frontend-only dependencies present in that environment.
- **SC-004**: The proxy and frontend console scripts each start and serve against a local
  fake engine within a short, scripted smoke check (no GPU/model).
- **SC-005**: All four distributions pass packaging-metadata validation (`twine check`-style)
  with zero errors/warnings, and the release pipeline passes static validation (workflow lint
  + reviewable, gated upload steps) — with zero external uploads performed.
- **SC-006**: 100% of the four packages carry complete metadata (description, keywords,
  classifiers, license, authors, all four project URLs, own README) when inspected.
- **SC-007**: A reader can determine the correct install command for any of the three
  personas from the README in one read, and the release procedure and v0.1.0 history entry
  are both present.
- **SC-008**: No artifact is uploaded to any external package index (neither the test index
  nor the public index) and no name is permanently claimed as a result of this feature.
- **SC-009**: Third-party dependency floors are bumped to the latest resolved versions
  (`grpcio>=1.80`, `fastapi>=0.136`, `uvicorn>=0.46`), the internal `vllm-grpc-gen` dependency
  uses `~=0.1.0`, and the full test suite remains green at those floors.
- **SC-010**: The four packages' own code emits zero deprecation warnings when their code
  paths are exercised; specifically, the frontend no longer uses the V0 `AsyncLLMEngine` path.
- **SC-011**: Every per-package README contains a runnable usage snippet; both `CHANGELOG.md`
  and `docs/RELEASES.md` exist with a `v0.1.0` entry; and every package's `changelog` URL
  resolves to a valid target.
- **SC-012**: Across all top-level documentary files, package names, install commands, and
  shared terminology are consistent (zero contradictory or stale variants), and every acronym
  or milestone shorthand is defined or linked on first use within each file.

## Assumptions

- The four distribution names follow PLAN.md (`vllm-grpc-gen`, `vllm-grpc-proxy`,
  `vllm-grpc-frontend`, `vllm-grpc-client`) and are available (or reservable) under the
  maintainer's account on both the test and real indexes; if any name is already claimed by a
  third party, implementation escalates rather than shipping a colliding name.
- The maintainer can configure a Trusted Publishing relationship for each package on both the
  test and real indexes; this configuration is an operator prerequisite performed alongside
  (not blocked by) this feature's code changes.
- The supported runtime is Python 3.12, consistent with the existing workspace.
- vLLM remains a peer dependency of the frontend and is installed separately by the operator
  for their platform; the project does not vendor or pin vLLM as a transitive dependency.
- Both the test-index upload and the real public-index publish are deliberate, manually-
  triggered operator actions taken after this feature merges; this feature delivers and
  validates everything needed for those actions but performs neither.
- The existing per-package source layout and runtime logic are correct; only packaging
  concerns (metadata, console scripts, READMEs, index-resolvable dependencies) are in scope.

## Dependencies

- Builds on the completed v0.0.1 bench-harness refactor; the `packages/` workspace members
  already exist with working source and a build backend configured.
- Independent of research milestones M7/M8 — per PLAN.md, v0.1.0 can land before, between, or
  in parallel with them.

## Out of Scope

- Publishing the benchmark harness (`tools/benchmark/` stays internal — heavy torch/numpy
  footprint, no SDK value).
- Removing vLLM as a peer dependency of the frontend (it stays peer, not transitive).
- 1.0 API stabilization (deferred until the proto schema is frozen).
- Any change to proto definitions, the benchmark harness, or runtime package logic beyond
  packaging needs.
- Executing any external upload — the test-index upload and the real public-index publish are
  both gated, manual, post-merge operator actions.
