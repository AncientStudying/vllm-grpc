---

description: "Task list for Milestone 2 — Cross-Repo Ground-Truth Research and Plan Realignment"
---

# Tasks: Milestone 2 — Cross-Repo Ground-Truth Research and Plan Realignment

**Input**: Design documents from `/specs/014-m2-ground-truth-research/`
**Prerequisites**: `plan.md` (loaded), `spec.md` (loaded), `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: The feature spec does not request automated tests for the documentation/skill changes. Validation is via `make check` (existing CI gate) and the Independent Test procedures embedded in each user story (`spec.md` and `quickstart.md`). No new test tasks are generated.

**Organization**: Tasks are grouped by user story. Each story is independently testable per `spec.md` Independent Test procedures and the matching `quickstart.md` checks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- File paths are absolute or repo-relative as documented

## Path Conventions

This is a documentation + tooling feature on top of an existing uv-workspace monorepo (see `plan.md` §Project Structure). All paths are relative to the repo root unless absolute. No new packages or test directories are introduced.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm one-time prerequisites that the rest of the work depends on. No source code changes.

- [ ] T001 Verify `graphify` CLI is installed and on PATH (`command -v graphify`); if missing, run `pip install graphifyy && graphify install` per `ground-truth-workflow-for-associated-projects.md` §Setup. Manual one-time check; documents prerequisite for US1, US3, US4.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Repository configuration that every user story depends on. Must complete before any user-story phase begins.

**⚠️ CRITICAL**: US1 produces `cross-repo.json` and a populated `graphify-out/` — both must be gitignored before they exist on disk to satisfy FR-003.

- [ ] T002 Add `/cross-repo.json` and `/graphify-out/` to `.gitignore` under (or near) the existing `# graphify output` block, with one-line comments naming `/ground-truth-refresh` as the rebuild path. Leave the existing more-specific entries (`graphify-out/cache/`, `graphify-out/manifest.json`, `docs/graphs/`) in place to avoid behavioral churn.

**Checkpoint**: `.gitignore` is ready — user story implementation can begin.

---

## Phase 3: User Story 1 — Authoritative Upstream References Wired In Before M3 (Priority: P1) 🎯 MVP

**Goal**: A maintainer (and Claude Code on their behalf) can consult `cross-repo.json` for vLLM-internals and grpcio-channel-behavior questions; the post-commit hook auto-rebuilds the project graph; CLAUDE.md tells the agent when to use the graph and when to read source directly.

**Independent Test** (`spec.md` US1):
1. From a fresh clone, follow the workflow doc end-to-end and confirm `cross-repo.json` exists and is loadable.
2. A vLLM-internals query returns useful results (god nodes near `LLMEngine`, `AsyncLLM`, scheduler, model executor).
3. A grpcio-channel query returns useful results (god nodes near `Channel`, `Server`, channel options, HTTP/2 framing).
4. The post-commit hook fires on a local commit and rebuilds the project graph.

### Implementation for User Story 1

- [ ] T003 [US1] Edit `ground-truth-workflow-for-associated-projects.md` — add a short paragraph under `## Setup → Merge into a cross-repo graph` stating that `cross-repo.json` and the project's `graphify-out/` directory are gitignored as locally-built artifacts (rebuilt cheaply via the refresh skill). Anchors FR-003 in the canonical workflow doc.

- [ ] T004 [US1] Edit `ground-truth-workflow-for-associated-projects.md` — add a "Versions resolved from `uv.lock`" subsection (under `## Setup` or near the cadence table) explaining that the refresh skill auto-detects target vLLM and grpcio versions from `uv.lock` (falling back to `pyproject.toml`) so refreshes stay in sync with project dependencies without manual version arguments. Anchors FR-019a.

