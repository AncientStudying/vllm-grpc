# vllm-grpc

A Protobuf/gRPC frontend for vLLM that measures wire-size and protocol-overhead tradeoffs for LLM inference. The core thesis: replacing the OpenAI JSON wire format with protobuf-over-gRPC reduces response size by up to 89% for chat completions and 25% for embed request payloads.

> **Affiliation:** vllm-grpc is an independent, community project and is not affiliated with, endorsed by, or sponsored by the vLLM project or its maintainers. "vLLM" is used here only to identify the inference engine this frontend works with.

---

## What is this?

vLLM's default interface is an OpenAI-compatible REST API. JSON is human-readable but verbose: a typical chat completion response is 611 bytes of JSON wrapping ~10 tokens of actual text. Protobuf encodes the same response in 65 bytes.

This project builds a gRPC frontend that sits in front of vLLM and exposes a proto-defined `ChatService` and `CompletionsService`. It measures wire overhead across three access paths and commits benchmark JSON to `docs/benchmarks/` so results are reproducible. It is a structured measurement exercise, not a production system.

---

## Three Access Paths

```
                          ┌──────────────────────┐
REST client ────────────► │                      │
                          │   gRPC proxy (:8000) │ ──► gRPC frontend (:50051) ──► vLLM
OpenAI SDK  ────────────► │   (FastAPI)          │
                          └──────────────────────┘

VllmGrpcClient ─────────────────────────────────► gRPC frontend (:50051) ──► vLLM
```

| Path | Client | Wire format | Proxy hop | When to use |
|------|--------|-------------|-----------|-------------|
| REST via proxy | curl, openai SDK | JSON | Yes | Drop-in for any OpenAI client |
| gRPC via proxy | same REST clients | JSON → gRPC (proxy translates) | Yes | Baseline for proxy overhead |
| gRPC-direct | `VllmGrpcClient` | Protobuf | No | Smallest wire size; isolates protocol overhead |

The gRPC-direct path is where the wire-size thesis is tested: raw proto bytes, no proxy.

---

## Prerequisites

- macOS (M2/M3) or Linux x86-64
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` — macOS: `xcode-select --install`; Linux: pre-installed
- A vLLM-compatible model (the frontend loads it via `MODEL_NAME`)
- For Modal GPU benchmarks: `modal token new`

---

## Quick Start

```bash
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap                              # install deps + generate proto stubs
make run-frontend                           # terminal 1 — gRPC server on :50051
make run-proxy                              # terminal 2 — REST proxy on :8000

# Demo scripts (any terminal)
bash demo/curl-rest.sh                      # REST via curl
uv run python demo/openai-sdk.py            # REST via openai SDK
uv run python demo/grpc-direct.py           # gRPC-direct (no proxy)
uv run python demo/streaming.py             # streaming SSE via proxy
```

Each demo reads an environment variable for the endpoint:

| Script | Variable | Default |
|--------|----------|---------|
| `demo/curl-rest.sh` | `PROXY_BASE_URL` | `http://localhost:8000` |
| `demo/openai-sdk.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |
| `demo/grpc-direct.py` | `FRONTEND_ADDR` | `localhost:50051` |
| `demo/streaming.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |

---

## Install (PyPI)

The four packages publish to PyPI independently. Pick the one for your role —
the shared `vllm-grpc-gen` stubs package installs transitively, so you never
install it directly.

| Role | Install | What you get |
|------|---------|--------------|
| **SDK consumer** | `pip install vllm-grpc-client` | Lean async gRPC client; no web-server deps |
| **Proxy operator** | `pip install vllm-grpc-proxy` | REST→gRPC proxy + `vllm-grpc-proxy` console script |
| **Frontend operator** | `pip install vllm-grpc-frontend` | gRPC server + `vllm-grpc-frontend` console script |

**Frontend + vLLM engine.** `pip install vllm-grpc-frontend` does **not** pull
vLLM, so it installs on any platform. The frontend drives vLLM's **V1 `AsyncLLM`**
API, which needs `vllm>=0.20`. Get it via the opt-in extra:

