# Implementation Plan: M5.2 — REST Transport Path × gRPC Tuning Surface

**Branch**: `019-m5-2-transport-tuning` | **Date**: 2026-05-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/019-m5-2-transport-tuning/spec.md`

## Summary

M5.2 closes two questions M5.1 left open: (1) a **production-equivalent REST transport** for the head-to-head — measuring Modal's HTTPS edge (TLS-terminated, anycast-routed) alongside M5.1's plain-TCP REST cohort so the operator sees how the network path moves the verdict, and (2) a **resolution increase from n=100 to n=250** so the small `default_grpc` vs `tuned_grpc_*` deltas M5.1 reported (frequently ±3%, at the noise floor) can be resolved as either genuinely neutral or real-but-small. M5.2 is **methodology continuity, not new methodology** — it reuses M5.1's harness end-to-end and widens the cohort surface from four (REST + 3 gRPC) to five (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`, `tuned_grpc_channels`) while raising per-cohort n.

The technical approach reuses M5.1's M5.1 sweep + supersede modules without methodological edit. A new `m5_2_sweep.py` wraps `m5_1_sweep`'s cohort runner with the dual-REST-transport extension (a second `rest_cohort` instance per cell pointed at the HTTPS edge URL while the plain-TCP REST cohort keeps M5.1's existing URL), a per-run **per-request JSONL events sidecar** (FR-012a — gzipped at commit time, ~1.5–3 MB compressed per full sweep), and a **three-tier symmetry block** (FR-005b) emitted into the M5.2 JSON schema and asserted at run start. A new `m5_2_supersede.py` builds the "Supersedes M5.1" table (parallel to `m5_1_supersede.py`). The existing `scripts/python/regen_bench_reports.py` is extended into a **round-trippable regenerator** (FR-012b) that reads only the gzipped JSONL sidecar + per-run config and produces a byte-identical Markdown + aggregate JSON — the harness MUST NOT emit aggregates directly. The CLI gains `--m5_2`, `--m5_2-modal-region`, `--m5_2-modal-token-env`, `--m5_2-rest-https-edge-host`, `--m5_2-rest-plain-tcp-host`, `--m5_2-grpc-host`, `--m5_2-skip-deploy`, `--m5_2-modal-endpoint`, `--m5_2-smoke`, `--m5_2-n` (default 250) flags, all parallel to M5.1's `--m5_1*` family. The pre-flight smoke harness (FR-005a) extends M5.1's existing `--m5_1-smoke` with M5.2-specific assertions (both REST transports reachable; M5.2-additive JSON schema fields round-trip; per-cohort RTT probe within thresholds for all five cohorts) under a new `--m5_2-smoke` flag that delegates to the M5.2 sweep with reduced cell coverage.

This plan also covers two documentation refactors (US2 + US3) that land in the same M5.2 PR: a new top-level `ANALYSIS.md` consolidating findings across M1–M5.2, a `docs/benchmarks/summary.md` replaced with a one-line redirect, `docs/PLAN.md` milestone-findings replaced with `ANALYSIS.md` pointers, and a `README.md` simplification + tooling-validation pass (target ≤180 lines from current 285). Per **FR-024 + FR-024a**, the PR commit log decomposes the narrative refresh into three discrete, ordered commits: (i) "Summarize M5.2 milestone findings" → (ii) "Compose ANALYSIS.md § M5.2 narrative" → (iii) "Refresh README narrative for M5.2 delivery" (last commit on the branch at `gh pr create` time). The PR description cites all three commit SHAs explicitly.

Per **FR-005c (the user's explicit anti-regression requirement)**, the implementation plan adds a discrete **payload-parity code-review audit step** in the maintainer's pre-PR checklist that re-audits the REST and gRPC harness payload-construction paths and explicitly cites the past regression where the REST harness was sending a different-sized embedding payload than gRPC. The audit's findings ("no payload-size regression confirmed against PR <SHA-or-#>") are recorded in the M5.2 report's executive metadata.

## Technical Context

**Language/Version**: Python 3.12 (`requires-python = ">=3.12,<3.13"` in `pyproject.toml`) — unchanged from M5.1.
**Primary Dependencies**: `grpcio==1.80.0` (unchanged), `modal` (unchanged), `protobuf` (transitive), `fastapi` (Modal-image-only; reused from M5.1's shim), `uvicorn` (Modal-image-only; reused from M5.1), `httpx` (REST cohort runner; reused from M5.1), `numpy` (unchanged). No new runtime dependencies in `proxy` / `frontend` / `client`. No new Modal-image deps relative to M5.1.
**Storage**: N/A on the runtime path. M5.2 report lands as Markdown + JSON under `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}` (committed). M5.2 also commits a **gzipped per-request events JSONL sidecar** at `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` (~1.5–3 MB compressed per full sweep, per FR-012a). Transient per-iteration arrays land under `bench-results/m5_2-full/` (gitignored, same convention as M3/M4/M5/M5.1). The Modal app uses no persistent volume; MockEngine is stateless.
**Testing**: `pytest` for unit and integration tests (`make check`). New M5.2 tests follow the M5.1 pattern: harness unit tests under `tools/benchmark/tests/` (HTTPS-edge REST cohort runner integration, 3-tier symmetry-block emitter + asserter, JSONL events sidecar emitter, regenerator round-trip + checksum verifier, supersede-M5.1 table emitter, M5.2 CLI flag wiring); integration tests under `tests/integration/` covering a Modal-secrets-gated smoke run that exercises deploy → both REST probes + gRPC probe → measure (3 smoke cells) → emit sidecar → regenerate report → teardown.
**Target Platform**: Local benchmark client on macOS (Apple Silicon M2/M3) and Linux x86-64 (unchanged from M5.1). Remote Modal CPU-only instance in `eu-west-1` (matches M5.1) so measured median RTT lands in 30–100 ms; HTTPS-edge anycast RTT is recorded separately per FR-004 and may differ from the plain-TCP RTT.
**Project Type**: Python `uv` workspace with multiple packages — `packages/{client,frontend,gen,proxy}` and `tools/benchmark`. M5.2 changes concentrate in `tools/benchmark/`. The operator-facing Modal-deployment script at `scripts/python/modal_bench_rest_grpc_server.py` (introduced by M5.1) is **reused unchanged** — M5.1's `modal.forward(8000)` HTTPS-edge call and `modal.forward(50051, unencrypted=True)` plain-TCP call already expose both transports M5.2 needs; M5.2 simply points both REST cohorts at the same dual-tunnel deploy. No `proto/` changes (M5.2 does not measure schema candidates; M5 US2's domain). Production proto in `proto/vllm_grpc/v1/{chat,completions}.proto` remains on M3's shape.
**Performance Goals**: M5.2 *measures*; it does not preset a verdict-shape target. Empirical questions (per spec SC-001..SC-014): does HTTPS-edge transport change REST's competitive position vs each gRPC cohort; what is the per-cell HTTPS-edge vs plain-TCP RTT delta; do `default_grpc` vs `tuned_grpc_*` deltas resolve at n=250 to defensible verdicts on a non-trivial cell subset. Run-level expectation: measured median RTT 30–100 ms (plain-TCP) and ~30–100 ms (HTTPS-edge, geography-dependent); per-cohort CV in the same band as M5.1 (~loopback-CV × 2–4× for real-network jitter).
**Constraints**:
- Constitution I (Proto-First): no `.proto` edits in M5.2. M3's production proto shape is consumed verbatim by the gRPC servicers in the Modal app (via M5.1's `modal_bench_rest_grpc_server.py`).
- Constitution II (Library Dependency, Not Fork): vLLM remains a published-library dependency; the M5.2 Modal app imports MockEngine, not vLLM proper (per M5.1 / Spec Assumptions). No vLLM source is patched.
- Constitution III (Phase Discipline): M5.1 closed on 2026-05-11 (PR #22, branch `018-m5-1-rest-vs-grpc`). M5.2 deliverables match `docs/PLAN.md`'s M5.2 section (production-equivalent REST transport + resolution increase + documentation refactors). No M6 (corpus expansion) or M7 (model expansion) functionality is pulled forward — the spec explicitly excludes both. The two doc refactors are M5.2 deliverables per the user's command-args directive.
- Constitution IV (CI is the Merge Gate): the M5.2 *harness mechanics* (HTTPS-edge REST cohort, 3-tier symmetry block, JSONL sidecar emitter, regenerator round-trip, supersede-M5.1 builder, CLI flag wiring) are unit-tested at PR time. The full M5.2 sweep is operator-triggered and not part of CI's runtime budget. The Modal-smoke integration test runs in CI only when `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` are present in the CI environment (gated; default-skip on PRs without secrets, identical to M5/M5.1's gating). `make lint` MUST run `ruff check` AND `ruff format --check` before push (project-specific local-lint discipline; CI runs both as separate gates).
- Constitution V (Honest Measurement): `server_bound` and `comparison_unavailable` honesty mechanisms inherited from M5.1 (FR-005); `low_rtt_caveat` inherited from M5/M5.1 (FR-004); `noise_resolved` and `transport_dependent` categories added to the Supersedes-M5.1 table (FR-016); negative-results appendix with full per-cohort CI bounds published when verdicts remain `no_winner` at n=250 (FR-012); the M1 bytes-axis (encoding-driven) and the M5 transport-axis (channel-tuning component) are explicitly **not** superseded (FR-014 (d)); the payload-parity audit (FR-005c) protects against the past embed-payload-size regression and the audit's confirmation is recorded in the report's executive metadata.
- Spec FR-002: both REST transports MUST exercise the **identical in-container engine code path** (HTTPS edge vs plain-TCP differ only on network path; FastAPI shim handlers, MockEngine instance, bearer-auth middleware are shared).
- Spec FR-005a: M5.2-specific assertion surface added to M5.1's existing smoke harness; smoke MUST refuse to advance to a full sweep on any assertion failure.
- Spec FR-005b: three-tier symmetry block (cross-cohort invariants / intra-protocol pair invariants / per-cohort metadata) emitted into the M5.2 JSON and asserted at run start with per-tier fail-fast diagnostics.
- Spec FR-005c: discrete payload-parity code-review audit step in the maintainer's pre-PR checklist; findings recorded in the M5.2 report's executive metadata.
- Spec FR-006: five cohorts per cell at c≥2; `tuned_grpc_multiplexed` and `tuned_grpc_channels` collapse to `tuned_grpc` at c=1 (matches M5.1 FR-006).
- Spec FR-008: identical REST client config across both REST transports except for target URL (HTTPS edge vs plain-TCP host:port).
- Spec FR-009: two verdict families per cell — protocol comparison (each gRPC cohort vs `rest_https_edge`) and transport-only comparison (`rest_https_edge` vs `rest_plain_tcp`).
- Spec FR-011: per-cohort default n=250; borderline-expand cascade does NOT expand beyond n=250 in M5.2.
- Spec FR-012a / FR-012b: per-request gzipped JSONL events sidecar; round-trippable regenerator with SHA-256 checksum verification; field provenance documented at section-header resolution in the markdown.
- Spec FR-013: JSON schema is a strict superset of M5.1's — new fields permitted; no renames, no removals.
- Spec FR-017 / FR-018 / FR-019 / FR-020: ANALYSIS.md added; summary.md folded + redirected; PLAN.md findings replaced with pointers; `docs/benchmarks/m*.md` cross-references updated.
- Spec FR-021 / FR-022 / FR-023: README simplified to ≤180 lines; every Make target / demo script / env var / external dependency validated.
- Spec FR-024 / FR-024a: three discrete, ordered narrative commits — (i) milestone summary, (ii) ANALYSIS.md § M5.2, (iii) README refresh (last on branch at PR-open time).

**Scale/Scope**:
- 2 paths (chat_stream, embed) × 3 widths (hidden_size 2048, 4096, 8192) × 3 concurrencies (c=1, c=4, c=8) = **18 cells** in the matrix (unchanged from M5.1).
- Cohort families per cell:
  - REST: 2 cohorts/cell × 18 cells = **36 REST cohorts** (`rest_https_edge` + `rest_plain_tcp`).
  - Tuned-gRPC: at c=1, 1 sub-cohort/cell × 6 cells = 6 cohorts (the multiplexed/channels distinction collapses to `tuned_grpc`); at c=4 and c=8, 2 sub-cohorts/cell × 12 cells = 24 cohorts. **Total tuned-gRPC = 30 cohorts** (unchanged from M5.1).
  - Default-gRPC control: 1 cohort/cell × 18 cells = **18 cohorts** (unchanged from M5.1).
  - Shared-baseline cohorts: 1 per (path × protocol-side) per run for CI anchoring; effectively folded into the per-cell measurements above.
  - Warm-up cohorts: 1 per protocol-side per path = 4 discarded cohorts (no recommend impact).
- **Total measurement cohorts ≈ 84** (36 + 30 + 18) plus ≈ 4 warmup discards.
- Per-cohort sample size: default n=250 (vs M5.1's n=100). Borderline-expand cascade does NOT expand beyond n=250.
- Total expected M5.2 runtime budget: target ≤ 40 minutes on Modal CPU-only instance class (per spec SC-007 / Edge Case "n=250 doubles per-cohort runtime"); realised ~25–30 min budget plus headroom. M5.1 ran in ~10–15 min at n=100 × 4 cohorts; M5.2's per-cell work is ~3.1× (5/4 × 250/100 = 3.125). Operator-triggered, not part of CI's runtime budget.
- Per-request JSONL events sidecar: ≈84 cohorts × 250 measurement records + ~5 warmup records per cohort × ~50–100 bytes per JSON record ≈ 14 MB raw / 1.5–3 MB gzipped.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | M5.2 alignment | Notes |
|-----------|----------------|-------|
| **I. Proto-First** | PASS | M5.2 makes no `.proto` edits. M3's production proto is consumed verbatim by the gRPC servicers in the dual-protocol Modal app (introduced by M5.1, reused unchanged here). M5.2 does not measure schema candidates (M5 US2's domain). |
| **II. Library Dependency, Not Fork** | PASS | M5.2's Modal app continues to import MockEngine from this repo (via M5.1's `scripts/python/modal_bench_rest_grpc_server.py`), not vLLM proper. vLLM remains a published-library dependency. No vLLM source is patched. |
| **III. Phase Discipline** | PASS | M5.1 closed on 2026-05-11 (PR #22, branch `018-m5-1-rest-vs-grpc`). M5.2 is the next active milestone per `docs/PLAN.md`. M5.2 deliverables match the PLAN's M5.2 section: production-equivalent REST transport (HTTPS edge) + n=100 → n=250 resolution increase + Supersedes-M5.1 table + ANALYSIS.md consolidation + README simplification/tooling validation. No M6 (corpus expansion) or M7 (model expansion) functionality is pulled forward — the spec explicitly excludes both. |
| **IV. CI is the Merge Gate** | PASS | The M5.2 harness mechanics (HTTPS-edge REST cohort wiring, 3-tier symmetry block emitter+asserter, gzipped JSONL events sidecar emitter, round-trippable regenerator + SHA-256 verification, supersede-M5.1 builder, CLI flag wiring) are unit-tested under `make check`. The full M5.2 sweep is operator-triggered and not part of CI's runtime budget. The Modal-smoke integration test runs only when Modal secrets are present in CI (default-skip, identical to M5/M5.1's gating). Local `make lint` runs `ruff check` + `ruff format --check` before push (project-specific local-lint discipline). |
| **V. Honest Measurement** | PASS — *strengthened* | M5.2 adds three honesty mechanisms beyond M5.1: (a) every verdict row in the markdown report explicitly names the network path each cohort travels (HTTPS edge or plain-TCP) so a reader cannot mistake a network-path artifact for a protocol property (FR-009 (c)); (b) the **3-tier symmetry block** (FR-005b) makes cross-cohort symmetry assertions auditable post-hoc — a reader can verify cohort invariants without re-running, and the markdown report MUST refuse to publish on tier (a) divergence; (c) the **gzipped per-request events JSONL sidecar** (FR-012a) + the round-trippable regenerator (FR-012b) make every aggregate in the markdown reproducible by `zgrep`-ing the sidecar with the section-header filter — published aggregates are computed from telemetry, not synthesized from harness-internal state. The discrete **payload-parity audit step** (FR-005c) protects against the past embed-payload-size regression as a code-review gate, with the audit's confirmation recorded in the report's executive metadata. |

