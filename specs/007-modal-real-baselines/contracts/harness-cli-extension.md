# Contract: Harness CLI Extensions (Phase 4.1)

**Module**: `vllm_grpc_bench` (extends `specs/004-benchmark-harness/contracts/cli.md`)

This document describes only the additions to the harness CLI. Existing commands
and flags are unchanged and remain under the Phase 4 contract.

---

## New Subcommand: `compare-cross`

Compares two `BenchmarkRun` JSON files that represent different deployment types
(e.g., REST vs gRPC). Aligns metrics by concurrency level; ignores the `target`
field. Produces a head-to-head table and exits 0 regardless of which run is faster
(this is a report command, not a regression gate).

```
python -m vllm_grpc_bench compare-cross --result-a PATH --result-b PATH
  [--label-a LABEL] [--label-b LABEL]
  [--output PATH]
```

### Arguments

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--result-a PATH` | `Path` | *(required)* | Path to the first `BenchmarkRun` JSON file (e.g., REST baseline) |
| `--result-b PATH` | `Path` | *(required)* | Path to the second `BenchmarkRun` JSON file (e.g., gRPC baseline) |
| `--label-a LABEL` | `str` | `"run-a"` | Human-readable label for run A in the report |
| `--label-b LABEL` | `str` | `"run-b"` | Human-readable label for run B in the report |
| `--output PATH` | `Path` | *(stdout)* | If set, writes the markdown report to this file; otherwise prints to stdout |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Report generated successfully |
| `2` | Usage error (missing flags, file not found) |

### Example

```bash
python -m vllm_grpc_bench compare-cross \
  --result-a docs/benchmarks/phase-3-modal-rest-baseline.json \
  --result-b docs/benchmarks/phase-3-modal-grpc-baseline.json \
  --label-a REST --label-b gRPC \
  --output docs/benchmarks/phase-3-modal-comparison.md
```

---

## Updated Makefile Target

```makefile
bench-modal:
	uv run --with modal modal run scripts/python/bench_modal.py
```

Added to `.PHONY` alongside existing bench targets.

---

## Backward Compatibility

- All existing `run` and `compare` subcommand flags are unchanged.
- `RunMeta` gains three optional fields (`modal_function_id`, `gpu_type`, `cold_start_s`); existing `results.json` files without these fields remain deserializable.
- The committed CI baseline (`docs/benchmarks/phase-3-ci-baseline.json`) is unaffected.
