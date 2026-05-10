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

The smoke mode confirms the bench harness is wired up without committing to a full sweep. **Invoke via `uv run` so the workspace's bench package is on the import path** — bare `python -m vllm_grpc_bench` only works inside an activated workspace venv.

```bash
uv run --package vllm-grpc-bench python -m vllm_grpc_bench --m3 \
    --smoke \
    --axis max_message_size \
    --width 2048 \
    --path embed
```

Expected: exit 0, a transient artefact under `bench-results/m3-smoke-<timestamp>.json`, no diff under `docs/benchmarks/`.

## Full P1 sweep (≈ 0.7–4 hours, dominated by `chat_stream`)

```bash
# All four channel axes × three widths × two paths × 30 iters/cell
uv run --package vllm-grpc-bench python -m vllm_grpc_bench --m3
```

Output:

- `docs/benchmarks/m3-channel-tuning.md` — human-readable bytes-axis report with per-axis, per-width recommendations
- `docs/benchmarks/m3-channel-tuning.json` — machine-readable companion (same data)

The full per-iteration sample data is **also** retained at `bench-results/m3-full/m3-channel-tuning.json` (gitignored; ~1 MB). The Phase A `--reanalyze` flow below consumes that full JSON.

Inspect `docs/benchmarks/m3-channel-tuning.md` and confirm it answers SC-001 ("which channel settings should I use for hidden_size 2048/4096/8192") and SC-002 ("at what width does default `max_message_size` first bind") for the embed path.

### Narrowing the sweep

If iterating on a single axis:

```bash
# Just compression, just width 4096, just streaming.
uv run --package vllm-grpc-bench python -m vllm_grpc_bench --m3 \
    --axis compression \
    --width 4096 \
    --path chat_stream
```

Partial reports overwrite the matching axis section of `m3-channel-tuning.md` only; other sections are preserved.

## Phase A wall-clock re-analysis (≈ 1 second; closes M3)

After PR #17 closed the bytes-axis verdicts as `no_winner` everywhere, Phase A re-analyses the same data on TTFT (chat_stream cells per FR-014) and total per-RPC wall-clock (embed cells). No new sweep — code-only re-analysis on the existing JSON.

```bash
# Reads the full sweep JSON; writes <stem>-time.json next to it.
uv run --package vllm-grpc-bench python -m vllm_grpc_bench --m3 \
    --reanalyze bench-results/m3-full/m3-channel-tuning.json
```

Output:

- `bench-results/m3-full/m3-channel-tuning-time.json` — slim companion with time-axis recommendations and `p1_frozen_config_time`
- (then copy to `docs/benchmarks/m3-channel-tuning-time.json` for publication; the markdown companion at `docs/benchmarks/m3-channel-tuning-time.md` is hand-authored from the JSON's per-cell data)

The `--reanalyze` mode prints a verdict breakdown summary on completion. Per `research.md` R-12, the time-axis builder uses **immediate-predecessor M1_BASELINE pairing** rather than the bytes path's "first M1_BASELINE in group" — the time metric exhibits ~13% cross-batch drift on this harness while bytes is robust to within 0.01%. See [`docs/decisions/0005-m3-statistical-methodology.md`](../../docs/decisions/0005-m3-statistical-methodology.md) for the rationale and the new `noise_bounded` verdict literal that flags cells the harness cannot defensibly resolve.

## P2 schema-level run (deferred to M4)

P2 is **deferred to milestone M4** per the 2026-05-10 spec clarifications session — protobuf-shape candidates are most likely to manifest as TTFT wins, and TTFT becomes a defensible verdict metric only under M4's harness changes (FR-012 / FR-013 / FR-014). The CLI flags below remain wired up for future M4 work but are not invoked on the 015 branch:

```bash
# (For reference; not used in M3.)
uv run --package vllm-grpc-bench python -m vllm_grpc_bench --m3 \
    --p2-revision chat-token-ids-packed \
    --frozen-channel max-msg-16mib \
    --width 4096 \
    --path chat_stream
```

P2 candidates will be checked-in `.proto` revisions on a side-branch (or behind a feature flag) when M4 opens. See `docs/PLAN.md` Milestone 4 for the M4 scope.

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
| `No module named vllm_grpc_bench` | Bare `python -m vllm_grpc_bench …` outside the workspace venv | Prefix with `uv run --package vllm-grpc-bench` (every command in this quickstart shows this) |
| `ValueError: hidden_size > 0` at startup | `--width` flag not in `{2048, 4096, 8192}` and validation rejected the value | Use a canonical width, or accept the off-canonical run is exploratory only |
| Many cells reporting `not_measurable` | Local CPU is too slow / busy; iterations time out | Close other heavy processes; rerun. If persistent, increase per-cell deadline via `BENCH_RPC_DEADLINE_S` env |
| `m3-channel-tuning.json` exists but `.md` is empty | Reporter crashed mid-write | Inspect `bench-results/<timestamp>/error.log`; rerun with `--smoke` first to isolate |
| Compression cell shows the candidate is *worse* than baseline | Expected for embed (dense float tensors). Verify the report records this honestly per Constitution V | No fix needed; this is a recorded "no_winner" outcome |
| `--reanalyze` returns `not_measurable` for chat_stream TTFT cells | Input JSON is the slim `docs/benchmarks/` companion with samples stripped, not the full `bench-results/m3-full/…` JSON | TTFT is computed per-sample; point `--reanalyze` at the FULL JSON (the one in `bench-results/m3-full/`, ~1 MB), not the slim docs companion |
| Many cells flagged `noise_bounded` | Cross-batch baseline drift larger than the candidate's apparent signal | Expected on the M3 harness; cells re-measure under M4's shared-baseline mode (FR-013) |

## What success looks like

- Four report files under `docs/benchmarks/`: `m3-channel-tuning.{md,json}` (bytes axis, PR #17) and `m3-channel-tuning-time.{md,json}` (time axis, this branch via Phase A).
- Every recommendation in either markdown report has one of: (a) a `winning_config` with a citation (`recommend`), (b) a clear `no_winner` verdict with the supporting numbers, (c) a `not_measurable` verdict with rationale, or (d) a `noise_bounded` verdict naming the dominating noise source and pointing at M4 for re-measurement.
- `summary.md` §4 cross-links to both reports with the dual-axis sub-table.
- `make check` is still green (201 passed at PR #17 + Phase A).
- Git diff for the Phase A PR is bounded to `tools/benchmark/{src,tests}/`, `docs/benchmarks/m3-channel-tuning-time.*`, `docs/benchmarks/summary.md`, `docs/decisions/0005-m3-statistical-methodology.md`, and the README/spec updates that record the milestone closure.