**Gate result**: PASS on initial check. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/019-m5-2-transport-tuning/
├── plan.md                            # This file (/speckit-plan output)
├── research.md                        # Phase 0 — methodology research (HTTPS-edge cohort wiring, RTT probe over HTTPS, 3-tier symmetry block design, JSONL sidecar format + checksum, regenerator round-trip, narrative-refresh discrete commits, ANALYSIS.md structure, README simplification audit method, payload-parity audit checklist)
├── data-model.md                      # Phase 1 — M5.2 dataclasses (M5_2RestHttpsEdgeCohort, M5_2SymmetryBlock 3-tier, TransportOnlyVerdict, SupersedesM5_1Entry, PerRequestEventRecord, M5_2 cohort root, ANALYSIS.md section schema)
├── quickstart.md                      # Phase 1 — how to reproduce the M5.2 sweep end-to-end (Modal token setup, smoke gate, full sweep, regenerator round-trip verification, payload-parity audit, discrete narrative commit sequence)
├── contracts/
│   ├── m5_2-bench-cli.md              # `vllm_grpc_bench --m5_2` CLI signature, flags, exit codes
│   ├── m5_2-report-schema.md          # JSON schema delta vs m5_1-rest-vs-grpc.json (strict superset; M5.2-additive fields named)
│   ├── m5_2-events-jsonl-sidecar.md   # Per-request JSONL sidecar format, gzip+checksum conventions, regenerator read contract, section-header filter syntax
│   ├── m5_2-regenerator.md            # Round-trippable regenerator (extends scripts/python/regen_bench_reports.py); SHA-256 verification protocol; idempotency contract; field provenance documentation rule
│   └── m5_2-payload-parity-audit.md   # FR-005c audit checklist: REST and gRPC payload-construction parity, the past embed-payload-size regression named explicitly, what to record in the report's executive metadata
├── checklists/
│   └── requirements.md                # Created by /speckit-specify
└── tasks.md                           # Created by /speckit-tasks (NOT this command)
```

### Source Code (repository root)

```text
proto/vllm_grpc/v1/
├── chat.proto                          # M3 production shape — UNCHANGED in M5.2
├── completions.proto                   # M3 production shape — UNCHANGED in M5.2
└── health.proto                        # untouched

