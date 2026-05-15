# Feature Specification: M6 — Real-Engine Mini-Validation

**Feature Branch**: `020-m6-real-engine-mini-validation`
**Created**: 2026-05-14
**Status**: Draft
**Input**: User description: "M6 — Real-Engine Mini-Validation from PLAN.md"

## Background *(non-normative summary)*

M5.1 and M5.2 published verdicts on REST vs gRPC over real wire using a MockEngine — i.e. with no inference cost between the request landing and the response being formed. Both reports name "real-engine validation" as their loudest open caveat. M6 closes that caveat with the minimum compute commitment so M7 (corpus expansion) can be designed against the actual residual transport/protocol signal that real inference leaves behind, rather than against MockEngine assumptions. M6 supersedes M5.2's verdicts only under a real-engine condition; M5.2's MockEngine verdicts remain the published baseline for traceability.

M6 deliberately picks a focused 6-cell × 3-cohort slice of M5.2's matrix at a single hidden_size (h=4096, fixed by the chosen real model's architecture). It does not expand corpus diversity (M7's job) or model coverage (M8's job).

## Clarifications

### Session 2026-05-14

- Q: How is "engine cost alone" measured so it can be published as a separate per-cell metric? → A: Server-side instrumentation — the gRPC frontend wraps the engine call and emits per-RPC engine-cost spans (forward-pass wall-clock for embed; TTFT and TPOT separately for chat_stream) returned to the harness via gRPC response/trailing metadata. No subtraction from a transport baseline; no separate engine-only cohort.
- Q: When does an overlapping-CI cell fall into `verdict_buried_by_engine` vs `no_winner_at_n100`? → A: Data-driven 5× threshold. Cell is `verdict_buried_by_engine` if cohort CIs overlap **and** `engine_cost_mean ≥ 5 × |M5.2_winner_delta|` (using the M5.2 published winner delta for that cell); otherwise overlapping-CI cells classify as `no_winner_at_n100`. Cells with no M5.2 winner delta to compare against (M5.2 verdict was itself `no_winner`) classify as `no_winner_at_n100`.
- Q: What are the smoke-gate exit-code and diagnostics semantics? → A: Single exit code (`0` if all 3 cohorts pass; `1` otherwise) plus a per-cohort one-line summary printed to stderr (`cohort=<name> status=<ok|failed> reason=<short string>`). No persistent diagnostic file — smoke is cheap to re-run. Smoke is operator-triggered (not a CI gate), so differentiated exit codes are out of scope.
- Q: Where does the verdict classifier read M5.2 winner deltas from? → A: Hybrid — classifier reads `docs/benchmarks/m5_2-transport-vs-tuning.json` at runtime as the single source of truth, AND snapshots the per-cell winner deltas it actually used into M6's JSON `RunMeta` (under a new `m5_2_winner_deltas` field). This gives one canonical input plus a per-run audit trail so an M6 report can be reread later against the exact M5.2 numbers it was classified against, even if the M5.2 JSON is later edited.

### Session 2026-05-14 (round 2 — real-engine-specific gaps)

