# Phase 0 Research: Phase 7 — Demo Polish

## Decision Log

| # | Topic | Decision | Rationale |
|---|-------|----------|-----------|
| 1 | What existing scripts can `demo/` be modeled after? | `scripts/curl/chat-nonstreaming.sh` → `demo/curl-rest.sh`; `scripts/python/chat-nonstreaming.py` → `demo/openai-sdk.py`; no existing streaming or gRPC-direct demo scripts exist | Both shell and Python patterns are already established in the project |
| 2 | What is the current README state? | Outdated — references only Phase 3 structure; no mention of streaming, completions, gRPC-direct client library, or any benchmark numbers | README must be substantially rewritten for Phase 7 |
| 3 | Which benchmark data covers the summary? | Phase 4.2 (three-way non-streaming), Phase 5 (three-way streaming), Phase 6 (completions wire-size and latency) — all JSON committed in `docs/benchmarks/` | No new benchmark runs needed; summary is a synthesis of existing files |
| 4 | What are the headline numbers for the benchmark summary? | Wire size: gRPC-direct response bytes −89% vs REST for chat (65 vs 611 bytes); embed request bytes −25% vs native REST. Latency: gRPC-direct is faster than gRPC-proxy at low concurrency but REST remains the latency leader. Story is nuanced: protocol efficiency wins on wire size; proxy overhead dominates latency. | Honest framing is that wire compression is the demonstrated benefit; latency gains require the direct path and are model/hardware dependent |
| 5 | What does `demo/streaming.py` target? | SSE via the proxy REST path using the `openai` Python SDK with `stream=True` | Keeps the demo script simple and shows the mainstream usage pattern |
| 6 | What does `demo/grpc-direct.py` target? | Non-streaming gRPC-direct using `VllmGrpcClient.chat.complete()` | Demonstrates the client library path with no proxy involved |
| 7 | Does `demo/` need a `VllmGrpcClient` streaming demo? | No — the spec requires exactly four scripts and does not list a `VllmGrpcClient` streaming script | Phase 7 scope is bounded; keep to the four specified scripts |
| 8 | Should demo scripts pass `mypy --strict`? | No — non-strict mypy is acceptable for demo scripts per FR-010; `ruff` + `shellcheck` are the gates | Demo scripts are user-facing examples, not library code |
| 9 | Does the local demo path require Modal? | No — the README quickstart must work without Modal credentials; Modal is described as the GPU benchmarking environment, not a local dev requirement | Exit criteria require local M2 reproducibility |

## Benchmark Headline Numbers (for `docs/benchmarks/summary.md`)

### Non-Streaming Chat (Phase 4.2, Modal A10G, concurrency=1)

| Path | P50 Latency | P95 Latency | Request bytes | Response bytes |
|------|-------------|-------------|---------------|----------------|
| REST | 106 ms | 161 ms | 506 B | 611 B |
| gRPC-proxy | 335 ms | 1591 ms | 506 B | 330 B |
| gRPC-direct | 144 ms | 272 ms | 419 B (−17%) | 65 B (−89%) |

*gRPC-proxy latency is dominated by the local-to-Modal tunnel hop, not protocol overhead.*

### Streaming Chat (Phase 5, Modal A10G, concurrency=1)

| Path | TTFT P50 | TPOT P50 | Request bytes |
|------|----------|----------|---------------|
| REST | 90 ms | 2.1 ms | 522 B |
| gRPC-proxy | 275 ms | 3.6 ms | 522 B |
| gRPC-direct | 125 ms | 7.0 ms | 419 B (−20%) |

### Completions Wire Size (Phase 6, Modal A10G)

| Path | Input type | Request bytes | Response bytes |
|------|------------|---------------|----------------|
| Native REST | text | 377 B | 702 B |
| gRPC-direct | text | 329 B (−13%) | 278 B (−60%) |
| Native REST | embeds | 606 KB | 687 B |
| gRPC-direct | embeds | 455 KB (−25%) | 280 B (−59%) |

*Embed requests are binary tensors; REST uses base64 encoding (~33% overhead). gRPC transmits raw bytes.*

## Phase 6 JSON Gap — Root Cause

`bench_modal.py` collects all completions results into `all_completions: list[RequestResult]` and calls `write_wire_size_comparison_md(completions_summaries, path)` — but unlike Phase 4.2/5 where `_run_harness()` saves JSON and the script then copies to `docs/benchmarks/`, the completions path only writes the markdown. The `all_completions` list is never serialized.

**Fix**: after `completions_summaries = compute_summaries(all_completions)`, filter `all_completions` by `target` to create 3 per-path `BenchmarkRun` objects and serialize each to `docs/benchmarks/phase-6-completions-{target}.json`. Requires a `make bench-modal` re-run.

## Phase 6 Format Gap — Root Cause

`write_wire_size_comparison_md` was implemented as a one-off function that produces a custom flat table rather than reusing the `write_three_way_md` concurrency-split format. The fix is to restructure the latency/throughput section to match `write_three_way_md`: `## Concurrency = N` top-level sections, sub-sections per input type, explicit Δ vs native columns. Wire-size summary section is unchanged.

## `regen_bench_reports.py` Gap — Root Cause

Phase 5 streaming JSON files exist (`phase-5-{rest,grpc-proxy,grpc-direct}-streaming.json`) but `regen_bench_reports.py` never loads them. Phase 6 completions JSON files do not exist yet. Once the Phase 6 JSON files are committed, both phases can be regenerated by adding two argument groups (--phase5-* and --phase6-*) with sensible defaults pointing at the committed files.

## Alternatives Considered

- **Include `VllmGrpcClient` streaming demo**: Rejected — four scripts are sufficient for the demo; streaming via the openai SDK covers the pattern for most viewers.
- **Re-run benchmarks before summary**: Rejected — all JSON files are committed from real A10G runs; re-running is not needed and would change nothing.
- **asciinema capture**: Listed as optional in PLAN.md and excluded from Phase 7 scope.
