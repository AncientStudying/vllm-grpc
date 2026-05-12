# vllm-grpc

A Protobuf/gRPC frontend for vLLM that demonstrates wire-size and protocol overhead tradeoffs for LLM inference. The core thesis: replacing the OpenAI JSON wire format with protobuf-over-gRPC reduces response size by up to 89% for chat completions and 25% for embed request payloads.

---

## What is this?

vLLM's default interface is an OpenAI-compatible REST API. JSON is human-readable but verbose: a typical chat completion response is 611 bytes of JSON wrapping ~10 tokens of actual text. Protobuf encodes the same response in 65 bytes.

This project builds a gRPC frontend that sits in front of vLLM and exposes a proto-defined `ChatService` and `CompletionsService`. It then measures the wire overhead across three access paths:

1. **REST via proxy** — the mainstream path; any OpenAI client just works
2. **gRPC via proxy** — REST client → proxy → gRPC frontend (same client, adds proxy RTT)
3. **gRPC-direct** — `VllmGrpcClient` speaks proto directly to the frontend, no proxy

The project is a structured measurement exercise, not a production system. Every phase commits benchmark JSON to `docs/benchmarks/` so results are reproducible.

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
| REST via proxy | curl, openai SDK | JSON | Yes | Drop-in for any existing OpenAI client |
| gRPC via proxy | same REST clients | JSON → gRPC (proxy translates) | Yes | Baseline comparison for proxy overhead |
| gRPC-direct | `VllmGrpcClient` | Protobuf | No | Smallest wire size; measures protocol overhead without proxy |

The **gRPC-direct** path is where the wire-size thesis is tested: it removes the proxy and sends raw proto bytes, isolating the protocol difference from the proxy overhead.

---

## Prerequisites

- macOS (M2/M3) or Linux x86-64
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `make` — macOS: `xcode-select --install`; Linux: pre-installed
- A running vLLM-compatible model (the gRPC frontend loads it via `MODEL_NAME`)

For GPU benchmarks on Modal: a Modal account with `modal token new`.

---

## Quick Start

```bash
# 1. Clone and bootstrap
git clone <repo-url> vllm-grpc && cd vllm-grpc
make bootstrap          # install deps + generate protobuf stubs

# 2. Start the gRPC frontend (terminal 1 — requires a GPU or CPU-only vLLM)
make run-frontend       # listens on :50051

# 3. Start the REST proxy (terminal 2)
make run-proxy          # listens on :8000

# 4. Run demo scripts
bash demo/curl-rest.sh                 # REST via curl
uv run python demo/openai-sdk.py       # REST via openai SDK
uv run python demo/grpc-direct.py      # gRPC-direct (no proxy)
uv run python demo/streaming.py        # streaming SSE via proxy
```

Each demo script reads an environment variable for the endpoint address:

| Script | Variable | Default |
|--------|----------|---------|
| `demo/curl-rest.sh` | `PROXY_BASE_URL` | `http://localhost:8000` |
| `demo/openai-sdk.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |
| `demo/grpc-direct.py` | `FRONTEND_ADDR` | `localhost:50051` |
| `demo/streaming.py` | `PROXY_BASE_URL` | `http://localhost:8000/v1` |

---

## Benchmark Headlines

All runs on Modal A10G GPU, vLLM 0.20.0, model `Qwen/Qwen3-0.6B`. Full numbers and methodology in [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md).

**Wire size** is where gRPC-direct wins cleanly and structurally: chat completion response bytes drop from 611 B (REST JSON) to 65 B (gRPC proto) — an 89% reduction. Embed request payloads drop 25% because gRPC transmits raw tensor bytes while REST base64-encodes them. **Latency** is more nuanced: at c=1, gRPC-direct adds ~35% latency over REST (35 ms) due to channel setup, while gRPC-proxy adds ~215% because of the local-to-Modal tunnel hop. At c=8, all three paths converge as the model's inference queue dominates. The honest summary: gRPC is the right choice when you need compact wire representation; REST remains the latency leader at low concurrency.

