# vllm-grpc

A Protobuf/gRPC frontend for vLLM that measures wire-size and protocol-overhead tradeoffs for LLM inference. The core thesis: replacing the OpenAI JSON wire format with protobuf-over-gRPC reduces response size by up to 89% for chat completions and 25% for embed request payloads.

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

## Benchmark Headlines

The structural, topology-immune wins from M1 (Modal A10G, vLLM 0.20.0, `Qwen/Qwen3-0.6B`): gRPC-direct cuts chat completion response bytes by **89%** (611 B → 65 B) and embed request bytes by **25%** (raw float32 vs base64 JSON). Latency results vary by deployment topology — same-fabric (M5.1) vs managed-edge-provider (M5.2) findings apply to different audiences. See [`ANALYSIS.md`](ANALYSIS.md) for the per-milestone narrative, the topology guide, and CI-bounded numbers under each network shape.

---

## Roadmap

Milestone-by-milestone findings live in [`ANALYSIS.md`](ANALYSIS.md); per-milestone benchmark reports under [`docs/benchmarks/`](docs/benchmarks/) are the source-data record.

- **M1** — Three access paths benchmarked on Modal A10G; 89% chat / 25% embed wire-size wins. [`ANALYSIS.md § M1`](ANALYSIS.md#m1--foundation).
- **M2** — Cross-repo ground-truth research practice formalised (vLLM + grpcio). [`ANALYSIS.md § M2`](ANALYSIS.md#m2--cross-repo-ground-truth-research).
- **M3** — Four-axis channel sweep at canonical embed widths; bytes uniformly `no_winner`, time axis surfaced 4 wins (PR #17, PR #19). [`ANALYSIS.md § M3`](ANALYSIS.md#m3--protobuf--grpc-tuning).
- **M4** — Time-axis harness redesign + definitive sweep; `max-msg-16mib` recommend at `embed/h=2048`. [`ANALYSIS.md § M4`](ANALYSIS.md#m4--time-axis-channel--schema-tuning).
- **M5** — Cross-host re-run resolved M4's loopback caveat; 5 channel-config wins at `embed/h=2048` (-23% to -25%). [`ANALYSIS.md § M5`](ANALYSIS.md#m5--cross-host-time-axis-validation).
- **M5.1** — REST vs gRPC head-to-head on the **same-fabric** topology (enterprise/homelab audience). [`ANALYSIS.md § M5.1`](ANALYSIS.md#m51--rest-vs-grpc-head-to-head-on-real-wire).
- **M5.2** — REST vs gRPC across HTTPS-edge and plain-TCP; **managed-edge-provider** topology (hobbyist tenant audience). [`ANALYSIS.md § M5.2`](ANALYSIS.md#m52--rest-transport-path--grpc-tuning-surface).
- **M6** — Real-engine mini-validation (delivered 2026-05-15): Qwen3-8B on Modal A10G, narrow 6-cell slice of the M5.2 matrix; 4 of 6 cells overturned M5.2 verdicts under real engine cost (M5.2's "REST wins at c≥4" did NOT hold). [`ANALYSIS.md § M6`](ANALYSIS.md#m6--real-engine-mini-validation).
- **M6.1** — Real-prompt-embeds engine path (delivered 2026-05-16): re-runs M6's 6-cell slice with vLLM's `enable_prompt_embeds=True` driven by `torch.save(tensor)` bytes; tally 1 verdict_survives / 2 verdict_buried_by_engine / 3 no_winner_at_n100; real prompt-embeds engine path costs ~338 ms per RPC at h=4096 (~7-8× the text-digest path), and ~33.7 ms/token steady-state generation rate falls out cleanly. [`ANALYSIS.md § M6.1`](ANALYSIS.md#m61--real-prompt-embeds-engine-path).
- **M6.1.1** — Engine-cost instrumentation diagnosis & symmetrisation (code landed 2026-05-16 on branch `023-m6-1-1-engine-cost-instrumentation`; first live Phase 1 run 2026-05-16 returned classifier-degenerate `channel_dependent_batching × 3` under sequential dispatch — saved as audit baseline at [`docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md`](docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md); **corrected re-run delivered 2026-05-17 under M6.0a** at [`docs/benchmarks/m6_1_1-engine-cost-instrumentation.{md,json}`](docs/benchmarks/m6_1_1-engine-cost-instrumentation.md)): close a measurement gap M6.1 surfaced. **Phase 2 still pending** — the FR-010 classifier degeneracy (`seg_bc_ms ≡ engine_ttft_ms` by construction) makes the `channel_dependent_batching` classification mechanically inevitable for any non-trivial chat_stream spread and blocks a clean Phase 2(b) verdict; resolution requires a checkpoint-placement revision in a separate sub-milestone. Drive with `python -m vllm_grpc_bench --m6_1_1-diagnose` (Phase 1 mini-sweep) then `--m6_1_1` (Phase 2 fix-or-document, gated on classifier resolution).
- **M6.0a** — Concurrent dispatch restoration (delivered 2026-05-17): corrective methodology fix discovered during M6.1.1's first live run. M5.1 / M5.2 used `asyncio.gather`-based concurrent client-side dispatch at cell concurrency c; M6 / M6.1 / M6.1.1 silently dropped this and used sequential `await driver(...)` loops, making the cell's `concurrency` field a metadata tag rather than an in-flight parallelism control. Restored canonical dispatch in five harness entry points (`m6_sweep._run_warmup` / `_run_measurement`, `m6_1_sweep._run_warmup_m6_1` / `_run_measurement_m6_1`, `m6_1_1_sweep._measure_cell`) plus path-agnostic regression test ([`tools/benchmark/tests/test_m6_concurrent_dispatch.py`](tools/benchmark/tests/test_m6_concurrent_dispatch.py), 18 parametrisations). Corrected M6.1.1 Phase 1 re-run completed in 15.6 min at $0.29 Modal A10G `eu-west-1`. Headline: c=4 / c=8 chat_stream per-cohort `engine_ttft_ms` spread *grew* from the audit baseline's 6.0% / 8.4% to 15.9% / 16.4% under real concurrency — disproves the "sequential-dispatch state-drift artifact" hypothesis cleanly. M6 / M6.1 main verdicts are dispatch-robust; only the M6.1 per-cohort drift sub-finding is dispatch-sensitive (re-interpreted via cross-link). Full bug + fix + before/after comparison + per-finding sensitivity classification in [`docs/benchmarks/m6_0a-dispatch-correction.md`](docs/benchmarks/m6_0a-dispatch-correction.md). [`ANALYSIS.md § M6.0a`](ANALYSIS.md#m60a--concurrent-dispatch-restoration).
- **M6.2** — Token-budget characterization (planned): lift `max_tokens` from M5.x/M6/M6.1's fixed cap (10/50) to a 6-point measurement axis (`10 / 50 / 256 / 512 / 1024 / 2048`) so the published latency budget covers the realistic production response-length regime. Report shape pivots from verdict-supersedes to p50/p95/p99 latency-budget tables + TPOT curves + protocol-crossover threshold (at what `max_tokens` does the M6.1 verdict collapse to "no winner"?). Speckit cycle runs after M6.1.1 publishes.
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
ANALYSIS.md                    # Top-level milestone-by-milestone findings (M1–M5.2)

specs/                         # spec-kit planning artifacts (per-feature)
```

---

## CI

GitHub Actions runs on every push and PR to `main`:

- **ci.yml** — three jobs gated independently: `lint` (`ruff check` + `ruff format --check`), `typecheck` (`mypy --strict packages/proxy/src packages/frontend/src tools/benchmark/src`), `test` (`pytest packages/proxy/tests packages/frontend/tests tools/benchmark/tests`).
- **proto.yml** — verifies committed stubs match proto sources (`make proto` + `git diff --exit-code`).
- **benchmark.yml** — operator-driven full benchmark runs on Modal.
