# Feature Specification: M6.0a — Concurrent Dispatch Restoration

**Feature Branch**: `024-m6-0a-concurrent-dispatch`
**Created**: 2026-05-16
**Status**: Draft
**Input**: User description: "M6.0a as described in PLAN.md"

## User Scenarios & Testing *(mandatory)*

<!--
  M6.0a is a methodology-correction sub-milestone discovered during M6.1.1's
  first live Phase 1 run (2026-05-16). The M6 / M6.1 / M6.1.1 benchmark
  harness inherited M5.x's cell × cohort × concurrency matrix but silently
  dropped concurrent in-flight dispatch — measurements at c=4 and c=8 ran
  sequentially. The classifier inside M6.1.1 that distinguishes engine
  channel-dependent batching from chronological state drift presupposes
  multiple in-flight RPCs; under sequential dispatch its labels are
  mechanically suspect. M6.0a is the surgical harness fix that restores
  real concurrent dispatch so M6.1.1's classifier can produce a trustworthy
  verdict. It is harness-only (no engine, no model, no Modal changes) and
  blocks M6.1.1's PR #27 from closing.
-->

### User Story 1 - Restore Real Concurrent Dispatch in the M6 Harness (Priority: P1)

A benchmark operator running `python -m vllm_grpc_bench --m6_1_1-diagnose` (or any
M6 / M6.1 / M6.1.1 sweep) at concurrency `c=4` or `c=8` needs the harness to
issue all four (or eight) RPCs of a batch *concurrently* — so the engine sees
overlapping requests across cohorts and its continuous-batching scheduler can
actually demonstrate (or fail to demonstrate) the channel-dependent batching
effect the M6.1.1 classifier tests for. Today the harness dispatches batch
indices one at a time inside an `await` loop, so `c` controls round-robin
batch sequencing but never produces more than one in-flight RPC.

**Why this priority**: Without this fix M6.1.1 cannot publish a trustworthy
classifier verdict — the `channel_dependent_batching` label cannot
mechanistically apply under sequential dispatch, so any current label is
either a false positive on chronological state drift or a mis-attribution.
This is the only blocker between the open M6.1.1 PR #27 and a closeable
Phase 1 result. M6 and M6.1's main verdicts (engine cost dominates,
prompt-embeds engine path equivalence) survive because they don't lean on
the concurrency axis; the per-cohort drift sub-finding M6.1.1 was created
to investigate is the data point most likely to change.

**Independent Test**: Can be fully tested by running a regression test that
wraps the benchmark driver with a counting Semaphore fake — the test asserts
that the peak number of concurrent driver entries across a `c=4` batch is
exactly 4 (and 8 for `c=8`). The test passes against the corrected harness
and fails against the current sequential harness, with no Modal compute
required.

**Acceptance Scenarios**:

1. **Given** the harness is invoked at concurrency `c=4`, **When** a measurement batch is dispatched to a counting fake driver, **Then** the peak observed concurrent driver entries equals 4.
2. **Given** the harness is invoked at concurrency `c=8`, **When** a measurement batch is dispatched to a counting fake driver, **Then** the peak observed concurrent driver entries equals 8.
3. **Given** the harness is invoked at concurrency `c=1`, **When** a measurement batch is dispatched, **Then** the peak observed concurrent driver entries equals 1 (no regression in the singleton case).
4. **Given** a re-run of `--m6_1_1-diagnose` under the corrected harness, **When** the run completes, **Then** every recorded seed equals the seed the pre-fix harness would have used for the same `(cohort, batch index, base_seed)` triple (seed determinism preserved).
5. **Given** the regression test fails, **When** CI evaluates the M6.1.1 PR #27 merge gate, **Then** the merge is blocked.

---

### User Story 2 - Re-run M6.1.1 Phase 1 Under Corrected Dispatch (Priority: P2)

