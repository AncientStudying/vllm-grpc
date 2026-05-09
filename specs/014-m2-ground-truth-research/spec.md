# Feature Specification: Milestone 2 — Cross-Repo Ground-Truth Research and Plan Realignment

**Feature Branch**: `014-m2-ground-truth-research`
**Created**: 2026-05-09
**Status**: Draft
**Input**: User description: "Milestone 2 — Cross-Repo Ground-Truth Research as documented in README.md and decide or propose changes to docs/PLAN.md to accomodate the currently laid out milestones 2+ in README.md"

## Clarifications

### Session 2026-05-09

- Q: Should `cross-repo.json` and the project's `graphify-out/` be committed to git, or gitignored? → A: Gitignore both — locally-built artifacts; the refresh skill makes rebuild cheap.
- Q: How should the refresh skill determine which vLLM and grpcio versions to graph? → A: Auto-detect from `uv.lock` / `pyproject.toml` — pin lives in one place; refresh stays in sync with project dependencies.
- Q: When the refresh skill detects a stale upstream cache (lockfile pin differs from cached graph version), how should it behave? → A: Auto-rebuild the affected upstream graph and surface the rebuild as a per-step entry in the skill's output (e.g., "rebuilding vLLM @ 0.21.0 (was 0.20.0)").

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Maintainer Has Authoritative Upstream References Wired In Before M3 Tuning Begins (Priority: P1)

The maintainer (and Claude Code on their behalf) is about to make decisions in Milestone 3 about proto schema shape, gRPC channel options, and decode tuning. Before that work begins, they need a reliable way to consult vLLM (the inference engine) and grpcio (the wire stack) as authoritative references — without grepping the upstream repos by hand each time. The cross-repo knowledge graph is built, merged, and queryable; CLAUDE.md tells the agent when to use it; an auto-rebuild hook keeps the local side fresh.

**Why this priority**: M3 wire-tuning decisions ride on accurate knowledge of two upstream codebases. Without indexed references in place, every M3 question becomes an open-ended file hunt or a guess. This is the primary value M2 delivers — every later milestone benefits.

**Independent Test**: From a fresh clone, follow the workflow document end-to-end and confirm that (a) `cross-repo.json` exists and is loadable, (b) a vLLM-internals query returns useful results (god nodes near `LLMEngine`, `AsyncLLM`, scheduler, model executor), (c) a grpcio-channel query returns useful results (god nodes near `Channel`, `Server`, channel options, HTTP/2 framing), and (d) the post-commit hook fires on a local commit and rebuilds the project graph.

**Acceptance Scenarios**:

1. **Given** the maintainer is starting an M3 task, **When** they (or Claude Code) ask "how does grpcio enforce max_message_size on streaming responses?", **Then** a query against `cross-repo.json` returns a relevant call path and the answer is grounded in upstream source rather than fabricated.
2. **Given** vLLM is bumped in the project's lockfile, **When** the maintainer follows the documented rebuild cadence, **Then** the vLLM graph is rebuilt and merged into `cross-repo.json` without ambiguity about which steps to run.
3. **Given** Claude Code is asked a `.proto`-shape question, **When** it consults its directives, **Then** it reads the relevant `.proto` file directly rather than querying the graph (because protobuf is a known gap).
4. **Given** the maintainer commits a local change, **When** the post-commit hook runs, **Then** the project's local graph is rebuilt automatically (cheap due to SHA256 cache) without manual intervention.

---

### User Story 2 — Forward-Looking Project Plan Reflects the Current Milestone Framing (Priority: P2)

A reader of `docs/PLAN.md` — the maintainer planning the next milestone, or a contributor trying to understand the project's research direction — sees a forward-looking section that matches the README's M1–M5 milestone framing. The historical Phase 1–7 content that captured Milestone 1's actual delivery is preserved as completed-work history, clearly marked as superseded for forward planning. Milestone entries align with the README, link to the ground-truth workflow document, and point M3 at the mock-model approach upstream guidance validated.

**Why this priority**: The README defines the canonical research roadmap (M1–M5). PLAN.md, as drafted, is in an older Phase 1–7 form that captured implementation tactics. Without realignment, the two documents drift and the canonical milestone language lives only in the README. Important enough to do alongside M2; not blocking M2 itself.

