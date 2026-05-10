# Phase 0 Research: M3 — Protobuf & gRPC Tuning

**Feature**: 015-m3-protobuf-grpc-tuning
**Date**: 2026-05-09
**Inputs**: spec.md (clarifications integrated), plan.md, README Milestone 3 section, M2 ground-truth workflow

This document resolves the open design questions from `/speckit-plan`'s Technical Context and from the two items the `/speckit-clarify` session deferred (workload sizing, harness observability depth). Every decision below is paired with a citation into either cloned grpcio or vLLM (per Constitution V "Honest Measurement" and FR-007 / FR-009 in the spec) or a short empirical justification.

## R-1 — Per-cell repetition count and CI estimator

**Decision**: 30 iterations per cell, with the 95% CI computed using the t-distribution on the mean of those 30 samples (`scipy.stats.t.ppf(0.975, 29)` ≈ 2.045 critical value). For "win" determination, the candidate's lower CI bound must exceed the baseline's upper CI bound — a stricter test than just comparing means.

**Rationale**:
- 30 samples is the smallest sample size at which the t-distribution converges close to the normal (so the math is stable) and is a long-standing convention in performance engineering for that reason.
- For a typical M1 measurement with relative noise ~5–10% (observed in `docs/benchmarks/phase-4.2-three-way-comparison.md`), 30 iterations puts the 95% CI half-width at roughly 2–4% of the mean — well below the kind of channel-tuning win we expect to see (M1's 89% / 25% wire-size deltas were huge, but channel-tuning wins are typically single-digit percent).
- The lower-CI-vs-upper-CI test is what the spec calls for ("exceeds the upper bound of the 95% CI of the baseline"); comparing means alone would let a noisy candidate accidentally claim a win.
- Welch's t-test is the right tool for unequal variances between baseline and candidate; we don't assume variances match.

**Alternatives considered**:
- *n=10 per cell*: too few; t-critical value is 2.262 and CI half-widths blow up. Rejected for SC-003 rigor.
- *Bootstrap resampling instead of t-distribution*: more robust to non-normal distributions, but adds complexity for marginal gain on a benchmark where each iteration is a clean repeated measurement of the same operation. Defer to a follow-up if any axis turns out to have heavy-tailed timing.
- *Bayesian / sequential testing*: overkill for the M3 budget and introduces priors that would need their own justification.

**Implementation note**: a `ci.py` helper computes mean, stddev, and 95% CI using `numpy.std(ddof=1)` and the t-critical from a hard-coded table (no `scipy` dependency to keep the bench tools light).

## R-2 — Per-cell workload size

**Decision**: For each cell (one width × one channel-axis × one path), the workload is **30 RPCs** (one per iteration). For embed RPCs, each iteration is a single embed request returning one embedding tensor of shape `[hidden_size]`. For streaming chat-completion RPCs, each iteration is one chat call streaming the tokens for one prompt drawn from the M1 corpus (or the M3 long-stream synthetic prompt for the long-stream cohort).

**Rationale**:
- One RPC per iteration matches the iteration semantics — a "measurement" is a single end-to-end request, the unit the report's wire-byte and decode-time numbers describe.
- Smaller batches per iteration reduce within-iteration variance from coalescing effects, making each iteration a clean i.i.d. sample.
- Total RPCs per cell = 30; total cells in the P1 sweep ≈ 3 widths × 2 paths × 4 axes × 2 configs/axis = 48; total RPCs ≈ 1440. With per-RPC latency ~50–500 ms on CPU, full sweep ≈ 0.7–4 hours. Fits the "≤4 hours" budget the plan sets.

**Alternatives considered**:
- *Higher RPCs per iteration (10 / iteration)*: each iteration would be a small mini-benchmark. Reduces variance per iteration but loses one-RPC-per-sample independence and complicates the CI math. Rejected.
- *Parametrize in the harness*: useful escape hatch, kept as a CLI flag (`--iters-per-cell N`), but the M3 report uses the n=30 default.

## R-3 — Channel-axis configuration matrix

For each axis, the M3 sweep tests at minimum the M1 baseline ("default", no explicit option) plus one or two tuned configurations. Each tuned setting is grounded in cloned grpcio source. Citations point into `~/.graphify/repos/grpc/grpc/src/python/grpcio/` (the local clone managed by the M2 workflow) or the C-core source under `~/.graphify/repos/grpc/grpc/src/core/`.

### R-3a — `max_message_size`

**Decision**: Test `default` (4 MiB on each side, per grpcio's compiled-in default) vs. `16 MiB` (large enough to clear `hidden_size=8192` × 4-byte-float embeddings = 32 KiB, with margin for streaming overhead) vs. `unlimited` (-1).

**Rationale & citation**: grpcio enforces `GRPC_ARG_MAX_RECEIVE_MESSAGE_LENGTH` and `GRPC_ARG_MAX_SEND_MESSAGE_LENGTH` (defaults: 4 MiB receive, no send limit). For a single embedding payload, even `hidden_size=8192` × 4 bytes = 32 KiB sits well below the 4 MiB default, so the default is **expected not to bind** for single-request embeds — the binding case is batched embeds or longer streams. The M3 report records the actual binding width per FR-006 and SC-002. The `unlimited` config exists to confirm the bind-vs-no-bind boundary cleanly.
- Source: `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` channel-args plumbing; default values surfaced in `~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc`.
- Bench query (recorded for the M3 report): `graphify path "Channel" "max_message_size" --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json`

### R-3b — Keepalive

**Decision**: Test `default` (no keepalive pings) vs. `aggressive` (`grpc.keepalive_time_ms=10000`, `grpc.keepalive_timeout_ms=5000`, `grpc.keepalive_permit_without_calls=1`) vs. `relaxed` (`grpc.keepalive_time_ms=60000`, `grpc.keepalive_timeout_ms=20000`).

**Rationale & citation**: Keepalive primarily affects long-lived connections and streaming RPCs. The "aggressive" config is well-documented to surface server-side `GOAWAY` storms when the server has not been configured to accept the ping rate (the keepalive-regression Edge Case in the spec). The "relaxed" config is closer to typical production tuning. Both are tested specifically against the long-stream synthetic prompt (R-7) to ensure the regression mode is observable.
- Source: `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc` keepalive timer logic.

### R-3c — Compression

**Decision**: Test `none` (default) vs. `gzip` (channel-level, applied to every message). The third option, `deflate`, is supported by grpcio but rarely deployed and adds little signal; skip unless `gzip` shows a surprising result.

**Rationale & citation**: Channel compression in grpcio is set via `grpc.default_compression_algorithm` and per-call via `compression=grpc.Compression.Gzip`. For embed payloads (dense float32 tensors with no exploitable redundancy), gzip is **expected to enlarge the payload** (the "Compression that lengthens the payload" Edge Case in the spec). For chat-completion streaming chunks (text tokens with high redundancy in punctuation/whitespace), gzip is expected to shrink the payload. Both directions are recorded.
- Source: `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` compression argument; `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc` for frame-level handling.

### R-3d — HTTP/2 framing

**Decision**: Test `default` flow-control window (65 KiB initial per the HTTP/2 spec) vs. `enlarged` (`grpc.http2.bdp_probe=1` on, with `grpc.http2.lookahead_bytes=16384`). The bdp-probe flag instructs grpcio's transport to dynamically size the BDP-window estimate based on observed throughput.

**Rationale & citation**: HTTP/2 flow control determines how much data the receiver will accept before the sender must wait for `WINDOW_UPDATE` frames. For the long-stream synthetic prompt (high token throughput) the default window can become a bottleneck. BDP-probing is grpcio's adaptive answer.
- Source: `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc` and `bdp_estimator.cc`.

## R-4 — Mock engine interface surface

**Decision**: `MockEngine` exposes the minimum slice of the vLLM engine that the project's existing servicers consume: the async generators yielded by `chat_servicer.py` and `completions_servicer.py`. Specifically, the methods `generate(prompt, sampling_params, request_id) -> AsyncIterator[RequestOutput]` for streaming and the embedding entry point for the embed path. Output tokens are dummy (a fixed pseudo-text generator seeded from the prompt hash); embeddings are dummy float32 tensors of shape `[hidden_size]` filled with values from a seeded `numpy.random.default_rng(prompt_hash)`.

**Rationale**:
- Per the M3 milestone framing, "GPU cost is removed from the loop." The mock is not asked to produce realistic outputs — only realistically-shaped wire payloads.
- Reusing the existing servicer interface means no proxy/frontend code paths change for P1 (only channel options become injectable, per plan.md). This isolates "channel-tuning effect" from "code-path-change effect."
- Per upstream guidance recorded in `upstream_advisors.md`: embed payload size is determined by `hidden_size`, not parameter count. The mock validates this empirically as a side-effect.

**Alternatives considered**:
- *Reuse `tools/benchmark/src/vllm_grpc_bench/fake_server.py`*: that's an HTTP-only fake; M3 needs a gRPC servicer-compatible engine. Different surface, kept separate.
- *Run a tiny real model (e.g., GPT-2 small) on CPU*: re-introduces tokenizer / sampler variability and slows iteration. Rejected.

**Citation**: `graphify explain "AsyncLLM" --graph ~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json` (recorded in the M3 report's methodology note).

## R-5 — Harness observability depth (clarification deferred from `/speckit-clarify`)

**Decision**: For M3 v1, the harness records request and response wire bytes (sender-side: serialized message size; receiver-side: bytes-on-wire including HTTP/2 framing, captured via grpcio's per-call `_observed_wire_bytes` accumulator if available, falling back to `len(message.SerializeToString())`) and end-to-end timings (per-RPC wall clock; for streaming, per-token deltas). It does **not** record HTTP/2 frame counts, retries, or compression ratios. If a P1 axis result is surprising or not explainable from the bytes/timing data alone, the harness gains a per-call grpcio tracing wrapper as a follow-up — but that's a v2 concern, not blocking M3.

**Rationale**:
- The questions M3 asks (SC-001, SC-002, SC-003) are answerable from bytes + timings. Adding deeper instrumentation upfront violates "Don't add abstractions beyond what the task requires" (CLAUDE.md guidance).
- grpcio does not expose per-frame counts cleanly from Python; getting them requires either patching `grpc-tools` or using `GRPC_TRACE=...` env vars and parsing logs. Both are heavy.

**Alternatives considered**:
- *Full grpcio tracing via `GRPC_TRACE=http,api`*: produces gigabytes of log output for an M3-scale sweep; parsing is brittle. Rejected for v1.
- *eBPF on Linux*: powerful but Linux-only and requires root. Out of scope (CONTRIBUTING.md commits to macOS+Linux parity).

## R-6 — Workload sizing for the harness (clarification deferred from `/speckit-clarify`)

Rolled into R-1 + R-2: 30 iterations × 1 RPC each per cell, with cell sweep dimensions enumerated in plan.md "Scale/Scope".

## R-7 — Long-stream synthetic prompt for the keepalive Edge Case

**Decision**: Add `tools/benchmark/corpus/m3_long_stream.json` with one synthetic prompt that, against the mock engine, produces a stream of ≥1024 tokens at one token per ~50 ms (so total stream wall-clock ≥ 50 s — long enough to cross the aggressive-keepalive `keepalive_time_ms=10000` ping interval multiple times). The prompt itself is a deterministic seed; the mock generates a fixed-length token sequence keyed off the prompt hash, ensuring reproducibility.

**Rationale**:
- The keepalive-regression Edge Case in the spec demands the bench actually exercise long-lived streaming. M1's existing chat corpus has ~30-token median completions (per `docs/benchmarks/phase-5-streaming-comparison.md`); on its own it would not cross the 10 s aggressive-keepalive interval. The long-stream prompt is the missing ingredient.
- Keeping the long-stream prompt deterministic and in-corpus means future M3 runs measure the same workload — required for SC-003's cross-run CI math to be valid.

## R-8 — M1 vs. M3 comparability under different hardware (Modal A10G vs. local CPU)

**Decision**: M3 reports **deltas relative to its own M1-baseline channel configuration measured on the same M3 hardware**, not deltas vs. the published M1 numbers. The M1 report's absolute timings stand as their own artefact; M3's job is "given default channel options on this hardware, what does tuning add?", not "is local CPU as fast as Modal A10G" (it isn't, and that comparison is meaningless for channel-tuning conclusions).

**Rationale**:
- Per FR-005, "deltas vs. the M1 baseline" — clarified here to mean the M1-baseline channel **configuration** measured on M3 hardware, not the M1-measured timings. The methodology section of the M3 report makes this explicit so external readers don't conflate the two.
- This sidesteps the inherent CPU-vs-GPU latency gap and lets the channel-tuning signal stand on its own.

**Alternatives considered**:
- *Run M3 on Modal A10G to match M1 hardware*: rejected — the milestone explicitly removes GPU cost from the loop, and Modal cycles cost money. The M3 mock is dummy-weighted, so GPU buys nothing.
- *Compare M3 wire-byte numbers (which are hardware-independent) directly against M1's wire-byte numbers*: this is fine for wire bytes specifically, since wire size doesn't depend on hardware. Allowed but called out separately in the report; for decode-time deltas the same-hardware rule stands.

## R-9 — P2 schema candidate selection

**Decision**: P2 begins after P1 closes (FR-008). The first P2 candidate is **packed scalars on the chat completion's token-id field** (per the spec's example in §User Story 2 / AS1) — measured at hidden_size=4096 with the P1-recommended channel configuration frozen in. Additional candidates (oneof layout, streaming chunk granularity) are evaluated per the same methodology if the first candidate produces a measurable signal; otherwise the report records the negative result and moves on (Constitution V).

**Rationale & citation**:
- The chat completion's token-id field is currently `repeated int32`; protobuf packed encoding (`[packed=true]` for proto2 / default-on for proto3) typically reduces wire bytes for sequences of small ints. Concrete win or loss is measured, not assumed.
- Source for proto3 packing semantics: protobuf language guide; grpcio's serialization path: `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_runtime_protos.py`.

## R-11 — Why total chat_stream wall-clock is dominated by mock pacing (added 2026-05-10)

**Decision**: For the chat_stream path under the M3 P1 sweep harness (the harness used in PR #17), total wall-clock is **not** a defensible time-metric signal for channel-tuning verdicts. TTFT (per-sample `time_to_first_token_seconds`) is.

**Empirical justification** (from `bench-results/m3-full/m3-channel-tuning.json`): at the mock's default pacing (~200 tokens/second), ~32 tokens emitted per RPC corresponds to ~32 × 5 ms = ~160 ms of deliberate `time.sleep` between yields. The observed total wall-clock for the same cell is ~184 ms. Pacing therefore accounts for ~87% of total chat_stream wall-clock; transport+serialization is the remaining ~13%. Channel-axis effects on transport+serialization are diluted to <5% of total signal — well below the 10–15% cross-batch noise documented in R-12 and well below the typical channel-tuning effect size we expect to detect.

**Implication**:

- Phase A / US3 (this milestone): use TTFT per-sample for chat_stream time-metric verdicts. Total chat_stream wall-clock cells are marked `noise_bounded` (FR-005) and listed in the report's Limitations section as inputs to M4.
- M4: add a no-pacing mode to the mock engine (FR-012) so a clean chat_stream total-wall-clock verdict becomes possible.

## R-12 — Cross-batch baseline drift in wall-clock time (added 2026-05-10)

**Decision**: The M3 P1 orchestrator's "fresh M1_BASELINE per axis batch" pattern is unsafe for the time metric. Phase A's re-analysis pairs each candidate with its immediate-predecessor M1_BASELINE in cohort run-order; M4 will replace per-axis fresh baselines with a single shared up-front baseline (FR-013).

**Empirical justification**: the same cell (chat_stream h=2048 m1_chat M1_BASELINE) measured at four different points in the M3 sweep run-order showed mean wall-clock of 184.4 / 182.4 / 204.9 / 207.9 ms — a 13% spread driven by ambient system load between axis batches. The bytes metric for the same baseline cohorts varied by <0.01% across all four. The bytes-axis SC-003 evaluation in PR #17 was therefore robust to this drift; a time-axis SC-003 evaluation against any of those baselines would be CI-bound to ±13% noise, larger than any expected channel-axis time win.

**Implication**:

- Phase A / US3: pair candidates with the immediate-predecessor baseline in cohort run-order (matched via `cell_id` ordering and the run-order embedded in the JSON). Where the spread between consecutive baselines for the same cell exceeds the candidate's expected effect size, mark the cell `noise_bounded`.
- M4: implement FR-013's shared-baseline mode — measure one M1_BASELINE cohort (n≥100) up front, reuse across all axes.

## R-13 — TTFT as the diagnostic streaming time metric (added 2026-05-10)

**Decision**: For chat_stream cells, the recommendation builder's time-metric path evaluates `time_to_first_token_seconds` (per-sample), not total wall-clock. Per FR-014, TTFT is the primary streaming time metric; total wall-clock is a secondary diagnostic; mean inter-token latency is reported but is not used as a primary verdict metric because it is mock-pacing-bounded.

**Rationale**: TTFT isolates connection-establishment and first-byte transport time from the mock's per-token pacing. For each axis, the channel-tuning hypothesis maps to TTFT or to embed total wall-clock as follows:

- `KEEPALIVE_*`: TTFT (ping-frame interleaving on a still-warming connection affects first-byte timing under contention).
- `HTTP2_BDP_PROBE`: TTFT (initial flow-control window sizing affects first-byte send) plus embed total wall-clock (window opening over the body of a single large embed response).
- `MAX_MSG_*`: irrelevant for TTFT (the limit binds at body, not at headers); embed total wall-clock would be the natural metric except the candidates don't bind at canonical widths (per the published M3 report's SC-002 finding).
- Compression: both — encoder/decoder setup contributes to TTFT, and the encode/decode tax dominates embed total wall-clock (the +18–39% gzip tax already in the M3 bytes report).

TTFT semantics are already documented in the project's M1 streaming methodology (`docs/benchmarks/phase-5-streaming-comparison.md`).

**Implementation note**: `time_to_first_token_seconds` is already populated per-sample for chat_stream cohorts in the existing JSON. No re-sweep is needed to compute TTFT-based verdicts in Phase A.

## R-14 — Phase A vs. M4 (Phase B) scope demarcation (added 2026-05-10)

**Phase A — lands in this milestone (M3) as US3**: Code-only re-analysis. Inputs: the existing `bench-results/m3-full/m3-channel-tuning.json`. Outputs: `docs/benchmarks/m3-channel-tuning-time.{md,json}` with per-axis time-metric verdicts using `metric=time` for embed cells, `metric=ttft` for chat_stream cells, and immediate-predecessor M1_BASELINE pairing throughout. Adds a `--reanalyze <existing-json>` mode to `python -m vllm_grpc_bench --m3` plus the corresponding helper paths in `m3_sweep.build_recommendations` and supporting tests. **No new sweeps, no harness behavior changes beyond the re-analysis path.**

**M4 — separate feature (016 when scoped)**: Harness redesign. Adds `--no-pacing` to the mock engine (FR-012), `--shared-baseline` to the orchestrator (FR-013), TTFT-as-primary in the streaming verdict path (FR-014). Re-runs the four-axis channel sweep under the new methodology and publishes a definitive time-axis report that supersedes Phase A's interim conclusions where they were `noise_bounded`. Also runs the deferred US2 schema-level candidates against the new frozen-channel baseline. Optionally adds a cross-host transport mode for keepalive / `http2_framing` axes that don't manifest savings on loopback.

**Why split this way**: Phase A is bounded (~1 day, code-only, no new measurement) and lands cheap defensible value on the M3 milestone before it closes. M4 is a real harness redesign that warrants its own `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` lifecycle, has its own constitution-check pass (no-pacing mode is a behavior change to a fixture some future test might depend on), and will generate enough new data that combining with Phase A would muddle the milestone story.

## Summary of unresolved items

None blocking M3. Phase A (US3) tasks are enumerated in `tasks.md` Phase 6 (T040..T046). M4 remains to be specified via `/speckit-specify` once M3 closes.