tools/benchmark/src/vllm_grpc_bench/
├── m5_2_sweep.py                       # NEW — five-cohort sweep orchestrator (parallel
│                                         to m5_1_sweep.py; wraps M5.1's per-cohort runner
│                                         with the HTTPS-edge REST cohort extension, dual
│                                         REST transport dispatch per cell, two-verdict-
│                                         family emitter, JSONL events sidecar writer,
│                                         3-tier symmetry block emitter+asserter)
├── m5_2_supersede.py                   # NEW — Supersedes-M5.1 table builder (parallel
│                                         to m5_1_supersede.py / m5_supersede.py); maps
│                                         each M5.1 verdict cell to the M5.2 protocol-
│                                         comparison verdict against rest_https_edge,
│                                         categorising as verdict_changed / verdict_confirmed
│                                         / noise_resolved / transport_dependent (FR-016)
├── m5_2_events.py                      # NEW — per-request labelled-events JSONL writer
│                                         (FR-012a); buffered append with gzip-on-close;
│                                         SHA-256 checksum computed at close
├── m5_2_symmetry.py                    # NEW — 3-tier symmetry block builder + asserter
│                                         (FR-005b); tier (a) cross-cohort invariants,
│                                         tier (b) intra-protocol pair invariants (with
│                                         c=1 degeneracy skip for tuned_grpc pair), tier
│                                         (c) per-cohort metadata (audit-only)
├── m5_1_grpc_cohort.py                 # UNCHANGED — gRPC cohort runner from M5.1 reused
├── m5_1_sweep.py                       # UNCHANGED — M5.2 imports its helpers (cohort
│                                         dispatch, RTT probe binding, server_bound
│                                         classifier wiring); does not edit it
├── m5_1_supersede.py                   # UNCHANGED — M5.2's supersede module is separate
├── rest_cohort.py                      # EXTENDED — accepts an optional network_path tag
│                                         (https_edge | plain_tcp) for record labelling;
│                                         RTT probe binding accepts the same tag so the
│                                         probe travels the cohort's path (FR-004); no
│                                         change to existing M5.1 call sites (default
│                                         tag preserves M5.1 behavior)
├── modal_endpoint.py                   # EXTENDED — the dual-protocol Modal deploy
│                                         already exposes both transports via M5.1's
│                                         modal_bench_rest_grpc_server.py; M5.2 reads
│                                         both URLs from the same handshake Dict (the
│                                         HTTPS-edge URL was already exposed and
│                                         consumed by M5.1's REST cohort; M5.2 adds the
│                                         second consumer for plain-TCP REST). Additive
│                                         — M5.1's behavior unchanged when the M5.2
│                                         flag family is not passed.
├── reporter.py                         # EXTENDED — adds M5.2 Markdown + JSON sections
│                                         per FR-013/FR-014 (executive section with
│                                         HTTPS-edge vs plain-TCP RTT delta + payload-
│                                         parity audit metadata; per-cell comparison
│                                         matrix with two verdict families and network-
│                                         path naming; Supersedes-M5.1 table per FR-016;
│                                         events JSONL sidecar checksum + filter
│                                         provenance per FR-012b; negative-results
│                                         appendix per FR-014 (e))
├── m3_types.py                         # EXTENDED — additive dataclasses for M5.2
│                                         (M5_2RestHttpsEdgeCohort, M5_2SymmetryBlock
│                                         with three tier sub-types, TransportOnlyVerdict
│                                         literal, SupersedesM5_1Entry, PerRequestEventRecord,
│                                         M5_2 cohort root)
├── __main__.py                         # EXTENDED — adds --m5_2 flag family (mutually
│                                         exclusive with --m3, --m4, --m5, --m5_1)
├── m3_sweep.py / m4_sweep.py / ...     # UNCHANGED
├── m5_sweep.py / m5_supersede.py       # UNCHANGED
├── mock_engine.py                      # UNCHANGED — same MockEngine call path on both
│                                         protocols inside the Modal container
├── channel_config.py                   # UNCHANGED — M5's per-axis frozen-tuned-channel
│                                         configuration loader is consumed verbatim by
│                                         m5_2_sweep.py (via M5.1's helpers)
├── rest_shim.py                        # UNCHANGED — M5.1's FastAPI shim is reused
├── rtt_probe.py                        # UNCHANGED — REST probe accepts the same
│                                         network_path tag introduced into rest_cohort.py
└── tests/
    ├── test_m5_2_sweep.py              # NEW
    ├── test_m5_2_supersede.py          # NEW
    ├── test_m5_2_events_sidecar.py     # NEW — JSONL writer, gzip-on-close, checksum
    ├── test_m5_2_symmetry.py           # NEW — 3-tier asserter; c=1 degeneracy skip
    ├── test_m5_2_regenerator.py        # NEW — round-trip + SHA-256 verification +
    │                                     refusal on checksum mismatch
    ├── test_m5_2_reporter.py           # NEW
    ├── test_m5_2_cli.py                # NEW
    └── ...                             # existing M5 / M5.1 tests unchanged

scripts/python/
├── modal_bench_grpc_server.py          # UNCHANGED — M5's gRPC-only deploy
├── modal_bench_rest_grpc_server.py     # UNCHANGED — M5.1's dual-protocol deploy
│                                         (already exposes both transports M5.2 needs)
├── regen_bench_reports.py              # EXTENDED — adds an --m5_2-sidecar flag family
│                                         and the round-trippable regenerator entrypoint
│                                         (FR-012b). Reads the gzipped JSONL + per-run
│                                         config; produces byte-identical markdown +
│                                         aggregate JSON; verifies the sidecar's SHA-256
│                                         against the executive-metadata-recorded value
│                                         and refuses on mismatch.
└── ...

tests/integration/
└── test_m5_2_modal_smoke.py            # NEW — Modal-secrets-gated smoke run that
                                          deploys the dual-protocol app, runs the
                                          M5.2 smoke (3-cell coverage minimum,
                                          all five cohorts), emits the JSONL sidecar,
                                          re-runs the regenerator, diffs against the
                                          published artifacts.

docs/benchmarks/
├── m5_2-transport-vs-tuning.md         # NEW — published M5.2 report (committed by
│                                         the "Summarize M5.2 milestone findings" commit)
├── m5_2-transport-vs-tuning.json       # NEW — companion aggregate JSON (additive
│                                         superset of M5.1's schema)
├── m5_2-transport-vs-tuning.events.jsonl.gz
│                                       # NEW — gzipped per-request events JSONL
│                                         sidecar (FR-012a); SHA-256 checksum recorded
│                                         in the report's executive metadata
├── m5_1-rest-vs-grpc.{md,json}         # UNCHANGED — M5.1's published report stays
├── m5-cross-host-validation.{md,json}  # UNCHANGED
├── m4-time-axis-tuning.{md,json}       # UNCHANGED
├── m3-channel-tuning.{md,json}         # UNCHANGED
├── m3-channel-tuning-time.{md,json}    # UNCHANGED
└── summary.md                          # REPLACED with a one-line redirect to
                                          ANALYSIS.md (file remains in place per
                                          FR-018 + Edge Cases; preserves M3-era
                                          methodology preamble for external link
                                          back-compatibility)