**Independent Test**: Read `docs/PLAN.md` cold. Confirm it identifies the current state as Milestone 1 complete, describes M2–M5 in the same one-to-two-sentence research-question form the README uses, and references both the ground-truth workflow document and the mock-model decision (hidden_size rather than parameter count) for M3.

**Acceptance Scenarios**:

1. **Given** a reader opens `docs/PLAN.md`, **When** they reach the milestone section, **Then** they can identify M1 as delivered, M2 as the active formalization milestone, and M3–M5 as upcoming research directions consistent with the README.
2. **Given** a reader wants to understand why M3 uses a mock model rather than real weights, **When** they read the M3 entry in `docs/PLAN.md`, **Then** the entry states that wire size is governed by `hidden_size` (canonical 2048 / 4096 / 8192) and a real model is not required.
3. **Given** a reader finishes the M2 entry, **When** they look for the workflow detail, **Then** the entry links to `ground-truth-workflow-for-associated-projects.md` rather than restating its content.
4. **Given** a reader compares PLAN.md against README.md, **When** they read the M2–M5 descriptions in both, **Then** the research questions match in framing and intent (no contradictions, no orphaned milestones).

---

### User Story 3 — Project-Local Skills Make the Graph-Refresh Workflow a Single Step (Priority: P2)

The maintainer (or Claude Code on their behalf) needs to keep `cross-repo.json` fresh. Without skills, the rebuild cadence is "remember to run four shell commands in the right order, with the right arguments, against the right repos" — and stale graphs are the workflow doc's named main failure mode. With skills, refresh becomes a single invocation: a slash command (or a small set of them) wraps the graphify operations — clone-or-update vLLM, clone-or-update grpcio, rebuild local, merge into `cross-repo.json` — surfaces progress and outcome, and reuses graphify's SHA256 cache so unchanged work is skipped.

**Why this priority**: The workflow exists in P1, but it only delivers value if it's actually run when triggers fire (dependency bumps, upstream pulls, substantial refactors). Skills convert remembering-and-typing into one-command ergonomics, directly mitigating the staleness failure mode. P2 because the workflow itself is usable without skills (graphify CLI works fine for someone who reads the doc); skills are the friction-reduction layer that makes the cadence durable.

**Independent Test**: With graphify already installed, invoke the project's graph-refresh skill from Claude Code and confirm that (a) it runs the documented sequence end-to-end, (b) it reports per-step success or failure, (c) it produces a current `cross-repo.json` at the documented path, and (d) re-invoking it on an unchanged tree completes quickly because the SHA256 cache is honored.

**Acceptance Scenarios**:

1. **Given** the maintainer has just bumped vLLM in the project's lockfile, **When** they invoke the project's graph-refresh skill, **Then** the vLLM upstream graph is rebuilt, the local project graph is rebuilt, the merge produces a current `cross-repo.json`, and the skill reports each step's outcome.
2. **Given** the maintainer has only made local code changes, **When** they invoke the refresh skill, **Then** local rebuild and merge complete and the upstream graphs are not unnecessarily re-cloned (cache is preserved).
3. **Given** graphify is not installed on the developer's machine, **When** they invoke the refresh skill, **Then** the skill reports the missing prerequisite clearly with an actionable next step rather than failing with a generic shell error.
4. **Given** the workflow document's rebuild cadence table, **When** a contributor reads it, **Then** each trigger row names the skill to invoke for that trigger so the contributor never has to assemble the underlying graphify commands themselves.
5. **Given** Claude Code is reasoning about whether the cross-repo graph is current, **When** it consults `CLAUDE.md`, **Then** the directives point at the refresh skill as the canonical way to bring the graph back to current.

---

### User Story 4 — Workflow Practice Is Discoverable and Self-Service (Priority: P3)

A new contributor or returning maintainer finds the ground-truth workflow document via the README, opens it, and can install graphify, build the three graphs, and merge them without asking further questions. CLAUDE.md and PLAN.md both link to the same document so there is one canonical source.

**Why this priority**: The workflow only delivers value if it is actually used. Discoverability and self-serve setup matter, but P1 (workflow exists and works) and P2 (PLAN.md alignment) deliver the structural change first.