---

## Roadmap

### Milestone 1 — Foundation (current release)

Three access paths (REST via proxy, gRPC via proxy, gRPC-direct) implemented and benchmarked end-to-end on Modal A10G. Headline finding: gRPC-direct reduces response bytes by **89%** for chat completions and **25%** for embed request payloads. See [`docs/benchmarks/summary.md`](docs/benchmarks/summary.md) for full numbers and methodology.

### Milestone 2 — Cross-Repo Ground-Truth Research

Formalize the practice of consulting cloned vLLM (the inference engine) and grpcio (the wire stack) as authoritative references when making proto, channel, or decode-tuning decisions in M3 and beyond. Tooling, merge process, and rebuild cadence are documented in [`ground-truth-workflow-for-associated-projects.md`](ground-truth-workflow-for-associated-projects.md). Known gap: graphify does not parse `.proto` files, so proto-shape questions are answered by reading `proto/` directly; graphify is leaned on for vLLM internals and grpcio channel implementation.

### Milestone 3 — Protobuf & gRPC Tuning

Drive wire-size and decode tuning from a mock model that exposes a configurable `hidden_size` (canonical values: 2048, 4096, 8192) and emits embeddings of the matching shape with dummy weights. Per upstream guidance, embed payload size is determined by `hidden_size` rather than total parameter count — Llama 3.1 8B and Llama 3.3 70B both use `hidden_size=8192` and produce identically-sized embed payloads, so a real model is not required for this milestone. GPU cost is removed from the loop.

The milestone splits into two axes:

**Schema-level (protobuf):**
- Can refinements to message shape (packed scalars, streaming chunk granularity, `oneof` layout for the input union) reduce response or request bytes below the M1 baseline?

**Channel-level (grpcio):**
- How do `max_message_size`, keepalive, compression, and HTTP/2 framing settings affect wire size and decode time across `hidden_size` 2048 / 4096 / 8192?
- At what `hidden_size` does grpcio's default `max_message_size` become binding for embed requests?

**Status:** bytes-verdict report shipped 2026-05-10 in PR #17 ([`m3-channel-tuning.{md,json}`](docs/benchmarks/m3-channel-tuning.md)) — `no_winner` across all 24 cells on the bytes metric. Wall-clock-time re-analysis (Phase A / US3) on the same data, shipped on this branch ([`m3-channel-tuning-time.{md,json}`](docs/benchmarks/m3-channel-tuning-time.md)), surfaced **four real time-axis wins** the bytes evaluation missed:

- **`max-msg-16mib` reduces TTFT by −31% on chat_stream/h=4096** and −29% on chat_stream/h=2048 (and −2.4% on embed/h=4096 wall-clock) — surprising because the 4 MiB default never binds at canonical widths, so the mechanism is not wire-byte size.
- **`keepalive-aggressive` reduces TTFT by −24% on chat_stream/h=2048**.

`max-msg-16mib` is the time-axis frozen config for the `max_message_size` axis; the other three axes default to baseline (one `noise_bounded` cell each on keepalive and HTTP/2 framing flags those cells for M4 re-measurement). Defensible verdicts for the cells M3's harness cannot resolve (chat_stream total wall-clock under any axis; the two `noise_bounded` cells) are deferred to **Milestone 4** per the methodology constraints documented in `specs/015-m3-protobuf-grpc-tuning/research.md` R-11..R-14 and `docs/decisions/0005-m3-statistical-methodology.md`.

Tuning decisions in this milestone lean on cloned vLLM and grpcio source as ground truth — see [`ground-truth-workflow-for-associated-projects.md`](ground-truth-workflow-for-associated-projects.md).

### Milestone 4 — Time-Axis Channel & Schema Tuning

Re-frame the M3 measurements around wall-clock time as a first-class success metric (TTFT for streaming, total per-RPC wall-clock for embed), and run the protobuf message-shape candidates deferred from M3 under that methodology. M3 closed with bytes verdicts and an interim time re-analysis; M4 produces the definitive time-axis result.