- Q: How does the harness handle real-engine warmup before measurement? → A: Per-cohort warmup, separate from the n=100 measurement budget. The harness runs 10 throwaway RPCs at the start of each (cell × cohort) before the 100 measurement RPCs. Warmup RPCs are discarded from all reported metrics (latency, TTFT, engine cost, CIs). Per-cohort (not just per-sweep) because a cohort context switch incurs channel re-warm. Measurement n stays at 100; FR-004 is unchanged.
- Q: How are the 3 cohorts sequenced within a cell to control for Modal/network/engine drift? → A: Round-robin per c-batch. Within each cell, at each round the harness fires `c` concurrent RPCs of cohort A and awaits them, then `c` of cohort B, then `c` of cohort C; repeats `100/c` rounds. Drift control comparable to per-RPC round-robin without the c≥2 implementation complexity. Replaces the M5.x sequential-per-cohort convention (which is inadequate for real-engine drift on Modal).
- Q: How does the harness handle per-RPC failures within a cohort? → A: Per-RPC retry up to 3 attempts; report at n_successes (CIs reflect actual sample size); cell marked `cell_incomplete` (a 5th terminal classification, distinct from the 4 verdict categories) if any cohort has fewer than 80 successes after retries. Retry handles transient Modal flakes without infinite-retry risk; the 80-floor flags untrustworthy cells loudly.
- Q: Which metric does the verdict classifier compare on for chat_stream cells? → A: TTFT (client-observed) is the chat_stream classifier metric. The classifier's CI-overlap test and the 5× engine-cost ratio for `verdict_buried_by_engine` both apply on the TTFT axis. Matches M5.2's chat_stream comparison axis (apples-to-apples for the survival comparison) and surfaces the residual transport signal at `max_tokens=50` where total wall-clock is engine-dominated. Total wall-clock and `engine_ttft_ms` / `engine_tpot_ms` are still published per cell for transparency but are NOT classifier inputs. (Embed cells classify on total per-RPC wall-clock — the only client-observed latency metric for unary embed.)
- Q: How is the engine instance lifecycle managed across the 6 cells? → A: One engine instance, shared across all 6 cells. The engine loads once at sweep start and serves every (cell × cohort) measurement until the sweep completes. No reload between cells, between paths, or between cohorts. Per-cohort warmup (FR-021) absorbs inter-cell state carryover; round-robin per c-batch (FR-022) controls inter-cohort drift within a cell. `cold_start_s` (FR-019) is therefore a single scalar per sweep, not a per-cell or per-path array. Matches PLAN.md's 75–90 min runtime budget (per-cell reloads would breach SC-001).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resolve the "real engine" caveat with a per-cell survival verdict (Priority: P1)

A vllm-grpc operator who has already published M5.2 wants to know which of M5.2's per-cell REST-vs-gRPC verdicts survive when the request actually drives real inference instead of a MockEngine. They run a single command and receive a published report whose headline section is a "Supersedes M5.2 under real engine" verdict table — one row per cell — so they can answer the question for every audience that previously asked "but does this hold against a real model?"

**Why this priority**: This is the entire reason M6 exists as a canonical milestone rather than a footnote. Without a per-cell categorical survival verdict, M5.2's caveat remains open and M7 cannot be designed against a known signal floor.

**Independent Test**: Drive the M6 sweep against the project's Modal eu-west-1 region with the chosen real model loaded on A10G. Confirm that the produced markdown report's executive section contains a verdict table covering all 6 cells, that each cell is classified into exactly one of the four canonical categories (survives / buried / changed / no_winner_at_n100), and that the JSON companion file is consumable by an M5.2-aware reader without schema breakage.

**Acceptance Scenarios**:

1. **Given** a configured Modal account and the M6 harness is built, **When** the operator runs the documented single-command M6 sweep against the eu-west-1 region, **Then** the run completes within the published runtime budget, writes a markdown + JSON report pair, and the markdown executive section contains a 6-row verdict table classifying each cell into one of the four canonical categories.
2. **Given** an M5.2-aware downstream consumer that already reads M5.2's JSON report, **When** the consumer reads M6's JSON output, **Then** the M5.2-aware consumer continues to work unmodified because M6's schema is a strict superset of M5.2's.
3. **Given** a cell whose M5.2 winner was non-overlapping CI in one direction, **When** M6 measures the same cell under real engine and observes non-overlapping CI in the opposite direction, **Then** that cell is classified `verdict_changed` (not `verdict_survives`).

---

### User Story 2 - Publish a real-engine cost floor so M7 can interpret prompt-length scaling effects (Priority: P2)

The operator (or the M7 designer) wants the per-cell engine cost as a separate, named metric — not folded into the cohort comparisons — so that M7's prompt-length scaling work can interpret deltas against a known real-engine cost floor instead of against MockEngine assumptions. For embed cells the metric is forward-pass wall-clock; for chat_stream cells it is TTFT + TPOT.

**Why this priority**: This is M6's gift to M7. Without it, M7 starts from the same MockEngine assumption that M6 was built to dispel. P2 because the headline survival table (US1) is the milestone exit deliverable; the engine-cost baseline is the milestone's load-bearing hand-off to the next milestone.