**Independent Test**: Without prior context, follow the workflow document's setup steps from a fresh machine and reach the point where `cross-repo.json` is built. Note any step that requires guessing or external context.

**Acceptance Scenarios**:

1. **Given** a contributor reads the README's M2 section, **When** they follow the link to the workflow document, **Then** the link resolves to the committed file at its stable path.
2. **Given** a contributor runs the documented setup steps, **When** they reach the merge step, **Then** they have produced `cross-repo.json` and the workflow doc has named no missing prerequisite the contributor had to figure out themselves.
3. **Given** Claude Code is asked about codebase navigation, **When** it consults `CLAUDE.md`, **Then** it finds the directives that point at `cross-repo.json` and the documented exception for `.proto` questions.

---

### Edge Cases

- The cloned vLLM and grpcio graphs go stale on upstream version bumps; rebuild cadence must be explicit so this is noticed instead of silently producing wrong answers.
- Initial graph builds for vLLM and grpcio are large — the workflow doc states what `--deep` costs and recommends starting without it.
- `.proto` files are not parsed by graphify; consumers must be told to read `proto/` directly for proto-shape questions, otherwise they may rely on incomplete graph nodes.
- CUDA kernels (`.cu`/`.cuh`) and grpcio C-core internals are partially or fully unparsed; the workflow doc must flag this so consumers don't assume coverage.
- If graphify is not installed, the workflow doc's first step covers it; otherwise setup fails with a generic shell error.
- Documentation-only changes must not regress `make check` (lint, type-check, tests).
- Preserving Phase 1–7 history in PLAN.md while adding the new milestone framing risks confusion if the boundary between historical and forward-looking content is not visually clear.
- A graph-refresh skill invoked while the network is unavailable (upstream clones fail) must distinguish "local rebuild succeeded, upstream skipped" from "everything failed" so the maintainer knows whether `cross-repo.json` is partially current or not current at all.
- A graph-refresh skill invoked when graphify is not installed must report the missing prerequisite in actionable terms (e.g., the install command), not a raw command-not-found error.
- A refresh skill running against an unrelated repository (e.g., the user has the skill in scope but is not in the vllm-grpc working tree) should refuse cleanly rather than producing a malformed merge.

## Requirements *(mandatory)*

### Functional Requirements

#### Ground-truth workflow setup

- **FR-001**: vLLM source MUST be cloned via graphify and indexed into a graph artifact at the documented path under `~/.graphify/repos/`.
- **FR-002**: grpcio source MUST be cloned via graphify and indexed into a graph artifact at the documented path under `~/.graphify/repos/`.
- **FR-003**: The project's local graph and the two upstream graphs MUST be merged into a single `cross-repo.json` artifact at a stable path inside the working directory, reproducible via the command sequence in the workflow doc. `cross-repo.json` and the project's `graphify-out/` directory MUST be gitignored as locally-built artifacts.
- **FR-004**: A graphify post-commit / post-checkout hook MUST be installed so the project's local graph auto-rebuilds on local commits and branch switches.
- **FR-005**: The Claude Code integration directive (`graphify claude install`) MUST be applied so the PreToolUse hook handles local graph queries automatically.
- **FR-006**: `CLAUDE.md` MUST contain explicit directives stating: (a) consult `cross-repo.json` for vLLM-internals questions before reading vLLM source, (b) consult `cross-repo.json` for grpcio channel-behavior questions before reading grpcio source, (c) for the project's own gRPC/proto layer the local graph plus PreToolUse hook is sufficient, and (d) `.proto` definitions are NOT in the graph and must be read directly.
- **FR-007**: A rebuild cadence table MUST be present in the workflow document covering: local commit, `git pull`, vLLM dependency bump, grpcio dependency bump, and substantial local refactor.
- **FR-008**: The workflow document MUST be committed to the repository at a stable, discoverable path that matches the link already used from `README.md`.

#### docs/PLAN.md realignment