**Harness redesign (Phase B):**
- Add a no-pacing mode to the mock engine so streaming wall-clock is dominated by transport+serialization rather than artificial token-emission delay.
- Add a shared-baseline orchestrator mode (one M1_BASELINE cohort measured up front, n≥100, reused across all axes) to eliminate cross-batch drift.
- Promote TTFT to a first-class metric in the recommendation builder for chat_stream cells.

**Definitive sweep + schema candidates:**
- Re-run the four-axis channel sweep under the new methodology.
- Measure protobuf-shape candidates (packed scalars on token-id fields, `oneof` flattening on the input union, alternative streaming chunk granularity) against the new frozen-channel baseline using both bytes and time verdicts.

**Status (delivered 2026-05-10):** harness redesign + definitive sweep merged on `016-m4-time-axis-tuning`. Published report at [`docs/benchmarks/m4-time-axis-tuning.{md,json}`](docs/benchmarks/m4-time-axis-tuning.md). Drive the sweep with `python -m vllm_grpc_bench --m4` (default no-pacing, shared baseline, n=100→250 cascade, per-cohort CV recorded — the run never aborts on a noisy baseline; cohorts above the warn threshold are flagged in the report for reader adjudication per FR-005). M5 addresses the loopback caveat axes (`keepalive`, `http2_framing`) by re-running the same sweep on Modal.

### Milestone 5 — Cross-Host Time-Axis Validation (delivered)

Re-ran the M4 sweep with the gRPC server deployed on Modal (eu-west-1) and the benchmark client running locally, so transmission crossed real wire (~52 ms RTT median) instead of `127.0.0.1`. M4's `keepalive` and `http2_framing` verdicts carried a loopback caveat because RTT-bounded behavior cannot manifest on a single host; M5 resolved that caveat and found **5 channel-config wins on `embed/h2048` with deltas of −23% to −25%**: `max-msg-16mib`, `max-msg-unlimited`, `keepalive-aggressive`, `keepalive-relaxed`, `http2-bdp-probe`. All were invisible on M4's loopback sweep. M5 also surfaced a `server_bound` classifier that correctly excludes cohorts at `embed/h8192` (~512 KB payloads, server-side serialization dominates) and on `compression-gzip` at large hidden sizes from the recommend tallies.

**Status (delivered 2026-05-11):** Published report at [`docs/benchmarks/m5-cross-host-validation.{md,json}`](docs/benchmarks/m5-cross-host-validation.md). Drive the sweep with `python -m vllm_grpc_bench --m5 --m5-modal-region=eu-west-1` (requires `MODAL_BENCH_TOKEN` exported plus `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`). Single deploy, ~10–15 min wall-clock on Modal CPU-only, clean teardown on exit. The published "Supersedes M4" table emits 20 entries (10 `loopback_resolution`, 8 `bound_classifier_transition`, 2 `verdict_confirmed`) — every M4 cell whose verdict M5 has resolved or contradicted is named explicitly.

### Milestone 5.1 — REST vs gRPC Head-to-Head on Real Wire (delivered)

Drove REST and gRPC head-to-head against the same Modal eu-west-1 MockEngine over real wire (~57 ms gRPC RTT, ~95 ms REST plain-TCP RTT). 18-cell matrix (2 paths × 3 widths × 3 concurrencies); 48 verdicts across four gRPC sub-cohorts (`tuned_grpc` at c=1, `tuned_grpc_multiplexed` and `tuned_grpc_channels` at c≥2, `default_grpc` everywhere) plus one REST cohort. Published report at [`docs/benchmarks/m5_1-rest-vs-grpc.{md,json}`](docs/benchmarks/m5_1-rest-vs-grpc.md). Drive with `python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=eu-west-1`.

**Headline findings:**

