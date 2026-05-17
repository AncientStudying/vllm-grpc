# M6.1.1 Phase 0 — Research Items & Decisions

**Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Nine research items. Each lists the **Decision**, **Rationale**, and **Alternatives considered**. All NEEDS CLARIFICATION items in the spec were resolved by the 3 clarify rounds (11 Q/A bullets); none remain for `/speckit-plan` to resolve. Research below documents the technical decisions that map spec FRs onto specific implementation choices.

---

## R-1: Where exactly do M6.1's `engine_ttft_ms` measurement boundaries live in the REST and gRPC paths?

**Decision**: Read the M6.1 implementation to locate the existing bracketing:
- **REST**: in `scripts/python/modal_bench_rest_grpc_server.py`, the FastAPI chat_stream handler computes `engine_start = perf_counter()` at the *beginning of the request body processing* (after FastAPI deserialisation but before any internal vLLM input handling), and emits `engine_ttft_ms = (first_chunk_perf_counter − engine_start) × 1000` on the terminal SSE event's JSON payload.
- **gRPC**: in `packages/frontend/src/vllm_grpc_frontend/completions.py` (or the chat_stream servicer module), the engine_ttft is captured around the first yielded chunk from `AsyncLLM.generate()` and emitted as the `engine_ttft_ms` trailing-metadata key. The exact anchor point (whether before or after `engine.generate(...)`'s internal tokenisation step) is the open question Phase 1's data answers.

**Rationale**: The 14–17% per-cohort spread M6.1 observed (rest_https_edge ≈ 43.5 ms / default_grpc ≈ 47.5 ms / tuned_grpc_multiplexed ≈ 41.5 ms) is consistent with the REST shim's `engine_start` straddling a few extra milliseconds of pre-engine ASGI work (FastAPI body parsing, request validation, async dispatch through Modal's HTTPS edge proxy) while the gRPC server-side captures `engine_ttft` at a tighter point. The four-checkpoint instrumentation lets the operator localise the gap to a specific segment (a→b pre-engine, b→c engine-internal first-token, c→d emit pipeline) on Phase 1's published table.

**Alternatives considered**:
- (a) Single-checkpoint comparison (measure only one boundary on both paths and align it): rejected — the spec explicitly says "the decision is data-driven, not pre-committed" (Background §). Without per-segment breakdown the operator can't distinguish `instrumentation_artifact` from `channel_dependent_batching`.
- (b) Reuse M6.1's existing `engine_ttft_ms` field plus one new key for the pre-engine bracket: rejected — too narrow. Four checkpoints give the operator the entire RPC lifecycle without committing to any specific hypothesis.

**Implementation pointer**: at `/speckit-tasks` time, T1 of Phase 1 (Modal-server-side) reads M6.1's existing bracketing code to confirm the exact line where `engine_start` is captured on each path, then inserts the 4 new `perf_counter_ns()` checkpoints surrounding it.

---

## R-2: Which clock source? `perf_counter_ns()` vs `time.monotonic_ns()` vs `os.times()` vs CLOCK_MONOTONIC_RAW?

**Decision**: `time.perf_counter_ns()` on both REST handler and gRPC servicer.

**Rationale**:
- **Resolution**: `perf_counter_ns()` returns nanosecond precision (Python 3.7+). Linux backend is `CLOCK_MONOTONIC` on most distros; macOS backend is `mach_absolute_time()`. Both are well-suited to sub-millisecond timing on commodity hardware.
- **Monotonicity**: `perf_counter_ns()` is monotonic and unaffected by wall-clock adjustments (NTP). Critical for per-RPC segment deltas — a backwards wall-clock jump would produce negative segment durations and trip the FR-010 classifier into the `inconclusive` fallback (which detects "negative spread ratios from non-monotonic cohort ordering").
- **Cost**: per-call overhead measured at ~50–200 ns on Linux/macOS (single `clock_gettime` syscall + ctypes marshalling); 4 calls per RPC × ~200 ns = 800 ns ≪ FR-012's 500 µs budget. Headroom is 600×, so the FR-012 gate is robust against future implementation changes (e.g., adding lightweight logging).
- **Alignment**: vLLM's internal timing uses the same `perf_counter` family (per the vLLM source tree); so cross-bracket comparisons are physically commensurable.

