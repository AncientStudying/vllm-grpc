# Project Plan: Protobuf/gRPC Frontend for vLLM

**Status:** Draft v7 — updated 2026-05-14: inserted M6 (Real-Engine Mini-Validation); renumbered prior M6/M7 to M7/M8 to make the focused real-engine validation a canonical milestone before corpus and model expansion
**Repo:** Private GitHub repo (already provisioned), MIT license

---

## 0. Document Purpose

This is the high-level project plan. It defines phases, deliverables, and exit criteria. It is *not* a design document — per-phase design happens via `spec-kit` (`/specify`, `/plan`, `/tasks`) at the start of each phase. Treat this document as the contract that decides *what* gets built and in *what order*; the detailed *how* lives in spec-kit specifications generated phase by phase.

When working with Claude Code on this project, point it at this file plus the active phase's spec-kit artifacts.

---

## Milestone Roadmap (canonical, M1–M8, with M6.1 / M6.1.1 / M6.0a / M6.1.2 / M6.1.3 / M6.2 follow-ups)

This section mirrors the milestone framing in [`README.md`](../README.md). M1 through M5.2 are delivered; M6 through M8 are upcoming research directions. As of Draft v7, the focused real-engine mini-validation (formerly a single line in M5.1/M5.2 caveats as "deferred to M7") is promoted to a canonical M6 milestone; what was previously M6 (Corpus Expansion) becomes M7 and what was previously M7 (Model Expansion) becomes M8. M6 has six narrow follow-ups: **M6.1** (real-prompt-embeds engine path — exactly one variable change vs M6), **M6.1.1** (engine-cost instrumentation diagnosis + symmetrisation), **M6.0a** (concurrent-dispatch restoration — corrective methodology fix discovered during M6.1.1's first live run), **M6.1.2** (methodology discipline — topology proof + 3-cohort reintroduction + harness QoL; scoped by [`spike/m6-1-roadmap-additions`](../docs/spikes/m6-1-roadmap-additions/) items #1 + #2 + #3), **M6.1.3** (Phase 1 attribution closure — proxy-edge instrumentation gap + engine_compute_variation root-cause + run-to-run variance; scoped by the same spike items #4 + #5 + #6), and **M6.2** (token-budget characterization — `max_tokens` axis across the realistic-generation regime). The Phase 1–7 plan below this section is preserved as completed-work history (see the boundary heading further down) — it captures decisions and trade-offs that still inform future work, but the milestones above are the canonical forward view.

### M1 — Foundation (delivered)

Three access paths (REST via proxy, gRPC via proxy, gRPC-direct) implemented and benchmarked end-to-end on Modal A10G. **Findings**: see [`ANALYSIS.md`](../ANALYSIS.md) § M1.

### M2 — Cross-Repo Ground-Truth Research (delivered)

Formalize the practice of consulting cloned vLLM (the inference engine) and grpcio (the wire stack) as authoritative references when making proto, channel, or decode-tuning decisions in M3 and beyond. Tooling, merge process, and rebuild cadence are documented in [`../ground-truth-workflow-for-associated-projects.md`](../ground-truth-workflow-for-associated-projects.md), and the project-local `/ground-truth-refresh` skill drives the documented cadence in one invocation. **Known gap:** graphify does not parse `.proto` files, so proto-shape questions are answered by reading [`../proto/`](../proto) directly; graphify is leaned on for vLLM internals and grpcio channel implementation.

### M3 — Protobuf & gRPC Tuning (delivered)

Drive wire-size and decode tuning from a mock model that exposes a configurable `hidden_size` (canonical values: 2048, 4096, 8192) and emits embeddings of the matching shape with dummy weights. Per upstream guidance, embed payload size is determined by `hidden_size` rather than total parameter count — Llama 3.1 8B and Llama 3.3 70B both use `hidden_size=8192` and produce identically-sized embed payloads, so a real model is not required for this milestone. GPU cost is removed from the loop. Tuning decisions lean on cloned vLLM and grpcio source as ground truth via `cross-repo.json`.

The milestone splits into two axes:

- **Schema-level (protobuf):** can refinements to message shape (packed scalars, streaming chunk granularity, `oneof` layout for the input union) reduce response or request bytes below the M1 baseline? (Originally scoped as US2 in `specs/015-m3-protobuf-grpc-tuning/`. **Deferred to M4** per the 2026-05-10 clarifications session, since the proto-shape candidates are most likely to manifest as wall-clock-time wins and time becomes a defensible verdict metric only under the M4 harness redesign.)
- **Channel-level (grpcio):** how do `max_message_size`, keepalive, compression, and HTTP/2 framing settings affect wire size and decode time across `hidden_size` 2048 / 4096 / 8192? At what `hidden_size` does grpcio's default `max_message_size` become binding for embed requests? (Bytes verdicts shipped 2026-05-10 in PR #17 → [`benchmarks/m3-channel-tuning.{md,json}`](benchmarks/m3-channel-tuning.md). Phase A time re-analysis closed M3 → [`benchmarks/m3-channel-tuning-time.{md,json}`](benchmarks/m3-channel-tuning-time.md).)

### M4 — Time-Axis Channel & Schema Tuning (delivered)

Re-frame the M3 measurements around wall-clock time as a first-class success metric (TTFT for streaming, total per-RPC wall-clock for embed), and run the protobuf message-shape candidates deferred from M3 under that methodology. M3's bytes verdicts stand; M4 closes the gap that became visible in M3's published report — the existing harness's mock-pacing and per-axis fresh-baseline pairing prevent a defensible time-metric verdict on chat_stream wall-clock, which is exactly the metric the project's wire-overhead thesis cares about most.

The milestone splits into two axes, both gated on M3 closure:

- **Harness redesign (Phase B, the prerequisite):** add a `--no-pacing` mode to the mock engine so streaming wall-clock is dominated by transport+serialization rather than artificial token-emission delay; add a shared-baseline orchestrator mode that measures one M1_BASELINE cohort up front (n≥100) and reuses it across all axes (kills cross-batch baseline drift, observed at ~13% in M3); promote TTFT to a first-class metric in the recommendation builder for chat_stream cells. Optional: add a cross-host transport mode for the keepalive and HTTP/2 framing axes that don't manifest savings on loopback.
- **Definitive time-axis sweep + schema-level candidates:** re-run the four-axis channel sweep under the new methodology, then measure the protobuf-shape candidates (packed scalars on token-id fields, `oneof` flattening on the input union, alternative streaming chunk granularity per `specs/015-m3-protobuf-grpc-tuning/research.md` R-9) against the new frozen-channel baseline using both bytes and time verdicts.

Outputs supersede M3's bytes-only verdicts where the new methodology produces a different result; M3's report stays in place as the bytes baseline for traceability. Citations follow the M2 ground-truth workflow.

**Status (delivered 2026-05-10):** harness redesign + definitive sweep merged on `016-m4-time-axis-tuning`. US1 (no-pacing mode, shared-baseline orchestrator, borderline-expand cascade, `client_bound` detection, per-cohort CV recording, TTFT-first-class verdicts) and US2 (per-path frozen-channel baselines, loopback caveat tagging, `validate_run` invariants, `m4_supersede` Supersedes-M3 builder, strict-superset M4 JSON+markdown reports) are landed. US3 schema-candidate proto files (`packed_token_ids`, `oneof_flattened_input`, `chunk_granularity`) live under `proto/vllm_grpc/v1/m4-candidates/` with stubs regenerated by `make proto`; the cascade rule, frozen-baseline pairing, and Negative-results classifier are merged. Published report at [`benchmarks/m4-time-axis-tuning.{md,json}`](benchmarks/m4-time-axis-tuning.md). FR-005 reworked late-stage from abort-on-CV to record-and-report (research.md R-11); per-cohort CV is surfaced in the report so the reader adjudicates trust on noisy baselines. M5 addresses the loopback caveat axes (`keepalive`, `http2_framing`) by re-running the same sweep on Modal.

### M5 — Cross-Host Time-Axis Validation (delivered)

Re-run the M4 four-axis channel sweep and the M4 schema-candidate sweep with the gRPC server deployed on Modal and the benchmark client running locally, so the transmission crosses real wire instead of `127.0.0.1`. M4's published verdicts on the `keepalive` and `http2_framing` axes carry the loopback caveat (FR-010) because RTT-bounded behavior cannot manifest on a single host; `max_message_size` and `compression` verdicts also benefit from a real-network sanity check. The local-to-Modal split (real RTT ~30–100ms, real bandwidth-delay product) exposes transport-layer behavior that loopback masks.

Approach reuses the existing M4 harness (`vllm_grpc_bench --m4`) unchanged: deploy the mock gRPC server (M4's `MockEngine` + `M3CompletionsServicer` + `M3ChatServicer`) as a Modal app exposing the same proto surface, add a connection-string flag so the harness's client points at the Modal endpoint instead of `serve_in_process`, and run the same axis × width × path matrix as M4 (no_pacing, shared baseline, n=100→250 cascade, per-cohort CV recorded per FR-005). M3/M4's strict-superset JSON schema is preserved.

Outputs land at `docs/benchmarks/m5-cross-host-validation.{md,json}` plus a "Supersedes M4" table for axes whose verdicts shift under real-wire conditions. M4's published report stays in place as the loopback baseline for traceability.

**Status (delivered 2026-05-11):** Full operator-driven sweep landed on branch `017-m5-cross-host-validation`. Published report at [`benchmarks/m5-cross-host-validation.{md,json}`](benchmarks/m5-cross-host-validation.md). **Findings**: see [`ANALYSIS.md`](../ANALYSIS.md) § M5. Harness implementation in `tools/benchmark/src/vllm_grpc_bench/{rtt_probe,modal_endpoint,m5_sweep,m5_supersede}.py` + reporter extensions; Modal app at `scripts/python/modal_bench_grpc_server.py`.

Out of scope: real model (narrow focused validation deferred to M6; full multi-model expansion deferred to M8), corpus diversity (deferred to M7), Modal-side observability beyond what's needed to record per-RPC wall-clock and TTFT, any non-`mock-engine` workload, **and a direct REST-vs-gRPC head-to-head under cross-host conditions (deferred to M5.1)**.

### M5.1 — REST vs gRPC Head-to-Head on Real Wire (delivered)

Drove REST and gRPC head-to-head against the same Modal eu-west-1 MockEngine over real wire. 18-cell matrix (2 paths × 3 widths × 3 concurrencies); 48 verdicts across four gRPC sub-cohorts (`tuned_grpc` at c=1, `tuned_grpc_multiplexed` and `tuned_grpc_channels` at c≥2, `default_grpc` everywhere) plus one REST cohort. Published report at [`benchmarks/m5_1-rest-vs-grpc.{md,json}`](benchmarks/m5_1-rest-vs-grpc.md). Drive with `python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=eu-west-1`.

**Status (delivered 2026-05-11):** Full operator-driven sweep landed on branch `018-m5-1-rest-vs-grpc`. **Findings**: see [`ANALYSIS.md`](../ANALYSIS.md) § M5.1. Harness implementation in `tools/benchmark/src/vllm_grpc_bench/{rest_shim,rest_cohort,m5_1_grpc_cohort,m5_1_sweep,m5_1_supersede}.py` + reporter extensions; Modal app at `scripts/python/modal_bench_rest_grpc_server.py`.

### M5.2 — REST Transport Path × gRPC Tuning Surface (delivered)

**Status (delivered 2026-05-14):** Full operator-driven sweep landed on branch `019-m5-2-transport-tuning`. Published report at [`benchmarks/m5_2-transport-vs-tuning.{md,json}`](benchmarks/m5_2-transport-vs-tuning.md). **Findings**: see [`ANALYSIS.md`](../ANALYSIS.md) § M5.2. Harness implementation in `tools/benchmark/src/vllm_grpc_bench/{m5_2_sweep,m5_2_events,m5_2_symmetry,m5_2_supersede,m5_2_regen,rest_cohort,modal_endpoint}.py` + reporter extensions; Modal app at `scripts/python/modal_bench_rest_grpc_server.py`.

M5.1 surfaced two questions it could not answer with n=100 and a single (plain-TCP) REST transport:

1. **Does Modal's HTTPS edge (anycast-routed, TLS-terminated) change REST's competitive position?** M5.1 forced both protocols through plain-TCP because a 2× RTT gap on the smoke run would have made the comparison meaningless. Production REST traffic almost always travels the HTTPS edge; M5.2 measures both REST transports so the operator can see how the network path changes the verdict, and so M5.1's verdict tally can be reread against a production-equivalent baseline.
2. **Does M5's tuned channel config provide measurable benefit over M1-default at higher iteration count?** M5.1's per-cell deltas between `default_grpc` and the tuned cohorts were frequently within ±3% (in the noise). Higher-n sampling resolves whether the tuning is genuinely neutral on this path or whether M5.1's n=100 was simply not enough resolution to distinguish them.

**Approach.** Five transport cohorts on the same 18-cell (path × hidden_size × concurrency) matrix from M5.1:

| cohort | wire format | transport |
|--------|-------------|-----------|
| `rest_https_edge` | JSON over HTTP/1.1 | Modal HTTPS edge (TLS-terminated, anycast-routed) — **honors FR-019** |
| `rest_plain_tcp` | JSON over HTTP/1.1 | Modal `modal.forward(unencrypted=True)` — matches M5.1's REST transport |
| `default_grpc` | Protobuf over HTTP/2 | Plain-TCP (M1-default channel config) |
| `tuned_grpc_multiplexed` | Protobuf over HTTP/2 | Plain-TCP (M5 tuned config; 1 channel, c concurrent streams) |
| `tuned_grpc_channels` | Protobuf over HTTP/2 | Plain-TCP (M5 tuned config; c channels, serial RPCs) |

**Methodology.**

- Same MockEngine, same Modal eu-west-1 region, same workload corpus as M5.1 — only the cohort surface widens.
- **n=250 per cohort** (vs. M5.1's n=100). Drives 95% CI half-widths down so the small `tuned_grpc_*` vs `default_grpc` deltas can be resolved against noise. Runtime budget: ~25–30 min wall-clock per full sweep (5 cohorts × 18 cells × n=250).
- **Per-cohort RTT probe.** The HTTPS-edge vs plain-TCP RTT delta is reported, not hidden. The report's executive section names the network path each verdict travels and includes the transport pair on every verdict row so a reader cannot accidentally read a `rest_plain_tcp` vs `tuned_grpc_multiplexed` comparison as a production-equivalent result.
- **Two verdict families per cell.** Protocol comparison (each gRPC cohort vs `rest_https_edge`) and a transport-only comparison (`rest_https_edge` vs `rest_plain_tcp`) so the HTTPS-edge transport cost is quantified separately from the protocol comparison.
- **Network-path awareness on every published delta.** The HTTPS edge and the plain-TCP tunnel reach the same Modal container via materially different network paths (anycast TLS termination near the client vs. direct TCP to the worker pod). M5.2's report calls this out per-verdict so the comparison's audience cannot mistake a network-path artifact for a protocol property.

**Outputs.** `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}` (strict superset of M5.1's JSON schema; M5.1-aware consumers continue to work unmodified). A "Supersedes M5.1" table for cells whose verdict moves under the HTTPS-edge transport or under the higher iteration count. Drive with `python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1`.

Out of scope: real vLLM (narrow focused validation deferred to M6; full multi-model expansion deferred to M8), corpus diversity (deferred to M7), additional gRPC channel-config axes beyond what M5 already winnowed, HTTPS-edge transport for gRPC (Modal's edge does not natively expose HTTP/2 plaintext + gRPC, so plain-TCP remains the only credible gRPC transport for this milestone; if Modal adds a TLS-terminated gRPC edge later, that becomes a follow-up).

### M6 — Real-Engine Mini-Validation (delivered 2026-05-15)

Run a focused, narrow re-measurement of the M5.2 transport × tuning matrix with the MockEngine replaced by real Qwen3-8B inference on Modal A10G. M5.1 and M5.2 both deferred real-engine validation, and that deferral is the loudest open caveat in both reports. M6 closes the caveat with the minimum compute commitment so M7 (corpus expansion) can be designed against the actual residual transport/protocol signal that real inference leaves behind, rather than against MockEngine assumptions.

**Approach.** Six-cell narrow slice of the M5.2 matrix at a single hidden_size (h=4096, fixed by Qwen3-8B's architecture):

| # | Path | Concurrency | What it tests |
|---|------|-------------|---------------|
| 1 | embed | c=1 | M5.2's largest c=1 gRPC win (−51 ms tuned_grpc) — most likely to survive |
| 2 | embed | c=4 | Mid-concurrency embed; engine batching dynamics enter the picture |
| 3 | embed | c=8 | M5.2's high-concurrency REST win — tests whether RTT or batching dominated |
| 4 | chat_stream | c=1 | TTFT under real generation; ~1.5–2.5 s total wall-clock |
| 5 | chat_stream | c=4 | Median chat_stream cell — TTFT vs total wall-clock contrast |
| 6 | chat_stream | c=8 | High-concurrency chat_stream; engine + tokenisation under load |

Three cohorts (down from M5.2's five): `rest_https_edge`, `default_grpc`, `tuned_grpc_multiplexed`. `rest_plain_tcp` and `tuned_grpc_channels` are dropped — transport-only delta already characterised by M5.2, and `_channels`/`_multiplexed` were empirically interchangeable at c≥2 in M5.1 and M5.2.

**Methodology.**

- Same harness as M5.2 with the gRPC frontend launching real `AsyncLLM` (`enable_prompt_embeds=True`) loaded with Qwen3-8B on Modal A10G. MockEngine paths are not exercised.
- **n=100 per cohort per cell** (vs M5.2's n=250). M6 is asking the larger "does the verdict structure survive?" question, not resolving sub-noise tuned-vs-default deltas.
- **`max_tokens=50`** for chat_stream cells (vs M5.2's `max_tokens=10`). Bumps generation length into a production-realistic regime so engine cost is visible; preserves the chat_stream wall-clock vs TTFT contrast.
- **TTFT as a first-class metric** for chat_stream cells alongside total wall-clock. At `max_tokens=50`, total wall-clock is engine-bound (~1.5–2.5 s) and only TTFT exposes residual transport-cost effects.
- **Engine-cost-per-RPC published per cell** as a separate metric (forward-pass wall-clock for embed; TTFT + TPOT for chat_stream). This is M6's gift to M7: a real baseline against which corpus-length scaling effects can be interpreted.
- **Smoke gate** before the full sweep: 1 cell × 3 cohorts × n=10 to validate the harness wires real Qwen3-8B correctly under the real-engine path.

**Outputs.** `docs/benchmarks/m6-real-engine-mini-validation.{md,json}` plus a "Supersedes M5.2 under real engine" verdict table per cell, categorising each as `verdict_survives`, `verdict_buried_by_engine`, `verdict_changed`, or `no_winner_at_n100`. Drive with `python -m vllm_grpc_bench --m6 --m6-modal-region=eu-west-1`. Runtime budget: ~75–90 min on Modal A10G (Qwen3-8B fp16 ≈ 16 GB, fits with KV-cache headroom — no A100 needed).

**Bytes axis preserved.** M6 measures latency only. M1's topology-immune wire-size findings (89% chat / 25% embed reductions) remain in force — encoding is structural, not engine-dependent.

Out of scope: corpus diversity (deferred to M7), additional models (deferred to M8), real-engine validation at h≠4096 (deferred to M8 which uses multiple models spanning canonical widths), real-engine validation of the M3/M4 channel-tuning sweep (out of scope; M3/M4 verdicts were already validated cross-host by M5).

### M6.1 — Real-Prompt-Embeddings Engine Path (delivered 2026-05-16)

The harness, classifier, reporter, smoke gate, and torch-pin gate are in
place per `specs/022-m6-1-real-prompt-embeds/` (38 tasks; 87 unit tests
green; ruff / mypy --strict clean). Published artifacts at
`docs/benchmarks/m6_1-real-prompt-embeds.{md,json}` are produced by the
operator-driven Modal full sweep (`python -m vllm_grpc_bench --m6_1
--m6_1-modal-region=eu-west-1`). See ["Engine path differential"
section](./benchmarks/m6_1-real-prompt-embeds.md#engine-path-differential-m61--m6)
once the operator publishes the artifacts.



Re-run M6's narrow 6-cell × 3-cohort slice with the embed cohort wired to vLLM's **real `enable_prompt_embeds=True`** engine path on both transports, instead of M5.x's "hash binary payload → short text prompt" symmetry. Tests the protocol-comparison question for the workload where the caller sends actual prompt embedding tensors to vLLM (a path M3–M6 don't exercise because they hash the binary payload to a text digest server-side for apples-to-apples engine work).

**Why a separate slice rather than a wider M6.** M6 deliberately preserves M5.2's apples-to-apples engine work (both cohorts hash to a text digest server-side) so the protocol comparison stays clean and the "does M5.2 verdict survive?" question is answerable. Under M6 the gRPC and REST embed cohorts measure identical engine work — pure protocol/transport cost on identical engine code paths. M6.1 changes that one variable (engine code path) on the same 6 cells, so the diff against M6's published JSON quantifies the engine-path cost differential. Mixing both axes inside M6 would confound the verdict.

**Approach.** Same 6 cells × 3 cohorts × n=100 matrix as M6. The harness:

- **gRPC embed driver** sends `torch.save(tensor)`-pickled bytes in the `prompt_embeds` proto field. The frontend's `CompletionsServicer._resolve_prompt_embeds_input` already tries `decode_embeds` first → returns a real `torch.Tensor` → vLLM's `enable_prompt_embeds=True` path consumes it.
- **REST shim** gains a new `input_kind="prompt_embedding_torch_b64"` that b64-decodes torch-pickled tensors and passes `{"prompt_embeds": tensor}` to `engine.generate(...)` directly. REST embed cohort is updated to send this format. (Existing M5.x `input_kind="prompt_embedding_b64"` remains for back-compat with M5.x / M6 reproductions.)
- Operator's client machine needs `torch` installed locally (for the driver's `torch.save` call). Listed as a prerequisite in the quickstart.
- All other M6 wiring reused unchanged: same Modal app + `max_model_len=2048` + `gpu_memory_utilization=0.92` + classifier + reporter + smoke gate.

**Verdict table format.** Same 5-classification per-cell verdict (`verdict_survives` / `verdict_changed` / `verdict_buried_by_engine` / `no_winner_at_n100` / `cell_incomplete`) plus a separate **"Engine path differential"** section that subtracts M6's published baseline from M6.1's measurements per cell. Quantifies "engine cost of `enable_prompt_embeds=True` vs text-prompt completion" as a methodology disclosure for production callers picking between the two paths.

**Outputs.** `docs/benchmarks/m6_1-real-prompt-embeds.{md,json}` plus a "Supersedes M6 under enable_prompt_embeds" verdict table. Drive with `python -m vllm_grpc_bench --m6_1 --m6_1-modal-region=eu-west-1`. Runtime budget: ~75–90 min on Modal A10G (same hardware as M6; engine code path is the only operative change).

**Speckit cycle.** Run `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` against this section after M6 publishes its verdict table. M6's published JSON is M6.1's baseline reference (FR-014-equivalent hard precondition).

Out of scope: prompt-length variation in the embeddings (deferred to M7), additional models (deferred to M8), real-engine re-validation of M3/M4 channel-tuning under the embeddings path (defer until M6.1 produces a verdict — if M6.1 says `verdict_buried_by_engine` everywhere, channel-tuning re-validation is moot).

### M6.1.1 — Engine-Cost Instrumentation Diagnosis & Symmetrisation (code landed 2026-05-16; awaiting Modal end-to-end run)

Close a measurement gap M6.1's data surfaced before M6.2's token-budget axis builds on top. M6.1 fired `engine_cost_drift_warning` on **all 3 chat_stream cells** with a consistent ~14-17% per-cohort spread on `engine_ttft_ms` (rest_https_edge ~43.5 ms / default_grpc ~47.5 ms / tuned_grpc_multiplexed ~41.5 ms; see [§ M6.1 in ANALYSIS.md](../ANALYSIS.md#m61--real-prompt-embeds-engine-path)). The engine itself shouldn't see different first-token latencies based on which channel served the request, so the gap is most likely **measurement-window asymmetry**: REST's `engine_ttft_ms` is captured inside the FastAPI shim (`engine_start = perf_counter()` → first SSE chunk) while gRPC's is read from server-side trailing metadata. The two clocks may straddle slightly different windows. But there is a competing real-world hypothesis: **vLLM's continuous batching may see REST and gRPC arrival patterns differently** (HTTPS edge buffers requests with different jitter than raw TCP, so the engine batches them differently), making the gap a real channel-dependent batching effect rather than a measurement artifact. M6.1.1 distinguishes the two and acts accordingly.

**Why before M6.2 rather than bundled.** M6.2 already changes one variable (`max_tokens` axis). Bundling instrumentation with the axis change makes the M6.2 diff against M6.1 ambiguous: did the per-cohort engine_ttft shift because of longer generation or because the measurement window was fixed? Exactly the methodological confound the project is disciplined about avoiding. **Two more concrete reasons**: (1) M6.2's `max_tokens=10` / `50` null anchors validate the sweep against M6.1's published CIs — if the instrumentation gap is constant, every anchor on every cap will fire `engine_cost_drift_warning` regardless of whether the rest of the sweep is sound, and the anchor mechanism stops working. (2) The same gap will haunt M7 (corpus diversity) and M8 (multi-model) — every per-cohort engine-cost decomposition published from now on will carry a 14-17% asterisk until it's fixed. Cheap to fix once now; expensive to retrofit later.

**Approach — diagnosis first, then fix-or-document.**

*Phase 1 (diagnosis)*: add multi-point timing to both transport paths. Instrument **REST** with timestamps at: (a) FastAPI handler entry, (b) just before `engine.generate(...)` invocation, (c) first SSE chunk yielded, (d) terminal SSE event emitted. Instrument **gRPC chat_stream** with the same four points: (a) servicer handler entry, (b) just before `engine.generate(...)` invocation, (c) first streamed chunk produced, (d) trailing metadata emit. Both paths emit the four timestamps on the wire (REST as JSON fields on the terminal SSE event; gRPC as additional trailing-metadata keys). Run a quick 6-cell × 3-cohort × n=50 sweep against the M6.1 matrix to collect the multi-point data. Analyse: which segment carries the 5-6 ms gap? If the gap lives in **(a→b)** for one path, that's pre-engine ASGI/gRPC-servicer overhead and the `engine_ttft_ms` field is misnamed at that path (it's including pre-engine work). If the gap lives in **(b→c)**, the engine is genuinely seeing different first-token times depending on arrival pattern — real channel-dependent batching effect.

*Phase 2 (fix or document)*: based on diagnosis, either (a) **symmetrise the measurement window** by adjusting whichever path is mis-bracketing — likely the REST shim's `engine_start = perf_counter()` should move to AFTER the first internal vLLM input-processing step, OR the gRPC trailing metadata should anchor on the same earlier point — so both paths bracket the same engine work; OR (b) **publish the channel-dependent batching effect as a real M6.1.1 finding** with a methodology note in the M6.1.1 report and an updated `contracts/instrumentation.md` describing the operator-facing interpretation. The choice is data-driven, not pre-committed.

**Output shape.** `docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}` — a small differential report against M6.1:

- Multi-point timing breakdown per cohort per cell (4 segments × 3 cohorts × 6 cells from Phase 1).
- Root-cause attribution (which segment carries the gap; instrumentation vs batching).
- If Phase 2(a) — code change applied — a re-run of the M6.1 matrix at n=100 showing the drift warning cleared (delta against M6.1's published CIs should now overlap).
- If Phase 2(b) — finding documented — updated `contracts/instrumentation.md` describing the channel-dependent batching effect; M6.1's published JSON is annotated with a methodology-superset note (no re-sweep needed).

Drive with `python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1` (Phase 1 mini-sweep) followed by `--m6_1_1` (Phase 2 if (a) applies; n=100 verification sweep). Total Modal compute: ~$1-2 (Phase 1 ~30 min; Phase 2(a) ~75 min if needed; Phase 2(b) is doc-only).

**Speckit cycle.** Run `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` against this section after M6.1 publishes. M6.1's published JSON is M6.1.1's input data (the multi-point sweep compares against M6.1's per-cohort engine_ttft means and CIs).

Out of scope: token-budget axis (deferred to M6.2 — Phase Discipline), real engine path changes (M6.1's prompt-embeds path is unchanged; M6.1.1 only adds instrumentation), corpus diversity (M7), multi-model (M8), changes to how `engine_forward_ms` (embed) is measured (the drift warning fired on chat_stream only; embed cells are unaffected and out of scope for this milestone).

### M6.0a — Concurrent Dispatch Restoration (delivered 2026-05-17)

> **Delivered.** Harness-only dispatch correction committed at `f3ad158` on branch `024-m6-0a-concurrent-dispatch`; corrected M6.1.1 Phase 1 re-run completed 2026-05-17 02:10 UTC (15.6 min wall-clock, $0.29 Modal A10G `eu-west-1`). Headline finding: c=4 / c=8 chat_stream per-cohort `engine_ttft_ms` spread grew from the audit baseline's 6.0% / 8.4% to 15.9% / 16.4% under real concurrency, disproving the "sequential-dispatch state-drift artifact" hypothesis. M6 / M6.1 main verdicts are dispatch-robust; only the M6.1 per-cohort drift sub-finding is dispatch-sensitive (annotated via cross-link). M6.1.1 Phase 2 remains pending — separately blocked by the FR-010 classifier degeneracy ([PR #27 comment 4468600646](https://github.com/AncientStudying/vllm-grpc/pull/27#issuecomment-4468600646)). Full bug / fix / before-after / per-finding sensitivity classification in [`docs/benchmarks/m6_0a-dispatch-correction.md`](benchmarks/m6_0a-dispatch-correction.md). The planning narrative below is preserved for historical context.

#### Original planning narrative (pre-delivery)


Methodology correction surfaced during M6.1.1's first live Phase 1 run (2026-05-16). The M6 harness silently dropped `asyncio.gather`-based concurrent dispatch when it inherited the M5.x cell-cohort matrix. M5.1 / M5.2's REST + gRPC cohort runners spawn `c` concurrent worker coroutines per cell (`asyncio.gather(*(_channel_worker(i) for i in range(concurrency)))` — see `m5_1_grpc_cohort.py:387` and `rest_cohort.py:484`); M6 / M6.1 / M6.1.1 replaced this with sequential `for idx in batch_indices: await driver(...)` loops in `m6_sweep._run_measurement_m6` (and inheritors). The cell's `concurrency` field became a metadata tag controlling round-robin batch indexing, not actual in-flight parallelism.

**Why this matters.** M6.1.1's primary classifier (FR-010 magnitude-equivalence across `seg_ab` / `seg_bc` / `seg_cd`) presupposes that `channel_dependent_batching` is mechanistically possible — i.e., that the engine sees multiple in-flight requests from different cohorts and its continuous-batching scheduler exhibits per-cohort variation. Under sequential dispatch, the engine sees exactly one request at a time, fresh KV cache per RPC, and any per-cohort `seg_bc` spread can only come from chronological state drift (which is real but mislabelled by the classifier as "channel-dependent batching"). The first M6.1.1 live run (2026-05-16) returned mixed `channel_dependent_batching` + `drift_not_reproduced` classifications under sequential dispatch — interpretable as state-drift artifacts rather than a real channel-dependency signal. M6.1.1 cannot publish a trustworthy verdict without correcting this.

**What's invalidated vs robust.** Most M6 / M6.1 conclusions survive the dispatch-mode bug because they don't lean on the concurrency axis:

| Finding | Dispatch-mode sensitivity |
|---|---|
| M6 main: "engine cost dominates protocol cost at realistic workloads" | **Robust** — the ~50 ms engine TTFT vs ~5 ms protocol overhead conclusion holds regardless of dispatch mode |
| M6.1 main: "real-prompt-embeds engine path equivalent to text-prompt path" | **Robust** — about engine-path equivalence, not concurrency |
| M6 / M6.1 per-cohort `engine_ttft_ms` drift (chat_stream cells) | **Sensitive** — sequential dispatch artificially isolates cohorts; no batching cross-pollination across cohorts |
| M6.1.1 Phase 1 classifications | **Critically sensitive** — `channel_dependent_batching` label presupposes batched concurrent requests; under sequential dispatch it can fire on chronological state drift |

So M6 and M6.1's main verdict tables stand. The 14-17% per-cohort drift M6.1 reported (and that M6.1.1 was created to investigate) is the data point most likely to change under corrected dispatch.

**Approach.** Single narrow code fix to the M6 harness, no Modal compute:

1. Restore `asyncio.gather`-based concurrent dispatch in `m6_sweep._run_measurement_m6` (and have M6.1 / M6.1.1 inherit unchanged). The pattern is already in `m5_1_grpc_cohort.run_grpc_cohort` and `rest_cohort.run_rest_cohort` — port the `_channel_worker` / queue-drain pattern to M6's measurement loop.
2. Preserve M6's existing round-robin per-c-batch sequencing for index allocation (don't disturb `compute_rpc_seed` determinism); only the *dispatch* step within a batch changes from `for idx in batch: await ...` to `await asyncio.gather(*(driver_for(idx) for idx in batch))`.
3. Add regression tests asserting that at c=4 / c=8 cells, the bench client has the expected in-flight RPC count (e.g., via a `Semaphore`-wrapping fake driver that counts concurrent enters).
4. Update the `concurrency` field's documented semantics in `m6_types.py` / `m6_1_types.py` to confirm it now controls real in-flight parallelism (reverting it from "metadata-only" back to its M5.x semantics).

**Then re-run M6.1.1's Phase 1** (`--m6_1_1-diagnose`) under corrected dispatch. This single re-run directly answers the central M6.1.1 question:

- If chat_stream per-cohort `engine_ttft_ms` spread drops below 5% → M6.1's reported drift was a sequential-dispatch state-drift artifact (not a channel-dependent engine effect). M6.1's published per-cohort numbers would need a methodology-supersedence annotation pointing at M6.0a as the corrective baseline. **Phase 2(a) (symmetrisation code change) is not needed.**
- If the spread stays ≥10% under concurrent dispatch → M6.1's drift was real channel-dependent behaviour. **Phase 2(a) or 2(b) applies** per the M6.1.1 contract.

**Output shape.** No published benchmark artifact — this is a harness correction. Deliverable is:

1. Code: `m6_sweep._run_measurement_m6` restored to concurrent dispatch + `Semaphore`-counting test fixture.
2. Documentation: short `docs/benchmarks/m6_0a-dispatch-correction.md` documenting the bug, the fix, and the before/after of M6.1.1's chat_stream per-cohort spread. Saves the sequential-dispatch M6.1.1 run as the "before" data set; the corrected run as "after."
3. PR comments on M6.1.1's PR #27 cross-linked: this fix is a precondition to closing M6.1.1.

Drive: `git pull` (after M6.0a code change lands) then re-run `python -m vllm_grpc_bench --m6_1_1-diagnose --m6_1_1-modal-region=eu-west-1`. Total Modal compute: ~$0.50 (one ~30 min Phase 1 sweep). No new sweep needed for M6 / M6.1 themselves — their main conclusions are dispatch-robust.

**Speckit cycle.** Run `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` against this section. M6.1.1's PR #27 stays open during this fix; M6.1.1's Phase 2 dispatch happens after M6.0a's re-run produces a real classification.

Out of scope: re-running M6 (its main verdict is dispatch-robust), re-running M6.1's full verdict-supersedes table (also dispatch-robust; the per-cohort drift sub-finding may be annotated with a methodology-supersedence note after M6.0a but the verdict table itself stands), real engine code changes (M6.0a is harness-only), corpus diversity (M7), multi-model (M8).

### M6.1.2 — Methodology Discipline: Topology Proof + 3-Cohort Reintroduction + Harness QoL (planned, post-spike)

Three methodology-discipline additions that land **before** M6.2 so M6.2 / M7 / M8 all inherit them as the new sweep convention. Scoped by [`spike/m6-1-roadmap-additions`](../docs/spikes/m6-1-roadmap-additions/) items #1 + #2 + #3; the spike-produced findings notes are the spec input. The bundle exists because the three items share the same set of touched files (sweep orchestrator, artifact JSON schema, reporter, stderr emitter) and ship together more efficiently than as separate milestones.

**Why before M6.2.** M6.2 introduces the `max_tokens` axis as the new variable. Bundling methodology discipline into M6.2 would mix two changes in one verdict (axis change AND cohort/topology change) — exactly the methodological confound M6.1.1 was created to avoid. Per Phase Discipline (Constitution Principle III), M6.2's diff against M6.1.1 needs to be unambiguous, so the methodology changes ship as their own milestone first.

**Concrete additions.** Three deliverables, all on the harness + report side; no engine-cost code changes:

1. **Per-sweep traceroute probe** (item #1). The spike's [`01-topology-traceroute-findings.md`](../docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md) proved (via live deploy + `traceroute` from a Mac client) that the cohorts enter Modal via **entirely different cloud providers**: `*.modal.run` (HTTPS-Edge cohort) routes through Microsoft Azure; `*.modal.host` (plain-TCP cohorts including gRPC) routes through AWS us-west-1 via Telia transit. This is stronger than ANALYSIS.md's "different network path" claim and changes how cohort-comparison results should be interpreted. Tunnel IDs are ephemeral per-deploy, so the only way to keep the topology assertion supported by data is to capture per-cohort hop-traces at sweep start and store them in the artifact JSON under a new `network_paths: {<cohort>: {endpoint_ip, hops: [...], cloud_provider, region}}` block. Probe should use `tcptraceroute` (TCP-SYN) rather than UDP/ICMP `traceroute` to get past the AWS/Azure ICMP firewall around hop 5. Single-shot per sweep (paths are stable for the duration of a deploy). ANALYSIS.md gets a one-line correction citing the multi-CSP finding.

2. **Reintroduce `rest_plain_tcp` cohort** (item #2). The spike's [`02-cohort-reintroduction-disposition.md`](../docs/spikes/m6-1-roadmap-additions/02-cohort-reintroduction-disposition.md) confirms the 3-cohort split (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`) is structurally load-bearing: with all three, `rest_plain_tcp` vs `default_grpc` isolates pure protocol cost (same CSP, region, path; only HTTP/1.1+REST vs HTTP/2+gRPC changes); either vs `rest_https_edge` isolates multi-cloud routing cost. Without `rest_plain_tcp`, M6.x cells conflate the two. M5.2 had this cohort wired (`m5_2_sweep.py`, `m5_2_symmetry.py`, the harness CLI); M6 / M6.1 / M6.1.1 dropped it during simplification. M6.1.2 ports the cohort definition forward with M6.0a-corrected concurrent dispatch and the M6.1.1-expansion classifier instrumentation already in place.

3. **Timestamped progress lines** (item #3, **already implemented** on `spike/m6-1-roadmap-additions` at commit `3763687`). Each stderr emission from the M6 / M6.1 / M6.1.1 progress reporters carries an ISO-8601 UTC timestamp prefix (`[2026-05-17T12:34:56Z] [1/18] embed × c=1 / rest_https_edge — 50/50 succ — 29786 ms — ETA 75m`), matching the run_id timestamp convention used elsewhere. Code carries forward verbatim from the spike commit; only the spec/PLAN.md prose needs to reflect that this is now part of M6.1.2's bundle.

**Output shape.** Validation sweep + ANALYSIS.md edit + spec note.

- Validation sweep at n=50 against the new cohort + traceroute infrastructure — confirms `rest_plain_tcp` is reachable, traceroute captures populate cleanly, the JSON `network_paths` block parses. Cost: ~$0.30 Modal compute.
- `ANALYSIS.md` updated to cite the multi-CSP finding instead of the looser "different network path" wording.
- `contracts/instrumentation.md` (or equivalent) updated to document the per-sweep `network_paths` block as part of the M6.1.2-forward artifact schema.
- All M6.x / M7 / M8 sweep artifacts from M6.1.2 forward carry `network_paths` and the full 4-cohort split (or document explicitly when a milestone uses a subset and why).

**Speckit cycle.** Run `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` against this section. Input data: the three spike notes under [`docs/spikes/m6-1-roadmap-additions/`](../docs/spikes/m6-1-roadmap-additions/).

Out of scope: any per-sweep behaviour change beyond cohort restoration + traceroute capture (the M6.1.1-expansion classifier stays as-is; the M6.0a-corrected dispatch stays as-is); engine-cost decomposition changes (M6.1.3's territory); per-`max_tokens` axis (M6.2); model expansion (M8).

### M6.1.3 — Phase 1 Attribution Closure: Proxy-Edge Probes + Drift Root-Cause + Variance Characterization (planned, post-spike)

Bundle that closes M6.1.1's open Phase 2 verdicts. M6.1.1's published Phase 1 returned `engine_compute_variation` for chat_stream c=1 (reproducible) and `inconclusive` for chat_stream c=4 + c=8 (one or both of: unattributed proxy-edge budget; cohort signal not reproducible across runs). M6.1.3 ships three instrumentation/methodology additions that, in a single multi-run sweep, produce attributable verdicts on all three chat_stream cells — OR a defensible "this signal is noise-shaped at this concurrency" verdict if the data warrants it. Scoped by [`spike/m6-1-roadmap-additions`](../docs/spikes/m6-1-roadmap-additions/) items #4 + #5 + #6.

**Why bundle.** All three items share the same Phase 1 sweep infrastructure (per the M6.0a-corrected dispatch + M6.1.1-expansion classifier already in place). One 5-run multi-sweep at n=50 produces, per cell × cohort:

- 5 datapoints of proxy-edge attribution from the new probes (item #4 — ingress/egress segments of the unattributed budget).
- 5 datapoints of per-cohort token-count + token-hash distribution from the new audit instrumentation (item #5-A — distinguishes prompt-content drift from other root-cause hypotheses).
- 5 datapoints of `engine_ttft_ms` per cell × cohort for between-run variance estimation (item #6 — quantifies V2 run-state noise on top of V1 sample noise).

Bundling is maximally informative per Modal dollar. Splitting items #4 / #5 / #6 into separate milestones would require 3+ separate Modal-deploy cycles for data that's all produced by one multi-run sweep.

**Concrete additions.** Three instrumentation additions plus the multi-run scaffolding:

1. **Proxy-edge probes** ([item #4 spike note](../docs/spikes/m6-1-roadmap-additions/03-proxy-edge-instrumentation-gap.md)). Two new optional checkpoints in the frontend servicers' streaming paths: `m6_1_1_t_pre_engine_wall_ns = time.time_ns()` alongside the existing `pre_engine_ns`, and `m6_1_1_t_first_chunk_mono_ns = time.monotonic_ns()` alongside the existing `first_chunk_ns`. The first gives a wall-clock anchor for comparison against vLLM's `RequestStateStats.arrival_time` (the ingress gap); the second gives a monotonic anchor for comparison against `RequestStateStats.first_token_ts` (the egress gap). Confirmed feasible without an upstream vLLM contribution — `vllm/v1/engine/__init__.py:152` shows vLLM's engine-core monotonic timestamps use `time.monotonic()`, and the engine runs in-process with our servicer so the clocks are comparable. Classifier extends from M6.1.1's 5-bucket decision tree to 7-bucket with `proxy_ingress_dominated` / `proxy_egress_dominated` labels.

2. **Per-cohort prompt-content audit** ([item #5 spike note](../docs/spikes/m6-1-roadmap-additions/04-engine-compute-variation-rootcause.md)). Per-RPC tokenized prompt length + BLAKE2b-8 hash of the token id list captured on the wire (gRPC trailing metadata + REST SSE terminal event). Lets the classifier distinguish hypothesis H1 (prompt-content drift — most-likely root cause of the c=1 `engine_compute_variation`) from H2/H3/H4 (encoding drift, KV-cache prefix reuse, cohort-order warmup bias). The spike's investigation flagged a load-bearing context finding: M5.2 had prompt-symmetry enforcement (`m5_2_symmetry.py`); M6 / M6.1 / M6.1.1 dropped it. If the audit confirms H1, the M6.1.3 Phase B is to port M5.2's symmetric-prompts mode forward as the M6.x convention.

3. **Multi-run sweep + between-run variance compute** ([item #6 spike note](../docs/spikes/m6-1-roadmap-additions/05-run-to-run-variance.md)). `--m6_1_1-diagnose-repeat=N` CLI flag runs the existing Phase 1 sweep N times back-to-back, appending each to the existing `phase_1_runs[]` accumulator (the rehydration path landed in M6.1.1's expansion already supports this). New `compute_between_run_variance(phase_1_runs)` produces per-cohort per-cell `(mean_of_means, stddev_of_means, n_runs)`; new reporter section "Between-Run Variance" rendered when `phase_1_runs[] >= 3`. Classifier augmented with an `inconclusive_high_variance` label when between-run |Δ| outstrips a configurable fraction of within-run spread.

**Headline data motivating M6.1.3.** Computed directly from M6.1.1's two-run published artifact ([spike #6 note](../docs/spikes/m6-1-roadmap-additions/05-run-to-run-variance.md)):

| Cell | Between-run mean \|Δ\| | Within-run spread | Noise ÷ Signal |
|---|---:|---:|---:|
| chat_stream c=1 | 0.37 ms | 5.8 ms | 6–10% ✓ reproducible |
| chat_stream c=8 | 2.69 ms | 13–15 ms | 20–30% ⚠ marginal |
| chat_stream c=4 | 10.53 ms | 13–26 ms | 50–100% ✗ not reproducible |

The M6.1.1 published CIs capture sample noise only; they understate true cohort-comparison uncertainty at c=4. M6.1.3's multi-run characterization is what closes that gap.

**Modal compute budget.**

- Items #4 + #5-A baseline n=50 sweep, multi-run × 5: ~$1.45 (5 × ~$0.29).
- Item #6 Phase B n=200 single sweep: ~$1.16 (~60 min × A10G eu-west-1).
- **Total M6.1.3 Modal cost: ~$2.60**, comfortably under any reasonable per-milestone budget.

Optional follow-ups (only if A + B don't resolve): multi-deploy variance (~$1.70 more), multi-seed variance (~$1.45 more). Hard cap at ~$5.75 for the full experimental matrix.

**Output shape.** `docs/benchmarks/m6_1_3-attribution-closure.{md,json}` plus an updated `m6_1_1-engine-cost-instrumentation` annotation pointing forward.

- Per-cell attributed Phase 1 verdicts on chat_stream c=1 / c=4 / c=8 (one of: `engine_compute_variation`, `channel_dependent_batching`, `proxy_ingress_dominated`, `proxy_egress_dominated`, `engine_compute_variation`, `inconclusive_high_variance`, `inconclusive`).
- Per-cohort prompt-content audit table (token-count distribution per cohort; H1 confirmation or rejection).
- Between-run variance block (per-cell per-cohort stddev_of_means from the 5-run multi-sweep).
- `classifier_notes` field updated to the 7-bucket decision tree with multi-run augmentation.
- Spec decision: whether symmetric prompts become the M6.x convention going forward (binds M6.2 / M7 / M8 spec assumptions).

**Speckit cycle.** Run `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` against this section. M6.1.3 depends on M6.1.2 having landed first (the new cohort + traceroute infrastructure is in place); M6.2 depends on M6.1.3's resolved verdicts (the `max_tokens` axis's null anchors validate against M6.1.3's attributable Phase 1 baseline, not M6.1.1's `inconclusive` placeholders).

Out of scope: deeper attribution bisection if the proxy-edge probes show the remaining budget is, e.g., gRPC trailer-emit serialization (would become M6.1.4 territory); upstream vLLM contributions (the probes work entirely client-side); engine-config probes (prefix-caching disable, reversed cohort order) — only escalated to if items #4 / #5-A / #6-A multi-run doesn't resolve; corpus diversity (M7); multi-model (M8).

### M6.2 — Token-Budget Characterization (planned)

Re-run M6.1's narrow 6-cell × 3-cohort slice with **`max_tokens` lifted from a fixed cap to a 6-point measurement axis** (`10 / 50 / 256 / 512 / 1024 / 2048`) so the published latency budget covers the realistic production response-length regime, not just M5.x / M6 / M6.1's protocol-isolation regime. Same hardware (Modal A10G eu-west-1), same model (Qwen3-8B fp16, real prompt-embeds engine path from M6.1), same `max_model_len=2048` ceiling — `max_tokens` is the *only* variable that moves vs M6.1.1.

**Why a separate slice rather than bundling into M7.** M5.x / M6 / M6.1 deliberately held `max_tokens=10` (embed) / `max_tokens=50` (chat_stream) to keep engine work approximately constant, so the protocol/transport-cost differential was the signal. At realistic generation lengths the engine cost dominates: at `max_tokens=256` chat_stream completes in ~1.2–2.5s, making the 1-50 ms protocol-overhead differences M5.2/M6/M6.1 measured 2-5% of wall-clock — likely buried by run-to-run noise. **M6.2's operator question shifts** from *"which protocol wins under fixed engine work"* to *"what's the p50/p95/p99 latency budget per cohort at realistic response lengths, and at what `max_tokens` does protocol choice stop mattering?"*. Bundling into M7 (corpus diversity) would mix two variables in one verdict — exactly the methodological confound M6.1 was created to avoid. Phase Discipline (Constitution Principle III) keeps M6.2 narrow so the diff against M6.1's published JSON is unambiguous.

**Approach.** Reuse the M6.1 harness wholesale (engine config, RPC drivers, classifier primitives, smoke gate, torch-pin gate, M6 baseline loader — all already in place) **plus the symmetrised engine-cost instrumentation landed in M6.1.1** (without it the M6.2 null anchors can't function — see "Why before M6.2" in [§ M6.1.1](#m611--engine-cost-instrumentation-diagnosis--symmetrisation-planned-post-m61)). One change: the sweep orchestrator iterates `max_tokens ∈ {10, 50, 256, 512, 1024, 2048}` as an inner axis under each (cell × cohort) pair. Both embed and chat_stream cells vary the axis — embed's measurement becomes a hybrid engine-path + generation signal (informative for retrieval-then-generate workloads), while chat_stream remains a pure generation-latency measurement. The `max_tokens=10` and `max_tokens=50` points serve as null anchors: they should reproduce M6.1's measurements within published CIs (any drift surfaces as a chat_stream control-drift warning per FR-029-equivalent rule), validating that the M6.2 sweep wasn't compromised. `max_tokens=2048` (the `max_model_len` ceiling, set deterministically rather than "uncapped" to avoid EOS-sampling variance) probes the KV-cache-pressure-at-c=8 regime: 8 × 2048 = 16K tokens of needed KV cache against the ~31K-token budget — half-headroom; close enough to capacity that scheduling and prefix-caching dynamics may surface, far enough that OOM is unlikely.

**Report shape (different from M6.1).** Published artifacts are *not* a verdict-supersedes table — at realistic generation lengths most cells will classify `no_winner_at_n100` because generation dominates protocol. Instead M6.2 publishes:

- **Latency budget table** — p50 / p95 / p99 wall-clock per (cell × cohort × `max_tokens`) point (108 rows: 6 cells × 3 cohorts × 6 caps).
- **TPOT (time-per-output-token) curves** — chat_stream cohorts, becomes the primary throughput signal at `max_tokens ≥ 256`.
- **Engine-cost decomposition curves** — `engine_forward_ms` (embed) / `engine_ttft_ms` + `engine_tpot_ms` (chat_stream) per `max_tokens` point.
- **Protocol-crossover threshold** — for each cell, identify the smallest `max_tokens` at which the M6.1 cohort-pair CI overlap becomes statistically indistinguishable from "no winner". Tells the operator *"M6.1's verdict_survives at this cell holds up to `max_tokens=X`; above that the protocol choice doesn't matter"*.
- **KV-cache-pressure note** at `max_tokens=2048 × c=8` — fraction of KV cache budget consumed, scheduling-stall observation if any.

**Outputs.** `docs/benchmarks/m6_2-token-budget.{md,json}` plus a "Production latency budget" section. Drive with `python -m vllm_grpc_bench --m6_2 --m6_2-modal-region=eu-west-1`. Runtime budget: ~30 hours on Modal A10G — revised upward from the initial ~4-6 h estimate after M6.1's measured per-token rate (~33.7 ms/token) made the high-cap chat_stream cells the dominant cost. 10,800 RPCs total (108 measurement points × n=100) vs M6.1's 1,800; chat_stream cells dominate wall-clock because their per-RPC latency scales linearly with `max_tokens` (~580 ms at 10 tokens → ~69 s at 2048 tokens). Modal compute cost estimate: ~$20-30 (M6 was $0.87 at 1,800 RPCs; M6.2 is ~6× the RPC count but the high-cap RPCs each take ~70× longer at the tail). Still well under any practical budget; flagged here only for cost-projection accuracy. The JSON is a strict superset of M6.1's schema (FR-021-equivalent) so M6.1-aware consumers keep working.

**Speckit cycle.** Run `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` against this section after M6.1.1 publishes. M6.1.1's published JSON is M6.2's baseline reference (FR-008-equivalent hard precondition) — the `max_tokens=10` / `50` anchor points compare against M6.1.1's verdicts (which by then either have a clean per-cohort engine_ttft from the symmetrised instrumentation, or carry a documented channel-dependent-batching note) to validate sweep integrity.

Out of scope: corpus diversity (deferred to M7), additional models (deferred to M8), prompt-length variation in the embeddings (deferred to M7 — the *prompt* side is M7's axis, the *generation* side is M6.2's axis), `max_model_len` increase above 2048 (deferred to M8 — requires KV-cache budget re-tuning and likely a smaller model or larger GPU).

### M7 — Corpus Expansion (upcoming)

Re-run all three access paths against a larger, more varied prompt corpus covering short and long prompts, multi-turn conversations, and domain-specific content (code, structured data). Determine whether the M1 wire-size and latency findings hold across input diversity — do wire-size deltas change with longer prompts or multi-turn context windows, and does streaming TPOT variance increase with structurally different prompt types? M7 inherits M6's engine-cost-per-RPC baseline AND M6.2's per-`max_tokens` latency-budget tables so prompt-length scaling effects can be interpreted against a known real-engine cost floor and a known generation-length cost curve — rather than against MockEngine assumptions or a single fixed `max_tokens` point.

### M8 — Model Expansion (upcoming)

Repeat the M1, M3, M4, and M5 benchmarks with at least two additional models of different sizes and architecture families. Determine whether the wire-overhead thesis is model-agnostic or depends on tokeniser and output characteristics, and validate that the mock-derived findings from M3–M5 hold against real models. M8 extends M6's single-model-at-h=4096 mini-validation across canonical widths (h=2048 / 4096 / 8192) and architecture families; the M6 verdict structure is the starting hypothesis M8 tests against alternative models.

---

## Phase History (preserved as completed-work record)

The content below predates the milestone overlay above and is retained for the decisions and trade-offs it records. New phases of work are tracked under M3–M8 in the milestone roadmap; the Phase 1–7 framing here is read as history.

---

## 1. Project Overview

### Problem Statement

The OpenAI-compatible REST/JSON API used by vLLM (and most LLM serving stacks) carries non-trivial wire and parsing overhead per request: field-name strings repeat on every message, JSON tokenization is CPU-bound, and SSE-over-HTTP/1.1 is a poor fit for token streaming compared to gRPC's HTTP/2 multiplexed bidirectional streams. This project demonstrates whether replacing the wire format with protobuf-over-gRPC reduces that overhead in measurable ways without breaking compatibility for clients that only know the OpenAI REST surface.

### Goals (End-State)

By the end of the development cycle the project produces three artifacts and one functional demonstration.

The artifacts are:

1. **OpenAI REST → gRPC proxy server.** Accepts OpenAI-compatible chat completions and completions requests on its REST endpoint, translates them to protobuf, and forwards them via gRPC to the vLLM-side frontend.
2. **vLLM-side gRPC frontend.** Accepts protobuf/gRPC requests, translates them into `AsyncLLM` / `LLM` / `SamplingParams` calls, and returns protobuf responses. Effectively replaces the role of `vllm/entrypoints/openai/` for clients that come in via the proxy.
3. **Native gRPC Python client library** (`packages/client`). A standalone async Python library that sends protobuf/gRPC requests directly to the frontend, bypassing the REST proxy entirely. Demonstrates direct protocol access for Python-native consumers and provides the clean comparison baseline needed to isolate proxy overhead from protocol overhead in benchmarks.
4. **Test scripts and a benchmark harness** (curl + Python) that exercise the full pipeline end-to-end and measure wire-overhead claims against vLLM's native OpenAI server head-to-head.

The functional demonstration must show, end-to-end through the bridge:

- Chat completions, streaming and non-streaming
- Completions API with `prompt_embeds` (V0 vLLM path)

### Non-Goals (For This Cycle)

- OpenAI Batches API
- Authentication, multi-tenant routing, rate limiting, audit logging
- Production hardening (HA, TLS termination beyond minimum, observability beyond raw metrics)
- Caching layers (full-response cache, content dedup, prompt-prefix routing) — possible future work
- Non-Python proxy implementation (Go/Rust)
- Forking vLLM — sibling package only
- V1 prompt-embeds support (target V0)

### Audience

Python-shop developers and ML practitioners comfortable with vLLM, protobuf, gRPC, and FastAPI/asyncio. The demo is for them, not for end users.

---

## 2. Architecture Summary

### Topology

```
┌─────────────┐   OpenAI REST   ┌─────────────┐   protobuf/gRPC    ┌──────────────────┐
│   Client    │──(JSON / HTTP)─▶│    Proxy    │──(over HTTP/2)────▶│  vLLM Frontend   │
│ (curl/SDK)  │◀──(SSE / JSON)──│   Server    │◀──(stream/unary)───│ (AsyncLLM / LLM) │
└─────────────┘                 └─────────────┘                    └──────────────────┘
```

Both server processes run locally for the demo. Wire-format changeover happens at the proxy. The vLLM frontend imports `vllm` as a library and treats `AsyncLLM` / `LLM` / `SamplingParams` as the engine surface — exactly as `vllm/entrypoints/openai/` does today.

### Why a Sibling Package, Not a Fork

vLLM's serving frontend lives inside `vllm-project/vllm` at `vllm/entrypoints/openai/`. Forking the whole repo to replace that subtree would entangle this project with every upstream entrypoints refactor. A sibling package that depends on `vllm` as an ordinary library has zero upstream code entanglement, picks up engine improvements automatically, and follows the same architectural pattern as AIBrix and other `vllm-project/`-org sibling repos.

### Four Logical Components

- **`proto/`** — the shared protobuf schema. Source of truth for proxy, frontend, and client. Generated Python stubs are produced at build time, not committed.
- **`proxy/`** — FastAPI app exposing OpenAI REST endpoints, translating to protobuf, forwarding via a gRPC client.
- **`frontend/`** — gRPC server that imports `vllm` and translates protobuf RPCs into `AsyncLLM` / `LLM` / `SamplingParams` calls.
- **`client/`** — standalone async Python library that sends protobuf/gRPC requests directly to the frontend. Enables Python-native consumers to bypass the REST proxy and provides the direct-gRPC benchmark target needed to isolate proxy overhead from protocol overhead.

---

## 3. Technology Choices

### Confirmed

| Decision | Choice |
|---|---|
| License | MIT |
| Repository | Private GitHub repo (already provisioned) |
| Repository style | Monorepo |
| CI | GitHub Actions |
| Language | Python (both proxy and frontend) |
| Engine target | vLLM V0 path for prompt-embeds; current vLLM (V1) for chat completions |
| Target model | `Qwen/Qwen3-0.6B` |
| Dev hardware | M2 Pro MBP, 32 GB |
| API surface (in scope) | OpenAI Chat Completions + Completions (with `prompt_embeds`) |
| Streaming | Out of Phase 3, in by Phase 5 |
| Auth / multi-tenancy | Out of scope; single trusted client |
| Spec-kit agent | Claude Code |
| Knowledge graph | `graphify` (github.com/safishamsi/graphify) |

### Defaulted (Revisable in Phase 1)

| Decision | Default | Rationale |
|---|---|---|
| Python project tool | `uv` (workspaces) | Faster install/lock, modern, low-overhead in CI |
| Protobuf/gRPC library | `grpcio` + `grpcio-tools` (official) | Maximum compatibility; revisit `betterproto` if generated-code ergonomics hurt |
| gRPC server style | `grpc.aio` (asyncio gRPC) | Matches `AsyncLLM`'s async surface naturally |
| Proxy framework | `FastAPI` + `uvicorn` | Standard async REST, SSE support, familiar to the audience |
| Testing | `pytest` + `pytest-asyncio` | Standard |
| Linter / formatter / typecheck | `ruff` (lint + format), `mypy --strict` | Modern, fast |
| Task runner | `make` or `just` (pick one in Phase 1) | Simple, no debate |

### Deferred

| Question | Defer To |
|---|---|
| Where the prompt-embeds path actually runs (M2 vs CPU vs cloud GPU) | Phase 2 |
| Final protobuf schema for streaming chunks | Phase 5 |
| Backpressure & cancellation semantics | Phase 5 |
| Whether to expose `/v1/models` or stub it | Phase 3 |
| Final internal package names | Phase 1 (working names: `vllm_grpc_proxy`, `vllm_grpc_frontend`, `vllm_grpc_client`) |

---

## 4. Repository Structure (Proposed)

```
.
├── README.md
├── LICENSE                          # MIT
├── pyproject.toml                   # uv workspace root
├── .github/
│   └── workflows/
│       ├── ci.yml                   # lint, type, test
│       └── proto.yml                # protobuf compile check
├── .specify/                        # spec-kit artifacts
├── docs/
│   ├── PLAN.md                      # this document
│   ├── decisions/                   # ADRs
│   └── benchmarks/                  # phase-by-phase numbers
├── proto/
│   └── vllm_grpc/v1/
│       ├── chat.proto
│       ├── completions.proto
│       └── common.proto
├── packages/
│   ├── proxy/
│   │   ├── pyproject.toml
│   │   ├── src/vllm_grpc_proxy/
│   │   └── tests/
│   ├── frontend/
│   │   ├── pyproject.toml
│   │   ├── src/vllm_grpc_frontend/
│   │   └── tests/
│   └── client/                      # Phase 4.2+: direct gRPC Python client library
│       ├── pyproject.toml
│       ├── src/vllm_grpc_client/
│       └── tests/
├── scripts/
│   ├── curl/                        # curl-based test scripts
│   └── python/                      # Python-based test/benchmark scripts
└── tools/
    └── benchmark/                   # Phase 4 metrics harness
```

Final layout is locked in Phase 1.

---

## 5. Phase Plan

Each phase begins with a spec-kit `/specify` invocation that turns the phase goal below into a working specification, followed by `/plan` and `/tasks`. The phase is "done" when its exit criteria are met. A short retrospective is written into `docs/decisions/` before moving on.

---

### Phase 1 — Scaffolding

**Goal.** Bring the empty repo to the point where Claude Code, spec-kit, graphify, and GitHub Actions are all functioning, the monorepo skeleton is in place, and a "hello world" gRPC ping works between proxy and frontend.

**Inputs.** Empty private GitHub repo, MIT license, this plan.

**Deliverables.**

- Initialized monorepo with the structure in §4
- `uv` workspace configured for both packages
- Initial `proto/` with a `Health.Ping` RPC
- Generated stubs build cleanly via a single task (e.g. `make proto`)
- Minimal proxy server that responds to `GET /healthz`
- Minimal gRPC frontend that responds to `Health.Ping`
- End-to-end ping: proxy receives REST `/healthz`, calls `Health.Ping` over gRPC, returns OK
- GitHub Actions CI: lint, type-check, run unit tests, build proto stubs
- spec-kit initialized; `/specify`, `/plan`, `/tasks` produce expected artifacts
- graphify configured and indexing the repo
- Claude Code project config with this plan referenced
- README with developer onboarding instructions

**Exit criteria.**

- A new contributor can clone the repo, run a single bootstrap command, and see the proxy and frontend running with a working ping
- CI is green on `main`
- spec-kit produces useful spec artifacts when invoked
- graphify produces a useful graph

---

### Phase 2 — Prompt-Embeds Environment Investigation

**Goal.** Decide *where* the V0 prompt-embeds path will run, and document that decision before any chat-completions code is written. Avoids a late surprise in Phase 6.

**Inputs.** Phase 1 deliverables. Time-boxed: 2–3 days.

**Deliverables.**

- Investigation report at `docs/decisions/0001-prompt-embeds-environment.md` covering:
  - Whether `vllm-metal` on the M2 supports V0 fallback / `--enable-prompt-embeds`
  - Whether CPU-only vLLM on the M2 supports V0 fallback / `--enable-prompt-embeds`, and at what speed (Qwen3-0.6B, 50-token completion)
  - Cost and friction of running a small CUDA cloud instance (Modal / RunPod / Lambda L4) for Phase 6 only
- A decision: M2-vllm-metal, M2-CPU, or cloud-GPU-for-Phase-6 — with rationale
- A scripted setup for the chosen environment, runnable from a fresh machine
- A throwaway script that exercises `--enable-prompt-embeds` end-to-end (no bridge — direct to vLLM) to confirm the chosen environment actually works

**Exit criteria.**

- The chosen environment serves Qwen3-0.6B with `prompt_embeds` via vLLM's native OpenAI server end-to-end, with a known throughput number
- The setup script reproduces that environment from scratch on the dev machine

---

### Phase 3 — Minimal Non-Streaming Chat Completion Bridge

**Goal.** Prove the architecture end-to-end with the smallest possible scope. One REST endpoint, one unary RPC, one model, no streaming. **This is the "early successful demonstration" milestone.**

**Inputs.** Phase 1 scaffolding. The V0 question is parked.

**Deliverables.**

- `proto/vllm_grpc/v1/chat.proto` with a `ChatService.Complete` unary RPC and request/response messages covering enough of OpenAI's chat completion schema to round-trip a single-turn conversation: `messages` (role, content), `model`, `max_tokens`, `temperature`, `top_p`, `seed`. Stop there — feature surface is intentionally narrow.
- Proxy `POST /v1/chat/completions` handler that:
  - Rejects `stream: true` with a clear "not yet implemented in this phase" error
  - Translates the JSON request to protobuf
  - Calls `ChatService.Complete` over gRPC
  - Translates the protobuf response back to OpenAI JSON
- Frontend `ChatService.Complete` handler that:
  - Translates protobuf to `SamplingParams`
  - Calls `AsyncLLM.generate()` and awaits the final result
  - Returns the protobuf response
- `scripts/curl/chat-nonstreaming.sh` — curl example
- `scripts/python/chat-nonstreaming.py` — Python example using the `openai` SDK with `base_url` pointed at the proxy
- Unit tests for translation (JSON ↔ protobuf, protobuf → SamplingParams)
- Integration test that runs proxy + frontend together and exercises the curl path

**Exit criteria.**

- Both scripts produce sensible, deterministic completions (with a fixed seed)
- Integration test passes in CI (with a tiny stub model or a recorded fixture, to keep CI cheap)
- A live demo of the proxy + frontend running locally on the M2, from scratch, takes less than two minutes to bring up

---

### Phase 3.1 — Modal gRPC Frontend Deployment

**Goal.** Make the Phase 3 gRPC frontend deployable on Modal so that real GPU-backed benchmarks are possible. The M2 is adequate for local development and architecture validation, but its vLLM install is fragile and CPU-only numbers are not meaningful for the wire-overhead thesis. This phase produces a reproducible Modal deployment of `packages/frontend/` against which the Phase 4 harness can run real measurements.

**Inputs.** Phase 3 working bridge. ADR 0001 (Modal A10G confirmed as the viable compute environment).

**Deliverables.**

- `scripts/python/modal_frontend.py` — Modal app definition that:
  - Builds a `debian_slim(python_version="3.12")` image with `vllm==0.20.0` and the `vllm-grpc-frontend` wheel (or editable install from the workspace)
  - Exposes the gRPC server port via a Modal `@web_endpoint` tunnel or `allow_concurrent_inputs` function
  - Accepts the same `VLLM_MODEL` and gRPC listen address env vars already used by the local frontend
- `scripts/python/modal_vllm_rest.py` — Modal app definition for vLLM's native OpenAI REST server (the REST comparison target; mirrors the `verify_prompt_embeds_modal.py` pattern from Phase 2)
- Proxy config updated to accept a `GRPC_TARGET` env var so it can point at either localhost (local dev) or the Modal gRPC endpoint without code changes
- `scripts/curl/chat-nonstreaming-modal.sh` — smoke-test curl script that exercises the full path: local proxy → Modal gRPC frontend → vLLM on A10G
- Documentation in `docs/decisions/0002-modal-deployment.md` covering: container build approach, how to set `GRPC_TARGET`, known cold-start latency (excluded from benchmark timing), and teardown behavior

**Exit criteria.**

- `modal run scripts/python/modal_frontend.py` deploys the gRPC frontend and it responds to a `ChatService.Complete` RPC from the proxy
- The smoke-test curl script produces a deterministic completion (fixed seed) against the Modal endpoint
- Cold-start time is documented; the deploy-then-benchmark sequence is scripted so it can be reproduced from a fresh machine with only `modal token new` as a prerequisite

---

### Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Goal.** Establish the network path that Phase 3.1 deferred: the proxy runs on the developer's local workstation (M2), the gRPC frontend runs on Modal A10G, and protobuf/gRPC frames travel over an actual network connection between them. This is the only topology that exercises the wire-efficiency thesis, and it is a prerequisite for Phase 4.1 real benchmarks.

**Background.** Phase 3.1 placed both the proxy and the gRPC frontend as subprocesses inside the same Modal container (`FRONTEND_ADDR=localhost:50051` intra-container). This validated end-to-end functional correctness on GPU, but no protobuf bytes ever traversed a network. The original Phase 3.1 exit criteria in this plan called for "a ChatService.Complete RPC from the proxy" — meaning a separately-running proxy. Phase 3.2 closes that gap. Modal is currently the only GPU environment available; this phase is therefore the only credible means to test the prototype under real conditions.

**Approach.** Use `modal.forward(port, unencrypted=True)` to expose the gRPC frontend's TCP port from inside the Modal container as a stable external `host:port`. The proxy's existing `FRONTEND_ADDR` env var is set to this address — no proxy code changes required. The key design constraint is to avoid the generator-yield-inside-forward pattern flagged as unreliable in Phase 3.1 research (R-001). Instead, the Modal function blocks with a sleep loop (no `yield`), and the tunnel address is communicated to the local entrypoint via a `modal.Dict` shared-state object.

**Primary unknown to validate.** Whether `modal.forward(unencrypted=True)` correctly passes persistent HTTP/2 connections carrying gRPC frames. gRPC keeps connections alive with PING frames; the tunnel must tolerate this without dropping the connection. This must be confirmed empirically before implementation is considered complete.

**Inputs.** Phase 3.1 Modal deployment. Phase 3 working bridge (`packages/proxy/`, `packages/frontend/`).

**Deliverables.**

- `scripts/python/modal_frontend_serve.py` — long-lived Modal app that:
  - Starts the vLLM gRPC frontend subprocess inside Modal A10G (same image and volume as Phase 3.1)
  - Polls `Health.Ping` until the server is ready and records `cold_start_s`
  - Opens a `modal.forward(50051, unencrypted=True)` tunnel and writes the tunnel address (`host:port`) to a `modal.Dict` shared-state object
  - Blocks (sleep loop, no `yield`) until the function timeout, keeping the tunnel alive
  - Local entrypoint polls the `modal.Dict` for the tunnel address, prints it as `export FRONTEND_ADDR=<addr>`, and then blocks waiting for Ctrl+C; on exit the Modal app tears down automatically
- `Makefile` target `modal-serve-frontend`: `uv run --with modal modal run scripts/python/modal_frontend_serve.py`
- Updated `docs/decisions/0002-modal-deployment.md`: document the Phase 3.2 tunnel approach, the `modal.Dict` address-communication pattern, observed HTTP/2 tunnel behavior, and the validated local-proxy → Modal-gRPC topology
- Manual validation: start the proxy locally with `FRONTEND_ADDR` set to the Modal tunnel address; run `scripts/curl/chat-nonstreaming-modal.sh` and confirm a deterministic completion is returned

**Exit criteria.**

- `make modal-serve-frontend` brings up the gRPC frontend on Modal A10G and prints a stable `FRONTEND_ADDR=<host>:<port>` to the developer's terminal
- The proxy, started locally with that `FRONTEND_ADDR`, sends a `ChatService.Complete` request that travels as protobuf over the `modal.forward` tunnel and returns a valid, deterministic completion (`seed=42`)
- The tunnel remains stable for at least one full request/response cycle; any instability is documented
- `docs/decisions/0002-modal-deployment.md` is updated with the validated topology and any observed `modal.forward` behavior (PING handling, connection drops, reconnection)
- All new `.py` files pass `ruff` and `mypy --strict`

---

### Phase 4 — Metrics and Test Harness

**Goal.** Build the measurement infrastructure *before* adding more feature surface, so every later phase lands with numbers attached.

**Inputs.** Phase 3 working bridge.

**Deliverables.**

- A benchmark harness in `tools/benchmark/` that can:
  - Replay a fixed corpus of requests through (a) the proxy → frontend bridge, and (b) vLLM's native OpenAI server, head-to-head
  - Measure: wire bytes per request and per response, end-to-end latency (P50/P95/P99), throughput at concurrency, proxy CPU time per request
  - Emit a CSV/JSON report and a small markdown summary
- Baseline numbers for the Phase 3 non-streaming chat completion path, committed to `docs/benchmarks/phase-3-baseline.md`
- A GitHub Actions job that runs the benchmark on PRs touching proxy or frontend, and posts a regression comment
- Documentation: how to read the report, how to add a new metric

**Exit criteria.**

- A single `bench` task produces a head-to-head report on the dev machine in under five minutes
- The report shows whether the bridge is faster, slower, or neutral on each metric — honestly, no thumb on the scale
- CI regression comment works on a sample PR

---

### Phase 4.1 — Real Comparative Baselines (Modal)

**Goal.** Replace the stub-run baseline files committed in Phase 4 with real GPU-backed numbers that actually test the wire-overhead thesis. Because Modal functions are ephemeral, the two targets (REST and gRPC) cannot be held alive simultaneously; benchmarks are run sequentially and the harness's existing compare path stitches the two result files into a single report.

**Inputs.** Phase 3.2 validated local proxy → Modal gRPC tunnel. Phase 3.1 REST comparison deployment. Phase 4 benchmark harness.

**Deliverables.**

- `scripts/python/bench_modal.py` — orchestration script that:
  1. Deploys (or reuses a running) `modal_vllm_rest.py` app, waits for it to be healthy, runs the harness corpus against it, saves `results-rest.json`, then tears down
  2. Deploys `modal_frontend.py` (proxy + gRPC frontend pair), waits for health, runs the same corpus, saves `results-grpc.json`, then tears down
  3. Calls the harness `compare` module with the two result files and writes the comparison report to `docs/benchmarks/`
  - Cold-start time (Modal provisioning) is measured separately and excluded from per-request latency numbers; it is recorded in run metadata for transparency
  - Each run embeds `git_sha`, `hostname`, Modal function ID, and GPU type in its `RunMeta` so results are fully traceable
- Updated harness CLI: `--result-a` / `--result-b` flags (or `bench compare <file-a> <file-b>`) for the offline compare path, so the two sequential JSON files can be diffed without re-running
- `docs/benchmarks/phase-3-modal-rest-baseline.json` and `.md` — real REST results (committed from dev machine after first successful run)
- `docs/benchmarks/phase-3-modal-grpc-baseline.json` and `.md` — real gRPC results (committed from dev machine after first successful run)
- `docs/benchmarks/phase-3-modal-comparison.md` — head-to-head summary: P50/P95/P99 latency, wire bytes per request/response, throughput at each concurrency level, for REST vs gRPC; honest framing with no metric selectively omitted
- `Makefile` target `bench-modal` that runs `bench_modal.py` end-to-end

**Exit criteria.**

- `make bench-modal` runs both deployments sequentially, collects results, and writes the comparison report without manual intervention
- Cold-start latency is visible in run metadata but excluded from reported P50/P95/P99
- The comparison report honestly shows whether gRPC is faster, slower, or neutral on each metric against vLLM-native REST on the same A10G hardware
- Baseline JSON files are committed and the CI harness can detect regressions against them on future PRs

---

### Phase 4.2 — Direct gRPC Client Library and Three-Way Benchmark

**Goal.** Create a standalone Python client library (`packages/client`) that sends protobuf/gRPC requests directly to the gRPC frontend, bypassing the REST proxy entirely. This is the first benchmark that isolates proxy overhead from protocol overhead: the three-way comparison (REST / gRPC-via-proxy / gRPC-direct) shows whether gRPC itself is faster than REST once the translation layer is removed.

**Background.** Phase 4.1 revealed that the ~530% latency delta between REST and gRPC is driven by the proxy translation hop (local REST→gRPC) and the additional tunnel segment, not by the frontend itself. A native gRPC client connecting directly to the frontend is expected to show latency much closer to REST, with potential gains from protobuf serialization efficiency. Phase 4.2 proves or disproves this empirically.

**Inputs.** Phase 4.1 baselines (REST and gRPC-via-proxy). Phase 3 working bridge (`packages/gen` stubs, `packages/frontend`).

**Deliverables.**

- `packages/gen`: add `py.typed` marker so the compiled stubs are fully typed. All consumers (proxy, frontend, client) must pass `mypy --strict` with no `# type: ignore[import-untyped]` for gen imports after this change.
- `packages/client` — new workspace package `vllm_grpc_client` that:
  - Manages a persistent gRPC channel (reused across requests; not opened/closed per call)
  - Exposes `async with VllmGrpcClient("host:port") as client:` context manager
  - `await client.chat.complete(messages, model, max_tokens, ...)` for non-streaming — returns a typed response object; does not require callers to construct protobuf messages directly
  - Handles timeouts, connection errors, and channel teardown cleanly
  - Ships with `py.typed`; passes `mypy --strict` with no suppressions
- A `gRPC-direct` benchmark target in `tools/benchmark/` (new runner path in `runner.py` or a parallel module) that uses `vllm_grpc_client` instead of httpx to drive requests against the frontend
- `make bench-modal-three-way`: extended `bench_modal.py` (or a new script) that runs REST, gRPC-via-proxy, and gRPC-direct sequentially on Modal A10G, then produces a three-way comparison report
- `docs/benchmarks/phase-4.2-three-way-comparison.md` — the definitive comparison: REST vs gRPC-via-proxy vs gRPC-direct, at each concurrency level, on the same A10G hardware
- `scripts/python/grpc_client_demo.py` — annotated demo showing the client library used end-to-end from a developer workstation against the Modal-deployed frontend

**Exit criteria.**

- `VllmGrpcClient` completes a chat request against the Modal-deployed frontend end-to-end with no proxy involved
- `mypy --strict` passes on `packages/client` and on `packages/gen` with no `# type: ignore[import-untyped]` for gen imports
- The three-way benchmark report is committed to `docs/benchmarks/`; it shows gRPC-direct latency compared honestly against both REST and gRPC-via-proxy
- The gRPC-direct path demonstrates whether protocol-level efficiency is measurable once proxy overhead is eliminated

---

### Phase 5 — Streaming Chat Completions

**Goal.** Bridge OpenAI SSE chat completions through the proxy and a server-streaming gRPC RPC. This is where the project's wire-overhead thesis becomes most testable. The `packages/client` library gains a streaming method in this phase so direct-gRPC streaming can be benchmarked alongside proxy streaming.

**Inputs.** Phase 4.2 client library and three-way benchmark baseline.

**Deliverables.**

- `ChatService.CompleteStream` server-streaming RPC and chunk message in proto
- Proxy support for `stream: true`, emitting OpenAI-formatted SSE deltas terminated by `data: [DONE]`
- Frontend driving `AsyncLLM.generate()` as an async generator and yielding protobuf chunks
- Backpressure: gRPC flow control propagates to the AsyncLLM iteration
- Cancellation: client disconnect → cancel gRPC stream → cancel the generation task
- Mid-stream error path documented and tested
- `packages/client`: `await client.chat.complete_stream(...)` async generator yielding typed chunk objects — direct-gRPC streaming without the proxy
- Curl + Python streaming test scripts (proxy path and direct-gRPC client path)
- TTFT and TPOT measurements added to the benchmark harness for both the proxy path and the direct-gRPC client path
- ADR in `docs/decisions/` documenting the streaming design choices (chunk granularity, error encoding, backpressure model)

**Exit criteria.**

- Streaming produces the same final completion as non-streaming for a deterministic seed, via both the proxy path and the direct `VllmGrpcClient` path
- TTFT and TPOT numbers are within an explainable range of vLLM-native — equal or better preferred, but the goal is honesty, not winning
- Cancellation actually stops generation server-side (verifiable in logs / metrics)
- `mypy --strict` passes on the updated `packages/client` streaming methods

---

### Phase 6 — Completions API with Prompt Embeds (V0)

**Goal.** Add the `/v1/completions` endpoint with `prompt_embeds` support, end-to-end, in the environment chosen in Phase 2. The `packages/client` library gains a completions method so the prompt-embeds path can be exercised via direct gRPC as well as via the proxy.

**Inputs.** Phase 2 environment decision; Phase 5 streaming infrastructure (reusable for streaming completions); Phase 4.2 client library.

**Deliverables.**

- `proto/vllm_grpc/v1/completions.proto` with unary and server-streaming RPCs
- A `prompt_embeds` field carrying the base64-encoded torch tensor as `bytes` (decoded server-side; on the wire it's already binary)
- Proxy `POST /v1/completions` handler that accepts both `prompt` (string) and `prompt_embeds` (in `extra_body`, matching vLLM's existing convention)
- Frontend handler that decodes `prompt_embeds` and passes the tensor to `AsyncLLM.generate()` correctly under V0
- `packages/client`: `await client.completions.complete(prompt_embeds=...)` method exposing the prompt-embeds path without the proxy; callers pass a tensor directly and the client handles binary encoding
- Curl + Python test scripts demonstrating: client computes embeddings locally from chat-template-formatted token IDs, sends via the proxy (curl/openai-SDK path) and directly via `VllmGrpcClient` (Python-native path)
- Benchmark harness extension comparing wire size of (a) text prompt and (b) prompt embeddings — this is one of the most interesting wire-overhead cases in the project, since prompt embeddings are pure binary tensors and JSON's base64 expansion is roughly 33% bloat that protobuf avoids entirely

**Exit criteria.**

- A client can drive completions end-to-end via prompt-embeds, both through the proxy and via `VllmGrpcClient` directly
- Outputs match outputs from the vLLM-native server with the same prompt-embeds input (token-level equivalence with deterministic seed)
- Wire-size comparison numbers are recorded
- `mypy --strict` passes on the updated `packages/client` completions methods

---

### Phase 6.1 — Prompt Embedding Engine Flag

**Goal.** Enable the `completion-embeds` paths (proxy and gRPC-direct) to produce real latency/throughput numbers by passing `enable_prompt_embeds=True` to `AsyncEngineArgs` in the gRPC frontend.

**Inputs.** Phase 6 infrastructure (completions proto, servicer, proxy router, client methods). Finding documented in `docs/notes/vllm-embedding-input-limitation.md` corrected: root cause is a missing engine flag, not a missing vLLM API. `AsyncLLMEngine` in vLLM 0.19/0.20 is an alias for `AsyncLLM` (the v1 engine), which supports `prompt_embeds` input but only when the flag is set.

**Deliverables.**

- `packages/frontend/src/vllm_grpc_frontend/main.py` — `enable_prompt_embeds=True` added to `AsyncEngineArgs`
- `docs/notes/vllm-embedding-input-limitation.md` — root cause corrected; status updated to fixed
- `docs/PLAN.md` — this phase entry
- Modal benchmark re-run confirming `completion-embeds` paths produce real `resp_bytes_mean` / `success=True` results

**Exit criteria.**

- `make check` passes (mypy --strict, ruff, pytest)
- Modal benchmark shows `success=True` for both gRPC-direct and proxy `completion-embeds` rows with real latency and wire-size numbers committed to `docs/benchmarks/`

---

### Phase 7 — Demo Polish

**Goal.** Turn the working system into a 10-minute demo plus a self-contained README walkthrough. The demo covers all three access paths: REST via the proxy, gRPC via the proxy, and direct gRPC via `VllmGrpcClient`.

**Deliverables.**

- Polished README: what the project is, the wire-overhead thesis, how to run it locally in under five minutes, a one-paragraph summary of measured benefits
- A `demo/` directory with:
  - One curl script (OpenAI REST via proxy)
  - One Python script using `openai` SDK (OpenAI REST via proxy)
  - One Python script using `vllm_grpc_client` directly (native gRPC, no proxy)
  - One streaming Python script (SSE via proxy)
  - Each script annotated and runnable end-to-end
- A short benchmark write-up at `docs/benchmarks/summary.md` covering the headline numbers for all three paths across non-streaming and streaming
- Optional: a screen capture or asciinema of the demo

**Exit criteria.**

- A new viewer who has heard nothing about the project can read the README and run the demo locally on the M2 in under ten minutes
- The benchmark summary covers REST / gRPC-via-proxy / gRPC-direct and is written so that a sympathetic but honest reviewer would call it fair
- All three `demo/` scripts run without modification against a locally-deployed frontend

---

## 6. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| V0 prompt-embeds doesn't run on Apple Silicon | Medium | Medium | Phase 2 investigates explicitly; cloud-GPU fallback is named |
| V0 path gets deprecated mid-project | Low | High | Replan if it happens; demo what works pre-deprecation |
| OpenAI schema drift during the project | Low | Low | Demo targets a fixed schema slice; not aiming for full passthrough |
| gRPC streaming bridging is harder than estimated | Medium | Medium | Phase 5 is dedicated and lands after metrics tooling is in place |
| `vllm-metal` plugin is V1-only and breaks chat completions on M2 | Low–Medium | Medium | Phase 1 verifies; CPU-only vLLM is the fallback |
| Wire-overhead savings turn out to be negligible for this workload | Medium | High to thesis, low to demo | Honest reporting in Phase 4; the demo is still informative regardless |

---

## 7. Open Questions and Decisions to Revisit

- Final names for the two Python packages (working names used here)
- Whether to ship a `Dockerfile` for the demo environment in Phase 7
- Whether to publish to PyPI in Phase 7 or keep the repo private
- Whether to write up the project as a vLLM RFC or blog post (Phase 7+)

---

## 8. Working with Claude Code and spec-kit

For each new phase:

1. Read this plan's section for the phase.
2. In Claude Code, run `/specify` with the phase goal and deliverables as input.
3. Iterate on the spec until exit criteria are reflected as testable requirements.
4. Run `/plan` to break the spec into a build plan.
5. Run `/tasks` to generate the per-step task list.
6. Have Claude Code execute tasks one at a time, reviewing diffs before commit.
7. Update `docs/decisions/` with any non-obvious choices made along the way.
8. Run benchmarks (Phase 4 onward); commit the results.
9. Mark the phase complete in this document; write a brief retrospective.

Re-index `graphify` at the start of each phase to give Claude Code an updated knowledge graph of the codebase as it grows.

---

*End of plan v1.*