A future M6.x reader (or the M6.1.1 PR #27 reviewer) needs a definitive
classification for the chat_stream per-cohort `engine_ttft_ms` drift sub-finding
M6.1 published and M6.1.1 was created to investigate. The 2026-05-16 sequential-
dispatch baseline shows 19.5 % spread at `c=1` (mechanically inevitable under
the current classifier even if the underlying signal is zero), 6.0 % at `c=4`,
and 8.4 % at `c=8` — those numbers are *real* but their `channel_dependent_batching`
label is uninterpretable under sequential dispatch. After Story 1 lands, one
~30 min Modal run produces the corrected classification.

**Why this priority**: This is the deliverable that *closes* the M6.0a
methodology gap and unblocks M6.1.1 Phase 2 dispatch (symmetrisation code
change vs documented-effect note). Without this re-run the harness fix is
inert — there is no "after" data to compare against the audit baseline.

**Independent Test**: Can be fully tested by inspecting the artifacts written
by the re-run: the resulting markdown / JSON contains a `dispatch_mode`
attribute equal to `concurrent`, the per-cohort `engine_ttft_ms` spreads are
reported for each chat_stream cell, and the Phase 2 dispatch verdict (either
"drift drops below 5 % → state-drift artifact, Phase 2(a) not needed" or
"drift stays at or above 10 % → channel-dependent batching, Phase 2 applies")
is recorded as a single explicit field in the manifest.

**Acceptance Scenarios**:

1. **Given** the corrected harness is deployed, **When** the operator runs `python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1`, **Then** the run completes within 45 min wall-clock and produces both a markdown report and a JSON companion.
2. **Given** the corrected-dispatch run completes, **When** an automated reader parses the JSON manifest, **Then** the manifest contains a `dispatch_mode: concurrent` annotation distinguishing it from the sequential baseline.
3. **Given** the corrected-dispatch run completes, **When** the chat_stream per-cohort `engine_ttft_ms` spread is computed for each cell (`c=1`, `c=4`, `c=8`), **Then** the spread values are reported in the markdown table together with the audit baseline values for direct comparison.
4. **Given** the chat_stream per-cohort spread under corrected dispatch, **When** the spread for every cell drops below 5 %, **Then** M6.1's reported drift is annotated as a sequential-dispatch state-drift artifact and Phase 2(a) symmetrisation is recorded as not needed.
5. **Given** the chat_stream per-cohort spread under corrected dispatch, **When** the spread for any cell stays at or above 10 %, **Then** the drift is annotated as a real channel-dependent batching effect and Phase 2 (a or b) of M6.1.1 applies per the existing contract.

---

### User Story 3 - Publish the Dispatch-Correction Note for Future Readers (Priority: P3)

A future M6.x or M7 consumer reading the published benchmark archive needs a
short, self-contained explanation of (a) the dispatch-mode bug the M6 family
of milestones carried, (b) the surgical fix, and (c) the empirical before /
after evidence — so they can correctly weight every M6 / M6.1 / M6.1.1
finding by whether it is dispatch-sensitive or dispatch-robust. The PLAN.md
table already lists which findings fall in each bucket; M6.0a closes the loop
with measured evidence.

**Why this priority**: This is documentation that crystallises Stories 1 and 2
into something a reader six months from now can interpret without reading the
git history or the PR thread. It is genuinely valuable but not on the critical
path to closing M6.1.1's PR #27 — the PR can merge once Stories 1 and 2 are
done, with this note following in a small docs PR.

**Independent Test**: Can be fully tested by checking that
`docs/benchmarks/m6_0a-dispatch-correction.md` exists, has a stable URL, links
to the audit baseline (`m6_1_1-audit-2026-05-16-seq-dispatch.md`) and the
corrected-dispatch artifact, and is cross-referenced from PR #27 and from
M6.1's published narrative.

**Acceptance Scenarios**:

1. **Given** Stories 1 and 2 are complete, **When** a reader visits `docs/benchmarks/m6_0a-dispatch-correction.md`, **Then** they find a one-page explanation of the bug, the fix, the regression test, and a side-by-side per-cohort spread comparison (audit baseline vs corrected run).
2. **Given** the note is published, **When** a reader follows the cross-links, **Then** they can reach the audit baseline artifact, the corrected-dispatch artifact, the M6.1.1 PR #27 review thread, and the PLAN.md M6.0a section.
3. **Given** M6.1 / M6.1.1 documents are read in the future, **When** a reader encounters per-cohort engine_ttft language, **Then** an inline annotation (or footnote) directs them to the M6.0a note for dispatch-sensitivity caveats.

---

### Edge Cases

- **What happens if the corrected concurrent dispatch surfaces an engine-side issue (e.g., shared-state corruption or a Modal-side rate limit) that didn't appear under sequential dispatch?** The run is halted, the failure is recorded in the manifest, and the issue is filed as an out-of-scope blocker (M6.0a is harness-only; engine-side fixes belong to a separate milestone).
- **What if the per-cohort spread falls in the (5 %, 10 %) middle band — neither clearly drift nor clearly channel-dependent?** The existing M6.1.1 FR-010 classifier runs and produces whatever label its thresholds yield; the output drives Phase 2 dispatch through M6.1.1's existing decision rules. M6.0a does not change those thresholds.
- **What if seed determinism breaks under the corrected concurrent dispatch (e.g., the new implementation accidentally couples to async ordering)?** Acceptance Scenario 1.4 fails, the regression test catches it, the fix is rejected before merge. Determinism is a hard precondition.
- **What if a single RPC in a concurrent batch fails partway?** The harness applies the existing retry / failure-handling rules unchanged — concurrent dispatch is purely a structural change to the dispatch step, not to retry or error policy.
- **What if Modal cold-start or handshake timing differs under concurrent dispatch (e.g., handshake reuse changes)?** Cold-start data is recorded in the manifest as it always has been; if the cold-start profile differs from the audit baseline, the difference is reported but does not block closure.
- **What if the corrected re-run shows per-cohort spreads at the audit baseline values (no change)?** That result *is* the finding — it tells us the per-cohort drift is not driven by batching cross-pollination and supports the channel-dependent attribution. Phase 2 of M6.1.1 then proceeds under the channel-dependent branch.
- **What if PR #27 reviewers request that the audit baseline be re-classified rather than preserved as-is?** The audit file is preserved verbatim (it was committed for that purpose); any re-classification happens in a follow-up edit to the corrected-dispatch artifact, not by overwriting history.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The M6 measurement-loop dispatch step at concurrency `c` MUST issue up to `c` RPCs concurrently — so that across cohorts a single batch has up to `c` simultaneously in-flight RPCs visible to the engine.
- **FR-002**: The dispatch fix MUST preserve per-RPC seed determinism — every `(cohort, batch index, base_seed)` triple resolves to the same seed under the corrected harness as under the pre-fix harness, regardless of completion order.
- **FR-003**: A regression test MUST verify peak in-flight concurrency at `c=4` and `c=8` cells using a counting fake driver (e.g., a `Semaphore`-wrapped harness that records the maximum simultaneous entries), with `c=1` covered as a no-regression case.
- **FR-004**: The regression test failure MUST block the M6.1.1 PR #27 merge — the test is wired into the same gate set as ruff / mypy / pytest.
- **FR-005**: M6, M6.1, and M6.1.1 MUST inherit the corrected dispatch behaviour through the existing measurement loop — there MUST NOT be a parallel-fork "concurrent vs sequential" code path the operator chooses between.
- **FR-006**: The `concurrency` field's documented semantics in the M6 / M6.1 / M6.1.1 type definitions MUST be updated from "metadata tag for round-robin sequencing" back to "actual in-flight parallelism", matching M5.x semantics.
- **FR-007**: A corrected-dispatch re-run of `--m6_1_1-diagnose` MUST produce a manifest annotated with `dispatch_mode: concurrent` (or an equivalent unambiguous attribute) so downstream consumers can distinguish it from the 2026-05-16 sequential baseline.
- **FR-008**: The corrected-dispatch re-run MUST use parameters identical to the sequential baseline (`Qwen3-8B fp16`, Modal A10G eu-west-1, base seed 42, `n=50` per cohort per cell, 500 µs perturbation budget) — dispatch mode is the only variable that changes.
- **FR-009**: The corrected-dispatch run's chat_stream per-cohort `engine_ttft_ms` spread MUST be reported in the published markdown for each cell (`c=1`, `c=4`, `c=8`), alongside the audit baseline spread for direct comparison.
- **FR-010**: The M6.1.1 Phase 2 dispatch decision derived from the corrected run MUST be recorded as a single explicit field in the manifest — either "spread below 5 %, Phase 2(a) not needed" or "spread at or above 10 %, Phase 2 (a or b) applies" or "intermediate, follow FR-010 classifier output".
- **FR-011**: The 2026-05-16 sequential-baseline audit file (`docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md`, committed at `b63947a`) MUST be preserved verbatim as the "before" data set — no edits to its body, only additive cross-links from new artifacts may reference it.
- **FR-012**: A short dispatch-correction note (`docs/benchmarks/m6_0a-dispatch-correction.md`) MUST be published containing: bug description, fix summary, regression-test description, and a side-by-side per-cohort spread table (audit baseline vs corrected run).
- **FR-013**: The dispatch-correction note MUST cross-link to (a) the audit baseline artifact, (b) the corrected-dispatch artifact, (c) PR #27, and (d) PLAN.md's M6.0a section.
- **FR-014**: M6.0a MUST NOT modify engine, model, or Modal endpoint code — the fix is restricted to the benchmark harness (the `tools/benchmark/` package).
- **FR-015**: M6.0a MUST NOT modify the published verdict tables for M6's main finding ("engine cost dominates protocol cost at realistic workloads") or M6.1's main finding ("real-prompt-embeds engine path equivalent to text-prompt path") — those findings are dispatch-robust.
- **FR-016**: M6.0a's existence and outcome MUST be cross-referenced from M6.1's published narrative (the per-cohort drift sub-finding picks up a methodology-supersedence annotation once the corrected-dispatch result is known).
- **FR-017**: Total Modal compute spend for the corrective re-run MUST be at most ~$1 (one Phase 1 sweep at the existing M6.1.1 budget).

### Key Entities *(include if feature involves data)*

- **M6 Measurement Batch**: a group of RPCs (one per cohort × batch index) dispatched at a single concurrency level `c` within a single cell. Pre-fix: dispatched as a sequential `await` loop, peak in-flight = 1. Post-fix: dispatched concurrently, peak in-flight = `c`.
- **Dispatch Mode**: categorical attribute of every benchmark run, valued `sequential` (pre-fix) or `concurrent` (post-fix). Recorded in the published JSON manifest and the markdown header. Determines which classifier mechanisms in M6.1.1's FR-010 are interpretable.
- **Sequential-Baseline Audit Artifact**: the file `docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md` committed at `b63947a`. Preserved verbatim as the "before" data set. Contains real per-segment timings but mechanically inevitable classifier labels.
- **Corrected M6.1.1 Run Artifact**: the definitive Phase 1 run after the dispatch fix. Lives at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` (the canonical slot kept clean by the `m6_1_1-audit-` prefix naming choice in `b63947a`).
- **Dispatch-Correction Note**: `docs/benchmarks/m6_0a-dispatch-correction.md` — short standalone explainer cross-linking the audit baseline, the corrected run, and PLAN.md's M6.0a section. The deliverable that lets future readers weight every M6.x finding by dispatch-sensitivity.
- **In-Flight Concurrency Probe**: a counting fake driver (e.g., a `Semaphore`-wrapping harness) used by the regression test in FR-003 to assert peak simultaneous driver entries.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running the regression test against the corrected harness at `c=4` reports peak observed concurrent driver entries equal to 4; at `c=8`, equal to 8; at `c=1`, equal to 1.
- **SC-002**: The corrected-dispatch M6.1.1 Phase 1 re-run completes on Modal A10G eu-west-1 in 45 minutes or less of wall-clock time (matching the audit baseline's 26.7 min completion to within Modal cold-start variance).
- **SC-003**: The corrected-dispatch re-run produces a definitive classification for the chat_stream per-cohort `engine_ttft_ms` drift sub-finding — recorded as a single explicit manifest field falling into exactly one of three buckets: "below 5 %", "at or above 10 %", or "intermediate per FR-010 classifier output".
- **SC-004**: The dispatch-correction note `docs/benchmarks/m6_0a-dispatch-correction.md` is published and cross-linked from PR #27, M6.1's published narrative, and PLAN.md within 7 days of the corrected-dispatch run completing.
- **SC-005**: No regression in M6 or M6.1 main-verdict reproducibility — a spot-check of any one M6 or M6.1 published cell under the corrected harness produces a result whose mean falls within the published 95 % CI for that cell.
- **SC-006**: Total Modal compute cost for M6.0a's corrective re-run is $1 or less (single Phase 1 sweep at M6.1.1's existing per-run cost profile).
- **SC-007**: A reader unfamiliar with M6.x can determine in under 5 minutes (by reading only the dispatch-correction note plus its cross-links) which previously-published M6 / M6.1 / M6.1.1 findings are dispatch-sensitive and which are dispatch-robust.

## Assumptions

- M5.1 / M5.2 use a true concurrent dispatch pattern (`asyncio.gather(*(_channel_worker(i) for i in range(concurrency)))` in `m5_1_grpc_cohort.run_grpc_cohort` and `rest_cohort.run_rest_cohort`), and that pattern is the canonical reference the M6 harness will port. Confirmed by inspection prior to drafting this spec.
- M6.1.1's PR #27 stays open during M6.0a; the audit data committed at `b63947a` is the "before" baseline and is not edited.
- The Modal endpoint provisioning code (`provide_m6_endpoint` + `provide_m6_1_rpc_driver`) tolerates concurrent in-flight calls at the same level M5.1 / M5.2 produced; no Modal-side rate-limit re-tuning is anticipated.
- `compute_rpc_seed` is purely a function of `(cohort, batch index, base_seed)` and does not couple to async ordering — concurrent dispatch will not perturb it. The smoke / warmup `seed=0` convention (already accommodated by the `max(0, seed - base_seed)` clamp) is preserved verbatim.
- The 2026-05-16 audit run's per-segment timing numbers (`seg_ab`, `seg_bc`, `seg_cd`) are real and re-interpretable under corrected mechanisms — only the classifier *labels* are mechanically inevitable, not the underlying data.
- M6.1's verdict-supersedes table itself stands; only the per-cohort drift sub-finding may pick up a methodology-supersedence annotation after the corrected run.
- The open M6.1.1 PR #27 methodology issue regarding FR-010 classifier degeneracy on chat_stream cells (`seg_bc ≡ engine_ttft` by construction — filed at PR comment `4468600646`) is *not* in scope for M6.0a; it is a separate classifier-design issue handled in M6.1.1's resolution. M6.0a addresses dispatch mode only.
- The corrected-dispatch run will use the existing M6.1.1 sweep wiring (the `M6_1_1ProgressReporter`, `_default_write_report`, and `_sanitize_for_json` fixes already landed on the M6.1.1 branch) — no additional sweep-infrastructure changes are anticipated.
- "Concurrent in-flight count = c" is the operational meaning of FR-001; transient spikes from async scheduling jitter that briefly fall below `c` while RPCs complete and are not yet replaced are acceptable. The FR-003 regression assertion is on *peak* simultaneous entries, not on a sustained floor.