**Alternatives considered**:
- `time.monotonic_ns()`: also monotonic but lower resolution on some platforms (1 ms on Windows). Project targets Linux/macOS so this is a non-issue, but `perf_counter_ns()` is the canonical Python choice for sub-ms timing.
- `os.times()`: returns user/system CPU time, not wall-clock — wrong tool for measuring elapsed time across async I/O.
- `CLOCK_MONOTONIC_RAW` via ctypes: marginally more accurate (immune to NTP frequency-adjustments) but adds a non-portable dependency for a sub-µs improvement that doesn't change classifier outcomes.

**Implementation pointer**: a helper `_t_now_ns() -> int` (probably in `m6_1_1_timing.py` server-side mirror) wraps `time.perf_counter_ns()` — keeps the checkpoint sites identical between REST and gRPC.

---

## R-3: How does the client extract the 4 timestamps from the wire?

**Decision**:
- **REST**: parse the terminal SSE event's JSON payload; read the `m6_1_1_timings` sub-object as a dict `{"handler_entry_ns": int, "pre_engine_ns": int, "first_chunk_ns": int, "terminal_emit_ns": int}` (FR-007 wire shape). Extraction logic lands in `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` alongside the existing engine_cost trio parser.
- **gRPC**: read the four trailing-metadata keys (`m6_1_1_t_handler_entry`, `m6_1_1_t_pre_engine`, `m6_1_1_t_first_chunk`, `m6_1_1_t_terminal_emit`) per FR-008. Values arrive as ASCII strings (gRPC trailing metadata is byte-string only); parse to int. Extraction logic lands alongside the existing engine_cost trio parser in `m6_engine_cost.py` or a new helper in `m6_1_1_timing.py`.

**Rationale**: Reuses the M6 / M6.1 client-side extraction pattern verbatim. The four keys are namespaced (sub-object on REST, prefix on gRPC) per the spec's Edge Cases lines 110–111, so the existing M6 / M6.1 engine_cost parsers continue to work — they simply skip the new keys when M6.1.1's server isn't running.

**Alternatives considered**:
- Sidecar HTTP/2 stream for instrumentation (separate channel): rejected — adds plumbing complexity and racing concerns; the trailing-metadata + SSE-terminal-event mechanism already exists for engine_cost.
- Out-of-band time-series database push (Prometheus / OTLP): rejected — adds a fourth dependency for a one-shot diagnostic milestone.
- Inline log line scraping: rejected — fragile, requires log parsing on the client, perturbs the perturbation budget.

**Implementation pointer**: `m6_1_1_timing.py` exposes `extract_rest_timings(sse_terminal_event: dict) -> TimingCheckpoint | None` and `extract_grpc_timings(trailing_md: dict[str, str]) -> TimingCheckpoint | None`. Both return `None` on absence — the existing per-RPC event-record assembly silently skips the M6.1.1 fields when running under the M6 / M6.1 dispatch.

---

## R-4: Reuse M6's engine_cost emission/extraction infrastructure?

**Decision**: Yes — reuse `m6_engine_cost.py` (gRPC trailing metadata + REST JSON parsers) unchanged. M6.1.1's new wire fields ride on the same transport mechanisms; the extraction is a *parallel* parser in `m6_1_1_timing.py` rather than a modification to `m6_engine_cost.py`.