docs/
└── PLAN.md                             # EDITED — embedded milestone findings
                                          replaced with "Findings: see ANALYSIS.md §
                                          M<N>" pointers per FR-019; plan content
                                          (goals, phase descriptions, exit criteria,
                                          risk register) intact

ANALYSIS.md                             # NEW — top-level cumulative findings document
                                          per FR-017. One H2 section per milestone
                                          (M1, M2, M3, M4, M5, M5.1, M5.2). Established
                                          as the running document future milestones
                                          add sections to.

README.md                               # EDITED — simplified to ≤180 lines per
                                          FR-021; embedded milestone findings
                                          replaced with high-level phase summary +
                                          ANALYSIS.md pointers per US3 acceptance
                                          scenario 1; every tooling reference
                                          validated per FR-022. This file is the
                                          last commit on the PR branch per FR-024.
```

**Structure Decision**: M5.2 mirrors M5.1's package layout (a per-milestone sweep module + a per-milestone supersession module under `tools/benchmark/src/vllm_grpc_bench/`, plus per-milestone events + symmetry + regenerator extensions). New code is additive — every existing M5/M5.1 module remains importable and its behavior unchanged when the new `--m5_2` flag is not passed. The dual-protocol Modal app introduced by M5.1 (`scripts/python/modal_bench_rest_grpc_server.py`) is reused unchanged — it already exposes both `modal.forward(8000)` (HTTPS edge for REST) and `modal.forward(50051, unencrypted=True)` (plain-TCP for gRPC and now also for the second REST cohort), so M5.2 needs no new Modal-image work. The split between `m5_2_sweep.py` (orchestration), `m5_2_events.py` (JSONL sidecar writer), `m5_2_symmetry.py` (3-tier symmetry block builder + asserter), `m5_2_supersede.py` (Supersedes-M5.1 table builder), and the round-trippable `regen_bench_reports.py` extension preserves single-responsibility per module: the sweep emits the sidecar + config; the regenerator builds the report; nothing in the sweep emits markdown or aggregate JSON directly (FR-012b).

The two documentation refactors (US2 + US3) land in the same PR but are scoped to three discrete, ordered narrative commits per FR-024a + FR-024: (i) milestone summary into `docs/benchmarks/m5_2-transport-vs-tuning.md`, (ii) cross-phase narrative into `ANALYSIS.md`, (iii) README refresh + tooling-validation pass (last commit on the branch at PR-open time). The PR description cites all three commit SHAs explicitly so reviewers can verify the discrete-summarization sequence from the commit log alone.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. No complexity-tracking entries required.

---

## Implementation Phases (preview — `/speckit-tasks` will expand)

This section previews the phases `/speckit-tasks` will turn into discrete tasks. It is **not** the task list; it is a scaffolding note so a reviewer can read this plan top-to-bottom and understand where the implementation goes.

- **Phase A — Dual-REST-transport cohort wiring**: extend `rest_cohort.py` with an optional `network_path` tag (`https_edge` | `plain_tcp`); thread the tag through RTT probe binding; verify the M5.1 default-tag path still works (no behavioral change when `--m5_2` is off).
- **Phase B — JSONL events sidecar + symmetry block**: build `m5_2_events.py` (buffered append, gzip-on-close, SHA-256 at close) and `m5_2_symmetry.py` (3-tier builder + asserter with c=1 degeneracy skip for the tuned_grpc pair).
- **Phase C — Sweep orchestrator**: `m5_2_sweep.py` — assemble the 18-cell matrix; dispatch the five cohorts per cell at c≥2 (four at c=1); emit per-request events to the sidecar; assert tier (a) and tier (b) symmetry at run start; emit two-family per-cell verdicts; emit the M5.2 JSON aggregate at run end (consumed by the regenerator, NOT by the markdown writer per FR-012b).
- **Phase D — Supersede-M5.1**: `m5_2_supersede.py` — load M5.1's published cells from `docs/benchmarks/m5_1-rest-vs-grpc.json`; build the Supersedes-M5.1 table with `verdict_changed` / `verdict_confirmed` / `noise_resolved` / `transport_dependent` categories per FR-016.
- **Phase E — Round-trippable regenerator**: extend `scripts/python/regen_bench_reports.py` with the M5.2 entrypoint: read the gzipped JSONL + run config; verify the sidecar's SHA-256 against the executive-metadata-recorded value (refuse on mismatch); produce byte-identical markdown + aggregate JSON; document field provenance at section-header resolution per FR-012b.
- **Phase F — Reporter**: extend `reporter.py` with M5.2 Markdown + JSON sections; executive section names the HTTPS-edge vs plain-TCP RTT delta + the payload-parity audit confirmation metadata; per-cell comparison matrix with two verdict families and network-path naming per row; Supersedes-M5.1 table; negative-results appendix; field-provenance footnotes naming the sidecar filter / aggregate-JSON key per section.
- **Phase G — CLI**: extend `__main__.py` with the `--m5_2*` flag family + the `--m5_2-smoke` shortcut for the pre-flight smoke gate; mutual exclusion with `--m3` / `--m4` / `--m5` / `--m5_1`; document in `contracts/m5_2-bench-cli.md`.
- **Phase H — Tests**: unit tests under `tools/benchmark/tests/` for each new module + the extended modules; Modal-secrets-gated smoke test under `tests/integration/test_m5_2_modal_smoke.py` (deploy → both REST probes + gRPC probe → 3-cell smoke → sidecar emit → regenerator round-trip diff → teardown).
- **Phase I — Run**: operator-triggered full sweep via `python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1`; verify the smoke gate first; commits the report + sidecar under `docs/benchmarks/m5_2-transport-vs-tuning.{md,json,events.jsonl.gz}`.
- **Phase J — Payload-parity audit (FR-005c, pre-narrative-refresh)**: maintainer conducts the discrete code-review audit per `contracts/m5_2-payload-parity-audit.md`; records the audit's findings ("no embed-payload-size regression confirmed against PR <SHA-or-#>") in the M5.2 report's executive metadata.
- **Phase K — Narrative refresh — three discrete commits (FR-024a + FR-024)**:
    - **K1 "Summarize M5.2 milestone findings"** — first narrative commit: adds milestone-scoped executive section + headline findings per verdict family + "Supersedes M5.1" rationale text to `docs/benchmarks/m5_2-transport-vs-tuning.md`. Numbers come from the FR-012b regenerator's output, not recomputed inline.
    - **K2 "Compose ANALYSIS.md § M5.2 narrative"** — second narrative commit: composes the cross-phase summary into `ANALYSIS.md` § M5.2 citing K1's milestone report. Folds `docs/benchmarks/summary.md`'s legacy content into `ANALYSIS.md` § M3 byte-for-byte equivalent; replaces summary.md with the one-line redirect; replaces PLAN.md's embedded findings with `ANALYSIS.md` pointers; audits `docs/benchmarks/m*.md` cross-references and re-points them at ANALYSIS.md.
    - **K3 "Refresh README narrative for M5.2 delivery"** — third narrative commit, **last commit on the PR branch at `gh pr create` time**: simplifies README to ≤180 lines per FR-021 with high-level phase summary + ANALYSIS.md pointers; runs the FR-022 tooling-reference validation pass and fixes any drift discovered in the README, Makefile, demo scripts, or consuming code (drift fixes named in the PR description).
- **T-FINAL — Open PR**: `gh pr create` with a PR description citing all three commit SHAs (K1, K2, K3) explicitly + any drift fixes the K3 tooling-validation pass made + the smoke gate's outcome (per SC-012) + the payload-parity audit's "no regression confirmed" line (per SC-013) so reviewers can verify the discrete-summarization sequence + the symmetry/payload-parity confirmations + the README-narrative-current rule from the PR description alone.

### Phase L — Unplanned methodology fixes (post-implementation 2026-05-12)

This phase did not exist in the original plan preview above; it was inserted **after** the first end-to-end smoke + cell-12 preemption crash exposed methodology gaps that the original phases A–K did not anticipate. The work was completed before the K-series narrative-refresh commits and is recorded here so a future reader can reconstruct *why* the sidecar contracts and the audit contract talk about chat-corpus prompts, ShareGPT V3, and a `failed_cells` field that have no counterpart in the original spec text. The fixes are also recorded in `research.md` (R-12 chat corpus, R-13 preemption resilience) and `spec.md` (Session 2026-05-12 — post-implementation revisions).

The phase is a retroactive grouping of three streams of work:

- **L-1: Payload-parity audit fixes (chat-path)** — addressed two gaps the FR-005c audit Step 1 caught:
    - **Fix A (chat response_body_bytes)**: REST `chat_stream` was emitting only the first SSE line's byte count to `response_body_bytes`, making the column not comparable to gRPC's "sum across `ChatStreamChunk` serializations". Corrected in `rest_cohort._single_chat_stream_request` to sum `len(line.encode()) + 1` across every SSE line including the trailing `data: [DONE]`. Recorded in the sidecar contract's [`response_body_bytes` field semantics](contracts/m5_2-events-jsonl-sidecar.md#field-semantics).
    - **Fix B (warmup record persistence)**: M5.1-inherited cohort runners discarded warmup samples internally, violating FR-012a (g) ("Every record retained in this sidecar — even warmup records flagged `phase=warmup` for FR-011 exclusion from aggregates"). Corrected by adding `warmup_samples` to `RESTCohortResult` and `GRPCCohortResult`, and emitting those records FIRST per cohort with `phase="warmup"` and `rtt_at_issue_ms=0.0`. Recorded in the sidecar contract's [`phase` field semantics](contracts/m5_2-events-jsonl-sidecar.md#field-semantics).
    - **Fix C (chat-corpus alignment via ShareGPT V3)**: REST and gRPC chat cohorts were using divergent synthetic prompts ("Hello world request-{i}" vs "M5.1 chat probe iter={N}") and divergent `max_tokens`. The first remediation was a shared `build_chat_prompt(iteration, cell_id)` helper with `DEFAULT_CHAT_MAX_TOKENS=64`. The second, stronger remediation per upstream-advisor guidance was to adopt **ShareGPT V3** (`anon8231489123/ShareGPT_Vicuna_unfiltered`, revision pinned in `tools/benchmark/corpus/chat_sharegpt_1000.provenance.json`) as the reference chat corpus and thread `RequestSample`s through both protocols. Both protocols now read the same `RequestSample` by `iteration % len(corpus)`. The strict-reading audit Step 1 mandates the corpus-driven path; legacy synthetic phrases are forbidden by `test_chat_corpus_parity.py`. Recorded in the audit contract's [Step 1](contracts/m5_2-payload-parity-audit.md#step-1--read-the-chat-path-payload-construction-side-by-side) + [historical note](contracts/m5_2-payload-parity-audit.md#step-1--read-the-chat-path-payload-construction-side-by-side) and in [research.md R-12](research.md).

- **L-2: Preemption-aware URL refresh** — addressed a Modal-specific failure mode the original plan did not anticipate: Modal can preempt the `serve_bench` worker mid-sweep, restart it on a new worker, and silently invalidate the `rest_https_edge_url` + `rest_plain_tcp_url` + `grpc_url` values published by R-1's two-uvicorn handshake. The first end-to-end run hit this at cell 12; cells 12–18 all failed with `httpx.ConnectError` against stale URLs, and (because the original sweep loop had no per-cell try/except) the whole run crashed with no report artifacts. The remediation was:
    - `modal_endpoint.refresh_rest_grpc_urls()` — re-reads the Modal `modal.Dict` keys (`rest_https_edge_url`, `rest_plain_tcp_url`, `grpc_url`) with a 90 s polling timeout, returning a fresh `EndpointConfig` if the deploy survived the preemption.
    - `_is_connect_error()` predicate + bounded retry loop in `m5_2_sweep.dispatch_cell` — on a connect-style exception, the loop calls `refresh_endpoints_fn` (a closure the CLI builds from `refresh_rest_grpc_urls`), updates the cell's `EndpointConfig`, and retries the cell once. Multiple consecutive connect failures escalate to `failed_cells` instead of crashing the sweep.
    - `_run_m5_2` in `__main__` builds the `refresh_endpoints_fn` closure from the Modal app handle so the CLI's `--m5_2` flow gets preemption resilience automatically. The smoke flow uses the same closure.
    Recorded in [research.md R-13](research.md), the [bench-CLI contract](contracts/m5_2-bench-cli.md), the [regenerator contract's `failed_cells` field](contracts/m5_2-regenerator.md#inputs), and the [report-schema contract's `failed_cells` row](contracts/m5_2-report-schema.md#top-level-keys-additive-to-m51).

- **L-3: Per-cell isolation + skeleton run_config + verbose error reporting** — the same cell-12 incident exposed three resilience gaps:
    - **Per-cell try/except**: `dispatch_cell` now catches everything except `KeyboardInterrupt` / `SystemExit`, records the failure to `failed_cells: list[dict]`, and continues with the next cell. A clean run has `failed_cells == []`.
    - **Skeleton `run_config.json` written at run start**: `_write_skeleton_run_config()` writes the run-config skeleton (with `run_id`, `run_started_at_iso`, `seed`, `symmetry`, `modal_region`, `https_edge_endpoint`, and an empty `failed_cells: []`) BEFORE the first cell dispatches. If the run crashes catastrophically (e.g., SIGKILL'd Modal worker, OOM on the bench host), the skeleton still exists and the operator can synthesize a partial recovery + run the regenerator on whatever sidecar records were flushed.
    - **Verbose error reporting in the CLI**: the original `Error: M5.2 sweep failed:` line printed an empty exception body when `repr(exc)` was empty. The remediation prints `type(exc).__name__`, `repr(exc)`, and the full traceback so the operator sees the underlying failure mode without re-running with `--verbose`. Recorded in the [bench-CLI contract](contracts/m5_2-bench-cli.md) Behavior section.

**Why these are recorded here rather than re-baselined into Phases A–K**: the original plan is the contract the spec-kit workflow signed off on; rewriting it would erase the audit trail of *what changed and why*. Phase L's existence is the audit trail. Future re-baselines (e.g., an M5.3 milestone that subsumes these fixes into a clean Phase B-prime) can collapse Phase L back into the appropriate earlier phases at that time.