**Independent Test**: Read any cell's row in the published report and confirm the engine-cost-per-RPC metric is present as a named field (with units), distinct from the cohort comparison columns, with a 95% CI half-width attached.

**Acceptance Scenarios**:

1. **Given** any embed cell in the published report, **When** the operator looks for an engine-cost row, **Then** the report names a forward-pass wall-clock metric for that cell with a 95% CI half-width.
2. **Given** any chat_stream cell, **When** the operator looks for the engine-cost row, **Then** the report names both TTFT and TPOT for the engine alone, each with a 95% CI half-width.

---

### User Story 3 - Catch real-engine harness wiring failures cheaply with a smoke gate (Priority: P3)

The operator wants to run a fast, low-cost smoke check before committing to the full ~75–90 min Modal A10G sweep, so that a wiring bug, a model-loading failure, or a cohort-misconfiguration error surfaces in minutes rather than after a full sweep is wasted.

**Why this priority**: P3 because the full sweep is recoverable on failure (just re-run) — but Modal A10G compute is metered, and a wiring bug that only surfaces after 80 minutes is a meaningful waste. The smoke gate keeps iteration fast during M6 bring-up.

**Independent Test**: Drive the documented smoke command. Confirm it exercises 1 cell × 3 cohorts × n=10 against the real engine, completes within ~5 minutes wall-clock, and either signals success (clean exit, no errors per cohort) or surfaces actionable diagnostics for the failing cohort(s).

**Acceptance Scenarios**:

1. **Given** the M6 smoke command and a healthy environment, **When** the operator runs it, **Then** the smoke run completes within ~5 minutes wall-clock and reports per-cohort success.
2. **Given** the M6 smoke command and a deliberately broken cohort wiring (e.g. wrong model identifier), **When** the operator runs it, **Then** the smoke run exits with status `1` and prints a stderr summary line for the failing cohort in the form `cohort=<name> status=failed reason=<short string>` identifying which cohort failed and why.
3. **Given** a successful smoke run, **When** the operator chooses to proceed, **Then** the full M6 sweep is the next step — the smoke run does not implicitly trigger the full sweep.

---

### Edge Cases

- **Smoke gate fails on one of three cohorts.** The full sweep MUST NOT proceed automatically. The operator's next action is to fix the failing cohort wiring and re-run the smoke gate.
- **Modal cold-start exceeds the per-cohort warmup budget.** Cold-start is excluded from per-RPC latency numbers and recorded separately in run metadata. A long cold-start does not invalidate the run; it is reported transparently.
- **A cell's CI half-width exceeds a defensibility threshold even at n=100.** That cell is published with the wide CI surfaced explicitly and classified `no_winner_at_n100` rather than forced into a survives/buried/changed bucket.
- **Real-engine generation hits its `max_tokens` cap before EOS** for every chat_stream RPC at this corpus. This is intentional; `max_tokens=50` is the chosen production-realistic cap and is documented in the report so the reader is not surprised.
- **A run is interrupted mid-cell** (e.g. operator Ctrl+C, Modal container OOM). Partial results are surfaced so the operator can decide whether to resume or restart; partial results MUST NOT be published as the canonical M6 verdict.
- **The chosen real model's GPU memory exceeds A10G's 24 GB** (e.g. quantisation pinning is missed and fp16 pushes past the headroom budget). The harness MUST surface this as a model-loading failure during the smoke gate, not silently OOM the worker pod.
- **A reader compares an M6 cell directly to an M1 GPU cell.** The report's executive section names the inference engine, model, and region so a reader cannot accidentally compare the M6 cell (Qwen3-7B at h=4096) to an M1 GPU cell (Qwen3-0.6B at a different hidden_size) without the framing being obvious.

## Requirements *(mandatory)*

### Functional Requirements

**Sweep matrix and cohorts**