- **FR-009**: `docs/PLAN.md` MUST contain a forward-looking milestone section that mirrors the README's M1–M5 framing, including each milestone's primary research question in one to two sentences.
- **FR-010**: `docs/PLAN.md` MUST mark Milestone 1 as delivered and reference the existing `docs/benchmarks/summary.md` for the headline numbers.
- **FR-011**: `docs/PLAN.md` MUST describe Milestone 2 as the formalization of cross-repo ground-truth research and link to the workflow document.
- **FR-012**: `docs/PLAN.md` MUST describe Milestone 3 as protobuf and gRPC tuning driven by a mock model with configurable `hidden_size` (canonical 2048 / 4096 / 8192), explicitly stating that real model weights are not required because embed payload size is determined by `hidden_size` rather than total parameter count.
- **FR-013**: `docs/PLAN.md` MUST describe Milestone 4 as corpus expansion across longer prompts, multi-turn context, and structurally varied content; and Milestone 5 as model expansion to validate the wire-overhead thesis across different sizes and architectures, including validation that mock-derived M3 findings hold against real models.
- **FR-014**: `docs/PLAN.md` MUST preserve the existing Phase 1–7 content as completed-work history with a clearly marked boundary so readers do not mistake it for a forward-looking plan.
- **FR-015**: `docs/PLAN.md` Milestone 2 entry MUST flag the same known gap the README does: graphify does not parse `.proto` files, so proto-shape questions are answered by reading `proto/` directly.

#### Skill ergonomics

- **FR-016**: The project repository MUST contain one or more Claude Code skills that wrap the graphify operations needed to keep `cross-repo.json` current — at minimum: rebuild the local project graph, refresh each upstream graph (vLLM, grpcio), and produce a merged `cross-repo.json`.
- **FR-017**: At least one skill MUST exist that performs the full refresh sequence — local rebuild, upstream refreshes (when needed), and merge — in a single invocation, so the maintainer does not have to compose the underlying graphify commands by hand.
- **FR-018**: Refresh skills MUST surface per-step progress and outcome (success / failure / skipped) and MUST report the path to the produced `cross-repo.json` on success.
- **FR-019**: Refresh skills MUST honor graphify's SHA256 cache so re-invocation on an unchanged tree completes without redoing expensive work; upstream clones MUST be reused if the pinned dependency version has not changed.
- **FR-019a**: Refresh skills MUST resolve the target vLLM and grpcio versions from the project's lockfile (`uv.lock`, falling back to `pyproject.toml` if the lockfile is absent) so the cross-repo graph stays in sync with the project's pinned dependencies without manual version arguments.
- **FR-019b**: When the resolved lockfile version differs from the version represented by the cached upstream graph, refresh skills MUST automatically rebuild the affected upstream graph and surface the rebuild as a per-step entry in the skill's output (e.g., "rebuilding vLLM graph @ 0.21.0 (was 0.20.0)") so the maintainer sees when expensive work runs.
- **FR-020**: Refresh skills MUST detect missing prerequisites (e.g., graphify not installed, working directory is not the vllm-grpc repository) and report them with an actionable next step rather than failing with a raw shell error.
- **FR-021**: The workflow document's rebuild cadence table MUST name the skill (or skills) to invoke for each trigger row so contributors do not need to know the underlying graphify CLI to follow the cadence.
- **FR-022**: `CLAUDE.md` MUST reference the refresh skill(s) as the canonical way to bring `cross-repo.json` back to current when the graph is suspected stale.

#### Cross-document consistency

- **FR-023**: The README's Milestone 2 link to the workflow document MUST resolve to the committed file at its stable path.
- **FR-024**: Milestone descriptions in `docs/PLAN.md` and `README.md` MUST not contradict one another in scope or research question; if either is updated, both stay aligned.
- **FR-025**: All documentation and skill changes MUST leave `make check` (lint, type-check, tests) passing.

### Key Entities

