# Quickstart: Reproducing the M3 sweep locally

**Feature**: 015-m3-protobuf-grpc-tuning
**Audience**: a contributor or external reviewer who wants to reproduce the M3 numbers from scratch

## Prerequisites

- macOS (M2/M3) or Linux x86-64. CPU only — no GPU required.
- Python 3.12, `uv` installed (`brew install uv` or equivalent).
- `make`, `git`, `protoc` (the existing project setup).
- Cloned `vllm-grpc` repo, on `main` (or any branch that has merged 015).

## One-time setup

```bash
# From repo root.
make install                 # uv sync the workspace + install dev deps
make proto                   # regenerate protobuf stubs
make check                   # baseline: 145+ passed, 4 skipped
```

If `make check` is red on your machine before running M3, fix that first — M3 assumes a green baseline.

## Smoke run (≈ 30 seconds)

The smoke mode confirms the bench harness is wired up without committing to a full sweep.

```bash
python -m vllm_grpc_bench --m3 \
    --smoke \
    --axis max_message_size \
    --width 2048 \
    --path embed
```

Expected: exit 0, a transient artefact under `bench-results/m3-smoke-<timestamp>.json`, no diff under `docs/benchmarks/`.

## Full P1 sweep (≈ 0.7–4 hours, dominated by `chat_stream`)

```bash
# All four channel axes × three widths × two paths × 30 iters/cell
python -m vllm_grpc_bench --m3
```

Output:

- `docs/benchmarks/m3-channel-tuning.md` — human-readable report with per-axis, per-width recommendations
- `docs/benchmarks/m3-channel-tuning.json` — machine-readable companion (same data)

Inspect `docs/benchmarks/m3-channel-tuning.md` and confirm it answers SC-001 ("which channel settings should I use for hidden_size 2048/4096/8192") and SC-002 ("at what width does default `max_message_size` first bind") for the embed path.

### Narrowing the sweep

If iterating on a single axis:

```bash
# Just compression, just width 4096, just streaming.
python -m vllm_grpc_bench --m3 \
    --axis compression \
    --width 4096 \
    --path chat_stream
```

Partial reports overwrite the matching axis section of `m3-channel-tuning.md` only; other sections are preserved.

## P2 schema-level run (after P1 closes)

P2 is gated by FR-008: every P1 axis must have a recorded outcome. Once that's true, freeze a channel configuration and run a P2 candidate:

```bash
python -m vllm_grpc_bench --m3 \
    --p2-revision chat-token-ids-packed \
    --frozen-channel max-msg-16mib \
    --width 4096 \
    --path chat_stream
```

P2 candidates are checked-in `.proto` revisions on a side-branch (or behind a feature flag). The CLI invokes `make proto` automatically before measurement so the bench reflects the candidate's wire shape.

Output: `docs/benchmarks/m3-schema-tuning.{md,json}`.

## Validating a recommendation against ground truth (M2 workflow)

Per FR-007 / FR-009, every recommendation in the M3 report MUST cite cloned grpcio or vLLM source. To check a citation by hand:

```bash
# Example: verify the keepalive setting names against grpcio source
graphify path "Channel" "keepalive_time_ms" \
    --graph ~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json
```

If `graphify` reports the cross-repo graph is stale (lockfile drift), run:

```bash
/ground-truth-refresh   # via Claude Code, or run the underlying commands manually
```

See `ground-truth-workflow-for-associated-projects.md`.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValueError: hidden_size > 0` at startup | `--width` flag not in `{2048, 4096, 8192}` and validation rejected the value | Use a canonical width, or accept the off-canonical run is exploratory only |
| Many cells reporting `not_measurable` | Local CPU is too slow / busy; iterations time out | Close other heavy processes; rerun. If persistent, increase per-cell deadline via `BENCH_RPC_DEADLINE_S` env |
| `m3-channel-tuning.json` exists but `.md` is empty | Reporter crashed mid-write | Inspect `bench-results/<timestamp>/error.log`; rerun with `--smoke` first to isolate |
| Compression cell shows the candidate is *worse* than baseline | Expected for embed (dense float tensors). Verify the report records this honestly per Constitution V | No fix needed; this is a recorded "no_winner" outcome |

## What success looks like

- Both report files exist under `docs/benchmarks/m3-*`.
- Every recommendation in the markdown report has either (a) a `winning_config` with a citation, (b) a clear `no_winner` verdict with the supporting numbers, or (c) a `not_measurable` verdict with rationale.
- `summary.md` cross-link to the M3 report is updated.
- `make check` is still green.
- Git diff is bounded to `docs/benchmarks/m3-*`, `tools/benchmark/`, and the surgical channel-options changes in `packages/{frontend,proxy,client}/`.
