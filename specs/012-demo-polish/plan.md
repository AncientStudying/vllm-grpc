# Implementation Plan: Phase 7 — Demo Polish

**Branch**: `012-demo-polish` | **Date**: 2026-05-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/012-demo-polish/spec.md`

## Summary

Phase 7 turns the working system into a self-contained demo and closes two benchmark data gaps. The deliverables are: a polished README covering the project thesis and quickstart; four annotated `demo/` scripts covering each access path; a `docs/benchmarks/summary.md` synthesizing headline numbers; three committed Phase 6 completions JSON files (missing from prior phases); a reformatted `phase-6-completions-comparison.md` matching the concurrency-split, delta-explicit layout of Phase 4.2/5 reports; and extended `regen_bench_reports.py` support for all phases. A `make bench-modal` re-run is required to generate the Phase 6 JSON files.

## Technical Context

**Language/Version**: Python 3.12 (demo scripts, bench scripts); Bash (curl-rest.sh)
**Primary Dependencies**: `openai` SDK, `vllm-grpc-client` (`VllmGrpcClient`) — both already in the workspace; `shellcheck` for shell script lint; `vllm_grpc_bench` reporter/metrics (existing)
**Storage**: N/A
**Testing**: `ruff` (Python demo scripts); `shellcheck` (curl-rest.sh); `mypy` non-strict (demo scripts); `make check` must stay green; `regen_bench_reports.py` must round-trip correctly from JSON
**Target Platform**: macOS arm64 (M2 Pro) for local demo; Modal A10G for GPU benchmark re-run
**Project Type**: Documentation + demo scripts + benchmark data fixes (no new packages or modules)
**Performance Goals**: All four demo scripts return a completion in under 30 seconds on a locally-running frontend; README quickstart reproducible in under 5 minutes from a clean clone
**Constraints**: `make check` green; no new packages; no proto changes; Phase 6 JSON files must come from a real Modal A10G run (not synthetic)
**Scale/Scope**: 4 new files in `demo/`; 3 new JSON files in `docs/benchmarks/`; 2 updated Python scripts (`bench_modal.py`, `regen_bench_reports.py`); 1 updated reporter function (`reporter.py`); 1 new `docs/benchmarks/summary.md`; 1 updated `README.md`; 1 regenerated `phase-6-completions-comparison.md`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Proto-First ✅ Compliant

No proto changes. All RPC schemas are unchanged.

### II. Library Dependency, Not Fork ✅ Compliant

No vLLM source copied or modified. Demo scripts use `vllm` only through existing workspace packages.

### III. Phase Discipline ✅ Compliant

All deliverables (README polish, `demo/` scripts, benchmark summary) are explicitly listed as Phase 7 deliverables in `docs/PLAN.md`. No Phase 8 work introduced.

### IV. CI is the Merge Gate ✅ Required

`make check` (ruff + mypy --strict + pytest) must pass. Demo scripts must also pass `ruff` and non-strict mypy; `curl-rest.sh` must pass `shellcheck`. These checks do not require a running model.

### V. Honest Measurement ✅ Required

`docs/benchmarks/summary.md` must draw from all committed JSON result files, include all three paths, and not selectively omit any metric. The framing must acknowledge that gRPC-proxy latency is dominated by proxy overhead, not protocol overhead.

## Project Structure

### Documentation (this feature)

```text
specs/012-demo-polish/
├── plan.md              # This file
├── research.md          # Phase 0 complete
├── data-model.md        # N/A — no new entities
├── quickstart.md        # Phase 1 complete
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
demo/                                          ← NEW directory
├── curl-rest.sh                               ← NEW: OpenAI REST via proxy (curl)
├── openai-sdk.py                              ← NEW: OpenAI REST via proxy (openai SDK)
├── grpc-direct.py                             ← NEW: gRPC-direct via VllmGrpcClient
└── streaming.py                               ← NEW: SSE streaming via proxy (openai SDK stream=True)

docs/benchmarks/
├── phase-6-completions-native.json            ← NEW: native REST completions BenchmarkRun
├── phase-6-completions-proxy.json             ← NEW: proxy REST completions BenchmarkRun
├── phase-6-completions-grpc-direct.json       ← NEW: gRPC-direct completions BenchmarkRun
└── summary.md                                 ← NEW: headline numbers synthesis across phases 3–6

scripts/python/
├── bench_modal.py                             ← MODIFY: add Phase 6 JSON serialization
└── regen_bench_reports.py                     ← MODIFY: add Phase 5 + Phase 6 regen support