```bash
pip install "vllm-grpc-frontend[engine]"     # pulls vllm>=0.20
```

…or install vLLM yourself for your platform (e.g. macOS uses `vllm-metal`). A
missing engine surfaces only at runtime, never as an install failure.

---

## Benchmark Headlines

The structural, topology-immune wins from M1 (Modal A10G, vLLM 0.20.0, `Qwen/Qwen3-0.6B`): gRPC-direct cuts chat completion response bytes by **89%** (611 B → 65 B) and embed request bytes by **25%** (raw float32 vs base64 JSON). Latency results vary by deployment topology — same-fabric (M5.1) vs managed-edge-provider (M5.2) findings apply to different audiences. **As of M6.1.2 the topology is captured machine-readably in every sweep artifact** under the `network_paths` top-level key, so verdict reads no longer depend on a static assumption about which CSP a cohort lands in (a 9-hour spike → validation-sweep drift on 2026-05-17 demonstrated why per-sweep evidence is necessary). See [`ANALYSIS.md`](ANALYSIS.md) for the per-milestone narrative + topology guide and [`contracts/instrumentation.md`](contracts/instrumentation.md) for the artifact-schema reference.

---

## Topology Recommendations

Pick by deployment shape; the same-fabric and managed-edge audiences are both first-class. The M6.2 token-budget publish sweep (n=40, 2026-05-26) confirms both directions under tighter CI than the earlier M5.1 / M5.2 reads: REST-edge's anchor advantage widened to ~25–26%, and gRPC's `c=8` wall-clock advantage at `chat_stream_c8 × max_tokens=10` widened to +15.6% (tuned-gRPC vs plain REST). At `c=1` the protocols are statistically indistinguishable — choose on operational simplicity.

| Topology | Audience | Recommendation |
|---|---|---|
| Client ↔ managed-provider with anycast HTTPS edge | Hobbyist or enterprise tenant on Modal / RunPod / Replicate / similar | **Use REST over the HTTPS edge.** The edge POP terminates HTTP/2 + TLS near the client, amortising handshake + framing costs end-to-end protocols can't avoid. The advantage holds across the `max_tokens` axis. |
| Client + server inside the same enterprise network | Corporate-internal deployments, well-connected colo, datacenter | **Use gRPC for `c≥4` workloads.** Wire-transmission cost is 10–55% lower than plain REST across the matrix; wall-clock advantage at `c=8` is +10–16%. At `c=1` the protocols are statistically indistinguishable — choose on operational simplicity. |
| Hobbyist self-hosting | DIY / homelab on LAN, single-host or LAN-local | Same as same-fabric — **gRPC for `c≥4`**. No managed edge available to flip the verdict. |
| Enterprise with internal anycast / edge infrastructure | Global SaaS fronting REST with their own edge layer | Same as managed-provider — **use REST through the edge layer**. Same dynamics as a managed edge POP. |

