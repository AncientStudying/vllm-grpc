# Cross-Milestone Analysis: vllm-grpc

This document is the canonical home for vllm-grpc benchmark findings, milestone by milestone, in chronological order. Each milestone section names its source report, summarises the headline finding(s), and links cross-milestone where one milestone's result resolved (or recontextualised) an earlier one.

The per-milestone benchmark reports under [`docs/benchmarks/`](docs/benchmarks/) remain the source-data record; this document is the narrative cross-reference. `docs/benchmarks/summary.md` (the M1/M3-era summary) has been folded into § M1 and § M3 below and now lives as a one-line redirect.

> **Reading order tip.** M1–M4 measure single-protocol or pre-REST-vs-gRPC questions; their findings are largely topology-independent. M5 onward measures cross-host and REST-vs-gRPC dynamics where deployment topology starts to matter. The [Topology guide](#topology-guide--which-milestone-result-applies-to-your-deployment) at the bottom names which M5-era milestone applies to which deployment shape.

---

## M1 — Foundation

**Status**: delivered (Phase 4.2 / 5 / 6 benchmark reports under `docs/benchmarks/phase-*`)
**Report**: [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md) § 1–3 (folded in below) — `docs/benchmarks/phase-4.2-*.json`, `phase-5-*.json`, `phase-6-*.json` for source data

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

### § M3 fold-in (from `docs/benchmarks/summary.md` § 4, byte-for-byte equivalent per FR-018)

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

- **The `embed` cohort under M6 does NOT exercise real prompt-embeddings inference.** The frontend hashes opaque prompt_embeds bytes to a text digest (preserving M5.x behaviour) because the bytes the bench client emits are raw float32 arrays rather than `torch.save`-encoded tensors with the ZIP magic prefix. M6's "embed" path therefore measures text-prompt unary completion through the embeddings endpoint, not real `enable_prompt_embeds=True` inference. **M6.1 will close this specific gap** — see Phase Roadmap in [`docs/PLAN.md`](docs/PLAN.md) and [`README.md`](README.md).
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

## Topology guide — which milestone result applies to your deployment

The M5.1 and M5.2 findings are not redundant and neither supersedes the other. They measure two **different and equally valid deployment topologies**. Pick the milestone whose topology matches your deployment shape; both audiences are first-class.

| Topology | Audience | Applicable milestone |
|---|---|---|
| Client ↔ managed-provider with anycast HTTPS edge | Hobbyist or enterprise tenant on Modal / RunPod / Replicate / similar | **M5.2** — HTTPS-edge wins broadly; pick REST baseline |
| Client + server inside the same enterprise network | Corporate-internal deployments, well-connected colo, datacenter | **M5.1** — protocol-cost comparison applies; no managed edge to flip the verdict |
| Hobbyist self-hosting | DIY / homelab on LAN, single-host or LAN-local | **M5.1** — same fabric, no managed edge |
| Enterprise with internal anycast / edge infrastructure | Global SaaS fronting REST with their own edge layer | **M5.2** — same edge dynamics as a managed provider |

**Bytes-axis findings from § M1 are topology-immune** — protobuf vs JSON encoding wins apply to every deployment shape. The topology matters only for the time-axis verdicts (latency, TTFT, wall-clock).

**Two practical reads of the same matrix:**

- The same-fabric reader looks at M5.1: gRPC wins embed broadly; REST wins chat_stream at c≥4. M5's channel tuning is in the noise on this path. (Pick gRPC for embed-heavy workloads; pick REST for chat_stream above c=1.)
- The managed-edge reader looks at M5.2: gRPC still wins embed at c=1 (and decisively as hidden_size grows); the HTTPS-edge REST baseline wins everything at c=4 / c=8 **under MockEngine**. **M6 corrects this read under real engine cost** — for Qwen3-8B at h=4096 on A10G, gRPC reclaims all four c≥4 cells M5.2 awarded to REST. Managed-edge tenants serving real models at this scale should tilt back toward gRPC; the operational-simplicity argument for HTTPS-edge REST stands but is no longer backed by a real-engine latency win on this model.

**Engine-cost axis (added by M6):** the M5.1 / M5.2 verdicts reflect protocol cost with engine cost held neutral. M6 establishes that real-engine cost reshapes the protocol verdict at c≥4 for one (model, hidden_size) point; readers serving a different model family or hidden_size should treat M5.1 / M5.2 verdicts at c≥4 as a transport-only ranking and consult M6's per-cohort engine_cost numbers in `docs/benchmarks/m6-real-engine-mini-validation.md` before generalising.