- **FR-001**: The system MUST run a 6-cell narrow slice of the M5.2 matrix at a single hidden_size fixed by the chosen real model's architecture (h=4096 for the chosen Qwen3-7B model). The 6 cells are: `embed × c={1,4,8}` and `chat_stream × c={1,4,8}`.
- **FR-002**: The system MUST exercise three cohorts per cell: `rest_https_edge`, `default_grpc`, `tuned_grpc_multiplexed`. The system MUST NOT exercise `rest_plain_tcp` or `tuned_grpc_channels` (transport-only and multiplexing-vs-channels deltas already characterised by M5.2 — see Out of Scope).
- **FR-003**: The system MUST drive the gRPC frontend with a real inference engine loaded with the chosen real model on Modal A10G. MockEngine paths MUST NOT be exercised under the M6 sweep.
- **FR-004**: The system MUST run **n=100 iterations per cohort per cell** (vs M5.2's n=250). M6 is asking the larger "does the verdict structure survive?" question, not resolving sub-noise tuned-vs-default deltas.
- **FR-005**: The system MUST cap chat_stream completions at **`max_tokens=50`** (vs M5.2's `max_tokens=10`) so generation length is in a production-realistic regime and engine cost is visible.
- **FR-006**: The system MUST honor the M5.2 HTTPS-edge convention for the REST cohort: `rest_https_edge` traffic MUST traverse Modal's TLS-terminated, anycast-routed HTTPS edge so the M6 verdict table is comparable to M5.2's HTTPS-edge baseline.

**Metrics**

- **FR-007**: The system MUST publish **TTFT** as a first-class metric for every chat_stream cell, alongside total wall-clock per RPC.
- **FR-008**: The system MUST publish an **engine-cost-per-RPC** metric per cell as a named, separate metric distinct from the cohort comparisons. Engine cost MUST be measured by **server-side instrumentation**: the gRPC frontend wraps the engine call and emits per-RPC engine-cost spans, returned to the harness via gRPC response or trailing metadata. The harness MUST NOT derive engine cost by subtraction from a transport baseline, and MUST NOT introduce a separate "engine-only" cohort to estimate it.
  - For embed cells: `engine_forward_ms` (forward-pass wall-clock attributable to the engine alone).
  - For chat_stream cells: `engine_ttft_ms` and `engine_tpot_ms` (separately).
- **FR-009**: The system MUST publish 95% CI half-widths for every numeric metric in the verdict table and engine-cost row, so the operator can adjudicate trust.
- **FR-010**: The system MUST run a per-cohort RTT probe before the sweep and surface the result in the executive section of the report (inherits the M5.2 convention).

**Smoke gate**

- **FR-011**: The system MUST provide a smoke command that runs **1 cell × 3 cohorts × n=10** against the real engine. The smoke command MUST be invocable independently of the full sweep. The smoke command MUST exit with status `0` if all 3 cohorts pass and status `1` if any cohort fails. The smoke command MUST print one summary line per cohort to **stderr** in the form `cohort=<name> status=<ok|failed> reason=<short string>`. The smoke command MUST NOT write a persistent diagnostic file (smoke is cheap to re-run; the operator's terminal is the only consumer).
- **FR-012**: The full M6 sweep MUST NOT proceed automatically when the smoke gate is failing; the operator's next action on smoke failure is to fix the failing cohort wiring and re-run smoke.

**Outputs and reproducibility**

- **FR-013**: The system MUST emit `docs/benchmarks/m6-real-engine-mini-validation.md` (markdown report) and `docs/benchmarks/m6-real-engine-mini-validation.json` (JSON companion) on a successful full sweep.
- **FR-014**: The markdown report's executive section MUST contain a "Supersedes M5.2 under real engine" verdict table, one row per cell, classifying each cell into exactly one of four canonical categories: `verdict_survives`, `verdict_buried_by_engine`, `verdict_changed`, `no_winner_at_n100`. Discrimination rule:
  - `verdict_survives`: M6 cohort CIs are non-overlapping in the **same** direction as M5.2's published winner for that cell.
  - `verdict_changed`: M6 cohort CIs are non-overlapping in the **opposite** direction from M5.2's published winner.
  - `verdict_buried_by_engine`: M6 cohort CIs overlap **and** `engine_cost_mean ≥ 5 × |M5.2_winner_delta|` for that cell.
  - `no_winner_at_n100`: M6 cohort CIs overlap **and** the `verdict_buried_by_engine` condition is not met (including the case where M5.2 itself published `no_winner` for the cell, so no winner delta exists to compare against).
  The classifier MUST be deterministic given the M6 numeric inputs and the M5.2 published winner deltas; operator post-hoc re-classification is not permitted. The classifier MUST read M5.2 winner deltas from `docs/benchmarks/m5_2-transport-vs-tuning.json` at runtime (single source of truth) and MUST snapshot the per-cell deltas it used into M6's JSON `RunMeta` for audit traceability (see FR-018).
  **Comparison metric per path.** The CI-overlap test and the `engine_cost_mean ≥ 5 × |M5.2_winner_delta|` ratio for `verdict_buried_by_engine` MUST be applied on:
  - For **chat_stream** cells: client-observed **TTFT** (matches M5.2's chat_stream comparison axis; surfaces residual transport signal at `max_tokens=50` where total wall-clock is engine-dominated). Total wall-clock and `engine_ttft_ms` / `engine_tpot_ms` are published per cell but are NOT classifier inputs.
  - For **embed** cells: client-observed **total per-RPC wall-clock** (the only client-observed latency metric for unary embed; matches M5.2's embed comparison axis). `engine_forward_ms` is published per cell but is NOT a classifier input.
- **FR-015**: The markdown report's executive section MUST name the inference engine, model identifier, hidden_size, Modal region, and GPU type, so a reader cannot mistake the M6 cell for an unrelated baseline.
- **FR-016**: The JSON companion MUST be a strict superset of M5.2's JSON schema. M5.2-aware downstream consumers MUST continue to work unmodified.
- **FR-017**: The system MUST be drivable from a single CLI invocation using the project's existing benchmark harness entry point, with `--m6` and `--m6-modal-region=<region>` flags (or equivalent) so the operator does not orchestrate cohorts or cells by hand.
- **FR-018**: The system MUST embed the following fields in the JSON run metadata so results are fully traceable: `git_sha`, `hostname`, Modal function ID, GPU type, Modal region, model identifier, engine version, `cold_start_s`, and `m5_2_winner_deltas` (a per-cell snapshot of the M5.2 winner deltas the classifier actually consumed for this run, sourced from `docs/benchmarks/m5_2-transport-vs-tuning.json` at runtime — see FR-014).
- **FR-019**: The system MUST exclude Modal cold-start time from per-RPC latency numbers; cold-start MUST be recorded as `cold_start_s` (a single scalar per sweep — see FR-024 for engine instance lifecycle) in run metadata for transparency (inherits the M3.2 / M4.1 convention).

**Engine warmup**

- **FR-021**: The system MUST run **10 throwaway warmup RPCs per (cell × cohort)** before the n=100 measurement RPCs (FR-004). Warmup RPCs MUST be excluded from every reported metric (per-RPC latency, TTFT, engine cost, 95% CIs, verdict classification). Warmup is per-cohort (not just one global warmup at sweep start) because each cohort context switch incurs channel re-warm and may revisit cold code paths. Warmup RPCs MUST exercise the same path/concurrency/cohort configuration as the measurement RPCs that follow them.

**Cohort sequencing**

- **FR-022**: Within each cell, the system MUST measure the 3 cohorts in **round-robin per c-batch** order: at each round, fire `c` concurrent RPCs of cohort A and await them, then `c` of cohort B, then `c` of cohort C; repeat `100/c` rounds. The harness MUST NOT measure all 100 RPCs of one cohort to completion before starting the next cohort. Rationale: Modal/network/engine drift over the 30–60 s a sequential per-cohort pass takes can leak into cohort deltas; round-robin per c-batch ensures each cohort sees the same minute-by-minute conditions. The MockEngine M5.x sequential-per-cohort convention is **superseded** for M6 because constant-time MockEngine measurement was insensitive to this drift; real-engine measurement is not. Warmup RPCs (FR-021) MUST follow the same per-c-batch rotation as the measurement RPCs.

**Engine instance lifecycle**

- **FR-024**: The system MUST maintain **one engine instance** loaded across all 6 cells of the sweep. The engine MUST load once at sweep start and serve every (cell × cohort) measurement until the sweep completes. The system MUST NOT reload the engine between cells, between paths (embed vs chat_stream), or between cohorts. Rationale: the PLAN.md 75–90 min runtime budget (SC-001) assumes a single multi-second cold-start; per-cell or per-path reloads would breach the budget. Inter-cell engine state carryover is absorbed by the per-cohort warmup convention (FR-021) and does not bias verdict computation. `cold_start_s` (FR-019) is therefore recorded as a single scalar per sweep.

**Per-RPC failure handling**

- **FR-023**: The system MUST retry each failed measurement RPC up to **3 attempts** before counting it as a failure. The system MUST report each cohort at `n_successes` (≤ 100), and 95% CIs MUST reflect the actual successful sample size. The system MUST publish per-cohort `n_successes` and `failure_count` fields in the JSON companion. If any cohort in a cell has fewer than **80 successes** after retries, the cell MUST be marked with the terminal classification **`cell_incomplete`** — a 5th classification distinct from the 4 verdict categories in FR-014. `cell_incomplete` cells MUST appear in the verdict table with a clear marker and MUST NOT be folded into any of the 4 verdict categories. Warmup RPC failures (FR-021) MUST be silently retried until 10 warmup successes accumulate per cohort; if warmup cannot succeed, the cell is marked `cell_incomplete` without measurement RPCs being attempted.

**Bytes axis (preserved, not re-measured)**

- **FR-020**: The system MUST NOT re-measure the wire-bytes axis. M1's topology-immune bytes-axis findings (~89% chat / ~25% embed reductions) remain authoritative because encoding is structural, not engine-dependent. The report MUST note this preservation explicitly so a reader does not infer that bytes are now in question.

### Key Entities

- **M6 cell**: A specific (path, hidden_size, concurrency) tuple in the 6-cell narrow slice. Each cell is benchmarked across all 3 cohorts and receives one canonical survival verdict.
- **M6 cohort**: One of `rest_https_edge`, `default_grpc`, `tuned_grpc_multiplexed`. The cohort defines the wire format and transport.
- **Verdict classification**: One of `verdict_survives` (M5.2 winner CI direction holds non-overlapping under real engine), `verdict_buried_by_engine` (CIs overlap AND engine cost is ≥5× the M5.2 winner delta for that cell — additional sampling cannot recover the prior signal), `verdict_changed` (real-engine CI direction is opposite of M5.2's), or `no_winner_at_n100` (CIs overlap and the `verdict_buried_by_engine` condition is not met — additional sampling could plausibly resolve the signal). Cells with insufficient data after retries (any cohort < 80 successes) take the terminal classification `cell_incomplete` instead (FR-023), distinct from the 4 verdicts. Discrimination rule is deterministic; see FR-014.
- **Engine-cost-per-RPC baseline**: Server-instrumented per-RPC measurement returned via gRPC response/trailing metadata. For embed cells, `engine_forward_ms` (forward-pass wall-clock attributable to the engine alone). For chat_stream cells, `engine_ttft_ms` and `engine_tpot_ms` separately. Inherited by M7 as a real cost floor.
- **Run metadata (RunMeta)**: git_sha, hostname, Modal function ID, GPU type, Modal region, model identifier, engine version, cold_start_s, m5_2_winner_deltas (per-cell snapshot of the M5.2 winner deltas the classifier consumed, for audit traceability). Embedded in every JSON report.
- **Smoke result**: Per-cohort pass/fail outcome of the 1-cell × 3-cohort × n=10 pre-flight check. Not part of the canonical M6 verdict; gates whether the full sweep is sensible to launch.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The full M6 sweep completes end-to-end within **90 minutes wall-clock** on Modal A10G in the configured region (PLAN.md budget: ~75–90 min).
- **SC-002**: Every one of the 6 cells in the published report receives **exactly one** terminal classification — one of the 4 canonical survival verdicts (survives / buried / changed / no_winner_at_n100) or `cell_incomplete` (FR-023). No cell is left unclassified.
- **SC-003**: Every chat_stream cell publishes both **TTFT** and **total wall-clock** for every cohort, each with a 95% CI half-width.
- **SC-004**: The smoke gate completes within **5 minutes wall-clock** on Modal A10G and either reports per-cohort success or surfaces actionable per-cohort diagnostics on failure.
- **SC-005**: The published report's executive section names the inference engine, model identifier, hidden_size, Modal region, and GPU type within the first screenful of content, so a reader can locate the topology in one read.
- **SC-006**: The engine-cost-per-RPC metric is recorded for **every cell** so M7's prompt-length scaling work can interpret prompt-length deltas against a known real-engine cost floor.
- **SC-007**: The JSON companion file is readable by an existing M5.2-aware consumer without schema breakage (strict superset compatibility).
- **SC-008**: A reader who has only read M5.2 can read the M6 executive section and answer the question "did M5.2's per-cell verdicts survive under real engine?" without consulting any external document or source code.

## Assumptions

- **Compute target.** Modal A10G (24 GB VRAM) is the compute target. The chosen real model (Qwen3-7B fp16, ~14 GB) fits with KV-cache headroom — no A100 needed. PLAN.md commits to A10G; M6 inherits.
- **Region.** Modal `eu-west-1` is the default region; this matches M5.2 so RTT-vs-RTT comparisons against M5.2 remain apples-to-apples.
- **Harness reuse.** The existing `vllm_grpc_bench` harness (M5.2 codebase) is the foundation; M6 is a focused extension with cohort/cell narrowing, an engine-mode flag, and the verdict-classification reporter described in FR-014. M6 does not require a harness redesign.
- **Real-engine path already exists.** The project's gRPC frontend is already capable of launching real `AsyncLLM` (Phase 6.1 added `enable_prompt_embeds=True` to `AsyncEngineArgs`); M6 inherits that capability and configures it for the chosen real model.
- **Topology comparability target.** M5.2's HTTPS-edge transport is the "production-equivalent" REST baseline against which the M6 REST cohort is measured under real engine. M6 deliberately does not re-validate the M5.1 plain-TCP REST topology under real engine; that comparison is a transport-only delta already characterised by M5.2.
- **Chat_stream `max_tokens=50`** is intentional and production-realistic. Hitting the cap before EOS is expected and is documented in the report so a reader is not surprised.
- **Smoke gate is operator-triggered**, not a CI gate. The full M6 sweep is also operator-triggered (Modal compute is metered).
- **Driver.** The operator drives from a developer workstation with `modal token new` already configured.
- **Bytes are not in question.** M1's bytes-axis findings (~89% chat / ~25% embed wire reductions) remain authoritative; M6 measures latency only.
- **Verdict classification is from M5.2's verdict, not M5.1's.** M6's "Supersedes M5.2 under real engine" framing is correct because M6 reuses M5.2's HTTPS-edge transport baseline; M5.1 is not in M6's comparison frame (M5.1 measured plain-TCP REST and is preserved as a different audience-specific guidance).

## Out of Scope *(explicit, mirrors PLAN.md M6 § "Out of scope")*

- **Corpus diversity** — deferred to M7. M6 reuses M5.2's workload corpus.
- **Additional models** — deferred to M8. M6 measures one model (Qwen3-7B); M8 spans multiple models across canonical hidden_size widths (h=2048 / 4096 / 8192).
- **Real-engine validation at hidden_size != 4096** — deferred to M8 which uses multiple models spanning canonical widths.
- **Real-engine validation of the M3/M4 channel-tuning sweep** — out of scope for M6. M3/M4 channel-tuning verdicts were already validated cross-host by M5.
- **Wire-bytes axis** — M1's findings remain authoritative; encoding is structural, not engine-dependent.
- **HTTPS-edge transport for gRPC** — Modal's edge does not natively expose HTTP/2 plaintext + gRPC, so plain-TCP remains the only credible gRPC transport for this milestone. If Modal adds a TLS-terminated gRPC edge later, that becomes a follow-up.
- **The `rest_plain_tcp` and `tuned_grpc_channels` cohorts** from M5.2's five-cohort matrix — dropped because the transport-only delta is already characterised by M5.2 and `_channels` / `_multiplexed` were empirically interchangeable at c≥2 in M5.1 and M5.2.
- **A real-engine head-to-head against M5.1's plain-TCP REST cohort** — M6's REST cohort is HTTPS-edge only; the plain-TCP comparison is preserved in M5.1 as audience-specific guidance for non-edge deployments.