- **Cross-repo knowledge graph (`cross-repo.json`)**: a merged structural index over the project, vLLM, and grpcio. Used by Claude Code to ground answers about upstream internals before falling back to source reads.
- **Workflow document (`ground-truth-workflow-for-associated-projects.md`)**: the canonical procedure for installing graphify, building the three graphs, merging them, and maintaining freshness. Referenced from `README.md`, `CLAUDE.md`, and `docs/PLAN.md`.
- **Milestone roadmap**: the M1–M5 framing established in the README. M2 ratifies the ground-truth workflow; PLAN.md is realigned so the milestone roadmap is canonical in both places.
- **Graph-refresh skill(s)**: project-local Claude Code skills that wrap the graphify operations needed to keep `cross-repo.json` current. Invoked by the maintainer or by Claude Code when the rebuild cadence calls for a refresh.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer with a fresh clone can complete the workflow document's setup steps and produce a queryable `cross-repo.json` end-to-end with no missing prerequisites — measured by following the doc cold and reaching a successful merge in one pass.
- **SC-002**: A query against `cross-repo.json` for a vLLM-internals question (e.g., "how a generate request flows through the engine") returns at least one relevant god node and one usable call path; the same holds for a grpcio channel-options question.
- **SC-003**: A reader who has not seen the project before can identify Milestone 1's delivered state and Milestones 2–5's open research questions from `docs/PLAN.md` in under 2 minutes.
- **SC-004**: `README.md` and `docs/PLAN.md` describe each of M2–M5 with the same research question and scope; a side-by-side read reveals no contradictions.
- **SC-005**: After the documented rebuild cadence is followed, the project's local graph reflects the current working tree without manual intervention beyond what the workflow doc specifies.
- **SC-006**: `make check` passes after all changes — documentation-only updates introduce no lint, type, or test regressions.
- **SC-007**: Time from a maintainer asking an M3-style upstream question to receiving a graph-grounded answer is reduced relative to the pre-M2 baseline of opening upstream source files manually (qualitative measure: maintainer reports the workflow saves time on the first M3 task).
- **SC-008**: A full graph refresh — local rebuild, upstream refreshes as needed, and merge — completes via a single skill invocation; the maintainer does not assemble multi-command sequences by hand for any documented trigger.
- **SC-009**: Re-invoking a refresh skill on an unchanged working tree completes substantially faster than a cold first build (cache reuse is observable), so the cadence is cheap enough to follow routinely.
- **SC-010**: The workflow document's rebuild cadence table names a skill for every trigger row; a contributor reading the table never has to translate a trigger into a graphify CLI invocation themselves.

## Assumptions

- The ground-truth workflow document remains at its current path at the repository root (`ground-truth-workflow-for-associated-projects.md`) because the README already links to that location. Moving the file into `docs/` is out of scope for this feature.
- The existing Phase 1–7 plan content in `docs/PLAN.md` is preserved as completed-work history rather than deleted, because it captures decisions and trade-offs that still inform future work; the realignment adds a milestone overlay rather than replacing the document.
- Cloned vLLM and grpcio repos are pinned to the versions this project depends on at the time of each build. Rebuilds happen on dependency bumps; continuous-tracking of upstream `main` is out of scope.
- `--deep` mode for graphify is opt-in and not required for M2 completion. Default AST extraction is sufficient for the kinds of questions M3 will ask.
- The actual M3 wire-tuning work — protobuf shape refinements, channel option sweeps, hidden_size scans — is out of scope for this spec. M2 only puts the references in place.
- Per upstream guidance relayed via the user's son (a vLLM contributor), embed payload size is determined by `hidden_size` rather than total parameter count. M3's mock-model approach is therefore validated; this assumption flows into the M3 description in PLAN.md.
- CUDA kernels (`.cu` / `.cuh`) and grpcio C-core internals are partially or unparsed by graphify; consumers needing those layers will read source directly. This is documented, not blocking.
- The project's CI does not need to depend on `cross-repo.json`; the workflow is a local-developer aid, not a build artifact.
- Graph-refresh skills are project-local — committed under this repository's skill directory — and not packaged for cross-project distribution. Other projects that adopt the workflow can copy or adapt these skills, but generalizing them is out of scope for M2.
- Graph-refresh skills wrap existing graphify CLI commands rather than reimplementing graph extraction or merging. No new external tooling is introduced beyond graphify itself.
- Whether the refresh capability is exposed as one parameterized skill or as a small set of specialized skills (e.g., one per refresh target plus a "refresh all" composer) is a presentation choice deferred to `/speckit-plan`; the spec only requires that a single-invocation full-refresh path exists.
