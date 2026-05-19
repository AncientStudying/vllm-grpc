# Feature Specification: M6.2 — Token-Budget Characterization: Production Latency Budgets Across `max_tokens` Axis

**Feature Branch**: `027-m6-2-token-budget`
**Created**: 2026-05-19
**Status**: Draft
**Input**: User description: "M6.2"

## Clarifications

<!--
  This section is intentionally empty in the initial /speckit-specify draft.
  Populated by subsequent /speckit-clarify cycles. Each round MUST add a new
  dated heading (e.g., "### Session YYYY-MM-DD") with Q/A bullets capturing
  the operator decisions that resolve scope ambiguity in the FR / SC blocks
  below.
-->

## User Scenarios & Testing *(mandatory)*

<!--
  M6.2 lifts `max_tokens` from M5.x / M6 / M6.1 / M6.1.1 / M6.1.2 / M6.1.3's
  fixed cap (10 for embed, 50 for chat_stream — held constant so the engine
  cost approximated a control variable and the protocol/transport differential
  was the signal) to a six-point measurement axis covering the realistic
  production response-length regime: `{10, 50, 256, 512, 1024, 2048}`. The
  operator question shifts from "which protocol wins under fixed engine work"
  (M6.1's framing) to "what is the per-cohort p50 / p95 / p99 wall-clock
  budget at realistic response lengths, and at what `max_tokens` does the
  protocol choice stop mattering?".

  The harness, engine config, RPC drivers, classifier primitives, smoke gate,
  torch-pin gate, M6 baseline loader, 4-cohort iteration (`rest_plain_tcp` /
  `rest_https_edge` / `default_grpc` / `tuned_grpc_multiplexed`),
  concurrent-dispatch loop (M6.0a), per-sweep `network_paths` topology
  evidence (M6.1.2), 5-segment engine-cost decomposition (`seg_ab` /
  `seg_queue` / `seg_prefill` / `seg_ingress` / `seg_egress`, from M6.1.3),
  and `m6_1_1.v1` wire schema are ALL reused unchanged. The single new
  variable is `max_tokens` as an inner axis under each (cell × cohort) pair.
  Per the M6.1.3 cross-milestone recommendation captured in
  [ANALYSIS.md § M6.1.3](../../ANALYSIS.md#m613--phase-1-attribution-closure-proxy-edge-instrumentation-gap-engine-compute-variation-root-cause-run-to-run-variance),
  symmetric prompts (`m6_1_3_symmetric_prompts` helper) are on by default for
  this milestone unless the spec explicitly documents a deviation.

  M6.2 depends on M6.1.3 having landed and published the attributed Phase 1
  verdicts (PR #31, 2026-05-19). The `max_tokens=10` and `max_tokens=50`
  points serve as null anchors: they MUST reproduce M6.1.3's published
  measurements within published CIs (any drift surfaces as a control-drift
  warning, mirroring the M6.1.2 / M6.1.3 anchor mechanism). M6.1.3's
  attributable Phase 1 verdicts (no longer `inconclusive` for c=4 / c=8 per
  M6.1.3's `proxy_*_dominated` resolution) are the baseline reference; the
  `max_tokens` axis tests how those verdicts evolve as engine generation
  cost grows from ~10 tokens to the 2048-token ceiling.

  Out of scope: corpus diversity (M7 — prompt-side variation), additional
  models (M8), prompt-length variation in the embeddings (M7), increasing
  `max_model_len` above 2048 (M8 — requires KV-cache budget re-tuning and
  likely a smaller model or larger GPU), changes to the engine config or
  cohort definitions, additional attribution segments beyond the inherited
  five.
-->

### User Story 1 - Publish a Per-Cohort Latency Budget Table Across the `max_tokens` Axis (Priority: P1)

A future operator selecting a serving cohort for a production workload needs to know, for each access path (REST-plain-TCP / REST-HTTPS-edge / default-gRPC / tuned-gRPC-multiplexed) and each measurement cell (embed × c={1,4,8}, chat_stream × c={1,4,8}), the **p50 / p95 / p99 wall-clock latency at realistic response lengths**, not just at M6.1's protocol-isolation regime of 10–50 tokens. The published M6.1.3 verdicts answer "which protocol wins when engine work is held constant"; M6.2's published budget table answers "what does the user-visible latency budget actually look like when the workload generates 256 / 512 / 1024 / 2048 tokens, and how do the four cohorts compare on that axis". Without this table, every M6 / M6.1 / M6.1.3 finding carries an unstated "applies at `max_tokens=10 / 50` only" caveat — the gap that motivates the milestone.

**Why this priority**: The latency budget table IS the headline deliverable. Stories 2 and 3 are derived analyses on top of the same sweep data — they require User Story 1's measurement loop to be in place, but neither produces output independent of it. The budget table is what an operator reading the milestone first wants to see; the protocol-crossover threshold (Story 2) and KV-cache-pressure note (Story 3) are interpretation aids that supplement the table.

**Independent Test**: Can be fully tested by running the milestone-publish sweep (`python -m vllm_grpc_bench --m6_2 --m6_2-modal-region=eu-west-1`) end-to-end and confirming the resulting artifact JSON contains a per-cell × per-cohort × per-`max_tokens` row with `wall_p50_ms`, `wall_p95_ms`, `wall_p99_ms` fields, and that the rendered markdown contains a "Production latency budget" section with one table per cell-cohort-axis combination. Reader can independently verify that the axis exactly covers `{10, 50, 256, 512, 1024, 2048}` and that the cohort set matches the M6.1.2 / M6.1.3 4-cohort convention.

**Acceptance Scenarios**:

1. **Given** the operator launches an M6.2 sweep (publish via `--m6_2` or smoke-equivalent wiring check via `--m6_2-validate`, per the paired-flag convention M6.1.2 / M6.1.3 established), **When** the sweep orchestrator iterates the measurement matrix, **Then** for every (cell, cohort, `max_tokens`) triple the orchestrator drives `n=100` RPCs (single-run mode; no `--repeat` multiplier in M6.2 — single-run-per-point is sufficient because the per-point sample size is already n=100 vs M6.1.3's effective n=50 per anchor) using the inherited concurrent-dispatch loop and inherited symmetric-prompts helper.
2. **Given** the sweep completes, **When** the reporter assembles the artifact, **Then** the published markdown contains a "Production latency budget" section presenting `wall_p50_ms / wall_p95_ms / wall_p99_ms` for every (cell × cohort × `max_tokens`) combination, AND a per-cohort summary row aggregating across the axis ("cohort budget envelope").
3. **Given** the artifact JSON, **When** any M6.1.x-aware reader (M6.1.1 / M6.1.2 / M6.1.3 consumers) parses it, **Then** the inherited per-cell / per-cohort fields are unchanged in shape and the new `max_tokens` axis is an additive top-level key per row (strict-superset evolution per the M6.1.1 / M6.1.2 / M6.1.3 precedent); `schema_version` stays at `m6_1_1.v1` (no bump).
4. **Given** any single (cell, cohort, `max_tokens`) measurement point, **When** the per-RPC timing rows are aggregated, **Then** the inherited 5-segment engine-cost decomposition (`seg_ab_ms`, `seg_queue_ms`, `seg_prefill_ms`, `seg_ingress_ms`, `seg_egress_ms`) is computed and persisted per point — the segments do not change shape with `max_tokens` but their relative shares evolve as generation cost grows.
5. **Given** the per-sweep topology probe runs (per the M6.1.2 `network_paths` machinery), **When** the artifact emits, **Then** the `network_paths` top-level block carries one entry per cohort (`endpoint_ip`, ordered `hops`, `cloud_provider`, `region`, timestamp) — unchanged from M6.1.2 / M6.1.3.
6. **Given** a cell-cohort row at `max_tokens=10` or `max_tokens=50` (the null anchors), **When** the post-sweep validator runs, **Then** the validator compares the M6.2 measurement against M6.1.3's published mean ± CI for the same cell-cohort, AND emits a control-drift warning if the M6.2 measurement falls outside the M6.1.3 published CI (no automatic abort — drift surfaces as a per-anchor warning line in the published artifact, mirroring the M6.1.2 / M6.1.3 cohort-CSP-mismatch warning).

---

### User Story 2 - Identify the Per-Cell `max_tokens` Crossover Threshold Where Protocol Choice Stops Mattering (Priority: P2)

A future operator deciding whether to invest in the gRPC-tuned cohort needs to know **at what `max_tokens` the M6.1 / M6.1.3 protocol verdicts collapse to "no winner"** — i.e., where the cohort-pair wall-clock CIs overlap so densely that the engine generation cost dominates and the 1–50 ms protocol differential drowns out. M6.1.3 published verdicts at the 10/50-token regime; the operator needs to know whether those verdicts hold at production response lengths (256 / 512 / 1024) or collapse early. The crossover threshold is the load-bearing claim a future "should we switch to gRPC" decision references.

**Why this priority**: P2 because it derives from User Story 1's table (no independent measurement loop) and addresses the cross-axis interpretation question — important but secondary to the budget table itself. The threshold is published as a per-cell row in a separate "Protocol crossover" table; an operator reading only that table without the underlying budget data loses the ability to verify the threshold's derivation.

**Independent Test**: Can be fully tested by reading the per-cell rows in the artifact's "Protocol crossover" table and verifying that each row carries a `crossover_max_tokens` field (or sentinel `null` meaning the verdict survives across the entire axis) plus a `crossover_evidence` field explaining the cohort-pair CI-overlap calculation. A reader can independently re-derive the threshold from the underlying per-cell × per-cohort × per-`max_tokens` rows in Story 1's table and check that the published crossover matches.

**Acceptance Scenarios**:

1. **Given** the sweep has populated per-cell × per-cohort × per-`max_tokens` `wall_p50_ms` measurements with CIs, **When** the reporter computes the per-cell crossover, **Then** for each measurement cell the reporter identifies the smallest `max_tokens` value on the axis at which the M6.1.3-winning cohort's CI overlaps with the second-place cohort's CI by ≥ 50% (operational definition of "statistically indistinguishable"; exact overlap-fraction threshold is a `/speckit-plan` deliverable consistent with M6.1.3's inline-threshold-pinning precedent).
2. **Given** a cell whose M6.1.3 verdict was `inconclusive_high_variance` or a `multi_factor_*` compound label, **When** the crossover analysis runs, **Then** the cell receives `crossover_max_tokens = null` with `crossover_evidence = "base verdict was already inconclusive at the M6.1.3 baseline"` — the crossover claim is only meaningful when a base-cell winner existed.
3. **Given** a cell whose cohort-pair CIs overlap at every measured `max_tokens` (including 10/50), **When** the crossover analysis runs, **Then** the cell receives `crossover_max_tokens = 10` with `crossover_evidence` explaining that the M6.1.3 verdict was not robust to the M6.2 sweep's resampling — surfaces the rare case where M6.2's larger n re-classifies an M6.1.3 published verdict.
4. **Given** the published "Protocol crossover" markdown table, **When** an operator reads it, **Then** each row contains the cell identifier, the M6.1.3 base verdict, the M6.2 crossover_max_tokens, and a one-line interpretation ("verdict survives across the axis" / "verdict collapses at `max_tokens=X`" / "no robust winner at any axis point").

---

### User Story 3 - Characterize KV-Cache Pressure at `max_tokens=2048 × c=8` (Priority: P3)

A future M8 (model-expansion) spec author needs to know whether the Qwen3-8B + A10G + `max_model_len=2048` configuration exhibits scheduling stalls or measurable prefix-caching dynamics at the high-cap × high-concurrency regime — `c=8 × max_tokens=2048` requires 8 × 2048 = 16,384 tokens of KV-cache budget against the engine's ~31K-token ceiling (half-headroom; close to capacity but not OOM). M6 / M6.1 / M6.1.3 never exercised this regime; M6.2's `max_tokens=2048` axis point is the first time it lands.

**Why this priority**: P3 because the KV-pressure observation is incidental data the sweep produces "for free" — it does not require additional measurement infrastructure beyond Story 1's loop, but it is not the headline question M6.2 answers. M8 inherits this as a single load-bearing data point for KV-budget sizing; absent the observation, M8 would have to re-derive it.

**Independent Test**: Can be fully tested by reading the artifact's "KV-cache pressure" subsection and verifying it contains: (a) the measured KV-cache budget fraction consumed at `c=8 × max_tokens=2048`, (b) any scheduling-stall observations from vLLM's engine logs captured during the sweep (queue depth, preemption events), (c) a flag indicating whether the regime crossed into OOM territory (sweep abort) or completed cleanly.

**Acceptance Scenarios**:

1. **Given** the sweep iterates the `c=8 × max_tokens=2048` cells (chat_stream and embed), **When** the orchestrator captures engine-side metadata, **Then** per-RPC `engine_kv_cache_used_fraction` is recorded (best-effort — if vLLM does not expose the field via gRPC trailing metadata, the field is `null` and the regime is characterized via wall-clock degradation relative to the 1024-cap point).
2. **Given** the published artifact, **When** the reporter assembles the "KV-cache pressure" subsection, **Then** it contains a one-paragraph narrative on the c=8 × 2048 regime: peak KV-budget consumption, observed scheduling-stall signals if any, and a comparison to the c=8 × 1024 point (the half-budget reference).
3. **Given** the sweep encounters an OOM or hard-fail at `c=8 × max_tokens=2048`, **When** the orchestrator's fail-handler runs, **Then** the failure is logged but does NOT abort the rest of the sweep (the cell's row in the latency budget table is rendered as `failed_oom` with a footnote); other (cell, cohort, `max_tokens`) points continue to publish.

---

### Edge Cases

- **Sweep partial failure at high-cap cells.** If `chat_stream × c=8 × max_tokens=2048` (the longest single RPC, ~69 seconds per RPC, ~115 minutes per cohort at n=100) fails — Modal preemption, gRPC timeout, OOM — the orchestrator MUST record the failure per-cohort and continue with remaining cohorts; the artifact's budget table renders failed points as `failed_<reason>` rather than missing rows. The control-drift warning at `max_tokens=10 / 50` is independent of high-cap failures.
- **Modal preemption mid-sweep.** Inherits the M6.1.3 FR-028 preemption-recurrence threshold (2 — one transient recovery acceptable, second failure aborts the sweep). At ~30–40 hours of wall-clock budget, mid-sweep preemption is more likely than for any prior M6.x sweep; the auto-resume / partial-artifact-merge behavior MUST handle this without requiring full sweep restart.
- **Null-anchor drift exceeding the CI threshold.** If the `max_tokens=10` or `=50` anchor measurements fall outside M6.1.3's published CIs at MORE than a configurable fraction of cells (threshold deferred to `/speckit-clarify` / `/speckit-plan`), the artifact emits a sweep-level integrity warning, NOT just per-anchor lines. The operator decides whether to publish or rerun against a fresh Modal deploy.
- **EOS sampling truncation at high caps.** The `max_tokens=2048` point sets the generation length deterministically to the ceiling (NOT "uncapped") to avoid EOS-token-sampling variance — Qwen3-8B will sample EOS before 2048 tokens on most prompts. The deterministic cap is necessary so the measurement reflects the "what if generation runs to KV ceiling" worst-case, not the natural-EOS distribution.
- **Topology drift mid-sweep at extended wall-clock.** At ~30–40 hours, the M6.1.2 `network_paths` probe may capture different cohort topologies between sweep start and sweep end. The probe MUST re-run periodically (frequency deferred to `/speckit-clarify`) so the artifact carries a topology trajectory rather than a single start-of-sweep snapshot.

## Requirements *(mandatory)*

### Functional Requirements

**Token-budget axis (M6.2's only structural change vs M6.1.3):**

- **FR-001**: The sweep orchestrator MUST iterate `max_tokens ∈ {10, 50, 256, 512, 1024, 2048}` as the innermost axis under each (cell × cohort) pair. The six values are spec-level literals; the orchestrator MUST NOT accept a CLI override that changes the axis set in milestone-publish mode (`--m6_2`). A `--m6_2-validate` smoke-equivalent mode MAY restrict to a subset of the axis (default and exact subset deferred to `/speckit-clarify` / `/speckit-plan`).
- **FR-002**: Both `embed` and `chat_stream` cells MUST vary the axis. Embed's measurement at `max_tokens > 10` becomes a hybrid engine-path + generation signal (informative for retrieval-then-generate workloads); chat_stream remains a pure generation-latency measurement.
- **FR-003**: The `max_tokens=2048` point MUST be set deterministically (not "uncapped") so EOS-token-sampling variance does not confound the worst-case KV-pressure observation. `max_model_len=2048` is the engine ceiling and MUST NOT be increased in M6.2 (deferred to M8).
- **FR-004**: Per-(cell × cohort × `max_tokens`) sample size MUST be `n=100` RPCs in the publish sweep (`--m6_2`); the smoke-equivalent (`--m6_2-validate`) sample size is `n=20` per point (final value deferred to `/speckit-clarify`).
- **FR-005**: The sweep MUST drive `(cell × cohort × max_tokens)` measurement points concurrently within a single Modal deploy session — no per-axis-point Modal redeploy. The total measurement-point count is `6 cells × 4 cohorts × 6 caps = 144` (a strict-superset of PLAN.md's pre-M6.1.2 `108`-point estimate; the cohort-count delta inherits from M6.1.2's `rest_plain_tcp` reintroduction).

**Inheritance from M6.0a / M6.1.1 / M6.1.2 / M6.1.3 (no re-derivation):**

- **FR-006**: The 4-cohort matrix MUST be the M6.1.2 / M6.1.3 set: `rest_plain_tcp`, `rest_https_edge`, `default_grpc`, `tuned_grpc_multiplexed`. Cohort definitions and channel configs are unchanged from M6.1.3.
- **FR-007**: The concurrent-dispatch loop from M6.0a MUST be the only dispatch path (no sequential-dispatch fallback flag, no `--m6_2-sequential` mode). `dispatch_mode = "concurrent"` MUST appear in the artifact JSON's `run_meta` block.
- **FR-008**: The symmetric-prompts helper from M6.1.3 (`symmetric_prompts` shared module — exact import path is M6.1.3 `/speckit-plan` territory) MUST be on by default. An `--m6_2-asymmetric-prompts` override MAY exist for diagnostic re-runs but is OFF by default; the artifact's `run_meta` block MUST record `symmetric_prompts_enabled: true` (or `false` if the override fires).
- **FR-009**: The per-sweep `network_paths` topology probe from M6.1.2 MUST run at sweep start AND periodically thereafter (interval deferred to `/speckit-clarify`); the artifact's top-level `network_paths` block MUST contain a trajectory of probe snapshots, NOT a single observation.
- **FR-010**: The M6.1.3 5-segment engine-cost decomposition (`seg_ab_ms`, `seg_queue_ms`, `seg_prefill_ms`, `seg_ingress_ms`, `seg_egress_ms`) MUST be computed and persisted per measurement point. M6.2 does NOT add new segments; the existing five characterize the new high-cap regime.
- **FR-011**: The wire schema version MUST stay at `m6_1_1.v1`. New top-level artifact keys introduced by M6.2 (e.g., `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation`) are additive optional fields per the M6.1.1 / M6.1.2 / M6.1.3 strict-superset precedent.

**Null-anchor validation:**

- **FR-012**: The artifact's `--m6_2-validate` and `--m6_2` outputs MUST include a "null anchor validation" block comparing M6.2's `max_tokens=10` and `max_tokens=50` measurements against M6.1.3's published mean ± CI for the same (cell, cohort) pair. Per-anchor drift exceeding M6.1.3's published CI fires a `control_drift_warning` line per affected cell-cohort.
- **FR-013**: The null-anchor reference data MUST be loaded from M6.1.3's canonical published JSON (`docs/benchmarks/m6_1_3-attribution-closure.json`), NOT M6.1.1's earlier baseline — M6.1.3's attributed verdicts supersede M6.1.1's `inconclusive` placeholders per M6.1.3's forward-pointing annotation convention.
- **FR-014**: When the fraction of cells flagged with `control_drift_warning` exceeds a sweep-level threshold (default deferred to `/speckit-clarify`), the artifact MUST emit a sweep-integrity warning header, NOT just per-cell lines. The operator decides whether to publish or rerun.

**Outputs:**

- **FR-015**: The milestone-publish artifact MUST be written to `docs/benchmarks/m6_2-token-budget.md` (markdown) and `docs/benchmarks/m6_2-token-budget.json` (machine-readable). The smoke-equivalent artifact MUST be written to a distinct sibling path `docs/benchmarks/m6_2-token-budget-validate.{md,json}` to avoid clobbering (per the M6.1.3 FR-038 precedent).
- **FR-016**: The published markdown MUST contain four sections: (1) "Production latency budget" (per-cell × per-cohort × per-`max_tokens` p50/p95/p99 table), (2) "TPOT curves" (chat_stream-only time-per-output-token vs `max_tokens`), (3) "Engine-cost decomposition curves" (segment-share evolution as generation length grows), (4) "Protocol crossover threshold" (per-cell crossover_max_tokens from User Story 2).
- **FR-017**: The published markdown MUST contain a "KV-cache pressure" subsection (User Story 3) characterizing the `c=8 × max_tokens=2048` regime.
- **FR-018**: The reporter MUST emit a "Null anchor validation" subsection rendering per-cell drift status (PASS / WARN / FAIL) against M6.1.3's published CIs.
- **FR-019**: The reporter MUST emit a leading `> **Note**:` line at the top of M6.1.3's published markdown body pointing forward to M6.2 for the realistic-generation-length budget (mirroring M6.1.3's own minimal-touch annotation convention for forward references; reciprocal cross-reference in M6.2's "Method / Background" section).

**Operational gates:**

- **FR-020**: Driver invocation MUST be `python -m vllm_grpc_bench --m6_2 --m6_2-modal-region=eu-west-1` (publish) or `python -m vllm_grpc_bench --m6_2-validate --m6_2-modal-region=eu-west-1` (smoke-equivalent), matching the M6.1.2 / M6.1.3 paired-flag convention.
- **FR-021**: The publish sweep MUST hard-cap total Modal spend at ~$40 (estimated ~$27–$40 range at 14,400 RPCs × Modal A10G eu-west-1 pricing; exact value deferred to `/speckit-clarify` after the validate sweep produces a measured cost-per-RPC datum to extrapolate from).
- **FR-022**: The validate sweep MUST hard-cap total Modal spend at ~$3 (estimated ~$2 at the proportional subset; exact value deferred to `/speckit-clarify`).
- **FR-023**: The publish sweep's wall-clock runtime budget MUST be ≤ 48 hours (estimated ~30–40 hours based on M6.1's measured ~33.7 ms/token TPOT × 14,400 RPCs × axis-weighted RPC duration; the high-cap chat_stream cells dominate).
- **FR-024**: The validate sweep's wall-clock runtime budget MUST be ≤ 4 hours.
- **FR-025**: The torch-pin gate from M6.1 / M6.1.1 / M6.1.2 / M6.1.3 MUST run before any sweep — same `transformers` and `vllm-metal` resolution as the M6.1.x family. The Modal-deploy lockfile-parity command on macOS remains `uv sync --frozen --all-groups` per the ANALYSIS.md M6.0a lesson.
- **FR-026**: The Modal preemption-recurrence threshold MUST be inherited from M6.1.3 FR-028 (pinned at 2). At the M6.2 wall-clock budget, the auto-resume / partial-artifact-merge handler MUST tolerate one transient preemption per cohort without sweep abort.

**Project-wide convention:**

- **FR-027**: The `m6_1_3_symmetric_prompts` helper, the 4-cohort matrix, the concurrent-dispatch loop, the 5-segment decomposition, the per-sweep `network_paths` probe, and the `m6_1_1.v1` wire schema are project-wide conventions of the M6.x family. M6.2's spec MUST cite them by reference rather than re-deriving; future M7 / M8 spec authors inherit M6.2's compounded conventions in the same way.

### Key Entities

- **MeasurementPoint**: A single (cell, cohort, `max_tokens`) tuple — the atomic measurement unit. Carries `n=100` per-RPC timing rows in publish mode, `n=20` in validate mode. Defining attributes: `cell_id` (one of `embed_c1` / `embed_c4` / `embed_c8` / `chat_stream_c1` / `chat_stream_c4` / `chat_stream_c8`), `cohort` (one of the four), `max_tokens` (one of `{10, 50, 256, 512, 1024, 2048}`), `n_rpcs`, `wall_p50_ms`, `wall_p95_ms`, `wall_p99_ms`, `tpot_ms` (chat_stream only), the inherited 5-segment decomposition.
- **NullAnchor**: A MeasurementPoint at `max_tokens ∈ {10, 50}` paired with the corresponding M6.1.3 published measurement. Carries the drift verdict (`PASS` / `WARN` / `FAIL`) and the CI-overlap statistic that produced the verdict.
- **CrossoverThreshold**: Per-cell record capturing the smallest `max_tokens` at which the M6.1.3 cohort-pair winner's CI overlaps with the second-place cohort by ≥ 50% (operational threshold). Carries `crossover_max_tokens`, `crossover_evidence`, and `m6_1_3_base_verdict`.
- **KVPressureObservation**: Single record for the `c=8 × max_tokens=2048` regime. Carries `kv_cache_used_fraction_peak`, `scheduling_stall_signals` (free-form notes from vLLM engine logs), `oom_observed` boolean.
- **NetworkPathSnapshot**: Inherited from M6.1.2. Carries `endpoint_ip`, ordered `hops` list, per-hop CSP annotation, cohort `cloud_provider` enum, `region`, `snapshot_timestamp`. M6.2 captures a trajectory of these (multiple snapshots over the ~30–40 hour wall-clock) rather than a single observation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An M6.2 publish sweep completes end-to-end within 48 hours of wall-clock time and within ~$40 of Modal spend, against a single eu-west-1 A10G deploy, and produces both the canonical `m6_2-token-budget.{md,json}` artifact pair.
- **SC-002**: The smoke-equivalent validate sweep completes within 4 hours and ~$3, and produces the validate-sibling artifact pair sufficient to verify all wiring properties (axis coverage, cohort coverage, schema additivity, null-anchor block presence) without requiring the full publish run.
- **SC-003**: The published latency budget table contains exactly `6 cells × 4 cohorts × 6 max_tokens = 144` rows (or `144 − F` rows where `F` is the count of cells legitimately marked `failed_<reason>` per the M6.2 edge-case rules, with each such row's failure mode recorded in the artifact narrative).
- **SC-004**: At every `max_tokens=10` and `max_tokens=50` (cell, cohort) anchor point, the M6.2 measurement falls inside M6.1.3's published CI for the same point. If MORE than 5% of anchor points fail this check, the publish artifact MUST carry a sweep-level integrity warning header per FR-014.
- **SC-005**: The protocol-crossover table (FR-016 section 4) covers every cell with a meaningful M6.1.3 base verdict (i.e., not `inconclusive_high_variance` or `inconclusive`); cells without a base winner are explicitly tagged `crossover_max_tokens = null` with a one-line explanation.
- **SC-006**: The published markdown's "KV-cache pressure" subsection contains observed `kv_cache_used_fraction_peak` (or a documented reason it could not be captured) for the `c=8 × max_tokens=2048` regime.
- **SC-007**: The artifact JSON is a strict superset of M6.1.3's schema: every M6.1.3-aware reader can parse the M6.2 artifact without modification, ignoring the new `max_tokens_axis` / `protocol_crossover` / `kv_pressure_observation` top-level keys.
- **SC-008**: The artifact's `run_meta` block carries `dispatch_mode = "concurrent"`, `symmetric_prompts_enabled` (boolean), the inherited M6.1.3 wire schema version `"m6_1_1.v1"`, and a `m6_1_3_baseline_artifact_path` field naming the M6.1.3 published JSON file used as the null-anchor reference.
- **SC-009**: The torch-pin gate runs successfully before sweep start (transformers and vllm-metal resolution via `uv sync --frozen --all-groups`). Any unresolved dependency aborts the sweep before Modal cost incurs.
- **SC-010**: The published artifact contains a topology trajectory of at least two `network_paths` snapshots over the sweep's wall-clock — start-of-sweep and end-of-sweep at minimum; periodic in-flight snapshots per FR-009. If any snapshot reveals a mid-sweep CSP / region change, a `cohort_csp_mismatch_warning` line is emitted per the M6.1.2 / M6.1.3 convention.
- **SC-011**: Clock-anomaly gate (inherited from M6.1.3 SC-013): negative-segment or impossible-ordering wire-format assertions fire on < 0.5% of measured RPCs across the full sweep; otherwise the artifact carries a clock-anomaly warning at the artifact header.
- **SC-012**: The published markdown contains a forward-link annotation in M6.1.3's markdown body (one-line leading `> **Note**:` per FR-019) AND a reciprocal Method / Background pointer in M6.2's body — the M6.x cross-milestone navigation convention M6.1.3 established is preserved.
- **SC-013**: A future M7 (corpus expansion) or M8 (model expansion) spec author reading M6.2's published artifact can answer "what is the p50/p95/p99 latency budget for cohort X at `max_tokens` Y in the M6.2 baseline?" without re-deriving from M6.1.3 — M6.2 IS the canonical reference for per-`max_tokens` latency budgets going forward.

## Assumptions

- **Hardware and engine config unchanged from M6.1 / M6.1.1 / M6.1.2 / M6.1.3.** Modal A10G eu-west-1 deploy, Qwen3-8B fp16, real prompt-embeds engine path, `max_model_len=2048`, concurrent dispatch. Any deviation invalidates the null-anchor comparison and would force re-baselining the entire M6.x family.
- **M6.1.3's published artifact is the canonical null-anchor reference.** PR #31 (2026-05-19) is the latest closed M6.1.x milestone; its `docs/benchmarks/m6_1_3-attribution-closure.json` is the spec-level source of truth for `max_tokens=10 / 50` anchor comparison. If M6.1.3's artifact is itself superseded mid-cycle (e.g., an M6.1.4 lands during M6.2 spec authoring), the reference MUST be updated in `/speckit-clarify` and FR-013 amended accordingly.
- **Symmetric prompts default on per M6.1.3's cross-milestone recommendation.** The `m6_1_3_symmetric_prompts` helper is the M6.x convention going forward; M6.2 inherits unchanged. An `--m6_2-asymmetric-prompts` diagnostic override is acceptable but the published artifact is symmetric-prompts by default.
- **4-cohort matrix per M6.1.2 reintroduction of `rest_plain_tcp`.** PLAN.md's M6.2 section (written before M6.1.2 landed) projected 3 cohorts × 6 caps × 6 cells = 108 measurement points; the current 4-cohort convention yields 144 measurement points (~33% more RPCs, ~33% more wall-clock, ~33% more Modal cost). FR-005, FR-021, FR-023 carry the recalibrated numbers.
- **Single-run-per-point in M6.2 publish mode.** M6.2 does NOT inherit M6.1.3's `--m6_1_3-diagnose-repeat` multi-run convention because the per-point sample size is already `n=100` (vs M6.1.3's `n=50`); between-run variance is bounded sufficiently by the larger per-point n. If validate-sweep data reveals high between-run variance at any high-cap point, a `--m6_2-repeat=N` flag MAY be added in `/speckit-clarify`.
- **Wall-clock budget assumes M6.1.3 TPOT scales linearly.** The ~30–40 hour estimate assumes ~33.7 ms/token TPOT (M6.1's measured rate at h=4096) holds across the axis. If validate-sweep TPOT at `max_tokens=256 / 512 / 1024` deviates materially (>20%), the publish-sweep budget MUST be revised before commit.
- **KV-cache budget is approximately ~31K tokens.** The half-headroom claim for `c=8 × max_tokens=2048` derives from this assumption; if vLLM's actual KV budget at the chosen engine config differs (e.g., due to fp16 vs fp8 KV cache, `gpu_memory_utilization` setting), the SC-006 narrative MUST cite the actual measured budget rather than the projected 31K.
- **No upstream vLLM contributions or engine-config probes required.** M6.2 reuses the M6.1.3 engine setup verbatim; the new `max_tokens` axis is a client-side sweep-orchestrator change only. Engine-side instrumentation (KV-cache fraction via gRPC trailing metadata) is best-effort — if vLLM does not expose the field, FR-017 / SC-006 fall back to wall-clock-derived signals.
- **Sweep mode persisted in artifact.** The `run_meta` block MUST record `sweep_mode = "m6_2_publish"` or `"m6_2_validate"` (strict-superset addition; no `schema_version` bump) so post-hoc consumers can distinguish the two modes' artifacts without inspecting the filename.

## Dependencies

- **M6.1.3 published artifact** (`docs/benchmarks/m6_1_3-attribution-closure.json`, merged via PR #31 on 2026-05-19). Mandatory hard precondition; FR-012 / FR-013 / SC-004 / SC-008 cite the file by name.
- **M6.1.2 `network_paths` probe machinery** (per-sweep topology probe + 4-cohort iteration + `cohort_set` / `cohort_omissions` machinery — see `contracts/instrumentation.md`).
- **M6.1.3 `symmetric_prompts` shared helper** (cross-milestone module; exact import path is M6.1.3 `/speckit-plan` territory).
- **M6.1.1 5-segment decomposition + classifier primitives** (`seg_ab_ms`, `seg_queue_ms`, `seg_prefill_ms`, `seg_ingress_ms`, `seg_egress_ms`).
- **M6.0a concurrent-dispatch loop** (the only dispatch path; no sequential-dispatch fallback per FR-007).
- **M6 / M6.1 harness wholesale**: engine config, RPC drivers, smoke gate, torch-pin gate, M6 baseline loader.
- **Modal A10G eu-west-1 quota** sufficient for ~48 hours of single-deploy wall-clock and ~$40 of compute budget.
