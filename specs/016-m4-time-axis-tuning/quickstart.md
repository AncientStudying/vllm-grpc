# M4 Quickstart — reproducing the time-axis sweep locally

This is the minimal recipe a contributor follows to reproduce the M4 measurements on a single host. It assumes you've already cloned the repo and installed the workspace (`uv sync`).

## Prerequisites

- macOS Apple Silicon (M2/M3) or Linux x86-64.
- Python 3.12 (managed by `uv`).
- `make` and `protoc` available on `PATH` (the project's `make proto` target shells out to `protoc`).
- `~4 hours` of mostly-idle CPU on the host. Background load drives within-cohort CV — the run still completes, but cohorts above `--baseline-cv-warn` (default 5%) carry a `noisy_baseline: true` flag in the published JSON for the reader's adjudication (FR-005).
- (Optional) the cross-repo graph at `cross-repo.json`, refreshed via `/ground-truth-refresh` if the lockfile pins have changed since the last refresh. Citations in the published report require the cloned vLLM and grpcio sources to be available.

## One-time setup (or after a candidate proto change)

```bash
# Regenerate stubs for production proto + the m4-candidates sibling namespace.
make proto

# Verify the harness imports the candidate stubs.
uv run python -c "from packages.gen.vllm_grpc_m4_candidates import packed_token_ids; print('ok')"
```

## Run the full M4 sweep

```bash
# Full sweep — US1 mechanics + US2 channel sweep + US3 schema candidates.
# Default flags: --no-pacing --shared-baseline --baseline-n=100 --candidate-n=100 --expand-n=250 --baseline-cv-warn=0.05
uv run python -m vllm_grpc_bench --m4
```

The run writes:

- `bench-results/m4-full/per-iteration/*.json` — transient per-iteration timings (gitignored).
- `docs/benchmarks/m4-time-axis-tuning.json` — the published JSON (strict-superset of `m3-channel-tuning-time.json`).
- `docs/benchmarks/m4-time-axis-tuning.md` — the human-readable companion.

stdout summary:

```text
M4 sweep complete: <N> recommend, <M> no_winner, <K> client_bound. <P> M3 cells superseded.
```

## Run incrementally while iterating

```bash
# US1 mechanics smoke (runs the harness mechanics tests only — no full sweep):
uv run pytest tools/benchmark/tests/test_m4_sweep.py tools/benchmark/tests/test_mock_engine.py -q

# US1 + US2 only (skip schema candidates while you iterate on the channel sweep):
uv run python -m vllm_grpc_bench --m4 --skip-schema

# Just one width while debugging:
uv run python -m vllm_grpc_bench --m4 --widths=4096
```

## Inspect what was measured

```bash
# Confirm no noise_bounded verdicts leaked into the M4 report (FR-007).
jq '[.cohorts[] | select(.recommendation? // "")] | map(.verdict) | unique' \
   docs/benchmarks/m4-time-axis-tuning.json

# List the cells M4 supersedes from M3.
jq '.supersedes[] | "\(.m3_cell_id) [\(.m3_verdict)] -> [\(.m4_verdict)]: \(.rationale)"' \
   docs/benchmarks/m4-time-axis-tuning.json

# Find borderline-expanded cohorts.
jq '.cohorts[] | select(.expansion_record.expanded == true) | .cell_id' \
   docs/benchmarks/m4-time-axis-tuning.json

# Find client_bound cohorts (excluded from recommend tallies, FR-004).
jq '.cohorts[] | select(.client_bound == true) | .cell_id' \
   docs/benchmarks/m4-time-axis-tuning.json
```

## When the run aborts

| Exit | What happened | What to do |
|------|---------------|-----------|
| `2` | CLI flag conflict or arithmetic violation. | Read the stderr message; fix flags. |
| `4` | Internal validation failure (e.g., harness tried to emit `noise_bounded`). | Bug in M4 code. File against `tools/benchmark/`. |
| `5` | A schema-candidate proto failed compilation. | Run `make proto` standalone to surface the protoc error; fix the offending `.proto` file under `proto/vllm_grpc/v1/m4-candidates/`. |

The run does **not** abort on noisy baselines (FR-005). Instead, every cohort's per-cohort CV is recorded on its JSON entry, and a closing warning names any baseline cohort whose CV exceeded `--baseline-cv-warn` (default 5%). Re-run only the affected cohorts in a follow-up if the noise was situational.

## Cross-host considerations

Cross-host transport mode is **out of scope** for M4 single-host runs. If the published report flags `keepalive` or `http2_framing` axes with the loopback caveat (FR-010 — these axes always carry the caveat on single-host runs per R-6), and you want to upgrade those verdicts, that work is a future-milestone task. Do not attempt to remove the caveat by re-running on a single host with different flags — the caveat is a deterministic function of the run topology, not the data.

## Citations expected in the published report

Per FR-015 and the M2 ground-truth workflow:
- gRPC channel-options behavior cites `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` and the targeted grpcio Python-wrapper graph at `~/.graphify/repos/grpc/grpc/src/python/grpcio/graphify-out/graph.json`.
- vLLM streaming surface cites `~/.graphify/repos/vllm-project/vllm/vllm/v1/engine/async_llm.py` and the vLLM graph at `~/.graphify/repos/vllm-project/vllm/graphify-out/graph.json`.
- Cross-repo paths (e.g., proxy → frontend → engine) cite `cross-repo.json` via `graphify path` queries per the project CLAUDE.md.