**Rationale**:
- **Backward compatibility**: M6's `engine_cost_drift_warning` flag is still emitted on the chat_stream cells under M6.1.1's Phase 2(a) verification sweep (it's expected to fire under the symmetrised instrumentation per round-1 Q2 — the supersedence is methodology-only). The M6 parser must continue to work unchanged.
- **Strict-superset compatibility (FR-022)**: M6.1.1's JSON is a strict superset of M6.1's `engine_cost_baseline` schema. M6.1.1 *adds* `multi_point_timings`, `phase_1_runs`, `chat_stream_baseline_post_symmetrisation`, etc., but does not modify existing keys.
- **Test isolation**: the existing M6 / M6.1 unit tests for engine_cost extraction continue to pass without modification; new tests cover only the new M6.1.1 fields.

**Alternatives considered**:
- Refactor `m6_engine_cost.py` into a generic per-RPC-instrumentation extractor with pluggable schemas: rejected — speculative abstraction (Constitution Principle III). Two parallel parsers (M6 + M6.1.1) is fine.

---

## R-5: Modal deployment lifecycle — Phase 1 deploys with checkpoints; Phase 2(a) requires the symmetrisation fix. How does the operator switch between them?

**Decision**: Two distinct Modal deployments — one for Phase 1 (instrumentation only) and one for Phase 2(a) (instrumentation + symmetrisation). The operator's workflow:
1. Phase 1 — instrumentation lands; operator runs `python -m vllm_grpc_bench --m6_1_1-diagnose` which deploys a fresh Modal app with the 4-checkpoint code.
2. Phase 1 reads `instrumentation_artifact` → operator applies the symmetrisation code change (specific edit identified by Phase 1's per-segment table) and commits it.
3. Phase 2(a) — operator runs `python -m vllm_grpc_bench --m6_1_1` which deploys a fresh Modal app with both the instrumentation AND the symmetrisation; runs the n=100 verification sweep.

The operator can use `--m6_1_1-skip-deploy --m6_1_1-modal-endpoint=...` between Phase 1 and Phase 2(a) ONLY if the Modal app definition hasn't changed (i.e., if Phase 1's deployment is still running and the operator hasn't yet applied the symmetrisation fix — useful for re-running `--m6_1_1-diagnose` without paying redeploy cost). After the symmetrisation fix, a fresh deploy is required.

**Rationale**: M6.1's deployment lifecycle established the pattern (deploy-per-sweep, optionally reuse via `--m6_1-skip-deploy`). M6.1.1 inherits the same pattern verbatim. Modal's app-state mechanism (the handshake-dict pop-loop landed in M6.1's modal_bench_rest_grpc_server.py) handles the cross-deploy state cleanly — see [`feedback_smoke_warmup_seed_zero`](../../specs/022-m6-1-real-prompt-embeds/spec.md) memory for related cross-deploy state-cleanup work.

**Alternatives considered**:
- Single deployment with feature-flag toggle for symmetrisation: rejected — couples Phase 1 (always-on instrumentation) with Phase 2(a) (conditional symmetrisation) and increases the test surface. Two deployments is conceptually cleaner.
- Use vLLM's `--max-model-len` etc. to switch behaviour at runtime: rejected — not applicable; the bracketing change is a code edit, not a config parameter.

---

## R-6: Sentinel-object JSON schema validation — golden file, Pydantic, or JSON Schema?

**Decision**: **Pydantic v2 dataclasses** (project standard for `m6_1_types.py`, `m5_2_types.py`, etc.) with a unit test that golden-files a representative report for each `phase_2_path` ∈ `{phase_2a_verified, phase_2b_documented, drift_not_reproduced_confirmed, split_required, phase_2_pending}`. The Pydantic shape is the source of truth; the golden file proves the serialisation is byte-stable across PRs.

**Rationale**:
- **Type safety at write time**: `m6_1_1_reporter.write_m6_1_1_report(run: M6_1_1Run, ...)` is type-checked end-to-end by `mypy --strict` (Constitution Principle IV).
- **Discoverability at read time**: Pydantic dataclass fields self-document for IDE/LSP users (M6.2's spec writer will read M6.1.1's `M6_1_1Run` to design its own schema).
- **Test ergonomics**: golden file diffing makes additive schema changes (M6.2 will add new keys atop M6.1.1's) obvious in PR review.

**Alternatives considered**:
- Hand-rolled `json.dumps`: rejected — loses type-safety; M6.1 already uses Pydantic v2 dataclasses; consistency wins.
- JSON Schema (`schemas/m6_1_1.v1.json`): rejected as the source of truth — Pydantic's `model_json_schema()` can *generate* the schema if M6.2's spec writer wants one, but writing the schema by hand is duplicative.

---

## R-7: `phase_1_runs[]` append-on-re-read pattern (round-3 Q1) — how to handle corrupted existing JSON gracefully?

**Decision**: Best-effort read + fallback:
1. `m6_1_1_diagnose` reads `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` with `try: json.loads(path.read_text()) except (FileNotFoundError, json.JSONDecodeError, ValidationError)`.
2. On `FileNotFoundError`: start with `phase_1_runs = []` (first-run case).
3. On `json.JSONDecodeError` or Pydantic `ValidationError`: emit a stderr warning ("existing M6.1.1 report at <path> is unreadable; starting fresh phase_1_runs[]"); start with empty array; the first-run data is unrecoverable per round-3 Q1.
4. On success: parse into `M6_1_1Run`; copy `phase_1_runs[]` into the new run record; append the new Phase 1 result.

**Rationale**: round-3 Q1 explicitly says "If the existing file is corrupted or missing on re-run, the harness emits a stderr warning and starts a fresh `phase_1_runs` array (the first-run data is then unrecoverable; the operator is advised to commit M6.1.1's report to git between runs)." Implementation must match the spec verbatim.

**Alternatives considered**:
- Refuse to overwrite if parse fails (force operator to delete or fix the file): rejected by round-3 Q1 — the operator may legitimately be re-running after a botched first run, and forcing a manual cleanup is friction.
- Backup the existing file before overwrite: rejected — duplicates git's job. Round-3 Q1 advises committing between runs.

---

## R-8: Embed regression check threshold (FR-015b) — against M6.1's `engine_forward_ms` mean, M6's, or both?

**Decision**: Against **M6.1's** published `engine_forward_ms` mean per (embed cell × cohort), with `±5%` tolerance. M6.1's JSON is the immediate baseline (M6.1.1's hard precondition input per FR-001); M6's numbers are one milestone removed and would conflate two methodology shifts (M6 → M6.1 real prompt-embeds engine path + M6.1 → M6.1.1 instrumentation symmetrisation).

**Rationale**:
- The regression check exists to detect whether the Phase 2(a) symmetrisation code change accidentally perturbed the embed measurement window (FR-015b + round-2 Q2). The relevant comparison is "did embed shift under M6.1.1's symmetrisation?" — M6.1's numbers are the right reference because M6.1 is the version of the engine code immediately before M6.1.1's edit.
- Comparing against M6 would catch real per-prompt-embeds engine changes that M6.1 already published; that's not the regression M6.1.1 is testing for.
- ±5% matches the spec's explicit threshold (FR-015b "outside ±5% of M6.1's published mean").

**Alternatives considered**:
- ±2% (tighter): rejected as not in the spec; would create false-positive regressions from normal Modal scheduler jitter.
- Compare against both M6 and M6.1 with separate flags: rejected as cosmetic; the operator-actionable comparison is against M6.1 (the immediate predecessor).

---

## R-9: Default output paths + sidecar — what should `--m6_1_1-events-sidecar-out` default to?

**Decision**: Defaults match M6.1's convention with the `m6_1_1` suffix.
- `--m6_1_1-report-out` defaults to `docs/benchmarks/m6_1_1-engine-cost-instrumentation.md`.
- `--m6_1_1-report-json-out` defaults to `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json`.
- `--m6_1_1-events-sidecar-out` defaults to `docs/benchmarks/m6_1_1-events.jsonl`.
- `--m6_1_1-m6-1-baseline` defaults to `docs/benchmarks/m6_1-real-prompt-embeds.json`.

**Rationale**: M6.1 used `m6_1-*` defaults; M6.1.1 mirrors with `m6_1_1-*`. The operator can override any default via the explicit flag. Sidecar JSONL events are useful for post-hoc segment-level analysis (e.g., per-RPC histograms beyond the per-cohort means the markdown table shows).

**Alternatives considered**:
- Hyphenated `m6-1-1-*`: rejected — inconsistent with the project's filename convention (`m6_1-*`, not `m6-1-*`).
- Drop the sidecar entirely: rejected — useful for the audit-trail and for ad-hoc plotting in future analysis.

---

## Closing note

All 9 research items resolved on first pass. No NEEDS CLARIFICATION markers in plan.md's Technical Context. The implementation can proceed straight to `/speckit-tasks` with the design artifacts in `data-model.md`, `contracts/*.md`, and `quickstart.md`.
