# Contract: bench_modal.py Orchestration Script

**Script**: `scripts/python/bench_modal.py`
**Invocation**: `modal run scripts/python/bench_modal.py`
**Makefile target**: `make bench-modal`

---

## Purpose

Runs both the REST and gRPC benchmark deployments sequentially on Modal A10G,
collects harness results for each, and writes a head-to-head comparison report.
No manual steps are required between the two deployments.

---

## Prerequisites

- Modal token configured (`modal token new` or existing token in env)
- `vllm-grpc-model-weights` Modal Volume pre-staged (from `make download-weights`)
- `uv sync --all-packages` completed locally

---

## Execution Flow

```
1. Spawn serve_rest_for_bench.remote.spawn()
2. Poll modal.Dict["rest_addr"] until address appears or timeout
3. Print: REST tunnel address
4. Invoke harness run (subprocess or module call):
     --proxy-url <rest_addr>  --native-url <rest_addr>
     --corpus tools/benchmark/corpus/chat_nonstreaming.json
     --concurrency 1,4,8
     --output-dir <tmp>
5. Copy tmp/results.json → bench-results/results-rest.json
6. Set modal.Dict["rest_stop"] = True
7. Print: REST run complete, tearing down

8. Spawn serve_grpc_for_bench.remote.spawn()
9. Poll modal.Dict["grpc_addr"] until address appears or timeout
10. Print: gRPC tunnel address
11. Start local proxy subprocess: FRONTEND_ADDR=<grpc_addr> make run-proxy ...
12. Invoke harness run:
      --proxy-url http://localhost:8000  --native-url http://localhost:8000
      --corpus tools/benchmark/corpus/chat_nonstreaming.json
      --concurrency 1,4,8
      --output-dir <tmp>
13. Copy tmp/results.json → bench-results/results-grpc.json
14. Kill proxy subprocess
15. Set modal.Dict["grpc_stop"] = True
16. Print: gRPC run complete, tearing down

17. Invoke compare_cross(rest_run, grpc_run, label_a="REST", label_b="gRPC")
18. Write docs/benchmarks/phase-3-modal-rest-baseline.json  (copy of results-rest.json)
19. Write docs/benchmarks/phase-3-modal-rest-baseline.md    (summary_md for REST run)
20. Write docs/benchmarks/phase-3-modal-grpc-baseline.json  (copy of results-grpc.json)
21. Write docs/benchmarks/phase-3-modal-grpc-baseline.md    (summary_md for gRPC run)
22. Write docs/benchmarks/phase-3-modal-comparison.md       (CrossRunReport rendered)
23. Print: All results written.
```

---

## Module-Level Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `_CORPUS_PATH` | `tools/benchmark/corpus/chat_nonstreaming.json` | Shared corpus for both runs |
| `_CONCURRENCY` | `"1,4,8"` | Shared concurrency levels for both runs |
| `_ADDR_POLL_TIMEOUT_S` | `600` | Seconds to wait for tunnel address before aborting |
| `_DICT_NAME` | `"vllm-grpc-bench-modal"` | modal.Dict namespace |
| `_VLLM_VERSION` | `"0.20.0"` | Pinned vLLM version (same as other Modal scripts) |
| `_MODEL_PATH` | `"/mnt/weights"` | Model volume mount path inside container |
| `_REST_PORT` | `8000` | vLLM REST server port inside container |
| `_GRPC_PORT` | `50051` | gRPC frontend port inside container |
| `_FUNCTION_TIMEOUT_S` | `3600` | Modal function timeout (1 hour) |

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| Tunnel address not received within `_ADDR_POLL_TIMEOUT_S` | Print error, send stop signal, exit code 1; partial result files NOT written |
| Harness run exits with non-zero code | Print error, send stop signals, exit code 1; partial result files NOT written |
| Proxy subprocess fails to start | Print error, send gRPC stop signal, exit code 1 |
| `compare_cross()` fails | Print warning, baseline JSON files still written; only comparison.md skipped |

---

## Output Files

| File | Written when | Description |
|------|-------------|-------------|
| `bench-results/results-rest.json` | After REST run | Raw harness output (temporary working copy) |
| `bench-results/results-grpc.json` | After gRPC run | Raw harness output (temporary working copy) |
| `docs/benchmarks/phase-3-modal-rest-baseline.json` | End of successful run | REST baseline to commit |
| `docs/benchmarks/phase-3-modal-rest-baseline.md` | End of successful run | REST summary markdown |
| `docs/benchmarks/phase-3-modal-grpc-baseline.json` | End of successful run | gRPC baseline to commit |
| `docs/benchmarks/phase-3-modal-grpc-baseline.md` | End of successful run | gRPC summary markdown |
| `docs/benchmarks/phase-3-modal-comparison.md` | End of successful run | Head-to-head comparison |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Both runs completed; all output files written |
| `1` | Deployment failure, harness error, or proxy startup failure |