- [ ] T005 [US1] Edit `ground-truth-workflow-for-associated-projects.md` — add an "Auto-rebuild on lockfile drift" subsection (immediately after T004's content) explaining that when the resolved lockfile version differs from the cached upstream graph's recorded version, the refresh skill automatically rebuilds the affected upstream and surfaces the rebuild as a per-step entry (e.g., `rebuilding vLLM graph @ 0.21.0 (was 0.20.0)`). Anchors FR-019b.

- [ ] T006 [P] [US1] Edit `CLAUDE.md` — add a `## Codebase navigation` section containing the four directives from `contracts/claude-md-directives.md` §2 verbatim (consult `cross-repo.json` for vLLM internals; consult for grpcio channel behavior; local graph + PreToolUse hook covers project's own gRPC/proto layer; `.proto` files read directly). Place after the existing SPECKIT block. Anchors FR-006.

- [ ] T007 [US1] One-time setup against the local clone: run `graphify claude install` (writes graphify's own block to `CLAUDE.md` and registers the PreToolUse hook) and `graphify hook install` (writes post-commit / post-checkout hooks under `.git/hooks/`). Anchors FR-004 and FR-005. Verify the new graphify block in `CLAUDE.md` does not collide with the directives added in T006.

- [ ] T008 [US1] One-time setup: run the four commands from `ground-truth-workflow-for-associated-projects.md` §Setup to produce the upstream graphs and the merged artifact — `graphify clone https://github.com/vllm-project/vllm`, `graphify clone https://github.com/grpc/grpc`, `graphify .`, `graphify merge-graphs ./graphify-out/graph.json ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json ~/.graphify/repos/grpc/grpc/graphify-out/graph.json --out cross-repo.json`. Confirms US1 acceptance scenarios 1 and 2; produces `cross-repo.json` at the documented path. (Skill-based path is delivered in US3.)

- [ ] T009 [US1] Verify US1 Independent Test items 1–3 from `quickstart.md` §Step 5: load `cross-repo.json`, run a vLLM-internals query, run a grpcio-channel-options query. Confirms SC-002.

- [ ] T010 [US1] Verify US1 Independent Test item 4 from `quickstart.md` §Step 6: make a throwaway commit, observe `graphify-out/manifest.json` mtime advance, then `git reset --hard HEAD^`. Confirms post-commit hook fires (FR-004).

**Checkpoint**: US1 complete — `cross-repo.json` is produced, queryable, and auto-rebuilt; CLAUDE.md directives are in place. The MVP path that unblocks M3 is delivered.

---

## Phase 4: User Story 2 — Forward-Looking Project Plan Reflects Current Milestone Framing (Priority: P2)

**Goal**: A reader of `docs/PLAN.md` sees a forward-looking section that mirrors the README's M1–M5 framing; the historical Phase 1–7 content is preserved as completed-work record under a clearly marked boundary.

**Independent Test** (`spec.md` US2): Read `docs/PLAN.md` cold and confirm M1 delivered, M2 active formalization, M3–M5 upcoming research questions consistent with README; M3 entry states `hidden_size` (canonical 2048 / 4096 / 8192) governs wire size and a real model is not required; M2 links to `ground-truth-workflow-for-associated-projects.md`.

### Implementation for User Story 2

- [ ] T011 [US2] Edit `docs/PLAN.md` — insert a new top-level section "Milestone Roadmap (canonical, M1–M5)" immediately after `## 0. Document Purpose`, opening with one paragraph noting M1 delivered, M2 active, M3–M5 upcoming. Implementation strategy from `research.md` R-007.

- [ ] T012 [US2] In the new milestone roadmap section of `docs/PLAN.md`, add the M1 entry: marked delivered, with a link to `docs/benchmarks/summary.md` for the headline numbers. Anchors FR-010.

- [ ] T013 [US2] In the new milestone roadmap section of `docs/PLAN.md`, add the M2 entry describing it as the formalization of cross-repo ground-truth research, linking to `ground-truth-workflow-for-associated-projects.md`, and flagging the same `.proto` known gap the README does (graphify does not parse `.proto` files; proto-shape questions are answered by reading `proto/` directly). Anchors FR-011 and FR-015.

- [ ] T014 [US2] In the new milestone roadmap section of `docs/PLAN.md`, add the M3 entry describing it as protobuf and gRPC tuning driven by a mock model with configurable `hidden_size` (canonical 2048 / 4096 / 8192), explicitly stating real model weights are not required because embed payload size is determined by `hidden_size` rather than total parameter count. Mirror the README's M3 framing for consistency (FR-024). Anchors FR-012.

- [ ] T015 [US2] In the new milestone roadmap section of `docs/PLAN.md`, add the M4 entry (corpus expansion across longer prompts, multi-turn context, and structurally varied content) and the M5 entry (model expansion validating the wire-overhead thesis across sizes/architectures, including validation that mock-derived M3 findings hold against real models). Mirror README M4/M5 framing. Anchors FR-013.

- [ ] T016 [US2] In `docs/PLAN.md`, immediately after the new milestone roadmap section, add an H2 boundary heading "Phase History (preserved as completed-work record)" with a one-sentence note that the content below predates the milestone overlay and is retained for the decisions and trade-offs it records. The existing §1 Project Overview through §8 Working with Claude Code remains unchanged below this boundary. Anchors FR-014 and the spec's "boundary must be visually clear" edge case.

- [ ] T017 [US2] Verify US2 Independent Test from `quickstart.md` §Cross-reference checks: a 2-minute cold read of `docs/PLAN.md` lets a reader identify M1 delivered, M2 active, M3 mock-model framing, M4 corpus, M5 model expansion. Confirms SC-003.

- [ ] T018 [US2] Verify FR-024 (no contradictions between `README.md` and `docs/PLAN.md` for M2–M5): side-by-side read of both files; flag and reconcile any divergence. Confirms SC-004.

**Checkpoint**: US2 complete — `docs/PLAN.md` carries the canonical M1–M5 milestone overlay and preserves Phase 1–7 history under a clear boundary.

---

## Phase 5: User Story 3 — Project-Local Skills Make the Refresh Workflow a Single Step (Priority: P2)

**Goal**: One slash-command invocation (`/ground-truth-refresh`) drives the documented refresh sequence end-to-end with per-step progress, SHA256 cache reuse, lockfile-driven version detection, and auto-rebuild on drift.

**Independent Test** (`spec.md` US3): With graphify already installed, invoke the project's graph-refresh skill from Claude Code and confirm (a) it runs the documented sequence end-to-end, (b) reports per-step success/failure, (c) produces a current `cross-repo.json` at the documented path, (d) re-invocation on an unchanged tree completes quickly because the SHA256 cache is honored.

### Implementation for User Story 3

- [ ] T019 [P] [US3] Create the skill directory `.claude/skills/ground-truth-refresh/`.

- [ ] T020 [US3] Create `.claude/skills/ground-truth-refresh/SKILL.md` — frontmatter modeled after the existing `speckit-*` skills (`name: ground-truth-refresh`, `description`, `user-invocable: true`, `disable-model-invocation: false`). Body documents the seven-step procedure from `data-model.md` §7 and `contracts/skill-commands.md` §Behavior: (1) verify cwd is vllm-grpc per `pyproject.toml [project] name`; (2) verify graphify on PATH; (3) resolve vLLM and grpcio versions from `uv.lock` falling back to `pyproject.toml`; (4) per-upstream drift check vs `~/.graphify/repos/<owner>/<repo>/graphify-out/manifest.json` with auto-rebuild and `rebuilding <repo> graph @ <new> (was <old>)` per-step output; (5) `graphify .` for project local graph; (6) `graphify merge-graphs ... --out cross-repo.json`; (7) print final status block including absolute path to `cross-repo.json`. Anchors FR-016 through FR-020 plus FR-019a/FR-019b.

- [ ] T021 [US3] In `.claude/skills/ground-truth-refresh/SKILL.md`, embed the actionable error messages required by FR-020 for: graphify-not-installed (point at `pip install graphifyy && graphify install` and at `ground-truth-workflow-for-associated-projects.md` §Setup); not-in-vllm-grpc-tree (instruct to `cd` to the repo root); vLLM/grpcio not pinned in lockfile or pyproject (skip the upstream and surface as `<package> not pinned — skipping`). Spec edge cases: missing prerequisite, unrelated-repo invocation.

- [ ] T022 [US3] Edit `ground-truth-workflow-for-associated-projects.md` — update the Rebuild cadence table so each trigger row names `/ground-truth-refresh` as the action (replacing the existing free-form actions where applicable: `git pull`, vLLM dependency bump, grpcio dependency bump, substantial local refactor; the local-commit / branch-switch row remains "auto-handled by `graphify hook install`" since that path does not need the skill). Anchors FR-021 and SC-010.

- [ ] T023 [US3] Edit `CLAUDE.md` — add a `## Keeping the cross-repo graph current` section per `contracts/claude-md-directives.md` §3 referencing `/ground-truth-refresh` as the canonical staleness recovery; place after the codebase-navigation section added in T006. Anchors FR-022.

- [ ] T024 [US3] Verify US3 acceptance scenario 1 from `quickstart.md` §Step 4: invoke `/ground-truth-refresh` from cold; confirm per-step progress, that `cross-repo.json` is produced, and that the final status line names the absolute path. Anchors FR-018, SC-008.

- [ ] T025 [US3] Verify US3 acceptance scenario 2 from `quickstart.md` §"Re-running the refresh skill": re-invoke on an unchanged tree; confirm the skipped steps are reported and total runtime is substantially faster than T024's cold run. Anchors FR-019, SC-009.

- [ ] T026 [US3] Verify US3 acceptance scenarios 3 from `quickstart.md` §Failure recoveries: temporarily move the `graphify` binary off PATH (or unset PATH in a subshell) and invoke the skill; confirm the actionable install message is surfaced rather than a raw `command not found`. Anchors FR-020.

- [ ] T027 [US3] Verify US3 acceptance scenario corresponding to drift: simulate a lockfile bump (e.g., temporarily edit `uv.lock`'s grpcio version in a worktree or use a local tag override); invoke the skill; confirm the `rebuilding grpcio graph @ <new> (was <old>)` per-step entry appears. Revert the lockfile change after the verification. Anchors FR-019b.

**Checkpoint**: US3 complete — the refresh cadence is one slash-command, the cadence table names that command, and CLAUDE.md points at it as the staleness recovery path.

---

## Phase 6: User Story 4 — Workflow Practice Is Discoverable and Self-Service (Priority: P3)

**Goal**: A new contributor or returning maintainer finds the workflow document via the README, opens it, and can install graphify, build the three graphs, and merge them without asking further questions. CLAUDE.md and PLAN.md both link to the same canonical document.

**Independent Test** (`spec.md` US4): Without prior context, follow the workflow document's setup steps from a fresh machine and reach the point where `cross-repo.json` is built. Note any step that requires guessing or external context.

### Implementation for User Story 4

- [ ] T028 [P] [US4] Verify the README's M2 link to `ground-truth-workflow-for-associated-projects.md` resolves to the committed file at the repo-root path. Read-only consistency check; anchors FR-023 and FR-008.

- [ ] T029 [P] [US4] Verify that all three documents — `README.md`, `CLAUDE.md`, `docs/PLAN.md` — link to the same canonical workflow path (`ground-truth-workflow-for-associated-projects.md` at the repo root). Spec assumption: the workflow doc stays at the root path the README already uses. No edits expected unless a divergent path is found.

- [ ] T030 [US4] Walkthrough validation per `quickstart.md` Steps 1–5 from a clean shell (no prior cwd assumptions, no shell aliases): confirm each step's command runs unmodified, every prerequisite is named in the workflow doc, and the maintainer reaches a queryable `cross-repo.json` in one pass with no missing context. Confirms SC-001 and US4 Independent Test.

**Checkpoint**: US4 complete — workflow is discoverable from the README, documented self-serve, and verified end-to-end from a cold start.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Repository-wide checks and timing guards that don't belong to any single user story.

- [ ] T031 Run `make check` (ruff + mypy --strict + pytest) and confirm zero regressions; FR-025 and SC-006 require the existing CI gate to stay green after the documentation, gitignore, and skill changes.

- [ ] T032 [P] `git status` after T031: confirm `cross-repo.json` and `graphify-out/` do not appear as untracked or modified entries. Anchors FR-003 and the gitignore work in T002.

- [ ] T033 SC-007 qualitative check: at the start of the next M3-style upstream question, confirm the workflow saves time relative to the pre-M2 baseline of opening upstream source manually; record the impression in `docs/decisions/` if M3 work has begun, otherwise close out as deferred.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 is a prerequisite check, not a code change. Can be done at any time before T008 (and T024–T027) executes.
- **Foundational (Phase 2)**: T002 (gitignore) MUST complete before T008 (which produces `graphify-out/` and `cross-repo.json`) and before T024 (skill verification that produces `cross-repo.json`).
- **User Stories (Phase 3+)**: All depend on the Foundational phase.
  - US1 (P1) is the MVP and should be completed first.
  - US2 (P2) is independent of US1, US3, US4 and can run in parallel by a different contributor.
  - US3 (P2) depends on US1's `cross-repo.json` having been produced at least once (T008 must precede T024, T025, T027). T019–T023 can be done before T008 — they are content edits that do not require runtime artifacts.
  - US4 (P3) depends on US1 and US3 having edited `README.md`, `CLAUDE.md`, and `docs/PLAN.md` so the cross-link consistency check has the final state to validate. T028–T029 are read-only consistency checks; T030 is the cold-start walkthrough.
- **Polish (Phase 7)**: T031 runs after all other tasks. T032 runs after T031. T033 is deferrable.

### User Story Dependencies

- **US1 (P1)**: Depends on Phase 2 (T002 gitignore). No dependencies on US2/US3/US4.
- **US2 (P2)**: Depends on Phase 2 only (no shared file with US1/US3 except `docs/PLAN.md`, which is exclusively US2's territory). Can run in parallel with US1 and US3.
- **US3 (P2)**: Depends on Phase 2; requires US1's T008 to have produced `cross-repo.json` once before T024–T027 verifications run. The skill-creation tasks (T019–T023) and CLAUDE.md edits can be done independently of US1's runtime tasks.
- **US4 (P3)**: Read-only verifications; depends on US1's CLAUDE.md edits (T006) and US2's `docs/PLAN.md` edits (T013) and US3's CLAUDE.md addition (T023) being in place so the cross-link check has final content to validate.

### Within Each User Story

- US1: T003–T005 (workflow doc edits) are independent of T006 (CLAUDE.md edit) and can run in parallel; T007 (graphify install) and T008 (initial graphify build + merge) MUST follow T002; T009 and T010 (verifications) MUST follow T008.
- US2: T011 sets up the new section; T012–T015 fill it in (parallel-safe with each other once T011 is done); T016 adds the boundary heading and reorganizes the existing content; T017 and T018 are verifications that follow T011–T016.
- US3: T019 (mkdir) precedes T020 (SKILL.md); T021 amends T020 in the same file. T022 (workflow doc cadence) and T023 (CLAUDE.md addition) are independent of T020/T021 and can run in parallel. T024–T027 are verifications that follow T020–T023 and require US1's T008 to have run.
- US4: T028 and T029 are independent read-only verifications; T030 is the end-to-end walkthrough.

### Parallel Opportunities

- T003, T004, T005 (workflow doc subsections) can be drafted in parallel — they target different sections of the same file but a final sequential write merges them; if a contributor batches them, they become one edit pass.
- T006 (CLAUDE.md navigation directives) is parallel with T003–T005 (different file).
- T011–T016 (PLAN.md edits, single file) are sequential; cross-story, T011 onward is parallel with US1's T003–T010.
- T019 (mkdir), T020 (SKILL.md), and T022 (workflow doc cadence table edit) — T019 and T022 can run in parallel; T020 follows T019.
- T028 and T029 (read-only verifications in US4) can run in parallel.

### Cross-Story Parallelism

- US1, US2, US3 content tasks can be split across contributors: one works workflow doc + CLAUDE.md (US1), one works docs/PLAN.md (US2), one works the skill + cadence table + CLAUDE.md refresh-skill section (US3). Single-writer coordination on `CLAUDE.md` (T006 from US1, T023 from US3) is the only file conflict — sequence those two writes.

---

## Parallel Example: User Story 1

```bash
# Independent file edits within US1 (different files, no shared state):
Task: "Edit ground-truth-workflow-for-associated-projects.md to add gitignore policy paragraph (T003)"
Task: "Edit ground-truth-workflow-for-associated-projects.md to add Versions resolved from uv.lock subsection (T004)"
Task: "Edit ground-truth-workflow-for-associated-projects.md to add Auto-rebuild on lockfile drift subsection (T005)"
Task: "Edit CLAUDE.md to add Codebase navigation section (T006)"
```

The first three target the same file and ultimately serialize at write time; T006 is genuinely parallel.

---

## Parallel Example: Cross-Story (US1 + US2 + US3)

```bash
# Three contributors in parallel:
Contributor A (US1):  T003–T010 (workflow doc, CLAUDE.md navigation, initial graphify build)
Contributor B (US2):  T011–T018 (docs/PLAN.md milestone overlay)
Contributor C (US3):  T019–T023 (skill + cadence-table edit + CLAUDE.md refresh-skill section)

# Coordination point: T006 (US1 CLAUDE.md edit) and T023 (US3 CLAUDE.md addition) target
# the same file. Write T006 first, then T023, or batch them in one edit pass.
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (T001 — graphify installed).
2. Complete Phase 2 (T002 — gitignore).
3. Complete Phase 3 (T003–T010 — workflow doc edits, CLAUDE.md navigation, graphify install + merge).
4. **STOP and VALIDATE**: Run the User Story 1 Independent Test from `spec.md` (cross-repo.json loadable, vLLM and grpcio queries return useful results, post-commit hook fires). This is the single most important M2 deliverable — the upstream references that unblock M3.
5. If MVP-only is acceptable, stop here. M2 is partially delivered: the workflow exists; PLAN.md realignment, refresh skill, and discoverability checks remain.

### Incremental Delivery

1. Setup + Foundational → ready.
2. US1 → MVP delivered (M3 unblocked).
3. US2 → PLAN.md aligned with the README's M1–M5 framing (independent of US1).
4. US3 → refresh ergonomics (cadence becomes one slash-command).
5. US4 → discoverability verified end-to-end from a cold clone.
6. Phase 7 polish.

### Parallel Team Strategy

Three contributors can work US1, US2, and US3 simultaneously after Phase 2 completes. Coordinate two writes to `CLAUDE.md` (T006, T023). US4 follows once all three stories' file edits land.

---

## Notes

- Tests are not generated for this feature: the work is documentation, configuration, and a Markdown skill file. `make check` (ruff + mypy --strict + pytest) is the existing gate and is verified in T031. Spec FR-025 and SC-006 require this gate to stay green; no new test infrastructure is in scope.
- `[P]` markers indicate genuine file-disjoint parallelism; tasks that target the same file are sequenced even when they could conceptually run together.
- Spec.md Independent Tests are the authoritative validation; `quickstart.md` walks through them step by step.
- Commit cadence: commit per story (US1, US2, US3, US4) at the checkpoint, or per logical group (workflow doc edits, CLAUDE.md edits, PLAN.md realignment, skill creation, cross-doc verification).
- Avoid: editing `proto/`, `packages/`, `tools/`, or `tests/` — none of those directories are in scope for M2. If a task tempts you to touch them, re-read the spec's Out-of-Scope clauses and the constitution's Phase Discipline principle.