- **Embed is gRPC's domain.** 16 of 17 embed verdicts are gRPC-recommend or `no_winner`; c=1 deltas are uniformly −32% to −35%. Protobuf packed-float embeds + HTTP/2 multiplexing beat REST's JSON-numeric arrays on every embed cell except `embed/h2048/c8` (REST wins on multiplexed/channels by +30% to +49%; default-gRPC is `no_winner`).
- **chat_stream above c=1 is REST's domain.** 12 of 18 c≥4 chat_stream verdicts are `rest_recommend` with deltas +11% to +29%. REST's HTTP/1.1 keep-alive + simpler framing beats gRPC's HTTP/2 streaming overhead under MockEngine's neutral inference cost. chat_stream c=1 flips to gRPC across all widths (−4% to −9%).
- **M5's tuned channel config provides no measurable benefit over M1-default on this path.** In 5 of 6 c≥2 embed cells where every gRPC sub-cohort wins, `default_grpc` matches or beats `tuned_grpc_multiplexed` and `tuned_grpc_channels` outright. Either the tuned axes (`max_message_size`, keepalive, HTTP/2 framing) are not load-bearing at these scales, or the cross-host RTT dominates what loopback-era tuning was harvesting. **This finding motivates M5.2.**
- **M1 supersession is substantial.** 4 of 6 M1 time-axis verdicts flip: chat_completion c=1's "REST faster" flips to `tuned_grpc_recommend` across all widths; chat_completion c=4's `no_winner` flips to `rest_recommend` across all widths; chat_completion c=8 flips at h2048/h8192 to `rest_recommend`; embed_completion c=1's `no_winner` flips to `tuned_grpc_recommend` across all widths.

**Caveats — kept prominent in the report:**

- **MockEngine, not real vLLM.** Engine cost is held constant across cohorts so the verdict reflects transport + framing only. Real-engine re-validation deferred to M7.
- **Both protocols travel Modal's plain-TCP tunnel** (`modal.forward(..., unencrypted=True)`). The FR-019 "REST uses Modal-managed TLS" assumption was voided after a smoke run measured a ~2× RTT gap between Modal's HTTPS edge (TLS-terminated, anycast-routed near the client) and plain-TCP that would have dominated every verdict. M5.1 therefore does **not** measure REST against the production-realistic HTTPS edge — **M5.2 closes that gap.**
- Bytes-axis findings from M1 (89% chat response reduction, 25% embed request reduction) remain in force unchanged (FR-021) — M5.1 measures time only.

### Milestone 5.2 — REST Transport Path × gRPC Tuning Surface (upcoming)

M5.1 surfaced two questions it could not answer:

1. **Does Modal's HTTPS edge (anycast-routed, TLS-terminated) change REST's competitive position?** M5.1 forced both protocols through plain-TCP because a 2× RTT gap on the smoke run would have made the comparison meaningless. Production REST traffic almost always travels the HTTPS edge; M5.2 measures both paths so the operator can see how the network path changes the verdict.
2. **Does M5's tuned channel config provide measurable benefit over M1-default at higher iteration count?** M5.1's per-cell deltas between `default_grpc` and the tuned cohorts were frequently within ±3% (i.e. in the noise). Higher-n sampling resolves whether the tuning is genuinely neutral on this path or whether M5.1's n=100 was simply not enough resolution.

**Approach.** Five transport cohorts on the same 18-cell (path × hidden_size × concurrency) matrix:

| cohort | wire format | transport |
|--------|-------------|-----------|
| `rest_https_edge` | JSON over HTTP/1.1 | Modal HTTPS edge (TLS-terminated, anycast-routed) — **honors FR-019** |
| `rest_plain_tcp` | JSON over HTTP/1.1 | Modal `modal.forward(unencrypted=True)` — matches M5.1 |
| `default_grpc` | Protobuf over HTTP/2 | Plain-TCP (M1-default channel config) |
| `tuned_grpc_multiplexed` | Protobuf over HTTP/2 | Plain-TCP (M5 tuned config; 1 channel, c concurrent streams) |
| `tuned_grpc_channels` | Protobuf over HTTP/2 | Plain-TCP (M5 tuned config; c channels, serial RPCs) |

**Methodology.**

