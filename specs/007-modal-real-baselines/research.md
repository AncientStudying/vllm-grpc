# Research: Phase 4.1 — Real Comparative Baselines (Modal)

**Branch**: `007-modal-real-baselines` | **Date**: 2026-05-02

---

## R-001: How to expose the Modal REST server externally for benchmark traffic

**Decision**: Use `modal.forward(8000, unencrypted=True)` inside a long-lived Modal function — the same pattern Phase 3.2 used for the gRPC port. The tunnel address is published to a `modal.Dict` so the local orchestration script can pick it up.

**Rationale**: `modal.forward()` is the only mechanism the project has validated for persistent TCP tunnels carrying non-HTTP/2 traffic. The REST port emits plain HTTP/1.1, so `unencrypted=True` is correct. Modal's web endpoint alternative (`@modal.web_endpoint`) would wrap the server in a Modal HTTP proxy and potentially add latency overhead that would confound the REST vs gRPC comparison. A raw TCP tunnel ensures the benchmark harness talks directly to the vLLM REST process.

**Alternatives considered**:
- `@modal.web_endpoint`: introduces Modal's own HTTP layer between harness and vLLM; unsuitable for an honest wire-overhead measurement.
- Running the REST server as a web endpoint that proxies to the subprocess: same issue plus added complexity.

---

## R-002: Where to define the REST and gRPC serve functions

**Decision**: Both serve functions (`serve_rest_for_bench` and `serve_grpc_for_bench`) are defined directly inside `scripts/python/bench_modal.py` as `@app.function` decorators on a single `modal.App`. The local entrypoint (also in `bench_modal.py`) orchestrates the sequential lifecycle: spawn REST function → wait for address → run harness → send stop signal → spawn gRPC function → repeat.

**Rationale**: Self-contained. `bench_modal.py` is the only script the developer needs to understand or run (`modal run scripts/python/bench_modal.py`). No cross-module Modal app imports are needed. The serve functions can share the same `modal.Dict` namespace under different keys (or under separate dicts) to avoid key collisions with `modal_frontend_serve.py`.

**Alternatives considered**:
- Import and reuse `modal_frontend_serve.py`'s `app` object: Python module-level imports of Modal apps do not compose cleanly (each script has its own `modal.App`). Cross-app function calls require remote lookup, not local import.
- Subprocess `modal run`: would lose programmatic control and return values; defeating the purpose of the orchestration script.

---

## R-003: Extending RunMeta with Modal-specific traceability fields

**Decision**: Add three optional fields to the existing `RunMeta` dataclass: `modal_function_id: str | None = None`, `gpu_type: str | None = None`, and `cold_start_s: float | None = None`. The serve function passes these values back to the local entrypoint via `modal.Dict`; the orchestration script sets them on the `RunMeta` before serializing the run result. Existing deserializer uses `.get()` for these keys so old JSON files remain readable.

**Rationale**: The spec requires per-run traceability to a specific Modal deployment and GPU. Optional fields with `None` defaults preserve backward compatibility with the `phase-3-ci-baseline.json` file already committed. No new dataclass needed.

**Alternatives considered**:
- Separate `ModalRunMeta` subclass wrapping `RunMeta`: more type-safe but requires a second deserialization path and breaks `isinstance` checks in `compare.py`.
- Sidecar metadata JSON file per run: splits traceability from results, making it easier to lose one half; rejected.

---

## R-004: REST vs gRPC cross-run comparison

**Decision**: Add a new `compare_cross(run_a: BenchmarkRun, run_b: BenchmarkRun, label_a: str, label_b: str) -> CrossRunReport` function in `compare.py`. This function aligns summaries by concurrency level only (ignoring the `target` field, since the two runs use different target labels). A new `CrossRunReport` dataclass holds side-by-side metric tables. A new `compare-cross` subcommand in the harness CLI exposes this via `--result-a` / `--result-b` flags. The `bench_modal.py` orchestration script calls this function after both runs complete and writes the report to `docs/benchmarks/`.

**Rationale**: The existing `compare()` function aligns on `(target, concurrency)` — appropriate for regression detection where both runs used the same targets. For REST vs gRPC, the two runs intentionally have different target labels (the REST run uses `target="native"` since the harness calls the REST endpoint directly; the gRPC run uses `target="proxy"` since the harness calls the local proxy). Aligning by concurrency alone and presenting the result as a head-to-head table is the correct framing for the thesis comparison.

**No change to the existing `compare()` function**: it continues to serve regression detection (CI baseline workflow). `compare_cross()` is a separate code path.

**Alternatives considered**:
- Relabeling both runs to use `target="rest"` and `target="grpc"` respectively: would break the existing `compare()` which expects `"proxy"` or `"native"`; also changes existing serialized baseline files.
- A single combined run that runs all four combinations in one `BenchmarkRun`: impossible due to Modal deployment constraint (cannot have both REST and gRPC endpoints live simultaneously).

---

## R-005: Benchmark target labels for the two Modal runs

**Decision**:
- **REST run**: The harness is called with `--native-url <modal-rest-tunnel>` and a synthetic `--proxy-url` pointing at a local stub (or the same REST URL) so that the harness runs without error. Only the `native` target results are used from this run. The result file is labelled `results-rest.json` at the orchestration level.
- **gRPC run**: The harness is called with `--proxy-url http://localhost:8000` (local proxy) and a synthetic `--native-url` pointing at the same proxy (or a local stub). Only the `proxy` target results are used. The result file is labelled `results-grpc.json`.

Both runs use the identical corpus and identical concurrency levels, ensuring the `compare_cross()` alignment by concurrency is apples-to-apples.

**Rationale**: The current harness requires both `--proxy-url` and `--native-url`. Rather than modifying the harness to accept a single-target mode, we pass the same URL for both targets and use only the relevant half of each result file in the comparison. This is the minimum-change path.

**Note**: `build_run_meta()` will record the actual URL used; the orchestration script sets `modal_function_id` and `gpu_type` from the `modal.Dict` metadata.

**Alternatives considered**:
- Adding a `--single-target` flag to the harness: clean but expands harness scope beyond Phase 4's boundary.
- Running both targets in a single Modal session (REST + gRPC simultaneously): violates the one-deployment constraint.

---

## R-006: Preventing test corpus and concurrency drift between runs

**Decision**: `bench_modal.py` hardcodes the corpus path and concurrency levels as module-level constants (`_CORPUS_PATH`, `_CONCURRENCY`). Both runs are called with the same values. The `compare_cross()` report includes a "run metadata" section showing corpus path and concurrency levels for both runs so any accidental drift is visible.

**Rationale**: The spec requires "identical corpus and concurrency settings." Embedding the values once in the orchestration script and passing them to both harness calls is the safest single-point enforcement.