tools/benchmark/src/vllm_grpc_bench/
└── reporter.py                                ← MODIFY: reformat write_wire_size_comparison_md

README.md                                      ← MODIFY: full rewrite for Phase 7 polish
```

No packages, no proto files, no new test files.

**Structure Decision**: Flat `demo/` directory at the repository root. Phase 6 JSON files follow the per-path naming convention established by Phase 4.2/5 (`phase-N-{path}.json`). The reporter change is a pure output-format update with no interface changes.

---

## Phase 0 Research — Complete

See `research.md` for the full decision log. Key findings:

- `scripts/curl/chat-nonstreaming.sh` and `scripts/python/chat-nonstreaming.py` are the existing patterns to adapt for `demo/curl-rest.sh` and `demo/openai-sdk.py`.
- No existing streaming or gRPC-direct demo scripts; both are new.
- README needs a substantial rewrite — current version covers Phase 3 only.
- All benchmark JSON files are committed; `summary.md` is purely a synthesis, no re-runs needed.
- Headline story: wire-size compression is the demonstrated benefit (gRPC-direct response bytes −89% for chat; embed request bytes −25%); latency story is nuanced (proxy hop dominates over protocol gains).

---

## Phase 1 Design — Complete

### Data Model

No new entities. See `data-model.md`.

### Contracts

No new interface contracts. No new RPCs, endpoints, or CLI commands. Existing `VllmGrpcClient`, proxy REST API, and `make` targets are unchanged.

### Implementation Detail

#### `demo/curl-rest.sh`

Sends a non-streaming chat completion via curl to the proxy REST endpoint. Annotated with comments explaining each flag. Fails with a clear message if proxy is not running.

```bash
#!/usr/bin/env bash
# Demo: OpenAI REST chat completion via the gRPC proxy
# Requires: proxy running on localhost:8000 (make run-proxy)

PROXY_URL="${PROXY_BASE_URL:-http://localhost:8000}/v1/chat/completions"

curl -sf "$PROXY_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-0.6B",
    "messages": [{"role":"user","content":"What is 2+2?"}],
    "max_tokens": 64,
    "seed": 42
  }' || { echo "ERROR: proxy not reachable at $PROXY_URL"; exit 1; }
```

#### `demo/openai-sdk.py`

Mirrors `scripts/python/chat-nonstreaming.py` with fuller annotation. Uses the `openai` SDK.

#### `demo/grpc-direct.py`

Uses `VllmGrpcClient` (`packages/client`) directly against the gRPC frontend, no proxy involved. Annotated to show the gRPC-direct path.

```python
#!/usr/bin/env python
"""Demo: gRPC-direct chat completion via VllmGrpcClient (no proxy).

Usage:
    uv run python demo/grpc-direct.py

Requires: frontend running on localhost:50051 (make run-frontend)
"""
import asyncio
from vllm_grpc_client import VllmGrpcClient

FRONTEND_ADDR = "localhost:50051"

async def main() -> None:
    async with VllmGrpcClient(FRONTEND_ADDR) as client:
        response = await client.chat.complete(
            messages=[{"role": "user", "content": "What is 2+2?"}],
            model="Qwen/Qwen3-0.6B",
            max_tokens=64,
            seed=42,
        )
        print(response.choices[0].message.content)

asyncio.run(main())
```

#### `demo/streaming.py`

Uses `openai` SDK with `stream=True` against the proxy. Prints tokens as they arrive.

```python
#!/usr/bin/env python
"""Demo: streaming chat completion via the gRPC proxy (SSE).

Usage:
    uv run python demo/streaming.py

Requires: proxy on localhost:8000 + frontend on localhost:50051
"""
import os, sys
import openai

client = openai.OpenAI(
    base_url=os.environ.get("PROXY_BASE_URL", "http://localhost:8000/v1"),
    api_key="none",
)