The bytes-axis wins from M1 (chat response −89%, embed request −25%) are topology-immune and apply to every deployment shape. The full guide with per-milestone provenance is in [`ANALYSIS.md`](ANALYSIS.md#topology-guide--which-milestone-result-applies-to-your-deployment).

---

## Roadmap

Milestone-by-milestone findings live in [`ANALYSIS.md`](ANALYSIS.md); per-milestone benchmark reports under [`docs/benchmarks/`](docs/benchmarks/) are the source-data record. The milestone IDs (M1, M5.1, M5.2, …) and shorthand (TTFT, TPOT, KV, CSP, cohort, cell, `c=N`) used below are defined once in the [ANALYSIS.md glossary](ANALYSIS.md#glossary).

- **M1** — Three access paths benchmarked on Modal A10G; 89% chat / 25% embed wire-size wins. [`ANALYSIS.md § M1`](ANALYSIS.md#m1--foundation).
- **M2** — Cross-repo ground-truth research practice formalised (vLLM + grpcio). [`ANALYSIS.md § M2`](ANALYSIS.md#m2--cross-repo-ground-truth-research).
- **M3** — Four-axis channel sweep at canonical embed widths; bytes uniformly `no_winner`, time axis surfaced 4 wins (PR #17, PR #19). [`ANALYSIS.md § M3`](ANALYSIS.md#m3--protobuf--grpc-tuning).
- **M4** — Time-axis harness redesign + definitive sweep; `max-msg-16mib` recommend at `embed/h=2048`. [`ANALYSIS.md § M4`](ANALYSIS.md#m4--time-axis-channel--schema-tuning).
- **M5** — Cross-host re-run resolved M4's loopback caveat; 5 channel-config wins at `embed/h=2048` (-23% to -25%). [`ANALYSIS.md § M5`](ANALYSIS.md#m5--cross-host-time-axis-validation).
- **M5.1** — REST vs gRPC head-to-head on the **same-fabric** topology (enterprise/homelab audience). [`ANALYSIS.md § M5.1`](ANALYSIS.md#m51--rest-vs-grpc-head-to-head-on-real-wire).
- **M5.2** — REST vs gRPC across HTTPS-edge and plain-TCP; **managed-edge-provider** topology (hobbyist tenant audience). [`ANALYSIS.md § M5.2`](ANALYSIS.md#m52--rest-transport-path--grpc-tuning-surface).
- **M6** — Real-engine mini-validation (delivered 2026-05-15): Qwen3-8B on Modal A10G, narrow 6-cell slice of the M5.2 matrix; 4 of 6 cells overturned M5.2 verdicts under real engine cost (M5.2's "REST wins at c≥4" did NOT hold). [`ANALYSIS.md § M6`](ANALYSIS.md#m6--real-engine-mini-validation).
- **M6.1** — Real-prompt-embeds engine path (delivered 2026-05-16): re-runs M6's 6-cell slice with vLLM's `enable_prompt_embeds=True` driven by `torch.save(tensor)` bytes; tally 1 verdict_survives / 2 verdict_buried_by_engine / 3 no_winner_at_n100; real prompt-embeds engine path costs ~338 ms per RPC at h=4096 (~7-8× the text-digest path), and ~33.7 ms/token steady-state generation rate falls out cleanly. [`ANALYSIS.md § M6.1`](ANALYSIS.md#m61--real-prompt-embeds-engine-path).
- **M6.1.1** — Engine-cost instrumentation diagnosis & symmetrisation (delivered 2026-05-17 via PR #27 merge). M6.1.1's Phase 1 re-runs under M6.0a-corrected concurrent dispatch published at [`docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`](docs/benchmarks/m6_1_1-engine-cost-instrumentation.md). The original FR-010 classifier was degenerate (`seg_bc_ms ≡ engine_ttft_ms` by construction) and was upgraded **in-branch** to a 5-bucket scheme using vLLM's `RequestStateStats` engine-internal timestamps (`seg_queue` = scheduler queue wait; `seg_prefill` = post-schedule compute). Verdicts: chat_stream c=1 → `engine_compute_variation` (99.8% of 5.77 ms cohort spread in `seg_prefill`; reproducible across runs); chat_stream c=4 + c=8 → `inconclusive`. The c=4 / c=8 unattributed budget (~17 ms / ~5 ms of cohort spread not explained by `seg_ab` / `seg_queue` / `seg_prefill`) was the open Phase 2 gap, now closed by M6.1.3 below (the published markdown carries a leading-note annotation forwarding to M6.1.3 for attributed per-segment labels and variance characterization). **Separate negative result preserved**: `seg_queue ≤ 0.02 ms across all 18 cohort×cell pairs`, empirically falsifying the continuous-batching hypothesis (the engine scheduler picks up every request within ~10µs of arrival). The audit baseline (sequential dispatch, classifier-degenerate) is preserved at [`docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md`](docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md). Drive with `python -m vllm_grpc_bench --m6_1_1-diagnose` (Phase 1 mini-sweep) then `--m6_1_1` (Phase 2 fix-or-document; the per-segment data now lives in M6.1.3's canonical artifact).
- **M6.0a** — Concurrent dispatch restoration (delivered 2026-05-17): corrective methodology fix discovered during M6.1.1's first live run. M5.1 / M5.2 used `asyncio.gather`-based concurrent client-side dispatch at cell concurrency c; M6 / M6.1 / M6.1.1 silently dropped this and used sequential `await driver(...)` loops, making the cell's `concurrency` field a metadata tag rather than an in-flight parallelism control. Restored canonical dispatch in five harness entry points (`m6_sweep._run_warmup` / `_run_measurement`, `m6_1_sweep._run_warmup_m6_1` / `_run_measurement_m6_1`, `m6_1_1_sweep._measure_cell`) plus path-agnostic regression test ([`tools/benchmark/tests/test_m6_concurrent_dispatch.py`](tools/benchmark/tests/test_m6_concurrent_dispatch.py), 18 parametrisations). Corrected M6.1.1 Phase 1 re-run completed in 15.6 min at $0.29 Modal A10G `eu-west-1`. Headline: c=4 / c=8 chat_stream per-cohort `engine_ttft_ms` spread *grew* from the audit baseline's 6.0% / 8.4% to 15.9% / 16.4% under real concurrency — disproves the "sequential-dispatch state-drift artifact" hypothesis cleanly. M6 / M6.1 main verdicts are dispatch-robust; only the M6.1 per-cohort drift sub-finding is dispatch-sensitive (re-interpreted via cross-link). Full bug + fix + before/after comparison + per-finding sensitivity classification in [`docs/benchmarks/m6_0a-dispatch-correction.md`](docs/benchmarks/m6_0a-dispatch-correction.md). [`ANALYSIS.md § M6.0a`](ANALYSIS.md#m60a--concurrent-dispatch-restoration).
- **M6.1.2** — Methodology discipline: per-sweep topology evidence + restored `rest_plain_tcp` cohort + timestamped progress (delivered 2026-05-17, PR #30). Three additions bundled before M6.2 so M6.2 / M7 / M8 inherit the new sweep convention: (1) **per-sweep `tcptraceroute` probe** runs once at sweep start, parallel across cohorts with a 30 s per-cohort timeout, writes per-cohort topology to artifact JSON under `network_paths` (`endpoint_ip`, ordered `hops` with per-hop best-effort CSP annotation, cohort-level `cloud_provider` enum, `region`, timestamp). The PR-validation sweep documented a 9-hour topology drift: spike (2026-05-17 ~11 UTC) showed cohorts in Azure + AWS multi-region; T037 sweep (~20 UTC) found Modal had consolidated all 4 cohorts into AWS us-east-1. FR-006's cohort-CSP-mismatch warning fired loudly, surfacing the methodology-significant change exactly as designed. (2) **reintroduced `rest_plain_tcp` cohort** (last present in M5.2) gives the 4-cohort split: with all cohorts in the same region now, `rest_plain_tcp` vs `default_grpc` isolates protocol-only cost cleanly — for embed cells gRPC is ~50-100 ms faster across c=1/4/8; for chat_stream the differential is in the noise (<5 ms cohort spread vs ~1500 ms engine generation). **Re-classifies M5.2 / M6's "HTTPS edge wins" finding as a multi-cloud-routing artifact, not a protocol effect.** (3) **ISO-8601 timestamp prefix on stderr progress lines** carries forward verbatim from `spike/m6-1-roadmap-additions` commit `3763687`. Strict-superset JSON additions (`network_paths`, `cohort_set`, `cohort_omissions`, `run_meta.sweep_mode`, `measurements[*].top_failure_reasons`) — M6.1.1-aware readers parse the M6.1.2 artifact unchanged. Validation sweep: 10.5 min wall-clock, ~$0.19 Modal A10G `eu-west-1` (well under SC-001's 35 min + SC-008's $0.50 budget). Schema reference: [`contracts/instrumentation.md`](contracts/instrumentation.md). Drive with `python -m vllm_grpc_bench --m6_1_2-validate`. [`ANALYSIS.md § M6.1.2`](ANALYSIS.md#m612--methodology-discipline-per-sweep-topology-evidence--restored-rest_plain_tcp-cohort).
- **M6.1.3** — Phase 1 attribution closure: proxy-edge probes + per-cohort prompt-content audit + multi-run between-run variance (delivered 2026-05-19 via [PR #31](https://github.com/AncientStudying/vllm-grpc/pull/31)). Three additions bundled into one 5-run multi-sweep: (1) **proxy-edge probes** — two new wire keys (`m6_1_1_t_pre_engine_wall_ns` + `m6_1_1_t_first_chunk_mono_ns`) bracket the asyncio handoff between the in-process frontend servicer and vLLM, deriving `seg_ingress_ms` + `seg_egress_ms` per RPC; classifier extends from 5-bucket to 7-bucket with `proxy_ingress_dominated` / `proxy_egress_dominated` labels plus a compound-label scheme. (2) **per-cohort prompt-content audit** — tokenized prompt length + BLAKE2b-8 hash on the wire feeds a pooled-distribution H1/H2/rejection verdict. (3) **multi-run sweep + between-run variance compute** — `--m6_1_3-diagnose-repeat=N` runs Phase 1 N times back-to-back; reporter renders a "Between-Run Variance" section; `inconclusive_high_variance` outer override fires when between-run stddev exceeds within-run CI half-width. **Headline finding — H1 confirmed at every chat_stream cell**: gRPC paths emit 36.88-token prompts vs REST paths' 28.88-token prompts (8-token chat-template padding gap, latent confound since M6 dropped M5.2's prompt-symmetry helper); the FR-017 recommendation block fires designating symmetric prompts the M6.x convention going forward (`--m6_1_3-symmetric-prompts` wires the cross-milestone helper). **Phase B (n=200 power test) NOT required** — between-run stddev sits well under within-run CI half-width on every cell × cohort (chat_stream c=4: 1.28–3.20 ms across cohorts vs ~88 ms means = 1.5–3.6% noise floor). **All six cells classified `inconclusive`** — not from high variance but from multi-factor offsetting (gRPC slower in `seg_prefill` per the H1 finding, REST slower in `seg_egress`); the per-segment data + audit verdict explain the cancellation directly. **SC-013 dual-gate PASS at 0.0%** (no clock anomalies across ~5500 RPCs). Modal cost ~$1.74 vs $6.05 cap (71% headroom). Three-path artifact publishing: canonical at [`docs/benchmarks/m6_1_3-attribution-closure.{md,json}`](docs/benchmarks/m6_1_3-attribution-closure.md), validate sibling at `-validate.{md,json}`, Phase B sibling skipped. Strict-superset schema under `m6_1_1.v1` (no version bump). Drive with `python -m vllm_grpc_bench --m6_1_3` (multi-run publish, ~75 min) or `--m6_1_3-validate` (single-run wiring check, ~15 min). [`ANALYSIS.md § M6.1.3`](ANALYSIS.md#m613--phase-1-attribution-closure-proxy-edge-probes--per-cohort-audit--multi-run-variance).
- **M6.2** — Token-budget characterization across the `max_tokens` axis (delivered 2026-05-26, branch `027-m6-2-token-budget`, git_sha `82bd55a`). Lifts `max_tokens` from M5.x/M6/M6.1's fixed cap (10/50) to a 6-point measurement axis (`10 / 50 / 256 / 512 / 1024 / 2048`) under the M6.1.1 6-cell × 4-cohort matrix at `n=40` per block, measuring `wall_p50` / `wall_p95` / TPOT / 5-segment decomposition at every (cell, cohort, `max_tokens`) tuple (132 main-sweep blocks). Three-regime prompt sourcing per FR-034 / FR-035 — synthetic seed-derived at null anchors `{10, 50}` (preserves M6.1.3 cross-baseline comparison), ShareGPT corpus + Qwen3-8B prompt-embeddings at interior caps for production-realistic distributions. A dedicated **KV-pressure sub-probe** per FR-036 / FR-017a runs after the main sweep: 16 blocks (4 cohorts × 2 cell-types × 2 caps `{1024, 2048}`) at `n=20` with `ignore_eos=True`, computing the wall-clock-ratio inference `R = wall_p50(c=8, 2048) / wall_p50(c=8, 1024)` per cohort × cell-type against a 2.2 threshold (10% margin above the linear ~2.0 expectation). **Headline findings**: (1) **M5.2 / M6 / M6.1's HTTPS-edge framing is reinforced and enlarged at the anchor** — `chat_stream_c1 × max_tokens=10` (synthetic prompt) puts `rest_https_edge` at 488.5 ms vs `default_grpc` 611.9 ms / `rest_plain_tcp` 614.6 ms, a **25–26% REST-edge advantage** (validate read was ~12%). (2) **Self-hosted / no-edge: gRPC's wire-transmission advantage is consistent across the full `max_tokens` axis** — `seg_egress_ms` shows gRPC ahead of plain REST in **9 of 9 chat_stream cells** (+9.5% to +55.2%); the validate sweep's `c1×50` counterexample sign-flipped to +12.5% under tighter n=40 CI, as that sweep's caveat anticipated. (3) **Wall-clock advantage concentrates at `c=8` and grew under n=40** — `tuned_grpc_multiplexed` vs `rest_plain_tcp` at `chat_stream_c8 × max_tokens=10` is **+15.6%** (validate read +5.1%); at `c=1` the protocols are statistically indistinguishable. (4) **KV-pressure characterization (Story 3 / FR-017a sub-probe)** — all 8 cohort × cell-type combinations classify as `kv_pressure_not_observable`; ratios cluster 1.81–2.05 (well below the 2.2 threshold); `oom_observed=false` everywhere. Qwen3-8B at `c=8 × max_tokens=2048` has half-headroom on the engine ceiling. **Caveats**: rest_plain_tcp drift FAIL at c1/c4 × `max_tokens=50` is a documented baseline-data-quality issue (M6.1.3 baseline outlier-contaminated), not an M6.2 regression — see ANALYSIS.md § M6.2; preemption recovery happened mid-sweep, `run_meta.preemption_events` reads `0` but is incorrect (resume process reset the counter); DO NOT cite `max_tokens=2048` headline wall_p50 numbers as protocol wins (prompt-driven early-EOS artifact, the artifact's auto-emitted audit section flags affected cells). Strict-superset schema additivity under `m6_1_1.v1` (no version bump) — new top-level keys `max_tokens_axis`, `protocol_crossover`, `kv_pressure_observation` + per-row `prompt_source` / `measurement_regime` / `prompt_corpus_idx` / `block_start_utc` / `block_end_utc` / `retry_attempted`. Two-path artifact publishing: canonical at [`docs/benchmarks/m6_2-token-budget.{md,json}`](docs/benchmarks/m6_2-token-budget.md), validate sibling at `-validate.{md,json}`. Total publish wall-clock 14.5 h across two processes (Modal A10G `eu-west-1`); validate sweep ~2.5 h. Drive with `python -m vllm_grpc_bench --m6_2` (publish, ~13–14 h) or `--m6_2-validate` (3-point axis subset wiring check, ~2–3 h). [`ANALYSIS.md § M6.2`](ANALYSIS.md#m62--token-budget-characterization-max_tokens-axis).
- **M7** — Corpus expansion (upcoming): longer prompts, multi-turn, domain-specific content. Inherits M6's engine-cost baseline AND M6.2's per-`max_tokens` latency-budget tables.
- **M8** — Model expansion (upcoming): real vLLM re-validation on multiple model sizes and architecture families.

The [Topology guide](ANALYSIS.md#topology-guide--which-milestone-result-applies-to-your-deployment) in `ANALYSIS.md` names which M5-era milestone applies to which deployment shape.

---

## Development Commands

```bash
make bootstrap          # Install deps + generate proto stubs (run after clone)
make proto              # Regenerate protobuf stubs only
make lint               # ruff check + format check
make typecheck          # mypy --strict
make test               # pytest
make check              # lint + typecheck + test (CI gate)
make run-frontend       # Start gRPC server on :50051
make run-proxy          # Start REST proxy on :8000
make bench              # Head-to-head benchmark (requires proxy + frontend running)
make bench-ci           # Benchmark smoke test with stub servers
make bench-modal        # Full A10G benchmark run on Modal
make regen-bench-reports  # Regenerate docs/benchmarks/*.md from committed JSON
make download-weights   # Download model weights to Modal volume
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_PORT` | `8000` | REST proxy listen port |
| `FRONTEND_PORT` | `50051` | gRPC frontend listen port |
| `FRONTEND_ADDR` | `localhost:50051` | Proxy → frontend address |
| `MODEL_NAME` | `Qwen/Qwen3-0.6B` | Model loaded by the frontend |
| `PROXY_BASE_URL` | `http://localhost:8000` | Base URL used by demo scripts |

---

## Repository Structure

```
proto/                         # Protobuf source of truth
  vllm_grpc/v1/
    health.proto               # Health.Ping RPC
    chat.proto                 # ChatService: Complete + CompleteStream
    completions.proto          # CompletionsService: Complete + CompleteStream

packages/
  gen/                         # Generated stubs (built by make proto, not committed)
  proxy/                       # FastAPI REST proxy → gRPC translator
  frontend/                    # grpc.aio gRPC server (ChatService + CompletionsService)
  client/                      # VllmGrpcClient: Python gRPC-direct client library

demo/                          # Annotated runnable examples (curl, openai-sdk, grpc-direct, streaming)

tools/benchmark/               # Benchmark harness (vllm_grpc_bench package)

scripts/python/
  bench_modal.py               # Modal A10G orchestration (Phase 3–6 benchmark runs)
  modal_bench_*.py             # M5/M5.1/M5.2 Modal apps (gRPC + REST endpoints)
  regen_bench_reports.py       # Regenerate .md reports from committed JSON + sidecars
  gen_chat_corpus.py           # Generate ShareGPT V3 chat corpus (pinned)

tests/integration/             # End-to-end bridge tests (no GPU required)

docs/
  PLAN.md                      # Project plan and phase roadmap
  decisions/                   # Architecture decision records
  benchmarks/                  # Per-milestone benchmark reports + JSON + sidecars
ANALYSIS.md                    # Top-level milestone-by-milestone findings (M1–M6.2)
contracts/
  instrumentation.md           # Canonical artifact-schema reference (dispatch_mode, network_paths, cohort_set, ...)

specs/                         # spec-kit planning artifacts (maintainers' internal workflow — optional, see below)
```

---

## Spec-Kit

> **Optional — not required to contribute.** The maintainers use [spec-kit](https://github.com/github/spec-kit) to plan larger phases of work, and you'll see its artifacts under `specs/NNN-feature-name/` and a `NNN-` branch-numbering scheme on some branches. None of this is a prerequisite for contributing — most fixes, docs changes, and self-contained features just need a branch, a passing `make check`, and a PR. See [CONTRIBUTING.md](CONTRIBUTING.md#branch-naming) for the (permissive) branch and PR conventions.

If you *do* want to use spec-kit for a large, multi-file change (and have the tooling installed), the cycle is:

```
/speckit-specify   → create feature specification (spec.md)
/speckit-plan      → generate implementation plan + research
/speckit-tasks     → generate ordered task list
/speckit-implement → execute the task list
```

Artifacts are written to `specs/NNN-feature-name/`.

---

## CI

GitHub Actions runs on every push and PR to `main`:

- **ci.yml** — three jobs gated independently: `lint` (`ruff check` + `ruff format --check`), `typecheck` (`mypy --strict packages/proxy/src packages/frontend/src tools/benchmark/src`), `test` (`pytest packages/proxy/tests packages/frontend/tests tools/benchmark/tests`).
- **proto.yml** — verifies committed stubs match proto sources (`make proto` + `git diff --exit-code`).
- **benchmark.yml** — operator-driven full benchmark runs on Modal.
