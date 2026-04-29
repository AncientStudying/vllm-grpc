# Project Plan: Protobuf/gRPC Frontend for vLLM

**Status:** Draft v1 — generated from planning session, April 28, 2026
**Repo:** Private GitHub repo (already provisioned), MIT license

---

## 0. Document Purpose

This is the high-level project plan. It defines phases, deliverables, and exit criteria. It is *not* a design document — per-phase design happens via `spec-kit` (`/specify`, `/plan`, `/tasks`) at the start of each phase. Treat this document as the contract that decides *what* gets built and in *what order*; the detailed *how* lives in spec-kit specifications generated phase by phase.

When working with Claude Code on this project, point it at this file plus the active phase's spec-kit artifacts.

---

## 1. Project Overview

### Problem Statement

The OpenAI-compatible REST/JSON API used by vLLM (and most LLM serving stacks) carries non-trivial wire and parsing overhead per request: field-name strings repeat on every message, JSON tokenization is CPU-bound, and SSE-over-HTTP/1.1 is a poor fit for token streaming compared to gRPC's HTTP/2 multiplexed bidirectional streams. This project demonstrates whether replacing the wire format with protobuf-over-gRPC reduces that overhead in measurable ways without breaking compatibility for clients that only know the OpenAI REST surface.

### Goals (End-State)

By the end of the development cycle the project produces three artifacts and one functional demonstration.

The artifacts are:

1. **OpenAI REST → gRPC proxy server.** Accepts OpenAI-compatible chat completions and completions requests on its REST endpoint, translates them to protobuf, and forwards them via gRPC to the vLLM-side frontend.
2. **vLLM-side gRPC frontend.** Accepts protobuf/gRPC requests, translates them into `AsyncLLM` / `LLM` / `SamplingParams` calls, and returns protobuf responses. Effectively replaces the role of `vllm/entrypoints/openai/` for clients that come in via the proxy.
3. **Test scripts and a benchmark harness** (curl + Python) that exercise the full pipeline end-to-end and measure wire-overhead claims against vLLM's native OpenAI server head-to-head.

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

### Three Logical Components

- **`proto/`** — the shared protobuf schema. Source of truth for both proxy and frontend. Generated Python stubs are produced at build time, not committed.
- **`proxy/`** — FastAPI app exposing OpenAI REST endpoints, translating to protobuf, forwarding via a gRPC client.
- **`frontend/`** — gRPC server that imports `vllm` and translates protobuf RPCs into `AsyncLLM` / `LLM` / `SamplingParams` calls.

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
| Final internal package names | Phase 1 (working names: `vllm_grpc_proxy`, `vllm_grpc_frontend`) |

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
│   └── frontend/
│       ├── pyproject.toml
│       ├── src/vllm_grpc_frontend/
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

### Phase 5 — Streaming Chat Completions

**Goal.** Bridge OpenAI SSE chat completions through the proxy and a server-streaming gRPC RPC. This is where the project's wire-overhead thesis becomes most testable.

**Inputs.** Phase 4 metrics — so we can measure the streaming path against non-streaming and against vLLM-native.

**Deliverables.**

- `ChatService.CompleteStream` server-streaming RPC and chunk message in proto
- Proxy support for `stream: true`, emitting OpenAI-formatted SSE deltas terminated by `data: [DONE]`
- Frontend driving `AsyncLLM.generate()` as an async generator and yielding protobuf chunks
- Backpressure: gRPC flow control propagates to the AsyncLLM iteration
- Cancellation: client disconnect → cancel gRPC stream → cancel the generation task
- Mid-stream error path documented and tested
- Curl + Python streaming test scripts
- TTFT and TPOT measurements added to the benchmark harness
- ADR in `docs/decisions/` documenting the streaming design choices (chunk granularity, error encoding, backpressure model)

**Exit criteria.**

- Streaming produces the same final completion as non-streaming for a deterministic seed
- TTFT and TPOT numbers are within an explainable range of vLLM-native — equal or better preferred, but the goal is honesty, not winning
- Cancellation actually stops generation server-side (verifiable in logs / metrics)

---

### Phase 6 — Completions API with Prompt Embeds (V0)

**Goal.** Add the `/v1/completions` endpoint with `prompt_embeds` support, end-to-end, in the environment chosen in Phase 2.

**Inputs.** Phase 2 environment decision; Phase 5 streaming infrastructure (reusable for streaming completions).

**Deliverables.**

- `proto/vllm_grpc/v1/completions.proto` with unary and server-streaming RPCs
- A `prompt_embeds` field carrying the base64-encoded torch tensor as `bytes` (decoded server-side; on the wire it's already binary)
- Proxy `POST /v1/completions` handler that accepts both `prompt` (string) and `prompt_embeds` (in `extra_body`, matching vLLM's existing convention)
- Frontend handler that decodes `prompt_embeds` and passes the tensor to `AsyncLLM.generate()` correctly under V0
- Curl + Python test scripts demonstrating: client computes embeddings locally from chat-template-formatted token IDs, base64-encodes the tensor, sends via the proxy
- Benchmark harness extension comparing wire size of (a) text prompt and (b) prompt embeddings — this is one of the most interesting wire-overhead cases in the project, since prompt embeddings are pure binary tensors and JSON's base64 expansion is roughly 33% bloat that protobuf avoids entirely

**Exit criteria.**

- A client can drive completions end-to-end via prompt-embeds, going entirely through the proxy
- Outputs match outputs from the vLLM-native server with the same prompt-embeds input (token-level equivalence with deterministic seed)
- Wire-size comparison numbers are recorded

---

### Phase 7 — Demo Polish

**Goal.** Turn the working system into a 10-minute demo plus a self-contained README walkthrough.

**Deliverables.**

- Polished README: what the project is, the wire-overhead thesis, how to run it locally in under five minutes, a one-paragraph summary of measured benefits
- A `demo/` directory with one curl script, one Python script, and one streaming Python script — each annotated and runnable
- A short benchmark write-up at `docs/benchmarks/summary.md` with the headline numbers
- Optional: a screen capture or asciinema of the demo

**Exit criteria.**

- A new viewer who has heard nothing about the project can read the README and run the demo locally on the M2 in under ten minutes
- The benchmark summary is written so that a sympathetic but honest reviewer would call it fair

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