try:
    stream = client.chat.completions.create(
        model="Qwen/Qwen3-0.6B",
        messages=[{"role": "user", "content": "Count to five."}],
        max_tokens=64,
        seed=42,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()
except openai.APIError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
```

#### `docs/benchmarks/summary.md`

Synthesizes the headline numbers from:
- `phase-4.2-three-way-comparison.md` (non-streaming chat)
- `phase-5-streaming-comparison.md` (streaming chat)
- `phase-6-completions-comparison.md` (completions wire-size and latency)

Format: three sections (non-streaming, streaming, completions), each with a summary table and a one-paragraph honest interpretation.

#### `README.md`

Full rewrite covering:
1. What the project is and the wire-overhead thesis
2. Architecture diagram (three access paths)
3. Prerequisites and quickstart (pointing at `demo/` scripts)
4. One-paragraph benchmark headline summary
5. Development commands reference (existing `make` targets)
6. Repository structure (updated for Phases 4–7)

#### `scripts/python/bench_modal.py` — Phase 6 JSON Serialization

After `completions_summaries = compute_summaries(all_completions)` and before `write_wire_size_comparison_md(...)`, create per-path `BenchmarkRun` objects and serialize them:

```python
# Save per-path Phase 6 completions JSON (matching Phase 4.2/5 naming convention)
completions_meta = RunMeta(
    timestamp=_dt.now(tz=UTC).isoformat(),
    git_sha=git_sha,
    hostname=socket.gethostname(),
    corpus_path="tools/benchmark/corpus/completions_*.json",
    concurrency_levels=concurrency_levels,
    proxy_url="N/A",
    native_url="N/A",
    gpu_type="A10G",
)
for target_slug, target_name in [
    ("native", "native"),
    ("proxy", "proxy"),
    ("grpc-direct", "grpc-direct"),
]:
    target_results = [r for r in all_completions if r.target == target_name]
    if not target_results:
        continue
    target_run = BenchmarkRun(
        meta=dataclasses.replace(completions_meta),
        summaries=compute_summaries(target_results),
        raw_results=target_results,
    )
    json_path = _DOCS_BENCHMARKS / f"phase-6-completions-{target_slug}.json"
    json_path.write_text(json.dumps(dataclasses.asdict(target_run), indent=2))
    print(f"[COMPLETIONS] JSON written to {json_path}")
```

Also add `json_path` to `output_paths` so it appears in the final summary.

#### `tools/benchmark/src/vllm_grpc_bench/reporter.py` — Phase 6 Format

Update `write_wire_size_comparison_md` to replace the flat latency table with per-concurrency tables. New structure:

```
## Wire-Size Summary               ← kept: aggregate across concurrencies
## Concurrency = 1
### Text Prompt Completions        ← NEW: sub-section per input type
| metric | native | proxy | Δ vs native | gRPC-direct | Δ vs native |
|--------|--------|-------|-------------|-------------|-------------|
| Latency P50 (ms) | ... | ... | ... | ... | ... |
...
### Prompt-Embed Completions
| metric | native | proxy | Δ vs native | gRPC-direct | Δ vs native |
...
## Concurrency = 4
...
## Concurrency = 8
...
```

Column order matches Phase 4.2/5: native (baseline), proxy + Δ, gRPC-direct + Δ. Δ computed as `(val - native) / native * 100` with sign prefix. Metrics: Latency P50/P95/P99 (ms), Throughput (rps), Request bytes (mean), Response bytes (mean).

The `write_wire_size_comparison_md` signature stays the same (`summaries: list[RunSummary], output_path: Path`).

#### `scripts/python/regen_bench_reports.py` — Phase 5 + Phase 6 Support

Add two new optional arg groups:

- `--phase5-rest`, `--phase5-proxy`, `--phase5-direct`: default to Phase 5 streaming JSON files; regenerate `phase-5-streaming-comparison.md`
- `--phase6-native`, `--phase6-proxy`, `--phase6-direct`: default to Phase 6 completions JSON files; regenerate `phase-6-completions-comparison.md` by combining summaries from all three runs

Both groups are optional (skip if files don't exist). When all three Phase 6 files are present, load them, combine their `summaries` lists, and call `write_wire_size_comparison_md(combined_summaries, output_path)`.

### Quickstart Notes

See `quickstart.md`. No changes to `make` targets or environment variables in this phase.

## Post-Design Constitution Re-Check

All five principles remain satisfied. No new packages, no proto changes, no new RPCs.

- **Honest Measurement (V)**: Phase 6 JSON files must come from a real `make bench-modal` run — the spec explicitly prohibits synthetic JSON. Once committed, the reformatted MD is regenerated from those JSON files via `regen_bench_reports.py`.
- **CI Gate (IV)**: `make check` covers ruff, mypy --strict, and pytest. The `write_wire_size_comparison_md` format change is covered by `test_reporter.py` (existing test); the new regen path is covered by a unit test in the updated test file.
