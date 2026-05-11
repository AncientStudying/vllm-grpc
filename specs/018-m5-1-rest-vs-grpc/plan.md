# Implementation Plan: M5.1 — REST vs gRPC Head-to-Head on Real Wire

**Branch**: `018-m5-1-rest-vs-grpc` | **Date**: 2026-05-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/018-m5-1-rest-vs-grpc/spec.md`

## Summary

M5.1 closes the protocol-comparison gap M5 left open: it drives **REST and gRPC against the same Modal-hosted MockEngine over real wire** so the cumulative "tuned protobuf+gRPC is more time-efficient than REST" claim gets a clean cross-host control. Per the spec's clarifications (2026-05-11), the harness measures three cohort families per (path × hidden_size × concurrency) cell: a REST cohort over HTTP/1.1 with `Limits(max_keepalive_connections=c, max_connections=c, keepalive_expiry=300s)`; at c ≥ 2, **two parallel** tuned-gRPC sub-cohorts (`tuned_grpc_multiplexed` and `tuned_grpc_channels`) that decompose the gRPC advantage into multiplexing vs encoding+framing components; and a **per-cell** default-gRPC control cohort that lets the M5.1 report stand alone without cross-citing M5. Chat is exercised in streaming mode on both protocols (REST via Server-Sent-Events from a FastAPI shim; gRPC via the M3 bidi-streaming chat servicer) so TTFT carries the same semantic on both sides.

The technical approach reuses M5's cross-host harness end-to-end. `tools/benchmark/src/vllm_grpc_bench/modal_endpoint.py` (M5's deploy-once endpoint provider) gains a sibling Modal app variant exposing a FastAPI REST shim alongside the M3 gRPC servicers; both share the same `MockEngine` instance in-container, so the engine variable is held constant between protocols. A new `m5_1_sweep.py` wraps M5's per-cohort orchestrator with REST-cohort plumbing (FastAPI `/v1/chat/completions` SSE handler, `/v1/embeddings` JSON handler reading base64-encoded prompt-embedding tensors) and the dual-gRPC-sub-cohort matrix. A new `m5_1_supersede.py` (parallel to `m5_supersede.py`) maps each M1 time-axis cell the M5.1 matrix covers to its M5.1 verdict. The CLI gains `--m5_1`, `--m5_1-modal-region`, `--m5_1-modal-token-env`, `--m5_1-rest-host`, `--m5_1-grpc-host`, `--m5_1-skip-deploy`, `--m5_1-modal-endpoint` flags, all parallel to M5's `--m5*` family.

A new operator-facing Modal-deployment script lands at `scripts/python/modal_bench_rest_grpc_server.py` (CPU-only image, FastAPI + gRPC under a single `modal.App`, two `modal.forward()` calls — one HTTPS for REST, one plain-TCP for gRPC per M5's ALPN-incompatibility finding; bearer-token auth on both protocols).

Per **FR-017 / FR-019 (the user's explicit requirement)**, the implementation plan adds a `T-FINAL` task: after the report is published and committed, the maintainer runs a `narrative-refresh` step that updates `README.md`, `docs/benchmarks/summary.md`, and `docs/PLAN.md` to cite M5.1's published numbers (flipping the "M5.1 (upcoming)" milestone to "(delivered)" regardless of outcome shape, per Clarifications 2026-05-11), and that commit MUST be the **last commit** on the branch at the moment `gh pr create` runs. The plan documents this as a procedural gate — the harness does not enforce it; the maintainer's pre-PR checklist does.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12,<3.13"` in `pyproject.toml`) — unchanged from M5.
**Primary Dependencies**: `grpcio==1.80.0` (unchanged), `modal` (already present as M5 tooling dep; M5.1 reuses), `protobuf` (transitive), `fastapi` (already present in `packages/proxy/`; M5.1 reuses it inside the Modal app), `uvicorn` (already a `proxy` dep), `httpx` (bench client REST path — already used by M1's REST cohort), `numpy` (unchanged). No new runtime dependencies in `proxy` / `frontend` / `client`. The Modal app gains `fastapi` and `uvicorn` as Modal-image deps (already in the workspace, so no workspace edit).
**Storage**: N/A on the runtime path. M5.1 report lands as JSON+Markdown under `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}` (committed); transient per-iteration timing arrays land under `bench-results/m5_1-full/` (gitignored, same convention as M3/M4/M5). The Modal app uses no persistent volume; MockEngine is stateless.
**Testing**: `pytest` for unit and integration tests (`make check`). New M5.1 tests follow the M5 pattern: harness unit tests under `tools/benchmark/tests/` (REST cohort runner, FastAPI shim contract, dual-sub-cohort matrix builder, supersede-M1 table emitter, CLI flag wiring); integration tests under `tests/integration/` covering a tiny CPU-only Modal smoke run that exercises deploy → REST probe + gRPC probe → measure → teardown (Modal-secrets-gated, default-skip).
**Target Platform**: Local benchmark client on macOS (Apple Silicon M2/M3) and Linux x86-64 (unchanged). Remote Modal CPU-only instance in a region geographically distant from the client so measured median RTT lands in 30–100 ms (continuity with M5's `eu-west-1` choice; configurable via `--m5_1-modal-region`).
**Project Type**: Python `uv` workspace with multiple packages — `packages/{client,frontend,gen,proxy}` and `tools/benchmark`. M5.1 changes concentrate in `tools/benchmark/`; a new operator-facing Modal-deployment script lives at `scripts/python/modal_bench_rest_grpc_server.py`. No `proto/` changes (M5.1 does not measure schema candidates — those are M5 US2's domain). Production proto in `proto/vllm_grpc/v1/{chat,completions}.proto` remains on M3's shape.
**Performance Goals**: M5.1 *measures* tuned-gRPC vs REST on cross-host real wire; it does not preset a verdict-shape target. The empirical questions (per spec SC-001..SC-008): which protocol wins on TTFT at each (path × hidden_size × concurrency) cell; which M1 time-axis cells M5.1 supersedes; whether tuned-gRPC's M5 wins compound with the gRPC-vs-REST gap or partly overlap with it (decomposable via the multiplexed/channels sub-cohort split). Run-level expectation: measured median RTT 30–100 ms; per-cohort CV in the same band as M5 (loopback-CV × 2–4× for real-network jitter).
**Constraints**:
- Constitution I (Proto-First): no `.proto` edits in M5.1. M3's production proto shape is consumed verbatim by the gRPC servicers in the Modal app.
- Constitution II (Library Dependency, Not Fork): vLLM remains a published-library dependency; the M5.1 Modal app imports the mock engine, not vLLM proper. No vLLM source is patched.
- Constitution III (Phase Discipline): M5.1 deliverables match `docs/PLAN.md` v4's M5.1 section (REST cohort vs tuned-gRPC head-to-head on cross-host real wire + Supersedes-M1-time-axis reporting + executive-narrative refresh). No M6 (corpus expansion) or M7 (model expansion) functionality is pulled forward — the spec explicitly excludes both.
- Constitution IV (CI is the Merge Gate): the M5.1 *harness mechanics* (REST cohort runner, FastAPI shim contract, dual-sub-cohort matrix, supersede-M1 builder, CLI flag wiring) are unit-tested at PR time. The full M5.1 sweep is operator-triggered and not part of CI's runtime budget. The Modal-smoke integration test runs in CI only when `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` are present in the CI environment (gated; default-skip on PRs without secrets, identical to M5's gating).
- Constitution V (Honest Measurement): `server_bound` cohorts (inherited from M5, FR-005) excluded from `recommend` tallies on **either protocol**; cells where either protocol's cohort is `server_bound` reported as `comparison_unavailable`; `low_rtt_caveat` attached every time RTT falls below 20 ms; M5.1 negative-result cells (no_winner with CIs) appendixed alongside their supporting numbers.
- Spec FR-002: REST shim must emit SSE for chat (per Clarifications 2026-05-11). Bearer-token auth on both protocols.
- Spec FR-006 / FR-008: dual-sub-cohort gRPC matrix at c ≥ 2; REST pool sized = c with keep-alive.
- Spec FR-007: default-gRPC control measured at **every** (path × hidden_size × concurrency) cell (18 cohorts, full re-measurement, per Clarifications 2026-05-11).
- Spec FR-014: M5.1 JSON schema is a strict superset of M5's `m5-cross-host-validation.json` — additive only.
- Spec FR-017 / FR-019: README refresh is **unconditional** on outcome shape and is the **last commit** on the PR branch (per Clarifications 2026-05-11).

**Scale/Scope**:
- 2 paths (chat_stream, embed) × 3 widths (hidden_size 2048, 4096, 8192) × 3 concurrencies (c=1, c=4, c=8) = **18 cells** in the matrix.
- Cohort families per cell:
  - REST: 1 cohort/cell × 18 cells = 18 cohorts.
  - Tuned-gRPC: at c=1, 1 sub-cohort/cell × 6 cells = 6 cohorts; at c=4 and c=8, 2 sub-cohorts/cell × 12 cells = 24 cohorts. **Total tuned-gRPC = 30 cohorts.**
  - Default-gRPC control: 1 cohort/cell × 18 cells = 18 cohorts.
  - Shared-baseline cohorts: 1 per (path × protocol) per run for CI anchoring; effectively folded into the per-cell measurements above.
  - Warm-up cohorts: 1 per protocol per path = 4 discarded cohorts (no recommend impact).
- **Total measurement cohorts ≈ 66** (18 + 30 + 18) plus 4 warmup discards ≈ 70 cohorts.
- Cohort sample sizes follow M5's cascade: default n ≥ 100; expand to n ≥ 250 on borderline.
- Total expected M5.1 runtime budget: target ≤ 60 minutes on Modal CPU-only instance class (per spec SC-007) for the full sweep. Cost target: well under one Modal CPU-instance-hour-class budget over the run.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | M5.1 alignment | Notes |
|-----------|----------------|-------|
| **I. Proto-First** | PASS | M5.1 makes no `.proto` edits. M3's production proto is consumed verbatim by the gRPC servicers in the Modal app. M5.1 does not measure schema candidates (M5 US2's domain). |
| **II. Library Dependency, Not Fork** | PASS | M5.1's Modal app imports M4's `MockEngine` and M3's `M3CompletionsServicer` / `M3ChatServicer` from this repo, plus a new FastAPI shim that calls the same `MockEngine` methods. vLLM remains a published-library dependency. No vLLM source is patched. |
| **III. Phase Discipline** | PASS | M5 closed on 2026-05-11 (PR #21, branch `017-m5-cross-host-validation`). M5.1 is the next active milestone per `docs/PLAN.md` v4. M5.1 deliverables match the PLAN's M5.1 section: cross-host REST-vs-tuned-gRPC head-to-head + Supersedes-M1-time-axis reporting + executive-narrative refresh. No M6 (corpus expansion) or M7 (model expansion) functionality is pulled forward — the spec explicitly excludes both. |
| **IV. CI is the Merge Gate** | PASS | The M5.1 harness mechanics (REST cohort runner, FastAPI shim contract, dual-sub-cohort matrix, supersede-M1 builder, CLI flag wiring) are unit-tested under `make check`. The full M5.1 sweep is operator-triggered and not part of CI's runtime budget. A small Modal-smoke integration test exercises deploy → REST probe + gRPC probe → single-cohort → teardown only when `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` are present in the CI environment (gated default-skip, identical to M5). |
| **V. Honest Measurement** | PASS — *strengthened* | M5.1 adds four honesty mechanisms beyond M5: (a) `comparison_unavailable` literal fires when either protocol's cohort is `server_bound`, so a one-sided cohort never produces a head-to-head verdict; (b) every M5.1 cell carries the **REST shim's intra-process overhead** alongside the protocol-comparison delta, so the reader can distinguish transport time from FastAPI-plumbing time; (c) per-cell `rest_connections_opened` + `grpc_channels_opened` carry the actually-observed connection counts so the pool-sizing claim is verifiable in the report; (d) **FR-017's narrative refresh is unconditional on outcome shape** — if M5.1's numbers contradict the anticipated headline, the README is rewritten to an honest mixed-results framing, not held pending a second PR. The M1 bytes-axis claims are explicitly **not** in the supersession scope (FR-021) because they are structural and unaffected by RTT, so M5.1 does not retract them by silence. |

**Gate result**: PASS on initial check. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/018-m5-1-rest-vs-grpc/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 — methodology research (FastAPI shim shape, dual-protocol Modal app, REST cohort runner, dual-sub-cohort matrix, supersede-M1 mapping, JSON schema delta, narrative-refresh gating)
├── data-model.md        # Phase 1 — M5.1 dataclasses (RESTCohortRecord, ShimOverheadRecord, GRPCSubCohortKind, ComparisonVerdict, SupersedesM1Entry, M5_1 cohort root)
├── quickstart.md        # Phase 1 — how to reproduce the M5.1 sweep end-to-end (Modal token setup, single-CLI invocation, narrative-refresh pre-PR step, teardown)
├── contracts/
│   ├── m5_1-bench-cli.md           # `vllm_grpc_bench --m5_1` CLI signature, flags, exit codes
│   ├── m5_1-report-schema.md       # JSON schema delta vs. m5-cross-host-validation.json (strict superset)
│   ├── m5_1-modal-app.md           # Modal app contract: image, dual entry-points (FastAPI + gRPC), exposed tunnel ports (HTTPS + plain-TCP), env vars / secrets, handshake with harness
│   └── m5_1-rest-shim-endpoints.md # FastAPI shim REST contract: /v1/chat/completions SSE + /v1/embeddings JSON, request/response shapes, bearer-token auth
├── checklists/
│   └── requirements.md             # Created in /speckit-specify
└── tasks.md             # Created by /speckit-tasks (NOT this command)
```

### Source Code (repository root)

```text
proto/vllm_grpc/v1/
├── chat.proto                          # M3 production shape — UNCHANGED in M5.1
├── completions.proto                   # M3 production shape — UNCHANGED in M5.1
└── health.proto                        # untouched

tools/benchmark/src/vllm_grpc_bench/
├── m5_1_sweep.py                       # NEW — cross-host REST-vs-gRPC sweep orchestrator
│                                         (parallel to m5_sweep.py; wraps M5's per-cohort
│                                          orchestrator with REST-cohort plumbing, dual-sub-
│                                          cohort gRPC matrix at c ≥ 2, default-gRPC control
│                                          at every cell, comparison-verdict emitter)
├── m5_1_supersede.py                   # NEW — Supersedes-M1-time-axis table builder
│                                         (parallel to m5_supersede.py; maps each M1 time-
│                                          axis cell the M5.1 matrix covers to its M5.1
│                                          verdict + supporting numbers + rationale)
├── rest_cohort.py                      # NEW — REST cohort runner: httpx.AsyncClient with
│                                         per-c pool sizing, SSE chat client, JSON embed
│                                         client, shim-overhead capture, RTT probe over
│                                         HTTP/1.1 keep-alive connection
├── modal_endpoint.py                   # EXTENDED — adds REST endpoint URL alongside the
│                                         gRPC tunnel URL in the deploy-once handshake
│                                         (additive — M5's gRPC-only path remains)
├── reporter.py                         # EXTENDED — adds M5.1 Markdown + JSON sections
│                                         (Per-cell comparison matrix; Supersedes-M1 table;
│                                          REST shim overhead appendix; M1 bytes-axis
│                                          preservation note per FR-021)
├── m3_types.py                         # EXTENDED — additive dataclasses for M5.1
│                                         (RESTCohortRecord, ShimOverheadRecord,
│                                          GRPCSubCohortKind, ComparisonVerdict,
│                                          SupersedesM1Entry, M5_1 cohort root)
├── __main__.py                         # EXTENDED — adds --m5_1 flag family
├── m3_sweep.py                         # UNCHANGED in M5.1
├── m4_sweep.py                         # UNCHANGED
├── m4_supersede.py                     # UNCHANGED
├── m5_sweep.py                         # UNCHANGED — M5.1 reuses M5's helpers (RTT probe,
│                                         server_bound classifier, frozen-channel
│                                         configuration loader); does not edit it
├── m5_supersede.py                     # UNCHANGED
├── mock_engine.py                      # UNCHANGED — same MockEngine call path on both
│                                         protocols inside the Modal container
├── channel_config.py                   # UNCHANGED — M5's per-axis frozen-tuned-channel
│                                         configuration loader is consumed verbatim by
│                                         m5_1_sweep.py
├── rtt_probe.py                        # UNCHANGED for gRPC; reused for REST via a new
│                                         lightweight HTTP/1.1 echo path (research.md R-3)
├── ...                                 # other M5 modules unchanged
└── tests/
    ├── test_m5_1_sweep.py              # NEW
    ├── test_m5_1_supersede.py          # NEW
    ├── test_rest_cohort.py             # NEW
    ├── test_modal_endpoint_rest.py     # NEW (extended modal_endpoint coverage)
    ├── test_m5_1_reporter.py           # NEW
    └── ...                             # existing M5 tests unchanged

scripts/python/
├── modal_bench_grpc_server.py          # UNCHANGED — M5's gRPC-only deploy
├── modal_bench_rest_grpc_server.py     # NEW — M5.1 dual-protocol deploy:
│                                         FastAPI shim + M3 gRPC servicers sharing one
│                                         in-container MockEngine instance; two
│                                         modal.forward() calls (HTTPS for REST, plain-
│                                         TCP for gRPC per M5's ALPN-incompatibility
│                                         finding); BearerTokenInterceptor for gRPC and
│                                         a FastAPI middleware for REST bearer auth
└── ...

tests/integration/
└── test_m5_1_modal_smoke.py            # NEW — Modal-secrets-gated smoke run that
                                          deploys the dual-protocol app, runs one tiny
                                          REST cohort + one tiny gRPC cohort against a
                                          single cell, verifies clean teardown.

docs/benchmarks/
├── m5_1-rest-vs-grpc.md                # NEW — published M5.1 report (committed by T-FINAL)
├── m5_1-rest-vs-grpc.json              # NEW — companion JSON (additive superset of M5's schema)
├── m5-cross-host-validation.{md,json}  # UNCHANGED — M5's published report stays in place
├── m4-time-axis-tuning.{md,json}       # UNCHANGED — M4's published report stays in place
├── m3-channel-tuning.{md,json}         # UNCHANGED
├── m3-channel-tuning-time.{md,json}    # UNCHANGED
└── summary.md                          # EDITED by T-FINAL (narrative refresh)

docs/
└── PLAN.md                             # EDITED by T-FINAL (M5.1 status flip to delivered)

README.md                               # EDITED by T-FINAL (narrative refresh; M5.1 status
                                          flip; last commit on PR branch per FR-019)
```

**Structure Decision**: M5.1 mirrors M5's package layout (a per-milestone sweep module + a per-milestone supersession module under `tools/benchmark/src/vllm_grpc_bench/`, plus an operator-facing Modal deployment script under `scripts/python/`). New code is additive — every existing M5 module remains importable and its behavior unchanged when the new `--m5_1` flag is not passed. The Modal app variant exposes both protocols under a single `modal.App` so the engine variable is held constant between cohorts; this requires two `modal.forward()` calls (HTTPS for REST, plain-TCP for gRPC) because of M5's documented ALPN-incompatibility constraint on Modal's HTTPS edge for HTTP/2.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. No complexity-tracking entries required.

---

## Implementation Phases (preview — `/speckit-tasks` will expand)

This section previews the phases `/speckit-tasks` will turn into discrete tasks. It is **not** the task list; it is a scaffolding note so a reviewer can read this plan top-to-bottom and understand where the implementation goes.

- **Phase A — Modal app (dual protocol)**: build `scripts/python/modal_bench_rest_grpc_server.py` exposing FastAPI + gRPC sharing one MockEngine. Smoke test locally then in CI under Modal secrets.
- **Phase B — REST cohort runner**: `rest_cohort.py` with SSE chat client, JSON embed client, configurable `httpx.AsyncClient` pool, shim-overhead capture, RTT probe over HTTP/1.1.
- **Phase C — Sweep orchestrator**: `m5_1_sweep.py` — assemble the 18-cell matrix; dispatch REST cohort + dual gRPC sub-cohorts + default-gRPC control per cell; emit comparison verdicts; honor `comparison_unavailable` when either side is `server_bound`.
- **Phase D — Supersede-M1**: `m5_1_supersede.py` — load M1's published time-axis cells, map to M5.1 matrix, build supersedes-M1 table (verdict-changed rows highlighted per FR-020).
- **Phase E — Reporter**: extend `reporter.py` with M5.1 Markdown + JSON sections; per-cell comparison matrix; Supersedes-M1 table; REST shim overhead appendix; M1 bytes-axis preservation note (FR-021); read-instruction caveat for MockEngine inference-cost neutrality (Edge Cases).
- **Phase F — CLI**: extend `__main__.py` with the `--m5_1*` flag family; document in `contracts/m5_1-bench-cli.md`.
- **Phase G — Tests**: unit tests under `tools/benchmark/tests/`; Modal-secrets-gated smoke test under `tests/integration/test_m5_1_modal_smoke.py`.
- **Phase H — Run**: operator-triggered full sweep via `python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=eu-west-1`; commits report under `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}`.
- **T-FINAL — Narrative refresh (FR-017/018/019)**: maintainer-driven; updates README.md, summary.md, PLAN.md to reflect M5.1's actual published numbers (whether confirming, contradicting, or mixed per Clarifications 2026-05-11). This commit MUST be the **last commit** on the branch at `gh pr create` time. The PR description cites this commit's SHA explicitly. (Procedural — not enforced by tooling; documented in `quickstart.md`.)