- Same MockEngine, same Modal eu-west-1 region, same workload corpus as M5.1 — only the cohort surface widens.
- **n=250 per cohort** (vs. M5.1's n=100) — narrows 95% CI half-widths so small tuned-vs-default deltas can be resolved against noise.
- **Per-cohort RTT probe.** The HTTPS-edge vs plain-TCP RTT delta is reported, not hidden. The report's executive section names the network path each verdict travels so a reader cannot accidentally read a `rest_plain_tcp` vs `tuned_grpc_multiplexed` row as a production-equivalent comparison.
- **Two verdict families per cell.** Protocol comparison (each gRPC cohort vs `rest_https_edge`) and a transport-only comparison (`rest_https_edge` vs `rest_plain_tcp`) so the HTTPS-edge cost is quantified separately from the protocol comparison.

**Outputs.** `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}` (strict superset of M5.1's JSON schema). Drive with `python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1`.

Out of scope: real vLLM (deferred to M7), corpus diversity (deferred to M6), additional gRPC channel-config axes beyond what M5 winnowed, HTTPS-edge for gRPC (Modal's edge does not natively expose HTTP/2 plaintext + gRPC, so plain-TCP remains the only credible gRPC transport here).

### Milestone 6 — Corpus Expansion

Re-run all three access paths against a larger, more varied prompt corpus covering short and long prompts, multi-turn conversations, and domain-specific content (code, structured data). Determine whether the Milestone 1 wire-size and latency findings hold across input diversity.

- Do wire-size deltas change with longer prompts or multi-turn context windows?
- Does streaming TPOT variance increase with structurally different prompt types?

### Milestone 7 — Model Expansion

Repeat the Milestone 1, 3, 4, and 5 benchmarks with at least two additional models of different sizes and architecture families. Determine whether the wire-overhead thesis is model-agnostic or depends on tokeniser and output characteristics, and validate that the mock-derived findings from M3–M5 hold against real models.

- Does a larger model (7B+) shift the latency story relative to wire-size gains?
- Do models with different default output lengths change the response-byte delta?

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
make bench              # Head-to-head benchmark (requires proxy + native servers running)
make bench-ci           # Benchmark smoke test with stub servers (no live model needed)
make bench-modal        # Full A10G benchmark run on Modal (requires Modal token + weights)
make regen-bench-reports  # Regenerate docs/benchmarks/*.md from committed JSON files
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
    completions.proto          # CompletionsService: Complete + CompleteStream (prompt embeds)

packages/
  gen/                         # Generated stubs (built by make proto, not committed)
  proxy/                       # FastAPI REST proxy → gRPC translator
  frontend/                    # grpc.aio gRPC server (ChatService + CompletionsService)
  client/                      # VllmGrpcClient: Python gRPC-direct client library

demo/                          # Annotated runnable examples (all four access paths)
  curl-rest.sh                 # REST via curl
  openai-sdk.py                # REST via openai SDK
  grpc-direct.py               # gRPC-direct via VllmGrpcClient
  streaming.py                 # Streaming SSE via proxy

tools/benchmark/               # Benchmark harness (vllm_grpc_bench package)

scripts/
  curl/                        # curl one-liners
  python/
    bench_modal.py             # Modal A10G orchestration (Phase 3–6 benchmark runs)
    regen_bench_reports.py     # Regenerate .md reports from committed JSON

tests/integration/             # End-to-end bridge tests (no GPU required)

docs/
  PLAN.md                      # Project plan and phase roadmap
  decisions/                   # Architecture decision records
  benchmarks/                  # Committed benchmark JSON + generated comparison reports
    summary.md                 # Headline numbers across all phases

specs/                         # spec-kit planning artifacts (per-phase)
```

---

## CI

GitHub Actions runs on every push and PR to `main`:

- **ci.yml** — lint (`ruff`), type-check (`mypy --strict`), tests (`pytest`)
- **proto.yml** — verifies committed stubs match proto sources (`make proto` + `git diff --exit-code`)
