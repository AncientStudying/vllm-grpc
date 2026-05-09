# Contract: `vllm_grpc_bench --m3` CLI

**Feature**: 015-m3-protobuf-grpc-tuning
**Path**: `tools/benchmark/src/vllm_grpc_bench/__main__.py` (extended) + `m3_sweep.py` (new orchestrator)

This contract defines the user-facing CLI entrypoint for the M3 sweep. It augments the existing `python -m vllm_grpc_bench` CLI; existing modes (corpus runners used in M1) are not touched.

## Synopsis

```text
python -m vllm_grpc_bench --m3 \
    [--axis {max_message_size,keepalive,compression,http2_framing,all}] \
    [--width {2048,4096,8192,all}] \
    [--path {embed,chat_stream,both}] \
    [--iters-per-cell N]                  (default: 30) \
    [--out-dir docs/benchmarks]           (default; report files written here) \
    [--smoke]                             (default: off; runs 1 iter/cell, no CI math, exits success on any non-error) \
    [--seed N]                            (default: 0) \
    [--p2-revision NAME]                  (P2 only; activates --frozen-channel automatically) \
    [--frozen-channel NAME]               (P2 only; required when --p2-revision is set)
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Sweep completed; report written; no harness-level errors |
| 2 | Argument validation failed (e.g., `--p2-revision` without `--frozen-channel`) |
| 3 | At least one cell failed all 30 iterations (recorded as `not_measurable` in the report; the run still produces output but exits 3 to flag operator attention) |
| 4 | I/O error writing report |
| 1 | Unhandled exception (bug; should not occur in production paths) |

Exit codes 0 and 3 both produce a complete report; the difference is whether any cell silently failed. CI (Constitution IV) treats both as merge-eligible; operator review is the gate, not exit code.

## Behaviour

1. Constructs the cartesian product of `axis × width × path`, restricted by CLI flags. `--axis all` (default) expands to the four P1 axes.
2. For each cell:
    a. Spawns a `MockEngine` with the cell's `MockEngineConfig`.
    b. Brings up `frontend.main`'s servicers in-process with the cell's `ChannelConfig.server_options`.
    c. Brings up the proxy or direct-grpc client with the cell's `ChannelConfig.client_options`.
    d. Drives `--iters-per-cell` RPCs through the appropriate path, recording one `Sample` per iteration.
    e. Tears down the channel and server (avoids cross-cell contamination).
3. Aggregates `Sample`s into `RunCohort`s; computes `Recommendation`s per axis using the SC-003 statistical rule.
4. Emits two files per run: `m3-channel-tuning.md` (human-readable) and `m3-channel-tuning.json` (machine-readable). For P2 runs, the filenames are `m3-schema-tuning.{md,json}`.
5. The JSON layout MUST match the schema captured in `data-model.md` so downstream tooling and the cross-link in `summary.md` remain stable.

## Smoke mode

`--smoke` runs exactly one iteration per cell and **does not compute CI**. It exists for CI use (`make check` in PRs that touch the bench) to catch wiring regressions cheaply. Smoke runs do not produce a `Recommendation` and do not write to `docs/benchmarks/`; they write a transient report to `bench-results/m3-smoke-<timestamp>.json` (gitignored) and exit 0 if all cells return at least one non-error sample.

## CLI compatibility / non-goals

- The existing M1 modes of `vllm_grpc_bench` (driven by `--corpus`, `--target`, etc.) are unchanged. M3 mode is gated behind `--m3`.
- No interactive prompts; the CLI is batch-friendly for CI.
- No remote-machine support (one host per run; no SSH/RPC orchestration).

## Test obligations

- `tests/test_m3_sweep_smoke.py` MUST verify `--smoke --axis max_message_size --width 2048 --path embed` returns exit 0 and writes the expected smoke artefact.
- An argument-validation unit test MUST verify exit 2 on `--p2-revision foo` without `--frozen-channel`.
