# Cross-Milestone Analysis: vllm-grpc

This document is the canonical home for vllm-grpc benchmark findings, milestone by milestone, in chronological order. Each milestone section names its source report, summarises the headline finding(s), and links cross-milestone where one milestone's result resolved (or recontextualised) an earlier one.

The per-milestone benchmark reports under [`docs/benchmarks/`](docs/benchmarks/) remain the source-data record; this document is the narrative cross-reference. The original M1/M3-era summary has been folded into § M1 and § M3 below; the pre-cleanup `docs/benchmarks/summary.md` redirect stub is recoverable from any milestone tag through `milestone/m6.1.3-attribution` (see § Repo housekeeping).

> **Reading order tip.** M1–M4 measure single-protocol or pre-REST-vs-gRPC questions; their findings are largely topology-independent. M5 onward measures cross-host and REST-vs-gRPC dynamics where deployment topology starts to matter. The [Topology guide](#topology-guide--which-milestone-result-applies-to-your-deployment) at the bottom names which M5-era milestone applies to which deployment shape.

### Glossary

Shorthand used throughout this document and the per-milestone reports. Each term
is defined here once; later sections use it without re-glossing.

| Term | Meaning |
|------|---------|
| **Milestone IDs** (M1, M3, M5.1, M5.2, M6.1.2, …) | Sequential research deliverables; each has a section below and a `milestone/*` git tag. Sub-numbers (M5.1, M6.1.2) are follow-ups that refine an earlier milestone. |
| **TTFT** | Time To First Token — latency from request send to the first streamed token. |
| **TPOT** | Time Per Output Token — steady-state per-token generation latency after the first. |
| **RPC** | Remote Procedure Call — one request/response over gRPC. |
| **KV cache** | Key/Value attention cache vLLM holds in GPU memory during generation. |
| **CSP** | Cloud Service Provider (AWS, Azure, …); relevant because routing between CSPs changes the network path. |
| **cohort** | One protocol/transport configuration under test (e.g. `default_grpc`, `rest_https_edge`, `rest_plain_tcp`). |
| **cell** | One workload point in the matrix — a (request type, concurrency `c`) pair, e.g. `chat_stream_c8`. |
| **c=N** | Concurrency: N requests dispatched in flight at once. |
| **wall_p50 / wall_p95** | 50th / 95th percentile wall-clock latency across a block of requests. |
| **seg_\* / segment decomposition** | Per-RPC latency broken into named segments (queue, prefill, ingress, egress, …) to attribute where time goes. |
| **anchor / null anchor** | A fixed reference workload point (`max_tokens` ∈ {10, 50}) kept stable across milestones for cross-baseline comparison. |
| **same-fabric vs managed-edge** | Two deployment topologies: client+server in one network vs client reaching a managed provider through its HTTPS edge POP. |
| **OIDC** | OpenID Connect — the token-less "Trusted Publishing" auth GitHub Actions uses to publish to PyPI. |

---

## M1 — Foundation

**Status**: delivered (Phase 4.2 / 5 / 6 benchmark reports under `docs/benchmarks/phase-*`)
**Report**: see § M1 fold-in below — historical phase-4.2 / phase-5 / phase-6 source-data JSON is recoverable via `milestone/m2-ground-truth` (see § Repo housekeeping).

Three access paths (REST via proxy, gRPC via proxy, gRPC-direct) implemented and benchmarked end-to-end on Modal A10G with vLLM v0.20.0 and `Qwen/Qwen3-0.6B`. M1 establishes the wire-size and time baselines that every later milestone supersedes or preserves.

**Headline finding(s)**:

- **Chat response bytes drop ~89%** via gRPC-direct (65 B vs 611 B REST JSON), structural and topology-immune — the win is protobuf framing over JSON, not network or model behaviour.
- **Embed request bytes drop ~25%** (455 KB gRPC vs 606 KB REST) because gRPC transmits raw tensor bytes while REST base64-encodes them. Also topology-immune.
- **At c=1**, gRPC-direct latency is slightly *below* native REST for both text (-4%) and embed (-7%) completions. The completions path has less per-request setup cost than chat.
- **At c=8** on the c=8 native-REST text completions cell, the run hit server-side queue saturation (P95 = 13.6 s, throughput 0.18 rps) while proxy and gRPC-direct held ~535 ms P95 / ~2.2 rps. Those Δ values reflect a degraded REST baseline, not a stable protocol comparison.
- **Proxy adds 42–44% latency at c=1** due to the REST→gRPC translation hop.

**Cross-milestone notes**:

- **Bytes-axis findings are NOT superseded** by any later milestone (M5.1 FR-021, M5.2 reiterates). Wire-size results come from encoding choice (JSON vs protobuf), not transport or topology.
- M1's time-axis findings are partially superseded by **M5.1** (which re-measures REST vs gRPC on real wire with engine cost held constant) and contextualised by **M5.2** (which measures the HTTPS-edge transport not captured in M1's plain-TCP runs).
- M1 ran on the live vLLM engine on Modal A10G. M3 onward runs CPU-only with a mock engine to isolate transport/framing effects from model execution — M3+ numbers are **not** comparable to M1's GPU numbers.

---

## M2 — Cross-Repo Ground-Truth Research

**Status**: delivered (process milestone)
**Report**: (none — process milestone)

Formalised the practice of consulting cloned vLLM (the inference engine) and grpcio (the wire stack) as authoritative references when making proto, channel, or decode-tuning decisions in M3 and beyond. Tooling, merge process, and rebuild cadence documented in [`../ground-truth-workflow-for-associated-projects.md`](ground-truth-workflow-for-associated-projects.md); the project-local `/ground-truth-refresh` skill drives the cadence in one invocation.

**Headline finding(s)**:

- Cross-repo `graphify` graph (vllm + grpcio + project) enables BFS-from-question, path traversal, and explain queries that span all three repos.
- Known gap: graphify does not parse `.proto` files; proto-shape questions are answered by reading [`../proto/`](proto/) directly.

**Cross-milestone notes**: methodology infrastructure underpinning M3 onward. No measured findings; the value of M2 is process discipline that survives in every subsequent milestone's code-citation pattern.

---

## M3 — Protobuf & gRPC Tuning

