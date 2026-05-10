# Implementation Plan: M5 — Cross-Host Time-Axis Validation

**Branch**: `017-m5-cross-host-validation` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/017-m5-cross-host-validation/spec.md`

## Summary

M5 re-runs M4's published channel sweep and schema-candidate sweep against a gRPC server deployed on Modal in a region geographically distant from the local benchmark client, so the per-RPC transmission crosses real wire (target measured median RTT 30–100 ms, per Clarifications 2026-05-10) rather than `127.0.0.1`. M4's `keepalive` and `http2_framing` verdicts carry an explicit "loopback caveat" (M4 FR-010) because RTT-bounded behavior cannot manifest on a single host; M5 resolves those caveats and sanity-checks `max_message_size` / `compression` on real-wire framing. The full axis × width × path matrix (4 × 3 × 2 = ~48 candidate cells) is re-run with M4's exact methodology — no-pacing mock cohort, shared-baseline orchestrator, n ≥ 100 / 250 borderline-expand cascade, per-cohort CV recording, TTFT-first-class verdicts, frozen-channel baseline for schema candidates — against an M5 cross-host shared-baseline cohort. M3's bytes report and M4's time report stay in place; the M5 report is a sibling at `docs/benchmarks/m5-cross-host-validation.{md,json}` with a JSON schema that is a **strict superset** of `m4-time-axis-tuning.json` (additive only — M4 readers continue to work).

The technical approach reuses the M4 harness modules under `tools/benchmark/src/vllm_grpc_bench/` essentially unchanged. `m4_sweep.py` is widened so its `serve_in_process` call becomes a switchable "endpoint provider" (in-process vs remote channel), preserving bit-identical M4 reproduction when no remote endpoint is given. A new `m5_sweep.py` wraps the existing orchestrator with cross-host concerns: deploying the Modal-hosted mock-engine gRPC server, capturing the published tunnel URL + bearer token, running an active RTT probe before each cohort (per FR-004), classifying cohorts as `server_bound` analogously to M4's `client_bound` (per FR-005), attaching `low_rtt_caveat` annotations when measured RTT is below the 20 ms exercise threshold, and tearing the Modal app down at run end. A new `m5_supersede.py` (parallel to `m4_supersede.py`) reads `m4-time-axis-tuning.json` and emits the "Supersedes M4" table per FR-015. The Modal app itself lives under `scripts/python/modal_bench_grpc_server.py` as a CPU-only container (per Clarifications Q2) that imports M4's `MockEngine` and M3's `M3CompletionsServicer` / `M3ChatServicer` verbatim and exposes the gRPC port via `modal.forward()` with Modal-terminated TLS plus an application-level bearer-token interceptor on the servicers (per Clarifications Q3 — concrete mechanism resolved in `research.md` R-1). The CLI gains `--m5`, `--m5-modal-endpoint`, `--m5-modal-token-env`, `--m5-rtt-validity-threshold-ms`, `--m5-rtt-exercise-threshold-ms`, and `--m5-warmup-n` flags.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12,<3.13"` in `pyproject.toml`) — unchanged from M4.
**Primary Dependencies**: `grpcio==1.80.0` (pinned in `[dependency-groups] graph-targets`), `modal` (already present via `scripts/python/modal_*.py`; M5 promotes it to a tools-benchmark-time dep used by `m5_sweep.py` for the deploy/teardown handshake), `protobuf` (transitive via `grpcio-tools`), `FastAPI` (proxy — untouched), `httpx` (bench client — untouched), `numpy` (mock embedding tensors and CI math — untouched). No new runtime dependencies in `proxy` / `frontend` / `client`. The harness gains `modal` as a tooling-only dependency.
**Storage**: N/A on the runtime path. M5 report lands as JSON+Markdown under `docs/benchmarks/m5-cross-host-validation.{md,json}` (committed); transient per-iteration timing arrays land under `bench-results/m5-full/` (gitignored, same convention as M3/M4). The Modal app uses no persistent volume; the mock engine is stateless.
**Testing**: `pytest` for unit and integration tests (`make check`). New M5 tests follow the M4 pattern: harness unit tests under `tools/benchmark/tests/` (RTT probe, server_bound classifier, supersession table builder, CLI flag wiring); integration tests under `tests/integration/` covering a tiny CPU-only Modal smoke run that exercises the deploy → probe → measure → teardown handshake without running a full sweep.
**Target Platform**: Local benchmark client on macOS (Apple Silicon M2/M3) and Linux x86-64. Remote gRPC server on Modal CPU-only instance (per Clarifications Q2), in a region geographically distant from the client (per Clarifications Q1) so measured median RTT lands in 30–100 ms. The harness runs locally; the Modal app is operator-deployed via the harness's `--m5` CLI mode.
**Project Type**: Python `uv` workspace with multiple packages — `packages/{client,frontend,gen,proxy}` and `tools/benchmark`. M5 changes concentrate in `tools/benchmark/`; a new operator-facing Modal-deployment script lives at `scripts/python/modal_bench_grpc_server.py`. No `proto/` changes (US3 schema candidates inherit M4's `proto/vllm_grpc/v1/m4-candidates/` namespace verbatim).
**Performance Goals**: M5 *validates* M4's time-axis numbers under real-wire transport; it does not preset a verdict-shape target. The empirical questions (per spec SC-001..SC-007): does M5's `keepalive` / `http2_framing` recommendation at each width × path differ from M4's loopback-caveated `no_winner`; do `max_message_size` / `compression` M5 verdicts confirm or contradict M4's loopback verdicts; do the schema candidates produce the same bytes/time effect on real wire as on loopback. Run-level expectation: measured median RTT 30–100 ms; per-cohort CV expected to be 2–4× M4's loopback CV given real-network jitter (FR-005 `noisy_baseline` flag handles this).
**Constraints**:
- Constitution I (Proto-First): no `.proto` edits in M5. M4's `proto/vllm_grpc/v1/m4-candidates/` namespace is consumed verbatim. The Modal-hosted server registers the same proto-derived servicers as M4.
- Constitution II (Library Dependency, Not Fork): vLLM remains a published-library dependency; the M5 Modal app imports the mock engine, not vLLM proper. No vLLM source is patched.
- Constitution III (Phase Discipline): M5 deliverables match `docs/PLAN.md` v4's M5 section (cross-host channel sweep + schema-candidate re-measurement + supersedes-M4 reporting). No M6 (corpus expansion) or M7 (model expansion) functionality is pulled forward — the spec explicitly excludes both.
- Constitution IV (CI is the Merge Gate): the M5 *harness mechanics* (RTT probe, server_bound classifier, supersession builder) are unit-tested at PR time. The full M5 sweep is operator-triggered and not part of CI's runtime budget. The Modal-smoke integration test runs in CI only when `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` are present in the CI environment (gated; default-skip on PRs without secrets).
- Constitution V (Honest Measurement): `client_bound` (inherited from M4) AND `server_bound` (new, per FR-005) cohorts are excluded from `recommend` tallies; `low_rtt_caveat` is attached every time the cell's RTT falls below the 20 ms exercise threshold; M5 negative-result schema candidates are appendixed alongside M4's negative results (FR-013).
- Spec FR-002: TLS via Modal's tunnel TLS termination + application-level bearer-token interceptor (mechanism finalized in research.md R-1). TLS overhead is constant across cohorts; the harness does not vary TLS as part of the channel sweep.
- Spec FR-004: measured median RTT in 30–100 ms; same-host-fallback threshold 1 ms (refuse verdict); exercise threshold 20 ms (attach `low_rtt_caveat`).
- Spec FR-014: M5 JSON schema is a strict superset of M4's `m4-time-axis-tuning.json` — additive only.
- Spec FR-015: M5 "Supersedes M4" table is forward-only; M4's report stays in place and is not edited.

**Scale/Scope**:
- 2 cross-host shared-baseline cohorts (one per path) at n ≥ 100 = up front, plus per-cohort warm-up discards (R-5 in research.md).
- 4 axes × 3 widths × 2 paths × ≥2 configs per axis = ~48 candidate cells (US1). Borderline-expand may grow some to n ≥ 250.
- 2 per-path frozen-channel baseline cohorts at n ≥ 100 (US2 prerequisite, derived from US1 winners).
- 3 named schema candidates (FR-011) × at least hidden_size 4096 = 3+ cohorts (4096-first cascade adds 2048 + 8192 for `recommend`/borderline candidates).
- Total expected M5 runtime budget: target ≤ 8 hours on Modal CPU-only instance class (per Clarifications Q2) for the full sweep, gated by real-network per-RPC latency. Cost target: well under one Modal CPU-instance-hour-class budget over the run (~10× cheaper than the equivalent A10G run).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | M5 alignment | Notes |
|-----------|--------------|-------|
| **I. Proto-First** | ✅ Pass | M5 makes no `.proto` edits. M4's `proto/vllm_grpc/v1/m4-candidates/` namespace is consumed verbatim by the Modal-hosted server. Production proto in `proto/vllm_grpc/v1/{chat,completions}.proto` remains on M3's shape per M4's Assumptions. |
| **II. Library Dependency, Not Fork** | ✅ Pass | M5's Modal app imports M4's `MockEngine` and M3's `M3CompletionsServicer` / `M3ChatServicer` from this repo, not from a vendored vLLM copy. vLLM remains a published-library dependency. No vLLM source is patched. |
| **III. Phase Discipline** | ✅ Pass | M4 closed on 2026-05-10 (PR #20, branch `016-m4-time-axis-tuning`). M5 is the active milestone per `docs/PLAN.md` v4. M5 deliverables match the PLAN's M5 section: cross-host channel sweep + cross-host schema-candidate re-measurement + Supersedes-M4 reporting. No M6 (corpus expansion) or M7 (model expansion) functionality is pulled forward — the spec explicitly excludes both. |
| **IV. CI is the Merge Gate** | ✅ Pass | The M5 harness mechanics (RTT probe, server_bound classifier, supersession builder, CLI flag wiring) are unit-tested under `make check`. The full M5 sweep is operator-triggered and not part of CI's runtime budget. A small Modal-smoke integration test exercises deploy → probe → single-cohort → teardown only when `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` are present in the CI environment (gated default-skip). |
| **V. Honest Measurement** | ✅ Pass — *strengthened* | M5 adds three explicit honesty mechanisms beyond M4: (a) `server_bound` cohorts are excluded from `recommend` tallies per FR-005 (parallel to M4's `client_bound`), (b) every M5 cell carries its measured RTT distribution alongside its supporting numbers (FR-004 + SC-006), (c) cells whose RTT falls in the 1 ms < median < 20 ms band carry `low_rtt_caveat` so the cross-host claim cannot be silently weakened by an unexpectedly fast Modal route. Constitution V's "no metric may be selectively omitted" applies to every cell. |

**Gate result**: ✅ Pass on initial check. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/017-m5-cross-host-validation/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 — methodology research (Modal-gRPC-TLS exposure, single-CLI orchestration, RTT probe, server_bound classification, warm-up cohorts, region pick, runtime budget, JSON schema delta)
├── data-model.md        # Phase 1 — M5 dataclasses (RTTRecord, LowRttCaveat, ServerBoundFlag, SupersedesM4 entry, M5 cohort root)
├── quickstart.md        # Phase 1 — how to reproduce the M5 sweep end-to-end (Modal token setup, single-CLI invocation, teardown)
├── contracts/
│   ├── m5-bench-cli.md            # `vllm_grpc_bench --m5` CLI signature, flags, exit codes
│   ├── m5-report-schema.md        # JSON schema delta vs. m4-time-axis-tuning.json (strict superset)
│   └── m5-modal-app.md            # Modal app contract: image, entry-points, exposed tunnel ports, env vars / secrets, handshake with harness
├── checklists/
│   └── requirements.md            # Created in /speckit-specify
└── tasks.md             # Created by /speckit-tasks (NOT this command)
```

### Source Code (repository root)

```text
proto/vllm_grpc/v1/
├── chat.proto                          # M3 production shape — UNCHANGED in M5
├── completions.proto                   # M3 production shape — UNCHANGED in M5
├── health.proto                        # untouched
└── m4-candidates/                      # UNCHANGED — M5 consumes M4's candidate proto shapes verbatim
    ├── packed_token_ids.proto
    ├── oneof_flattened_input.proto
    └── chunk_granularity.proto

packages/
├── frontend/src/vllm_grpc_frontend/    # untouched in M5
├── proxy/src/vllm_grpc_proxy/          # untouched in M5
├── client/src/vllm_grpc_client/        # untouched in M5
├── gen/                                # auto-regenerated; M5 reuses the M4-augmented stubs
└── per-package tests                   # untouched in M5

tools/benchmark/
├── src/vllm_grpc_bench/
│   ├── __main__.py                     # MODIFIED: add `--m5`, `--m5-modal-endpoint`, `--m5-modal-token-env`, `--m5-rtt-validity-threshold-ms`, `--m5-rtt-exercise-threshold-ms`, `--m5-warmup-n`, `--m5-modal-region` flags
│   ├── runner.py                       # untouched (M5 reuses M4's cohort-sizing cascade)
│   ├── reporter.py                     # MODIFIED: M5 report layout (Supersedes M4 table, per-cell RTT distribution, low_rtt_caveat / server_bound annotations); writes m5-cross-host-validation.{md,json}
│   ├── mock_engine.py                  # untouched (M5 reuses M4's no-pacing mock)
│   ├── m3_types.py                     # MODIFIED: add `Verdict` literal "server_bound"; add `RTTRecord`, `LowRttCaveat`, `SupersedesM4Entry`, `M5CrossHostBaseline` dataclasses; keep "client_bound" + "noise_bounded" literals for M3/M4-report compat
│   ├── m4_sweep.py                     # MODIFIED minimally: replace direct `serve_in_process(...)` call with `endpoint_provider` argument (callable returning an async context manager yielding `(host:port, channel_credentials, call_metadata)`); preserve in-process default so M4 reproductions remain bit-identical
│   ├── m4_supersede.py                 # untouched (M5 adds a parallel m5_supersede.py)
│   ├── m5_sweep.py                     # NEW: cross-host orchestrator — Modal deploy/teardown handshake, RTT probe per cohort, server_bound classifier, low_rtt_caveat annotator, supersession-table feeder, warm-up cohort discard
│   ├── m5_supersede.py                 # NEW: reads m4-time-axis-tuning.json + m5 results, emits Supersedes M4 table
│   ├── rtt_probe.py                    # NEW: pre-cohort active RTT probe (unary RPC against same channel; configurable probe count); returns RTTRecord
│   └── modal_endpoint.py               # NEW: harness-side Modal handshake — invokes `modal run scripts/python/modal_bench_grpc_server.py`, captures published tunnel URL + bearer token via `modal.Dict`, yields endpoint_provider context manager
├── corpus/
│   └── m3_long_stream.json             # untouched (M5 reuses M3's corpus, same as M4)
└── tests/
    ├── test_mock_engine.py             # untouched (M4 already covers pace_tokens=False)
    ├── test_m4_sweep.py                # MODIFIED: cover endpoint_provider abstraction with an in-process default (bit-identical to before) AND a stub remote-channel provider for unit-test coverage
    ├── test_m4_supersede.py            # untouched
    ├── test_m4_cli.py                  # untouched
    ├── test_m5_sweep.py                # NEW: cross-host orchestrator wiring, RTT-probe integration, server_bound classification on synthetic timings, low_rtt_caveat annotation, warm-up discard, run-level RTT summary
    ├── test_m5_supersede.py            # NEW: Supersedes M4 table generation from synthetic m4/m5 JSON pairs
    ├── test_m5_cli.py                  # NEW: CLI flag wiring (--m5 mode triggers m5_sweep entry point; all M5-specific flags surface through to the orchestrator)
    ├── test_rtt_probe.py               # NEW: probe count, median + p95 math, refuse-verdict gating below 1 ms
    └── test_modal_endpoint.py          # NEW (stubbed Modal handshake): unit-level verification that `modal_endpoint` correctly hands off the bearer token via call metadata; full Modal contact happens in integration tests

scripts/python/
└── modal_bench_grpc_server.py          # NEW: Modal app exposing M4's MockEngine + M3CompletionsServicer + M3ChatServicer on a CPU-only Modal container; opens `modal.forward(port, unencrypted=False)` (TLS-terminated by Modal — per research.md R-1) and registers a bearer-token interceptor on the servicers; publishes tunnel URL + bearer token via `modal.Dict` for harness pickup

tests/integration/
├── test_m4_cli.py                      # untouched
└── test_m5_modal_smoke.py              # NEW: end-to-end smoke — deploys the Modal app, runs a single 10-iteration cohort against it, validates RTT > 1 ms and a single cohort entry in a temp JSON output; gated by MODAL_TOKEN_ID/MODAL_TOKEN_SECRET in env (default-skip without them)

docs/
├── PLAN.md                             # MODIFIED at end: tick M5 from "upcoming" to "active" / "delivered" as the sweeps land
└── benchmarks/
    ├── m3-channel-tuning.{md,json}         # untouched (M3 bytes report — stays in place)
    ├── m3-channel-tuning-time.{md,json}    # untouched (M3 time report — stays in place; M4 cites supersession entries)
    ├── m4-time-axis-tuning.{md,json}       # untouched (M4 report — stays in place; M5 cites supersession entries)
    └── m5-cross-host-validation.{md,json}  # NEW: M5 report (strict-superset JSON schema vs. m4-time-axis-tuning.json)

bench-results/                          # gitignored — transient
└── m5-full/                            # NEW: per-iteration timing arrays for the M5 sweep
```

**Structure Decision**: Reuse the M4 layout — same `tools/benchmark/` package, same `docs/benchmarks/` report convention. The M4 harness internals are extended via a small, surgical refactor: `m4_sweep.py`'s direct `serve_in_process(...)` call is replaced with an `endpoint_provider` callable argument (default = the existing `serve_in_process`, preserving bit-identical M4 behavior). Cross-host concerns live in three NEW modules — `m5_sweep.py` (orchestrator), `modal_endpoint.py` (deploy/teardown handshake + tunnel-URL capture), `rtt_probe.py` (per-cohort RTT measurement) — plus the new operator-facing Modal app under `scripts/python/`. No new top-level packages. Existing M3 and M4 modules remain runnable, so M3 bytes reports and M4 time reports remain reproducible. The Modal app's CPU-only instance class is consistent with the project's "GPU cost removed from the loop" stance for the post-M3 mock-engine path; existing GPU-class Modal apps (`modal_frontend_serve.py` etc.) are untouched because they serve a different purpose (real-model M1 baseline).

## Complexity Tracking

> No Constitution Check violations to justify. Table omitted.
