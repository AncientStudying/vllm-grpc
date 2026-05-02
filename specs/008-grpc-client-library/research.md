# Research: Phase 4.2 — Direct gRPC Client Library

## R-001: py.typed Mechanism for Generated Stubs

**Decision**: Add an empty `py.typed` marker file at `packages/gen/src/vllm_grpc/py.typed`. No pyproject.toml change is needed — hatchling includes all files under the declared `packages = ["src/vllm_grpc"]` path automatically.

**Rationale**: PEP 561 requires a `py.typed` marker at the package root for a package to be recognized as typed. This is a one-file change. After adding it, the six `# type: ignore[import-untyped]` suppressions across `packages/proxy` and `packages/frontend` can be removed. The remaining suppressions in the frontend (`# type: ignore[misc]`, `# type: ignore[type-arg]`) are grpcio servicer inheritance patterns unrelated to the gen package and stay in place.

**Scope boundary**: Only `import-untyped` suppressions from the gen package are in scope. grpcio's own typing gaps are out of scope for this phase.

**Alternatives considered**: Stubs-only package (`vllm-grpc-gen-stubs`) — unnecessary overhead since the gen package is already part of the workspace. Inline type annotations in generated code — would be overwritten on the next `make proto` run.

---

## R-002: VllmGrpcClient Channel Lifecycle

**Decision**: Create the gRPC channel once in `__aenter__` and close it in `__aexit__`. Sub-clients (`.chat`) hold a reference to the shared channel. All calls within a single `async with` block share the same connection.

**Rationale**: The existing `GrpcChatClient` in `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` opens a new channel per call (`async with grpc.aio.insecure_channel(...)`). This is acceptable for a proxy that receives requests one at a time, but a benchmark client makes hundreds of concurrent requests. Per-call channel creation would incur TLS-equivalent handshake overhead on every request and negate any protocol efficiency measurement.

**Channel object**: `grpc.aio.Channel` (the async gRPC channel), created with `grpc.aio.insecure_channel(addr)`. Closed via `await channel.close()` in `__aexit__`.

**Alternatives considered**: Module-level singleton — not testable, not safe for concurrent test suites. `grpc.Channel` (sync) — inconsistent with the async-first workspace.

---

## R-003: gRPC-Direct Target in the Benchmark Harness

**Decision**: Add `run_grpc_target(addr, samples, concurrency, timeout)` alongside the existing `run_target()` in `tools/benchmark/src/vllm_grpc_bench/runner.py`. The new function is not an overload of `run_target()` — it takes an address string rather than a URL, uses `VllmGrpcClient` instead of httpx, and returns `RequestResult` with `target="grpc-direct"`.

**Wire bytes measurement for gRPC**: Request bytes = `len(chat_pb2.ChatCompleteRequest(...).SerializeToString())`. Response bytes = `len(response_proto.SerializeToString())`. This gives true protobuf wire size, making it directly comparable to the JSON byte counts in the REST and proxy runs — one of the most important data points of the phase.

**Concurrency model**: Same semaphore-bounded `asyncio.gather` pattern as `run_target()`. The `VllmGrpcClient` channel is opened once before the gather and shared across all concurrent coroutines. grpc.aio channels are safe for concurrent use.

**Alternatives considered**: Modify `run_target()` to detect gRPC via URL scheme — too much branching. Separate module — unnecessary for ~60 lines.

---

## R-004: Three-Way Comparison Structure

**Decision**: Add `ThreeWayReport` / `ThreeWayRow` dataclasses to `metrics.py`, `compare_three_way()` to `compare.py`, and `write_three_way_md()` to `reporter.py`. Add a `compare-three-way` subcommand to `__main__.py`. The three-way report shows REST / gRPC-proxy / gRPC-direct side-by-side with Δ(proxy vs REST) and Δ(direct vs REST) columns.

**Rationale**: Reusing `CrossRunReport` (two-column) for three targets would require a structural schema change that breaks the existing `compare-cross` interface. New types are additive and keep the existing two-way interface intact.

**Alternatives considered**: Two separate `compare-cross` invocations (proxy vs REST, direct vs REST) — produces two disconnected documents rather than a single at-a-glance table. Extend `CrossRunReport` to hold N runs — over-engineering for a fixed three-way case.

---

## R-005: Three-Way Orchestration in bench_modal.py

**Decision**: The gRPC serve function (`serve_grpc_for_bench`) stays alive for both gRPC-via-proxy and gRPC-direct runs. The orchestration order is:
1. REST phase: spawn → wait → REST harness → stop
2. gRPC phase: spawn → wait → proxy harness → gRPC-direct harness → stop
3. Comparison: load three JSONs → `compare_three_way()` → write five files

**Rationale**: Running gRPC-via-proxy and gRPC-direct back-to-back against the same warm Modal deployment avoids a third cold start (which would add ~75s and introduce measurement variance from model warm-up). Both harness runs use the same corpus and concurrency, so the comparison is fair.

**gRPC-direct address**: The same `grpc_addr` written to `modal.Dict` by `serve_grpc_for_bench` is used for both the local proxy target and the direct gRPC target. The local proxy subprocess is started only for the proxy harness run and torn down before the direct harness run.

**Alternatives considered**: Separate third Modal deployment for gRPC-direct — two cold starts makes variance analysis harder and costs more GPU time. Running gRPC-direct before proxy — either order works; proxy first is consistent with Phase 4.1 gRPC ordering.

---

## R-006: __main__.py Extension

**Decision**: Add `compare-three-way` subcommand with `--result-a PATH`, `--result-b PATH`, `--result-c PATH` (required), `--label-a/b/c LABEL` (defaults: `"rest"`, `"grpc-proxy"`, `"grpc-direct"`), and `--output PATH` (optional). Follows the same validation and output pattern as `compare-cross`.

**Rationale**: `compare-cross` is a stable interface already used in CI; adding a new subcommand avoids breaking the existing workflow.