**Status**: delivered 2026-05-10 (bytes axis PR #17; time-axis re-analysis PR #19)
**Report**: [`docs/benchmarks/m3-channel-tuning.md`](docs/benchmarks/m3-channel-tuning.md) (bytes) · [`docs/benchmarks/m3-channel-tuning-time.md`](docs/benchmarks/m3-channel-tuning-time.md) (time)

Four-axis P1 sweep (`max_message_size`, `keepalive`, `compression`, `http2_framing`) at three canonical embedding widths (2048, 4096, 8192) × two paths (`embed`, `chat_stream`) ran 24 cells. Bytes verdicts were uniformly `no_winner`. A Phase A re-analysis of the same n=30 sweep against the wall-clock-time metric surfaced four real wins the bytes axis missed.

**Headline finding(s)**:

- **Bytes axis: every cell `no_winner`** under SC-003. No candidate channel configuration's wire-byte 95% CI fell strictly below the M1-baseline's 95% CI in the same batch.
- **Time axis surfaced 4 real wins**: `max-msg-16mib` -28.66% TTFT (chat_stream/h=2048), -31.39% (chat_stream/h=4096), -2.43% wall-clock (embed/h=4096); `keepalive-aggressive` -24.20% TTFT (chat_stream/h=2048). 2 cells flagged `noise_bounded → M4` for re-measurement.
- **`max_message_size` default 4 MiB is never binding** at any canonical width up to h=8192. Embed payloads sit at ~131 KB / 262 KB / 524 KB for h=2048/4096/8192 — roughly 8× under the default ceiling at the largest canonical width.
- **P1 frozen channel config (time-axis)**: `max_message_size = max-msg-16mib`; remaining axes default to M1_BASELINE.

### § M3 fold-in (originally folded in from the pre-cleanup `docs/benchmarks/summary.md` § 4 per § M3 FR-018; pre-fold-in text recoverable via `milestone/m3-grpc-tuning-r1`)

**Methodology** (CPU-only, mock vLLM engine — distinct from § M1 GPU runs above)
- Sweep: 4 channel axes × 3 canonical widths × 2 paths × 30 iters/cell
- Bytes verdicts: [`m3-channel-tuning.md`](docs/benchmarks/m3-channel-tuning.md) | [`m3-channel-tuning.json`](docs/benchmarks/m3-channel-tuning.json)
- Time verdicts (Phase A / US3): [`m3-channel-tuning-time.md`](docs/benchmarks/m3-channel-tuning-time.md) | [`m3-channel-tuning-time.json`](docs/benchmarks/m3-channel-tuning-time.json)
- SC-003 win bar: candidate 95% CI strictly below baseline 95% CI (same statistical bar on both metrics)

#### Bytes axis (PR #17)

| Axis | Width range | Path | Verdict | Notes |
|---|---|---|---|---|
| `max_message_size` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | default 4 MiB never binds; embed payload is ~524 KB at h=8192 |
| `keepalive` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | aggressive 10 s pings completed long-stream cohort with no drops |
| `compression` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | gzip costs +18–39% time on dense-float embeds with no wire-byte win |
| `http2_framing` | 2048 / 4096 / 8192 | embed + chat_stream | no_winner (all 6 cells) | BDP-probe cannot manifest a win on loopback CPU-only mock |

#### Time axis — Phase A re-analysis (US3, PR #19)

Phase A re-evaluates the same n=30 sweep data on TTFT (chat_stream) and total per-RPC wall-clock (embed) per FR-014, with immediate-predecessor M1_BASELINE pairing per `research.md` R-12. Surfaces 4 wins the bytes axis missed plus 2 cells flagged for M4 re-measurement.

| Axis | Path | Width | Metric | Verdict | Δ% |
|---|---|---|---|---|---:|
| `max_message_size` | chat_stream | 2048 | TTFT | **recommend `max-msg-16mib`** | **−28.66%** |
| `max_message_size` | chat_stream | 4096 | TTFT | **recommend `max-msg-16mib`** | **−31.39%** |
| `max_message_size` | embed | 4096 | wall-clock | **recommend `max-msg-16mib`** | −2.43% |
| `keepalive` | chat_stream | 2048 | TTFT | **recommend `keepalive-aggressive`** | **−24.20%** |
| `keepalive` | embed | 2048 | wall-clock | noise_bounded → M4 | (13.5% baseline drift) |
| `http2_framing` | chat_stream | 4096 | TTFT | noise_bounded → M4 | (35.2% baseline drift) |
| (other 22 cells) | — | — | — | no_winner | — |

**P1 frozen channel config (time-axis):** `max_message_size = max-msg-16mib` (the rest default to M1_BASELINE; see `m3-channel-tuning-time.md` for the per-axis rationale and `p1_frozen_config_time` in the JSON companion).

**Cross-comparison caveat:** the M3 numbers above are **not** comparable to § M1 above. M3 runs CPU-only with a mock engine to isolate channel/protocol effects from model-execution effects, while § M1 benchmarks the live vLLM engine on Modal A10G. M3's "delta vs M1" is computed against the M3 in-batch baseline (also CPU-mock), not against the GPU numbers in § M1. The `noise_bounded` cells re-measure under M4's shared-baseline harness.

**Cross-milestone notes**: M3 winners re-validated by M5 on real wire (where keepalive and http2_framing wins on `embed/h=2048` finally manifest at 23–25%). M3's bytes-axis `no_winner` verdicts are preserved as the bytes baseline for traceability.

---

## M4 — Time-Axis Channel & Schema Tuning

**Status**: delivered 2026-05-10
**Report**: [`docs/benchmarks/m4-time-axis-tuning.md`](docs/benchmarks/m4-time-axis-tuning.md)

Re-framed M3's measurements around wall-clock time as a first-class success metric (TTFT for streaming, total per-RPC wall-clock for embed). Harness redesign added `--no-pacing` mode, a shared-baseline orchestrator (one M1_BASELINE cohort up front at n≥100, reused across all axes), a borderline-expand cascade (n=100 → n=250 on CI overlap), and `client_bound` detection. Per-cohort CV is recorded so the reader adjudicates trust on noisy baselines (FR-005 — record-and-report, not abort-on-CV).

**Headline finding(s)**:

- **`max-msg-16mib` recommend for `embed/h=2048`** with -30.00% wall-clock vs the shared baseline; `max-msg-unlimited` recommend for the same cell with -20.47%.
- **`chat_stream` axes flagged `client_bound`** — the loopback CPU-only harness cannot manifest the wins that real-wire conditions would surface. Those cells are M5's mandate.
- Per-path frozen-channel baselines and the Supersedes-M3 classifier landed; 274 harness tests green.

**Cross-milestone notes**: M4's `client_bound` and loopback-caveat flags directly motivated **M5** (cross-host re-run on Modal). The frozen-tuned channel composition M4 selected is what **M5.1** and **M5.2** reuse without re-tuning (per M5.2 FR-007).

---

## M5 — Cross-Host Time-Axis Validation

**Status**: delivered 2026-05-11
**Report**: [`docs/benchmarks/m5-cross-host-validation.md`](docs/benchmarks/m5-cross-host-validation.md)

Re-ran the M4 four-axis channel sweep with the gRPC server deployed on Modal eu-west-1 and the benchmark client local, so transmission crosses real wire (RTT median 52.18 ms from US client) instead of loopback. Same harness (`vllm_grpc_bench --m4`) targeting a Modal endpoint, same axis × width × path matrix as M4.

**Headline finding(s)**:

- **5 `recommend` wins, all at `embed/h=2048`**, deltas -23% to -25% vs M5 cross-host baseline: `max-msg-16mib`, `max-msg-unlimited`, `keepalive-aggressive`, `keepalive-relaxed`, `http2-bdp-probe`.
- **Keepalive and HTTP/2 framing effects, loopback-caveated under M4, materialize as 23–25% wall-clock wins on real wire** at `embed/h=2048`. This is the M5 thesis confirmed.
- 30 `no_winner`, 0 `client_bound`, 5 `server_bound` (all `embed/h=8192` plus `compression-gzip` at large h — server-side serialization dominates wall-clock at 512 KB+ payloads).
- Supersedes-M4 table emits 20 entries (10 `loopback_resolution` + 8 `bound_classifier_transition` + 2 `verdict_confirmed`, zero genuinely-unexpected rows after the 5th classifier was added).

**Cross-milestone notes**: M5's frozen-tuned channel composition is the gRPC tuning baseline reused unchanged by **M5.1** and **M5.2** (M5.2 FR-007 explicitly forbids re-tuning). M5 measured single-protocol gRPC; the REST-vs-gRPC head-to-head is **M5.1**'s mandate.

---

## M5.1 — REST vs gRPC Head-to-Head on Real Wire

**Status**: delivered 2026-05-11
**Report**: [`docs/benchmarks/m5_1-rest-vs-grpc.md`](docs/benchmarks/m5_1-rest-vs-grpc.md)

**Audience scope (topology-aware framing)**: M5.1 measures the **same-network-fabric** topology — both REST and gRPC travel Modal's plain-TCP `modal.forward(..., unencrypted=True)` tunnel so the network path is held constant across protocols. This isolates protocol cost (encoding, framing, multiplexing). The result applies to enterprise-internal deployments, self-hosted homelabs, well-connected colos, and any setup where REST and gRPC share a network fabric. See the [Topology guide](#topology-guide--which-milestone-result-applies-to-your-deployment) for which audience this is.

18-cell head-to-head matrix (2 paths × 3 widths × 3 concurrencies). 48 verdicts across four gRPC sub-cohorts (`tuned_grpc` at c=1, `tuned_grpc_multiplexed` and `tuned_grpc_channels` at c≥2, `default_grpc` everywhere) plus one REST cohort. n=100 per cohort, ~640 s wall-clock on Modal CPU-only.

**Headline finding(s)**:

- **Embed is gRPC's domain.** 16 of 17 embed verdicts are gRPC-recommend or `no_winner`; c=1 deltas are uniformly -32% to -35%. Protobuf packed-float embeds + HTTP/2 multiplexing beat REST's JSON-numeric arrays on every embed cell except `embed/h=2048/c=8` (REST wins multiplexed/channels by +30% to +49%; default-gRPC `no_winner`).
- **chat_stream above c=1 is REST's domain.** 12 of 18 c≥4 chat_stream verdicts are `rest_recommend` with deltas +11% to +29%. REST's HTTP/1.1 keep-alive + simpler framing beats gRPC's HTTP/2 streaming overhead under MockEngine's neutral inference cost. chat_stream c=1 flips to gRPC across all widths (-4% to -9%).
- **M5's tuned channel config provides no measurable benefit over M1-default on this path.** In 5 of 6 c≥2 embed cells where every gRPC sub-cohort wins, `default_grpc` matches or beats `tuned_grpc_multiplexed` and `tuned_grpc_channels` outright. Either the tuned axes are not load-bearing at these scales, or cross-host RTT dominates what loopback-era tuning was harvesting. **This finding motivated M5.2.**
- **M1 time-axis supersession is substantial.** 4 of 6 M1 time-axis verdicts flip on real wire.
- REST shim overhead median 0.55 ms / p95 3.04 ms — below the 5 ms materiality threshold; not a confound.

**Caveats — kept prominent in the report:**

- **MockEngine, not real vLLM.** Engine cost held constant across cohorts so the verdict reflects transport + framing only. Real-engine re-validation delivered as **M6** below (single model at h=4096); full multi-model expansion remains deferred to M8.
- **Both protocols travel Modal's plain-TCP tunnel.** The original FR-019 "REST uses Modal-managed TLS" assumption was voided after a smoke run measured a ~2× RTT gap between Modal's HTTPS edge and plain-TCP that would have dominated every verdict. M5.1 does **not** measure REST against the production-realistic HTTPS edge — **M5.2 closes that gap** by adding the HTTPS-edge transport as a separate cohort.
- Bytes-axis findings from M1 (89% chat response reduction, 25% embed request reduction) remain in force unchanged (FR-021) — M5.1 measures time only.

**Cross-milestone notes**:

- **M5.1 and M5.2 measure two distinct, valid topologies.** M5.2 does **not** supersede M5.1 in general. Both findings apply, to different audiences. See [Topology guide](#topology-guide--which-milestone-result-applies-to-your-deployment).
- M5.1's "M5 tuning provides no measurable benefit" finding was the explicit motivator for M5.2's higher-n (n=250) sweep, which confirmed it at higher resolution.

---

## M5.2 — REST Transport Path × gRPC Tuning Surface

**Status**: delivered 2026-05-14
**Report**: [`docs/benchmarks/m5_2-transport-vs-tuning.md`](docs/benchmarks/m5_2-transport-vs-tuning.md)

**Audience scope (topology-aware framing)**: M5.2 measures the **managed-edge-provider** topology — REST runs via Modal's HTTPS edge (TLS-terminated, anycast-routed near the client) while gRPC runs via plain-TCP `modal.forward(..., unencrypted=True)`. This captures the production deployment shape a hobbyist (or anyone) renting GPU from Modal, RunPod, Replicate, or similar managed providers actually experiences. See the [Topology guide](#topology-guide--which-milestone-result-applies-to-your-deployment) for which audience this is.

Five-cohort head-to-head on the same 18-cell (path × hidden_size × concurrency) matrix from M5.1: `rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`, `tuned_grpc_channels`. n=250 per cohort (vs M5.1's n=100), with per-cell verdicts split into protocol comparison (each gRPC cohort vs `rest_https_edge`) and a transport-only comparison (`rest_https_edge` vs `rest_plain_tcp`). Run `m5_2-3b58141c0d68` ran 50m41s on Modal eu-west-1, CPU instance class, 21,000 records, 0 failed cells.

**Headline finding(s)**:

- **Topology surprise — HTTPS-edge faster than plain-TCP.** Median Δ -47.46 ms, p95 -48.13 ms. Modal's HTTPS anycast edge beats direct public-URL routing for this client geolocation. This validates `rest_https_edge` as a legitimate production-equivalent REST baseline and is the foundation for the rest of the M5.2 verdicts.
- **Protocol verdicts bifurcate by concurrency:**
  - **At c=1**: gRPC wins or ties. `tuned_grpc` beats `rest_https_edge` by -103.3 ms at `embed/h=8192`, -51.0 ms at `embed/h=4096`. chat_stream c=1 results are at the edge of significance (some `no_winner`, some sub-millisecond gRPC wins).
  - **At c=4 / c=8**: `rest_https_edge` wins consistently — by +13 to +28 ms for chat_stream, **by +91 to +1481 ms for embed** with deltas scaling with hidden_size.
- **Supersedes-M5.1**: 3 `noise_resolved` cells (M5.1 `no_winner` resolved at n=250 under HTTPS-edge); many `verdict_confirmed`; several `verdict_changed` reflecting the topology shift rather than regression.
- **Payload-parity audit (FR-005c) PASS.** Engine-input bytes identical across REST and gRPC for h=2048/4096/8192 (131072/262144/524288 = 16 × 4 × hidden_size). Empirically verified, not just code-reviewed.
- **HTTPS-edge wins the transport-only comparison broadly.** 13 of 18 cells favour `rest_https_edge` over `rest_plain_tcp`; 5 transport cells fall to `no_winner` at the largest embed widths where signal vs noise is the tightest.

**Cross-milestone notes**:

- **M5.2 does not supersede M5.1 in general.** It measures a different deployment topology — the production-equivalent managed-edge baseline — that M5.1 deliberately controlled out. Verdict-changed cells in the Supersedes-M5.1 table are **topology-dependent**, not regressions of M5.1's measurement. The audience for M5.2 is the managed-provider tenant; the audience for M5.1 is the same-fabric operator. See [Topology guide](#topology-guide--which-milestone-result-applies-to-your-deployment).
- **M1 bytes-axis preserved.** Topology-immune encoding wins from M1 still apply (89% chat response reduction, 25% embed request reduction).
- **M5 transport-axis preserved.** M5.2 reuses M5's frozen-tuned channel composition unchanged per FR-007; the M5 axis-level recommendations are not re-litigated.
- **M6 contextualises M5.2 along the engine-cost axis.** M6 re-runs the 6-cell subset at h=4096 (c=1/4/8 × embed/chat_stream) against a real vLLM AsyncLLM. Four of the six M5.2 verdicts flip direction (REST→gRPC) once real engine cost is loaded — the topology framing still applies, but the protocol verdict at c≥4 is not engine-invariant for this model. See § M6 below.

---

## M6 — Real-Engine Mini-Validation

**Status**: delivered 2026-05-15
**Report**: [`docs/benchmarks/m6-real-engine-mini-validation.md`](docs/benchmarks/m6-real-engine-mini-validation.md)

Closes the MockEngine caveat that M5.1 and M5.2 both deferred. M6 re-runs a focused 6-cell × 3-cohort subset of the M5.2 matrix against a real `vllm.AsyncLLM(Qwen/Qwen3-8B, dtype=fp16, max_model_len=2048, gpu_memory_utilization=0.92)` engine on Modal A10G eu-west-1. Hidden_size=4096 fixed by Qwen3-8B's architecture; paths × concurrencies = {embed, chat_stream} × {c=1, c=4, c=8}. Cohorts: `rest_https_edge`, `default_grpc`, `tuned_grpc_multiplexed`. n=100 measurement RPCs per (cell × cohort) plus 10 warmup; cohorts run round-robin per c-batch to control for engine/network drift (FR-022). Per-RPC engine cost recorded via gRPC trailing metadata and REST JSON top-level fields (`engine_forward_ms` for embed, `engine_ttft_ms`/`engine_tpot_ms` for chat_stream).

**Headline finding(s)**:

- **4 of 6 cells overturned M5.2 under real engine.** Every `verdict_changed` cell — `embed/c=4`, `embed/c=8`, `chat_stream/c=4`, `chat_stream/c=8` — flips from `rest_wins` (M5.2) to `grpc_wins` (M6). M5.2's "REST wins at c≥4" headline does **not** hold under real-engine cost for this model.
- **`embed/c=1` verdict survives.** M6 cohort-pair CIs non-overlapping; rest_https_edge=519.73 ms vs default_grpc=489.02 ms / tuned_grpc_multiplexed=495.69 ms. Direction matches M5.2's gRPC win.
- **`chat_stream/c=1` buried by engine.** M5.2 winner delta was 0.96 ms (gRPC); M6 engine TTFT is ~46.6 ms cohort-mean. Engine cost ≥ 5× |M5.2 winner delta| classifies as `verdict_buried_by_engine` per FR-014 — no protocol verdict can be drawn at this scale for this model.
- **Engine-cost drift flag set on all 3 chat_stream cells.** Per-cohort `engine_ttft_ms` varies 7–14% between cohorts (e.g. chat_stream/c=4: rest=45.10, default=48.72, tuned=43.05). Verdict still computed per FR-014; per-cohort engine_cost values surfaced in the report. Embed paths show no drift (per-cohort variation <1%).
- **`tuned_grpc_multiplexed` matches or beats `default_grpc` on every cell under real engine.** M5.1's "M5 tuning provides no measurable benefit over M1-default on this path" finding holds — the tuned config is never worse, but the win it claims over default-gRPC is within CI on this subset. RTT shim overhead median below the 5 ms materiality threshold.

**Caveats — kept prominent:**

- **The `embed` cohort under M6 does NOT exercise real prompt-embeddings inference.** The frontend hashes opaque prompt_embeds bytes to a text digest (preserving M5.x behaviour) because the bytes the bench client emits are raw float32 arrays rather than `torch.save`-encoded tensors with the ZIP magic prefix. M6's "embed" path therefore measures text-prompt unary completion through the embeddings endpoint, not real `enable_prompt_embeds=True` inference. **M6.1 closes this gap (delivered 2026-05-16)** — see [§ M6.1 — Real-Prompt-Embeds Engine Path](#m61--real-prompt-embeds-engine-path) below. Per FR-020 the published differential quantifies the engine-path cost on identical hardware/model/matrix shape as M6; consult it as the methodology disclosure for choosing between the M5.x/M6 text-digest path and the real prompt-embeds engine path.
- **Single model, hidden_size=4096 fixed.** Qwen/Qwen3-8B chosen for fp16 VRAM fit on A10G after the `max_model_len=2048` cap. Multi-model expansion (other model families, larger hidden_size, larger VRAM classes) remains deferred to M8.
- **`max_model_len=2048` is a KV-cache fit cap, not a workload limit.** The model's natural context window is 40,960 tokens. M6's worst-case RPC length is ≤100 tokens (prompt + max_tokens=50), so the cap is 20× the actual sequence demand and does not affect measured engine cost.
- **`engine_version` recorded as `unknown` for this run.** The helper that reads it from `pyproject.toml` landed after the sweep (commit `e385881`); future M6 reruns will record the pinned vLLM version automatically.
- **Bytes axis from M1 preserved unchanged** (FR-020). Encoding is structural, not engine-dependent.

**Cross-milestone notes**:

- **M5.1 and M5.2 verdicts at chat_stream/c=1 should be treated as `unverified by M6`.** The M5.2 winner delta there (~1 ms) is below real-engine TTFT cost (~46 ms) — neither M5.1 nor M5.2 can be confirmed or refuted there from M6's data alone.
- **The topology framing for M5.1/M5.2 still applies.** M6 is a vertical correction along the engine-cost axis, not a topology change — same-fabric vs managed-edge reads remain valid lenses; M6 says that for this model at h=4096, gRPC wins both the c=1 case (where M5.2 already had it) and the c≥4 cases (where M5.2 had REST winning under MockEngine).
- **M5 channel tuning conclusion holds.** Tuned-gRPC never worse than default-gRPC on real engine for this subset.
- **MockEngine caveat from M5.1/M5.2 reports is partially closed by M6.** Real-engine cost on Qwen3-8B at h=4096 is now measured; multi-model and real-prompt-embeddings dimensions remain open (M6.1, M8).

---

## M6.1 — Real-Prompt-Embeds Engine Path

**Status**: delivered 2026-05-16
**Report**: [`docs/benchmarks/m6_1-real-prompt-embeds.md`](docs/benchmarks/m6_1-real-prompt-embeds.md)

Closes the real-prompt-embeddings caveat M6 left open. M6.1 reruns M6's 6-cell × 3-cohort matrix with exactly one variable change: the embed cohort emits `torch.save(tensor)` bytes (M6 emitted raw float32 bytes that the frontend hashed to a text digest), so the frontend's prefix-aware `_resolve_prompt_embeds_input` dispatch routes the request through `decode_embeds` → `{"prompt_embeds": tensor}` → vLLM's `enable_prompt_embeds=True` engine path. Hardware (Modal A10G eu-west-1), model (Qwen/Qwen3-8B fp16), engine config (`max_model_len=2048`, `gpu_memory_utilization=0.92`), classifier, sequencer, reporter all reused unchanged. Per FR-028 the prompt-embeds tensor shape is `[seq_len=19, hidden_size=4096] fp16`, with `seq_len` pinned at sweep start by tokenising M6's `embeds:<hex>` digest format against Qwen3-8B's tokenizer.

**Headline finding(s)**:

- **Tally: 1 verdict_survives / 2 verdict_buried_by_engine / 3 no_winner_at_n100.** No `verdict_changed`, no `cell_incomplete`. The lone survivor is `embed/c=8` — the cell with M6's largest winner delta (80.7 ms), comfortably under the 5× engine-bury threshold (5 × 80.7 = 404 ms vs 341 ms engine_forward).
- **The real prompt-embeds engine path costs ~338 ms per RPC at h=4096, seq_len=19.** That's ~7-8× heavier than M6's text-digest path (~40-50 ms). The wall-clock differential M6.1 publishes per FR-020 quantifies this on identical hardware: **+67 to +162 ms vs M6 across the 3 embed cells × 3 cohorts**. Engine cost is now the dominant per-RPC cost component for embed cells at this matrix shape — M6's 24-26 ms protocol winner deltas at c=1 and c=4 fall below the 5× materiality threshold, hence `verdict_buried_by_engine`.
- **A clean per-token generation rate falls out: ~33.7 ms/token at h=4096 on A10G.** chat_stream's measured `engine_tpot_ms` is 33.67 ms ± 0.04 across all 3 cells × 3 cohorts. embed's 338 ms engine_forward divided by 10 generations also yields ~33.8 ms/token. **Once normalised per generated token, the prompt-embeds and text-digest paths run at the same engine rate** — the ~290 ms gap is the *setup* cost (decoding `torch.save` bytes + materialising tensor on GPU + skipping the embedding lookup), not the per-token generation cost. Useful baseline for M6.2 projections.
- **`verdict_survives` at `embed/c=8` is consistent in direction with M6.** tuned_grpc_multiplexed=565.45 ms ± 7.17 vs rest_https_edge=681.37 ms ± 52.14 — non-overlapping CIs, grpc_wins as M6 predicted. **gRPC's protocol win on real prompt-embeds inference at high concurrency is the only verdict that survives the engine-path variable change.**
- **All 3 chat_stream cells fire both `chat_stream_control_drift_warning` (FR-029) and `engine_cost_drift_warning` (FR-022).** Diagnostic only — verdicts still computed. See caveats below for the root cause of each.

**Caveats — kept prominent:**

- **chat_stream cells should not be read as M6 → M6.1 protocol-comparison findings.** M6.1's chat_stream wire format is unchanged from M6 (FR-005); the chat_stream cells exist in M6.1's matrix as control cells, not as new measurements. The published TTFT shifted by +73 to +127 ms vs M6, which the FR-029 drift check correctly flags. Most likely cause: **Modal infrastructure day-over-day drift** (M6 ran 2026-05-15, M6.1 ran 2026-05-16; same hardware class but different physical instance and KV-cache fragmentation pattern). Less likely but possible: KV-cache competition with the new prompt-embeds activations interleaved by the round-robin per c-batch sequencer. Either way, the *operator implication* is the same: if you re-run M6 today you'd see similar drift, so M6.1's chat_stream verdicts depend on a control measurement that itself moved. Treat chat_stream cell verdicts as `unverified between M6 and M6.1` rather than as M6.1 conclusions.
- **`engine_cost_drift_warning=True` on all 3 chat_stream cells flags a likely instrumentation gap, not an engine-side regression.** Per-cohort engine_ttft: rest_https_edge ~43.5 ms (consistent), default_grpc ~47.5 ms (slowest), tuned_grpc_multiplexed ~41.5 ms (fastest) — a ~14-17% spread that exceeds the 10% FR-022 threshold. The engine itself shouldn't see different first-token latencies based on which channel served the request; the most likely explanation is that **REST's engine_ttft is measured inside the FastAPI shim (`engine_start → first_chunk`) while gRPC's is read from server-side trailing metadata — the two clocks straddle slightly different windows**. Worth investigating as a separate followup or as part of M6.2's spec cycle. Does not affect verdicts (drift warning is diagnostic-only).
- **Cohort RTT distribution favors rest_https_edge on p95 tail latency, contradicting per-RPC mean expectations.** Modal RTT probe (n=32 per cohort): rest_https_edge median=139.93 ms / p95=141.86 ms (very tight); default_grpc median=164.29 ms / p95=301.16 ms (2× tail); tuned_grpc_multiplexed median=274.58 ms / p95=352.67 ms (highest tail). **Modal's HTTPS edge + anycast routing produces more consistent latency than raw TCP tunnels** — relevant for operator SLOs measured on p95 rather than mean. Same pattern observed in M5.2.
- **engine_version mismatch is informational, not blocking.** M6.1's pinned vLLM is `0.20.1` (read from `pyproject.toml`); M6's baseline records `engine_version=unknown` because M6's version-reader landed post-sweep. FR-030 publishes this as a methodology note; future M6 republishes will resolve cleanly through the same plumbing.
- **`seq_len=19` was determined dynamically at sweep start** by tokenising M6's canonical `embeds:` + 16-hex-char digest format against Qwen3-8B's tokenizer — slightly larger than M6's hardcoded `seq_len=16` for raw float32 bytes. The choice is published in `run_meta.seq_len` for reproducibility; future M6.1 reruns at a different model identifier will re-pin per-tokenizer.

**Cross-milestone notes**:

- **M5.x / M6 reproductions are unaffected.** The REST shim accepts `input_kind="prompt_embedding_b64"` (M5.x / M6 wire format, raw float32 → text-digest hash) and `input_kind="prompt_embedding_torch_b64"` (M6.1 wire format, `torch.save` bytes → real engine path) indefinitely per FR-004 — no deprecation, no migration mandate. M5.x / M6 reproductions select the b64 kind and get bit-identical engine work to their published runs.
- **The M6 verdict table is the right reference for "fixed engine work, protocol comparison" operator questions.** The M6.1 verdict table is the right reference for "real prompt-embeds inference, protocol comparison" questions. **They are not interchangeable** — at c=1 / c=4, M6 says gRPC wins on embed cells; M6.1 says the engine path drowns the protocol signal at those concurrencies. The operator question dictates the reference.
- **Methodologically, M6.1 vindicates the "exactly one variable per milestone" Phase Discipline rule.** Had the prompt-embeds change been bundled into M6, the verdict_buried_by_engine reading at c=1/c=4 would have been ambiguous: was the gRPC win lost because of MockEngine→real engine, or because of text-digest→prompt-embeds? The narrow M6 → M6.1 differential disambiguates it cleanly: M6 says gRPC wins under real-engine + text-digest at c=1/c=4; M6.1 says that win is invisible under real-engine + real prompt-embeds at the same concurrency.
- **M5/M5.1 channel tuning conclusion still holds.** Tuned_grpc_multiplexed produces the tightest CIs at all 3 embed cells (CI half-widths 7-17 ms vs default_grpc 6-56 ms vs rest_https_edge 30-52 ms). M3/M4's "tuned never worse than default" finding survives the engine code-path change.
- **MockEngine caveat from M5.1/M5.2 reports is now fully closed for the M6 + M6.1 matrix shape.** Real-engine cost on Qwen3-8B at h=4096 *under both engine paths* (text-digest and real prompt-embeds) is now measured. Multi-model and the corpus-diversity / max_tokens-axis dimensions remain open (M6.2 token-budget characterization, M7 corpus, M8 model expansion — see [`docs/PLAN.md`](docs/PLAN.md)).

---

## M6.0a — Concurrent Dispatch Restoration

**Status**: delivered 2026-05-17
**Report**: [`docs/benchmarks/m6_0a-dispatch-correction.md`](docs/benchmarks/m6_0a-dispatch-correction.md)
**Sequel-to**: M6.1.1 audit baseline at [`docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md`](docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md)
**Corrected baseline**: [`docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`](docs/benchmarks/m6_1_1-engine-cost-instrumentation.md)

Methodology correction discovered during M6.1.1's first live Phase 1 run (2026-05-16). The M6 / M6.1 / M6.1.1 benchmark harness inherited M5.x's cell × cohort × concurrency matrix but silently dropped `asyncio.gather`-based concurrent in-flight dispatch in favour of a sequential `await` loop. Peak in-flight RPCs equalled 1 regardless of `cell.concurrency`, so vLLM's continuous batching never saw overlapping requests from different cohorts — making the M6.1.1 FR-010 classifier unable to mechanistically distinguish real channel-dependent batching from chronological state drift. M6.0a restores the canonical M5.1 dispatch pattern (per-cohort `asyncio.gather`; sequential across cohorts) in five harness entry points across three modules, adds a path-agnostic regression test (`test_m6_concurrent_dispatch.py`), and re-runs M6.1.1 Phase 1 against the same Modal A10G `eu-west-1` configuration to produce the corrected baseline. Harness-only fix; no engine, transport, or wire-format changes.

**Headline finding(s)**:

- **The "sequential-dispatch state-drift artifact" hypothesis is disproved.** Under M6.0a's corrected dispatch, chat_stream per-cohort `engine_ttft_ms` spread at c=4 and c=8 *grows* from the audit baseline's 6.0% / 8.4% to 15.9% / 16.4%. If the original M6.1 per-cohort drift had been a sequential-state artifact, real concurrency would have collapsed it; instead it amplifies. The effect is engine-side under continuous batching, not a measurement artifact.
- **The FR-010 classifier produces `channel_dependent_batching × 3` for the corrected run — same label as the audit baseline.** But this classification remains **classifier-degenerate**: `seg_bc_ms ≡ engine_ttft_ms` by construction (both measure `first_chunk_ns − pre_engine_ns`), so the classifier's `spread(seg_bc) / spread(engine_ttft) ≥ 0.80` attribution rule fires for *any* non-trivial chat_stream spread. The classifier-degeneracy issue ([PR #27 comment 4468600646](https://github.com/AncientStudying/vllm-grpc/pull/27#issuecomment-4468600646)) remains unresolved after M6.0a — it is out of M6.0a's scope (M6.0a is a dispatch correction, not a classifier redesign). **M6.1.1 Phase 2 stays pending until the checkpoint placement is revisited.**
- **M6 and M6.1 main verdicts are dispatch-robust.** M6's "4 of 6 cells overturned M5.2 under real engine" and M6.1's "engine-path equivalence" hold under both dispatch modes — they read aggregate per-cell timings, not per-cohort spread. The M6.1 per-cohort drift sub-finding (14-17% on chat_stream cells, originally flagged as `engine_cost_drift_warning`) is the one sub-finding that is dispatch-sensitive; its narrative now carries a forward cross-link to [§ M6.0a Methodology Supersedence](docs/benchmarks/m6_1-real-prompt-embeds.md#methodology-supersedence-m60a--dispatch-correction).
- **Wall-clock and cost.** Corrected re-run took 15.6 min wall-clock (~4.3 min cold-start + ~11.3 min for 18 cell × cohort pairs) at $0.29 Modal A10G `eu-west-1` — well under the M6.0a spec's SC-002 (≤ 45 min) and SC-006 (≤ $1) budgets.

**Caveats — kept prominent:**

- **The corrected-run JSON manifest carries a new top-level `dispatch_mode: "concurrent"` key** (strict-superset addition per FR-007; no `schema_version` bump). Pre-existing M6.1.1 / M6.2-aware readers ignore the unknown key; an absent `dispatch_mode` is read as `"sequential"`. The audit-baseline markdown does NOT receive a retroactive `dispatch_mode: "sequential"` annotation; it is preserved byte-identical to commit `b63947a` per FR-011, and the audit-callout header at the top of that file already documents the sequential-dispatch context.
- **No new M6.1.1 Phase 2 verdict.** M6.0a removes the dispatch-correctness ambiguity but does not close M6.1.1's Phase 2 — the classifier-degeneracy issue blocks a clean `channel_dependent_batching` verdict. Operators should treat the M6.1.1 Phase 1 classification as data, not as a Phase 2(b) action recommendation, until the checkpoint placement is revisited in a separate sub-milestone.
- **Two-PR sequence (FR-018), single-branch delivery in practice.** The original plan called for PR-1 (harness fix) to merge before PR-2 (corrected artifact + this note). In practice both PRs were committed to branch `024-m6-0a-concurrent-dispatch` and the operator deferred PR opening — the branch carries the complete M6.0a deliverable as commits `f3ad158` (PR-1 contents) plus the dispatch-correction note and FR-016 cross-link annotation as a follow-up commit.

**Cross-milestone notes**:

- **Dispatch-sensitive vs dispatch-robust finding classification.** See [`m6_0a-dispatch-correction.md § 5`](docs/benchmarks/m6_0a-dispatch-correction.md#5-implication-for-m6x-findings--dispatch-sensitive-vs-dispatch-robust) for the per-finding table. Short version: M6 main verdicts robust, M6.1 main verdicts robust, M6.1 per-cohort drift sub-finding sensitive (re-interpreted), M6.1.1 Phase 1 classification sensitive-but-degenerate (label survives, evidentiary weight does not).
- **Future M6.x sub-milestones inherit the corrected dispatch automatically.** M6.2 (`max_tokens` axis) reuses M6.1's measurement loop, which now uses the corrected dispatch unconditionally (no parallel-fork code path, no `--m6-sequential-dispatch` flag — per FR-005 the corrected harness is the only harness). M6.2's manifests will emit `dispatch_mode: "concurrent"` from the first run.
- **Lessons learned for future operators.** The FR-008 lockfile-parity command on macOS is `uv sync --frozen --all-groups` (not just `uv sync --frozen`); plain `--frozen` doesn't pull the `investigation` dependency group that supplies `transformers` and `vllm-metal`. This trap surfaced during the M6.0a re-run setup and is documented here so future re-runs (e.g., M6.2) don't repeat it.

---

## M6.1.2 — Methodology Discipline: Per-Sweep Topology Evidence + Restored `rest_plain_tcp` Cohort

**Status**: delivered 2026-05-17
**Report**: [`docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`](docs/benchmarks/m6_1_2-methodology-discipline.md)
**Schema doc**: [`contracts/instrumentation.md`](contracts/instrumentation.md)

Methodology-discipline bundle on top of M6.1.1: (1) per-sweep `tcptraceroute` topology probe with cohort-level CSP attribution (closed enum `AWS` / `Microsoft Azure` / `GCP` / `unknown` plus per-hop best-effort annotation), (2) reintroduces M5.2's `rest_plain_tcp` cohort to give the 4-cohort split that isolates protocol-only effects from multi-cloud-routing effects, (3) timestamped progress lines on stderr for long-sweep diagnosability. Harness-only — no engine, transport, or wire-format changes. The validation sweep at n=50 × the M6.1.1 6-cell matrix × 4 cohorts completed in 10.5 min wall-clock at ~$0.19 Modal A10G `eu-west-1`.

**Headline finding(s)**:

- **Per-sweep topology evidence overturns a static "Modal HTTPS edge → Azure West Europe" assumption that informed M5.2 / M6 / M6.1.** Spike #1 captured (2026-05-17 ~11 UTC) showed cohorts entering Modal via entirely different cloud providers (Microsoft Azure for `*.modal.run`; AWS us-west-1 for `*.modal.host`). The M6.1.2 PR-validation sweep captured 9 hours later (2026-05-17 ~20 UTC) found Modal had **consolidated all 4 cohorts into AWS us-east-1** (`rest_https_edge` → `98.92.241.71`, `rest_plain_tcp` → `100.26.248.115`, both gRPC cohorts → `13.220.63.3`). FR-006's cohort-CSP-mismatch warning fired loudly during the sweep, and the `network_paths` block records the observed reality faithfully. See [`docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md`](docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md) for the spike's earlier traceroute proof and [`docs/benchmarks/m6_1_2-methodology-discipline.json`](docs/benchmarks/m6_1_2-methodology-discipline.json) for the per-sweep evidence the M6.1.2 artifact ships with every run.
- **The "HTTPS edge wins" finding from M5.2 / M6 / M6.1 is re-classified as a multi-cloud-routing artifact, not a protocol effect.** Under the spike-era topology, `rest_https_edge` (Azure anycast, TLS-terminated near client) raced against `default_grpc` / `tuned_grpc_multiplexed` (raw TCP into AWS us-west-1) — two cohorts that differed on protocol AND CSP AND region AND TLS-vs-plaintext simultaneously. M6.1.2's `rest_plain_tcp` cohort is the protocol-only control: REST over the same raw-TCP transport as gRPC. With all 4 cohorts now in AWS us-east-1, the protocol-only differential for embed cells is **gRPC faster by ~50-100 ms per RPC** (rest_plain_tcp 542 / 669 / 766 ms vs default_grpc 465 / 574 / 712 ms across c=1 / 4 / 8). The M5.2 / M6 cells where rest_https_edge appeared to win were measuring the Azure-anycast-vs-AWS-region routing advantage, not a wire-protocol property. Operators rendering M5.2 / M6 findings should add the caveat "applicable only to the multi-CSP Modal topology that existed prior to 2026-05-17 consolidation"; the topology guide below remains valid for that earlier topology.
- **chat_stream cells show no measurable protocol differential at any tested concurrency.** Wall-clock means at c=1 / c=4 / c=8: default_grpc 1810 / 1938 / 1969 ms, rest_https_edge 1781 / 1923 / 1952 ms, rest_plain_tcp 1804 / 1941 / 1972 ms — all within ~5 ms of each other. Engine generation (50 tokens × ~30 ms/token ≈ 1500 ms) dominates the ~50-100 ms wire-protocol overhead seen on embed cells. **chat_stream is not a useful discriminator for protocol cost; embed cells are.** This validates M6's design decision to include embed cells alongside chat_stream.
- **`tuned_grpc_multiplexed` shows a c=8 anomaly on embed (1068 ms vs 712 ms for default_grpc at the same cell).** The 16-MiB channel config that wins at c=1/c=4 (tightest CIs in M5/M6/M6.1) inverts at c=8. Likely cause: larger flow-control windows interact poorly with the engine's continuous-batching arbiter at higher concurrency. Worth investigating in a follow-up but not a methodology blocker — M6.1.2 publishes the observation faithfully.
- **Probe runs in parallel across cohorts with a 30 s per-cohort wall-clock budget**, scoped via `asyncio.gather` + `asyncio.to_thread`. Real-world probe wall-clock on this sweep was 23 sec total (4 cohorts in parallel). Probe failure NEVER aborts the sweep (FR-005 / FR-005a) — per-cohort errors are recorded as `M6_1_2NetworkPathError` entries in `network_paths` with a discriminator `error` field, and an all-cohort-failed event triggers a loud stderr warning at sweep start.

**Caveats — kept prominent:**

- **Modal infrastructure is volatile.** The 9-hour drift between spike (2026-05-17 ~11 UTC) and validation sweep (~20 UTC) collapsed a documented multi-CSP topology into a single-region one. The M6.1.2 artifact records the observed topology faithfully via `network_paths`, but operators reproducing this sweep at a different date may observe a different topology entirely. **Always read the `network_paths` block in the actual artifact you're consuming; never assume the spike's or M6.1.2 baseline's topology.** This is exactly the methodology-discipline gap M6.1.2 closes: prior milestones documented a static assumption about Modal routing; M6.1.2 captures it per-sweep.
- **CSP attribution for the `cloud_provider` field is best-effort and may be ambiguous for transit hops.** Cohort-level attribution uses AWS / Azure / GCP published IP-range JSON (24h cache) with an ARIN whois fallback that follows RIR referrals (RIPE / APNIC / AFRINIC / LACNIC) for non-ARIN-owned blocks. The per-hop annotation field additionally accepts transit-ASN strings (e.g., `"Telia"`) for hops that don't resolve to a CSP. The closed enum applies only at the cohort level.
- **Cell-by-cell comparability with M6.1.1's published baseline is preserved (FR-024).** M6.1.2 uses the identical M6.1 RPC drivers (`_drive_grpc_embed_m6_1`, `_drive_grpc_chat_stream`, `_drive_rest_embed_m6_1`, `_drive_rest_chat_stream`) and the same seq_len pinning (`pin_seq_len_at_sweep_start` → 19 tokens for Qwen3-8B) so the embed payload is ~157 KB — same wire shape as M6.1.1. The new `rest_plain_tcp` cohort uses the existing REST shim path with a plain-HTTP base URL pointing at Modal's `modal.forward(unencrypted=True)` tunnel; no new server code.
- **Two iteration-order properties are belt-and-suspenders defenses against Modal tunnel idle timeouts**: (1) `cohorts_at_concurrency` dispatches gRPC cohorts FIRST within each cell so the gRPC tunnel sees traffic before the longer REST phases; (2) the wire-format `cohort_set` field is sorted alphabetically (separate from iteration order) so downstream reader-script stability holds independent of iteration changes. An earlier attempt to add 60 s client-side keepalive to the gRPC channels failed in live testing — Modal's gRPC frontend rejected the pings with `ENHANCE_YOUR_CALM: too_many_pings` GOAWAY frames. The cohort reorder + the gRPC server's tolerance of ~10 min idle (empirically established by M6.1.1 working under the same pattern) is the workable defense.

**Cross-milestone notes**:

- **M6.1.2 ships a strict-superset JSON schema addition** (`network_paths`, `cohort_set`, `cohort_omissions` — all top-level keys; no `schema_version` bump) per the same FR-007 precedent M6.0a established for `dispatch_mode`. M6.1.1-aware readers (and M6.2-to-be) parse M6.1.2 artifacts unchanged, ignoring the new keys. See [`contracts/instrumentation.md`](contracts/instrumentation.md) for the schema reference; [`specs/025-m6-1-2-methodology-discipline/contracts/{network-paths,artifact-schema}.md`](specs/025-m6-1-2-methodology-discipline/contracts/) for the design contracts.
- **Topology guide framing is preserved AND made conditional.** The M5.1 (same-fabric) vs M5.2 (managed-edge) framing remains the right reading for those milestones' historical results AND for any future deploy where the assumed topology actually holds. M6.1.2 doesn't invalidate the guide — it adds an empirical check: read `network_paths` from your actual sweep artifact and confirm the topology matches the milestone's expected shape before applying the verdict. When topology drifts (as it did 2026-05-17), the older verdict is data about a topology that no longer exists, not a blanket statement about the protocols.
- **M6.2 / M7 / M8 inherit the per-sweep evidence pattern automatically.** Future milestones reuse the M6.1.2 `network_paths` probe + 4-cohort iteration + `cohort_set` / `cohort_omissions` machinery; their artifacts will carry the topology evidence by default. Operator-visible: `network_paths.<cohort>.cloud_provider` is the authoritative answer to "which CSP did this cohort talk to during this sweep" — no need to re-derive from URL strings or external assumption.
- **The protocol-only differential (rest_plain_tcp − default_grpc) is now the canonical protocol-cost measurement.** It supersedes the M5.2 / M6 / M6.1 implicit protocol comparisons that conflated wire-protocol with cloud-routing. The multi-cloud-routing differential (rest_plain_tcp − rest_https_edge) is **zero in the current topology** but the methodology to measure it stays in the harness for future topologies where Modal might re-introduce multi-CSP routing.

---

## M6.1.3 — Phase 1 Attribution Closure: Proxy-Edge Probes + Per-Cohort Audit + Multi-Run Variance

**Status**: delivered 2026-05-19 ([PR #31](https://github.com/AncientStudying/vllm-grpc/pull/31))
**Report**: [`docs/benchmarks/m6_1_3-attribution-closure.{md,json}`](docs/benchmarks/m6_1_3-attribution-closure.md) (canonical 5-run publish artifact) + [`docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}`](docs/benchmarks/m6_1_3-attribution-closure-validate.md) (single-run validate sibling)
**Schema doc**: [`contracts/instrumentation.md`](contracts/instrumentation.md) (M6.1.3 vocabulary: `between_run_variance`, `inconclusive_high_variance`, `proxy_ingress_dominated` / `proxy_egress_dominated`, compound-label scheme, audit section)

Bundle that closes M6.1.1's open Phase 2 attribution gap with three additions in a single 5-run multi-sweep: (1) **proxy-edge probes** — two new wire keys (`m6_1_1_t_pre_engine_wall_ns` + `m6_1_1_t_first_chunk_mono_ns`) bracket the asyncio handoff between the in-process frontend servicer and vLLM, deriving `seg_ingress_ms` (wall-clock-anchored) and `seg_egress_ms` (monotonic-anchored) per RPC; classifier extends from 5-bucket to 7-bucket with `proxy_ingress_dominated` / `proxy_egress_dominated` labels. (2) **per-cohort prompt-content audit** — tokenized prompt length + BLAKE2b-8 hash on the wire, lets a pooled-distribution H1/H2/rejection verdict distinguish prompt-content drift from KV-cache / encoding / warmup hypotheses. (3) **multi-run sweep + between-run variance compute** — `--m6_1_3-diagnose-repeat=N` runs Phase 1 N times back-to-back; reporter renders a "Between-Run Variance" section; classifier upgrades cells to `inconclusive_high_variance` when between-run stddev exceeds within-run CI half-width per a unified threshold (one knob fires both FR-026's inner override and FR-043's Phase B publication requirement). The publish sweep at `repeat=5, n=50, 4-cohort, full M6.1.1 6-cell matrix` completed in 57.7 min wall-clock at ~$1.45 Modal A10G `eu-west-1`; the preceding validate-sibling sweep cost ~$0.29. Phase B (n=200 power test, conditional per the high-variance trigger) did not fire.

**Headline finding(s)**:

- **H1 confirmed at every chat_stream cell — prompt-content asymmetry is real and quantifiable.** The pooled-distribution audit (pooled n = 5 × 50 = 250 per cohort) shows gRPC paths emit 36.88-token prompts vs REST paths' 28.88-token prompts at every chat_stream cell — an 8-token chat-template padding gap. The gRPC frontend applies the chat template through its own path; the REST shim reaches the OpenAI-compat handler differently and the template tokenizes with 8 fewer tokens. Embed cells: H1 rejected (uniform 19 tokens, no chat template). This is the root cause M6.1.1 could not name: `seg_prefill` differences across cohorts at chat_stream were partially driven by gRPC carrying 8 more tokens to prefill, not by an engine-side bucketing effect. **FR-017 recommendation fires: symmetric prompts SHOULD become the M6.x convention going forward** (the `--m6_1_3-symmetric-prompts` flag wires the cross-milestone helper at `tools/benchmark/src/vllm_grpc_bench/symmetric_prompts.py`).
- **Phase B (n=200 power test) NOT required.** No cell carries `inconclusive_high_variance`. Between-run stddev sits well under within-run CI half-width on every healthy cell × cohort. Concrete bounds at chat_stream: c=1 between-run stddev 0.16–1.49 ms vs ~44 ms means (0.4–3.4% noise floor); c=4 between-run stddev 1.28–3.20 ms vs ~88 ms means (1.5–3.6%); c=8 between-run stddev 1.60–4.51 ms vs ~93 ms means (1.7–4.8%). M6.1.1's headline "variance dominates attribution at c=4" concern from spike #5 weakens at the larger pooled n — V2 (run-state) variance is bounded and small at this sample size.
- **Classifier returns `inconclusive` at every chat_stream cell — multi-factor offsetting, not high variance.** The 7-bucket classifier finds no single segment carries ≥40% of the per-cohort spread at any cell. Reading the per-segment data for chat_stream c=1 (3.48 ms total gRPC-vs-REST drift): `seg_prefill` is +5.3 ms gRPC-slower (consistent with the H1 audit finding — gRPC's 8 extra prompt tokens prefill slower), `seg_egress` is -3.5 ms gRPC-faster (REST's HTTPS edge eats ~4 ms vs gRPC's bare trailers). The two segments cancel at the cell level; the dominance check legitimately fails. Compound-label tie-breaking didn't fire either (no two-segment pair near the threshold). This is a defensible attribution outcome that the audit explains directly — the unattributed budget is now bisected into per-segment contributions even when the cell-level verdict reads "multi-factor."
- **SC-013 dual-gate PASS at 0.0%.** The FR-006 negative-value assertion (`seg_ingress_ms < 0` or `seg_egress_ms < 0` indicates a wall↔monotonic clock-source mismatch) never fired across ~5500 RPCs on the publish sweep (worst `clock_anomaly_fraction = 0.0` across all 11 chat_stream rows). The proxy-edge derivation is clock-safe under healthy conditions, validating the spike-era assumption that vLLM's in-process `time.monotonic_ns()` reading and the frontend's `time.monotonic_ns()` reading are directly comparable.
- **Modal cost ~$1.74 vs $6.05 hard cap (71% headroom).** Validate sweep ~$0.29 + publish sweep ~$1.45 + Phase B $0.00 (skipped). The full experimental matrix (Phase A + B) was budgeted at ~$2.90; Phase B not firing keeps actual spend at $1.74 with substantial headroom for any future re-run.

**Caveats — kept prominent:**

- **SC-003 "partially satisfied."** The spec called for M6.1.1's two `inconclusive` cells at c=4 / c=8 to either re-classify under the 7-bucket extension OR receive `inconclusive_high_variance`. M6.1.3 produced plain `inconclusive` at all six cells (including c=1, which the validate-sibling artifact had labeled `engine_compute_variation` — the multi-run mean-of-means shifted the cell-level spread under the dominance threshold). This is a defensible third outcome that the FR-016 audit verdict explains as multi-factor offsetting, not a defect — but readers comparing M6.1.3 against M6.1.1 should not expect "all cells now attributable" in the single-bucket sense.
- **The 8-token chat-template asymmetry is a latent M5.2 / M6 / M6.1 / M6.1.1 confound.** M5.2 carried symmetric prompts via the explicit gRPC/REST prompt-pair helper; M6 onward dropped that convention because the helper wasn't ported to the new harness loop. M6.1.3's audit retroactively confirms the M6.1.1 c=1 `engine_compute_variation` verdict was partially load-bearing on this asymmetry — the FR-017 recommendation tells future M6.x milestones to flip `--m6_1_3-symmetric-prompts` on by default OR document an explicit deviation. M6.2 / M7 / M8 spec authors MUST cite this recommendation as a precondition per SC-012.
- **The `rest_https_edge` topology drifted to `unknown` on both validate and publish sweeps.** The FR-006 (inherited from M6.1.2) cohort-CSP attribution could not resolve the edge IP (130.61.32.116 on the publish sweep) into AWS / Azure / GCP — likely because Modal's HTTPS-edge IP sits in a transit AS that doesn't fall in the published cloud IP ranges. The probe reports `unknown` faithfully and the warning fires; methodology-significant but not a blocker since the cohort itself runs cleanly. M6.1.2's `network_paths` block records the observed reality for future operators.
- **H1-confirmed-across-all-cells is a verdict ABOUT the audit instrumentation, not necessarily ABOUT cohort discrimination.** The 8-token gap is the same across every chat_stream cell (it's a template-tokenization property, not an engine state). This is exactly what the audit was designed to catch — the test isn't "did cohorts behave differently" but "were cohorts sent comparable inputs." H1 saying "no, inputs differed" is the signal that supports running symmetric-prompt re-validation in a future milestone, not necessarily a re-interpretation of any specific cell's verdict beyond what the per-segment data already shows.
- **2 RPC failures out of ~5500 attempts (~0.036%, well under the 0.5% SC-013 tolerance).** Both failures: `RemoteProtocolError: Server disconnected without sending a response` on `rest_plain_tcp` chat_stream — known transient REST upstream pattern from earlier sweeps; not a regression and not material to the verdicts.

**Cross-milestone notes**:

- **M6.1.1's c=4 / c=8 "unattributed budget" is now bisected into per-segment contributions per FR-031 + FR-041.** A leading-note annotation prepended to [`docs/benchmarks/m6_1_1-engine-cost-instrumentation.md`](docs/benchmarks/m6_1_1-engine-cost-instrumentation.md) forwards readers to M6.1.3 for the attributed labels and variance characterization. The bidirectional cross-reference: M6.1.1's verdicts are not retroactively rewritten; M6.1.3 publishes the deeper breakdown. Readers wanting the engine-internal split (`seg_queue`, `seg_prefill`) consult M6.1.1's report; readers wanting the proxy-edge split (`seg_ingress`, `seg_egress`) consult M6.1.3's.
- **Strict-superset schema evolution under `m6_1_1.v1`** (no version bump per FR-010 + round-3 Q1). M6.1.3 adds: 4 new wire keys (`pre_engine_wall_ns`, `first_chunk_mono_ns`, `tokenized_prompt_length`, `tokenized_prompt_hash`), 2 new derived per-segment fields (`seg_ingress_ms`, `seg_egress_ms`), the 7-bucket classifier labels, compound-label scheme, `inconclusive_high_variance` outer override, `between_run_variance` top-level block, and the per-cohort audit section. M6.1.1-aware readers parse M6.1.3 artifacts unchanged, ignoring the unknown keys; M6.1.2-aware readers see the topology probe + 4-cohort iteration the same way they did at M6.1.2.
- **Three-path artifact publishing per FR-038 + R-7.** Canonical at `docs/benchmarks/m6_1_3-attribution-closure.{md,json}` (the 5-run publish); validate sibling at `-validate.{md,json}` (single-run smoke-equivalent); Phase B sibling at `-phase-b.{md,json}` (conditional, NOT produced this milestone). Each artifact has a clear purpose and there is no clobber risk between operator invocations.
- **M6.2 / M7 / M8 inheritance.** M6.1.3's `symmetric_prompts` helper module is the canonical cross-milestone shared helper for prompt-symmetry per FR-019. Future milestones either flip the `-symmetric-prompts` flag on by default (per FR-017's recommendation) or document an explicit deviation. M6.1.2's per-sweep topology evidence machinery (`network_paths`) carries forward unchanged into M6.1.3's artifacts and into M6.2+.
- **M6.0a's classifier-degeneracy issue is now fully closed.** M6.0a flagged that M6.1.1's original FR-010 classifier was degenerate (`seg_bc_ms ≡ engine_ttft_ms` by construction). M6.1.1's in-branch upgrade resolved that with the 5-bucket scheme; M6.1.3's 7-bucket extension + compound-label vocabulary (`multi_factor_<a>_<b>` with 5pp dominance margin) + `inconclusive_high_variance` outer override completes the classifier work. The classifier is now mechanistic across the full chat_stream segment chain (handler entry → pre-engine wall → engine arrival → engine queued → engine scheduled → engine first token → first chunk monotonic → terminal emit).

---

## M6.2 — Token-Budget Characterization (`max_tokens` axis)

**Status**: delivered 2026-05-26 (publish sweep on branch `027-m6-2-token-budget`, git_sha `82bd55a`)
**Report**: [`docs/benchmarks/m6_2-token-budget.{md,json}`](docs/benchmarks/m6_2-token-budget.md) (canonical n=40 publish artifact, 132 main-sweep + 16 KV-pressure sub-probe blocks) + [`docs/benchmarks/m6_2-token-budget-validate.{md,json}`](docs/benchmarks/m6_2-token-budget-validate.md) (validate sibling on 3-point axis subset)
**Working notes**: [`M6_2-ANALYSIS-FRAMING-DRAFT.md`](M6_2-ANALYSIS-FRAMING-DRAFT.md) (per-claim n=40 verification of the topology framing finalized here)

Sweeps the `max_tokens ∈ {10, 50, 256, 512, 1024, 2048}` axis under the M6.1.1 6-cell × 4-cohort matrix at `n=40` per-block (publish), measuring `wall_p50` / `wall_p95` / TPOT / 5-segment decomposition at every (cell, cohort, max_tokens) tuple. Three-regime prompt sourcing per FR-034 / FR-035 (synthetic seed-derived at null anchors `{10, 50}` to preserve M6.1.3 cross-baseline comparison; ShareGPT corpus + Qwen3-8B prompt-embeddings at interior caps for production-realistic distributions). A dedicated KV-pressure sub-probe per FR-036 / FR-017a runs after the main sweep: 16 blocks (4 cohorts × 2 cell-types × 2 caps `{1024, 2048}`) at `n=20` with `ignore_eos=True`, computing the wall-clock-ratio inference `R = wall_p50(c=8, 2048) / wall_p50(c=8, 1024)` per cohort × cell-type against a 2.2 threshold (a 10% margin above the linear ~2.0 expectation under forced-cap generation). Total publish wall-clock 14.5 h across two processes (see preemption caveat below); Modal `eu-west-1` A10G.

**Headline finding(s)**:

- **M5.2 / M6 / M6.1's "HTTPS-edge wins" managed-edge framing is reinforced and enlarged at the `max_tokens` anchor.** Single-prompt cross-cohort comparison at `chat_stream_c1 × max_tokens=10` (synthetic seed-derived prompt, the cleanest apples-to-apples cell in the artifact): `rest_https_edge` p50 = 488.5 ms (CI ±17.2) vs `default_grpc` 611.9 ms (CI ±3.9) and `rest_plain_tcp` 614.6 ms (CI ±12.5). REST-edge is **25–26% faster** than both gRPC and plain REST at the anchor — up from the validate sweep's ~12% gap. The advantage is product-attributable (Modal's edge POP terminates HTTP/2 + TLS near the client, amortising handshake + framing costs); it isn't available outside managed-provider topologies.
- **Self-hosted / no-edge topology: gRPC's wire-transmission advantage is consistent across the full `max_tokens` axis.** `seg_egress_ms` (engine → client wire transmission, the surface most directly sensitive to wire-level efficiency) shows gRPC ahead of `rest_plain_tcp` in **9 of 9 chat_stream cells** sampled across the full axis: +9.5% to +55.2% gRPC advantage (largest gap at `c4×10`). The validate-sweep's lone counterexample (`c1×50`, −9%) sign-flipped to +12.5% under the tighter n=40 CI — bootstrap noise on n=20, exactly as that sweep's caveat anticipated. The story is "consistent +20–55% gRPC wire-transmission advantage across the matrix", not "doubling at any specific cell."
- **Wall-clock advantage concentrates at `c=8` and grew substantially under n=40.** `tuned_grpc_multiplexed` vs `rest_plain_tcp` at `chat_stream_c8 × max_tokens=10`: **+15.6%** (up from validate's +5.1%); at `c8×50`: +3.3%. `default_grpc` vs `rest_plain_tcp` at `c8×10`: +10.6%; at `c8×50`: +3.5%. At `c=1` cells the protocols are statistically indistinguishable (~0% wall-clock gap) — consistent with HTTP/2 multiplexing benefiting only concurrent streams. At `c=4` the picture is noisier (default-gRPC and tuned-mux disagree on direction at `c4×10`), but the `c=8` conclusion is the load-bearing claim and the tighter n=40 CI strengthened rather than washed it out.
- **TPOT (per-token decode cost) is gRPC-cleaner only at the long-generation high-concurrency cell.** `chat_stream_c8 × max_tokens=2048`: gRPC 37.43 ms/token vs plain REST 39.55 ms/token, a **+5.7% REST overhead** (up from validate's +4.0%). Elsewhere TPOT sits within ±1% across cohorts — too tight to claim a winner. The TPOT signal is the cleanest long-generation throughput measurement the artifact produces.
- **KV-pressure characterization (Story 3, FR-017a sub-probe at `c=8 × {1024, 2048}` × `ignore_eos=True` × n=20): no cohort × cell-type combination reaches the threshold.** All 8 ratios cluster around the linear ~2.0 expectation (chat_stream 1.81–2.02; embed 1.98–2.05); every cohort × cell-type classifies as `kv_pressure_not_observable` under the 2.2 threshold. `oom_observed = false` for every sub-probe block. **Qwen3-8B at `c=8 × max_tokens=2048` has half-headroom on the engine ceiling and is not KV-pressured at this configuration.** Downstream consumer: M8 inherits this number as a single load-bearing data point for KV-budget sizing on this model.
- **The bytes-axis finding from M1 remains the topology-immune protocol claim.** M6.2 measures latency, not bytes. The `seg_egress_ms` segment is the cleanest proxy for wire-level protocol efficiency the harness produces, but it isn't a direct byte count. ANALYSIS.md should pair M6.2's wire-time results with M1's chat response −89% / embed request −25% byte savings when stating the gRPC-wins-on-wire claim — they corroborate each other on independent surfaces.

**Caveats — kept prominent:**

- **DO NOT cite the headline wall_p50 numbers at `max_tokens=2048` as a protocol win — they are overwhelmingly prompt-content-driven.** The wall_p50 row at `chat_stream_c8 × 2048` reads `default_grpc=5,103 ms` vs the other three cohorts at ~80,000 ms — a 16× gap. The cause is iter-idx-keyed corpus-prompt selection drawing a short-completion prompt for one cohort that hits natural EOS at a few hundred tokens. TPOT and `seg_egress` (the per-token-normalised surfaces) cluster within ~6% across all four cohorts at this cell — the clean signal. The artifact's auto-emitted `## Prompt-driven early-EOS audit` section names the affected cells; ANALYSIS.md cites only the per-token-normalised surfaces (TPOT, `seg_egress`, anchor) for the topology recommendation.
- **FR-012 null-anchor drift FAIL at `chat_stream_c1 / rest_plain_tcp / max_tokens=50` and `chat_stream_c4 / rest_plain_tcp / max_tokens=50` — documented baseline-data-quality issue, not an M6.2 regression.** The drift check compares M6.2 p50 against M6.1.3 mean (M6.1.3 didn't publish per-cohort p50). M6.1.3's `rest_plain_tcp` baselines at c1/c4 sit 300–800 ms above their sibling-cohort means at the same concurrency (no such anomaly at c8 where the cohort matches its peers). The smoking gun: M6.1.3's `chat_stream_c4 / rest_plain_tcp` was specifically computed from `n_successes=49/50` — the lone sub-50 cell in the entire M6.1.3 chat_stream matrix, consistent with mean-inflation by a slow-tail or dropped outlier RPC. M6.2's `rest_plain_tcp` measurements are internally consistent (CI 12–30 ms, per-concurrency cohort spread ≤140 ms across all four cohorts). The integrity warning `null_anchor_drift` fires correctly under the FR-012 audit machinery, but the FAIL is a baseline artifact, not a regression in M6.2's rest_plain_tcp path.
- **Preemption recovery happened mid-sweep; `run_meta.preemption_events` reads `0` but is incorrect.** The original sweep process crossed Modal's 12-h per-input timeout at hour 12.1 (`Task's current input hit its timeout of 43200s`), killing 5 measurement blocks (108–112) on the chat_stream c4/c8 tuples. The orchestrator's `make_driver()` refresh exhausted its 10-min refresh timeout and the per-block wrapper mis-classified `PreemptionRecoveryFailed` as `unexpected_PreemptionRecoveryFailed` (root cause: `m6_2_sweep.py:316` `except BaseException` swallows the recovery-fatal exception — filed as M6.2.x follow-up). Operator intervention (`SIGINT` → strip failed checkpoint rows → `--m6_2-resume`) reseated the sweep on a fresh Modal worker that re-measured all 5 cells cleanly. **The true value across both processes is ≥2 detected preemption events + 5 collateral block failures, all recovered.** Within-tuple temporal locality is broken for blocks 108–112 (re-measured ~3–12 h after their original sweep-window siblings); the measurements themselves are clean.
- **Anchor-trajectory snapshots insufficient (`trajectory_insufficient_snapshots` integrity warning).** Only 2 anchor snapshots per cohort (sweep start + t=8 h) reached the checkpoint. The 4-h / 12-h / sweep-end cadence anchors didn't fire — long inner-loop tuples (`embed_c1 × 2048` at 134 min; `chat_stream_c1 × 1024` at 70 min) pushed cadence checks past their windows, and the resume process didn't re-fire an end-of-sweep anchor in its 1-h working window. Filed as M6.2.x follow-up. Does not affect the topology framing above — the FR-031 trajectory is a diagnostic surface, and the underlying budget-table measurements are independently captured.
- **Modal `eu-west-1` absolute-latency drift between validate and publish runs (~17–32%) without reordering cohorts.** Anchor `chat_stream_c1 × max_tokens=10` moved from validate's 416 ms (`rest_https_edge`) / 467 ms (`rest_plain_tcp`) to publish's 488.5 ms / 614.6 ms across one day of wall-clock. Cohort ratios and percent gaps (the durable signal) held; absolute values shifted by Modal-environment variability. **Treat the relative claims above as the milestone's verdict; treat absolute numbers as point-in-time on `eu-west-1` during 2026-05-25/26.** Region-sensitivity of the REST-edge advantage is unmeasured here (`eu-west-1` only).

**Cross-milestone notes**:

- **M6.2 reinforces both audiences of the M5.1 / M5.2 split, not just one.** Managed-edge (M5.2 audience): the HTTPS-edge advantage grew from M5.2's modest win + M6.1's confirmation to **+25–26% over the next-fastest cohort at the anchor**; same-fabric (M5.1 audience): the gRPC `c=8` advantage at `chat_stream_c8 × 10` is **+15.6% (tuned-gRPC over plain REST)**, larger than the M5.1-era validate read. The topology framing the project has carried since M5.1 / M5.2 is not weakened by the `max_tokens`-axis sweep — it's confirmed under tighter CI and across a wider operating envelope.
- **Strict-superset schema additivity under `m6_1_1.v1`** (no version bump per FR-011, mirrors M6.1.2 / M6.1.3 precedent). M6.2 adds top-level `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation` keys + per-row `prompt_source`, `measurement_regime`, `prompt_corpus_idx`, `block_start_utc`, `block_end_utc`, `retry_attempted` fields. M6.1.x-aware readers parse M6.2 artifacts unchanged, ignoring the new keys. M6.1.2's `network_paths` block + 4-cohort iteration machinery carries forward; M6.1.3's `symmetric_prompts` helper is used for cohort-symmetric corpus selection at interior caps per FR-019.
- **`protocol_crossover` returns `inconclusive` for every cell** because M6.1.3's per-cell `base_verdict` was `inconclusive` (multi-factor offsetting, per M6.1.3's headline finding). M6.2's reporter correctly emits `crossover_evidence = "base verdict was already inconclusive at the M6.1.3 baseline"` for all six cells. This is inherited from M6.1.3's verdict structure, not a new M6.2 finding — the cohort comparison the crossover analysis would require can't be computed from an inconclusive base.
- **M8 inheritance — KV-budget sizing input.** The KV-pressure observation (`wall_clock_ratio_c8_2048_over_1024 ≈ 1.8–2.0` across all cohorts × cell-types; `kv_pressure_not_observable` verdict everywhere) is the single load-bearing data point M8 inherits from M6.2 for KV-cache budget calibration on Qwen3-8B. M8 will revisit at larger context windows; the M6.2 result fixes the `max_model_len=2048` ceiling characterization. No upstream vLLM contributions or engine-config probes required (per FR-040); the wall-clock ratio is the canonical surface.
- **Four M6.2.x follow-ups filed.** (1) `m6_2_sweep.py:316` `except BaseException` swallows `PreemptionRecoveryFailed` (rc=7 abort path unreachable) + `KeyboardInterrupt` (operator SIGINT looks like a transient block failure). (2) Resume process loses prior `preemption_events_total` from the original run; artifact's `run_meta.preemption_events` undercounts. (3) Anchor-cadence machinery doesn't fire when inner-loop tuples exceed the cadence window. (4) Resume process doesn't re-fire the sweep-end anchor in its working window. None block the milestone — all surfaced as integrity warnings in the artifact and documented above.

---

## Topology guide — which milestone result applies to your deployment

The M5.1 and M5.2 findings are not redundant and neither supersedes the other. They measure two **different and equally valid deployment topologies**. Pick the milestone whose topology matches your deployment shape; both audiences are first-class. M6.2 (`max_tokens`-axis publish, n=40) verified both audiences' verdicts under tighter CI and across the full `max_tokens` axis — both directions strengthened.

| Topology | Audience | Recommendation | Primary milestone | Confirmed / strengthened by |
|---|---|---|---|---|
| Client ↔ managed-provider with anycast HTTPS edge | Hobbyist or enterprise tenant on Modal / RunPod / Replicate / similar | **Use REST over the HTTPS edge.** The edge POP terminates HTTP/2 + TLS near the client, amortising handshake + framing costs end-to-end protocols can't avoid. The advantage holds across the `max_tokens` axis. | **M5.2** — HTTPS-edge wins broadly | **M6.2** widens the gap to ~25–26% at the anchor under n=40 (validate read was ~12%); **M6** confirms the verdict survives real engine cost |
| Client + server inside the same enterprise network | Corporate-internal deployments, well-connected colo, datacenter | **Use gRPC for `c≥4` workloads.** Wire-transmission cost is 10–55% lower than plain REST across the matrix; wall-clock advantage at `c=8` is +10–16%. At `c=1` the protocols are statistically indistinguishable — choose on operational simplicity. | **M5.1** — same-fabric protocol-cost ranking | **M6.2** strengthens the `c=8` wall-clock advantage to +15.6% (validate read +5.1%); **M1** bytes-axis +89% / +25% savings remain topology-immune |
| Hobbyist self-hosting | DIY / homelab on LAN, single-host or LAN-local | Same as same-fabric — **gRPC for `c≥4`**. No managed edge available to flip the verdict. | **M5.1** — same fabric | **M6.2** under tighter n=40 CI |
| Enterprise with internal anycast / edge infrastructure | Global SaaS fronting REST with their own edge layer | Same as managed-provider — **use REST through the edge layer**. Same dynamics as a managed edge POP. | **M5.2** — internal-edge equivalent | **M6.2** confirms the anchor-level edge advantage is robust across `max_tokens` |

**Bytes-axis findings from § M1 are topology-immune** — protobuf vs JSON encoding wins (chat response −89%, embed request −25%) apply to every deployment shape. The topology matters only for the time-axis verdicts (latency, TTFT, wall-clock).

**Three practical reads of the same matrix:**

- **The same-fabric reader (M5.1 + M6.2):** gRPC wins embed broadly; REST wins chat_stream at c≥4 under MockEngine, BUT real engine cost (M6) reclaims chat_stream for gRPC, AND M6.2's `max_tokens`-axis sweep at n=40 confirms a consistent +10–55% gRPC wire-transmission advantage and a +15.6% gRPC wall-clock advantage at `c8×10` (tuned-gRPC vs plain REST). Pick gRPC for any `c≥4` workload; at `c=1` choose on operational simplicity since the protocols tie.
- **The managed-edge reader (M5.2 + M6.2):** gRPC wins embed at c=1; HTTPS-edge REST wins everything at c=4 / c=8 under MockEngine; **M6 corrects this read under real engine cost** — for Qwen3-8B at h=4096 on A10G, gRPC reclaims all four c≥4 cells M5.2 awarded to REST. **M6.2 then re-confirms HTTPS-edge as the headline win at the anchor**: 488.5 ms vs 611.9 ms gRPC vs 614.6 ms plain REST (a 25–26% edge advantage at `c1×10`). Managed-edge tenants serving real models should reach for HTTPS-edge first; gRPC is the backup if the edge product isn't available.
- **The engine-cost reader (M6 + M6.2 KV-pressure sub-probe):** M5.1 / M5.2 verdicts reflect protocol cost with engine cost held neutral. M6 establishes that real-engine cost reshapes the protocol verdict at c≥4 for Qwen3-8B at h=4096 on A10G. **M6.2's KV-pressure sub-probe characterises the engine's behaviour at the `max_model_len=2048` ceiling**: wall-clock ratio `wall_p50(c=8, 2048) / wall_p50(c=8, 1024) ≈ 1.8–2.0` across all cohorts × cell-types, well below the 2.2 threshold — Qwen3-8B at `c=8 × max_tokens=2048` is not KV-pressured at this configuration. Readers serving a different model family, hidden_size, or context window should treat M5.1 / M5.2 verdicts at c≥4 as a transport-only ranking and consult M6's per-cohort engine_cost numbers + M6.2's per-cap `wall_p50` / TPOT in `docs/benchmarks/m6-real-engine-mini-validation.md` and `docs/benchmarks/m6_2-token-budget.md` before generalising.

---

## Repo housekeeping

The repository maintains two parallel tag tracks:

- **`milestone/*` — research deliverables.** One tag per closed milestone (M2 through M6.2 as of 2026-05-26). Each tag fixes the working tree at the commit that publishes the milestone's report + sweep harness, so any pre-cleanup historical artifact (benchmark report, sweep script, era-specific integration test) is recoverable by checking out the matching tag.
- **`v*` — codebase state.** Semver-style tags (`v0.0.0`, `v0.0.1`, `v0.1.0`, …) mark maintenance and release-readiness checkpoints. `v0.0.0` marks the post-M6.2 cleanup that removed pre-M6.2 milestone-specific `.md` writeups + obsolete tests + scripts from `main`; the 9 baseline-chain JSON data files (M3→M6.2) stay tracked because the sweep harness reads them at runtime via default-path constants in `tools/benchmark/src/`.

To recover a deleted historical narrative:

    git show milestone/m5.2-transport-tuning:docs/benchmarks/m5_2-transport-vs-tuning.md

Replace `milestone/m5.2-transport-tuning` with the milestone tag whose era owns the file, and the path with the file you want. `git tag --list 'milestone/*'` lists every available tag.

### Bench-harness refactor (v0.0.1)

After M6.2 closed, the `tools/benchmark/` harness still carried every milestone's
sweep code side-by-side — 84 source modules and 137 test files, most named by
milestone (`m3_*`, `m4_*`, `m5_2_*`, `m6_1_3_*`, `m6_2_*`, …). v0.0.1 refactored
the live tree into a **forward-only codebase organized by function, not by
milestone**: generic homes (`types.py`, `prompts.py`, `timing.py`,
`exceptions.py`), one `reporter.py`, and de-prefixed sweep/driver/validate modules
(`sweep.py`, `rpc_driver.py`, `validate.py`, `resume.py`, `crossover.py`,
`null_anchor.py`, `anchor_trajectory.py`, `sub_probe.py`, `network_probe.py`,
`engine_cost.py`, `seq_len.py`, `grpc_servicers.py`). Result: **35 source modules
(−58%) and 41 test files (−70%)**, with zero milestone-prefixed module names and
zero milestone-prefixed import statements anywhere in `src` or `tests`. The
non-obvious architectural choices are recorded in
[ADR 0008](docs/decisions/0008-bench-harness-refactor.md) (citing the feature's
`research.md`), with two mid-flight course corrections in
[ADR 0006](docs/decisions/0006-cli-keep-bench-add-sweep.md) (keep `bench`/`compare*`,
add `sweep` subcommand) and [ADR 0007](docs/decisions/0007-m3-sweep-servicer-relocation.md)
(relocate the live `m3_sweep` servicers to `grpc_servicers.py`).

**Deliberate backward-compatibility breaks** (all forward-only, all recoverable —
see below):

- **Renamed modules + import paths.** Every `from vllm_grpc_bench.m6_2_sweep import …`
  (and all other `m*` module paths) is gone; the surfaces live in their de-prefixed
  homes.
- **Unified prompt format.** The two divergent chat-prompt builders collapsed to a
  single seed+digest `build_chat_prompt(seed)` in `prompts.py`; `rest_cohort` was
  repointed at it, so **the prompt bytes the REST cohort sends changed** (the M5.2
  `iteration`/`cell_id` builder is gone).
- **Dropped cohort members.** `CohortKind` collapsed from the M5.2 6-member enum to
  the forward **4 members** (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`,
  `tuned_grpc_multiplexed`); the vestigial `tuned_grpc_channels` / `tuned_grpc`
  members and their dead `symmetric_prompts` branches were removed.
- **Flat CLI.** The ~30 `--m3`…`--m6_1_3` flag groups and their dispatch branches
  were deleted; the surviving operator flags de-prefixed (`--m6_2-modal-region` →
  `--modal-region`, etc.). The CLI is now `bench` (no-arg default) +
  `{compare, compare-cross, compare-three-way, sweep}` subcommands — **old
  `--mN` invocations no longer parse.**

**Recovery path.** Every removed module, dropped cohort member, old prompt
convention, and retired CLI invocation is intact at its `milestone/m*` tag (all 16
tags, M2→M6.2, are on origin). For example, the full M5.2 harness + its 6-member
cohort enum + its prompt builder:

    git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py

The milestone-named **data pointers were deliberately preserved** — the published
deliverable `docs/benchmarks/m6_2-token-budget.{json,md}` and every baseline-chain
input the sweep reads at runtime (e.g. `m6_1_3-attribution-closure.json`) keep their
names on disk; only *code* was de-prefixed. Re-targeting those output paths to a new
milestone's artifacts is future (M7) scope.
