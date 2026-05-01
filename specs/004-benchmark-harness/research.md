# Research: Metrics and Benchmark Harness (Phase 4)

**Branch**: `004-benchmark-harness` | **Date**: 2026-05-01
**Purpose**: Resolve design questions before implementation begins.

---

## Topic 1: Wire Bytes Measurement Approach

**Question**: What constitutes "wire bytes per request and per response" when both the proxy bridge and the native vLLM server expose the same OpenAI-compatible REST interface to the harness?

**Decision**: Measure HTTP body bytes only — `len(request_body_utf8)` + `len(response_body_utf8)`.

**Rationale**:
- Both endpoints accept and return identical JSON payloads for the same request; header overhead is functionally identical between the two paths (same HTTP/1.1 framing).
- Body bytes are the meaningful signal: they document the payload size the harness and each server are exchanging and confirm neither path inflates the response.
- True TCP wire bytes require OS-level socket instrumentation (e.g., `SO_RCVBUF` accounting or `tcpdump`) that is not portable across macOS and Linux CI environments.
- Documenting body bytes is honest and reproducible from the corpus fixtures alone.

**Alternatives Considered**:
- *Full HTTP wire bytes (headers + body)*: More accurate, but header overhead (~200-400 bytes) is constant across both paths and adds noise without signal.
- *OS-level TCP accounting*: Most accurate, but requires root-level tooling incompatible with GitHub Actions sandbox.
- *httpx custom transport layer*: Wrapping the transport to count bytes is possible but adds brittle dependency on `httpx` internals; body-size measurement is simpler and just as informative for this project's claims.

---

## Topic 2: Proxy Processing-Time Isolation

**Question**: How do we measure time spent in the proxy translation layer per request, separately from gRPC round-trip time and model inference time?

**Decision**: Instrument the proxy with a FastAPI middleware (`bench_middleware.py`) that records wall-clock timestamps at four points per request: (a) after request body is decoded, (b) immediately before the gRPC call starts, (c) immediately after the gRPC call returns, and (d) before the HTTP response is serialized. The sum of (b−a) + (d−c) is "proxy translation time." This value is written to the `X-Bench-Proxy-Ms` response header (float, milliseconds). The harness reads this header for each response from the proxy path; it is absent on the native path.

**Rationale**:
- Wall-clock translation time is the right measure for an async server: under normal load the CPU is idle during the gRPC round-trip, so `resource.getrusage()` per-request would be near-zero and uninformative.
- Middleware placement captures the real boundary: everything before the gRPC call (request deserialization + proto translation) and everything after it (response translation + JSON serialization).
- Writing the measurement to a response header keeps the harness stateless: it does not need to correlate async request IDs.
- The header is unconditional (always emitted by the proxy); this avoids conditional logic in the proxy and is harmless for non-benchmark callers.

**Alternatives Considered**:
- *Differential timing (proxy_latency − native_latency)*: Does not isolate translation overhead from gRPC round-trip network time, which is real overhead even with localhost addresses.
- *`psutil.Process.cpu_times()` before/after each request*: Gives cumulative process CPU time, not per-request data — incorrect in a concurrent async environment.
- *Prometheus metrics endpoint*: More powerful but adds a new dependency and requires a running metrics server; out of scope for Phase 4.

---

## Topic 3: Concurrency Model

**Question**: How should the harness issue concurrent requests and measure per-request latency correctly?

**Decision**: Use `asyncio.gather()` to issue N concurrent `httpx.AsyncClient.post()` calls per concurrency level. Record `time.perf_counter()` immediately before and after each individual `post()` call as the per-request wall-clock latency. Repeat the full corpus at each concurrency level (e.g., 1, 4, 8 concurrent requests).

**Rationale**:
- `httpx.AsyncClient` with `asyncio.gather()` matches the project's existing async patterns (proxy and frontend both use `grpc.aio`).
- `time.perf_counter()` is the highest-resolution Python clock for wall-clock latency; it is not affected by `asyncio` event-loop scheduling overhead in a meaningful way for HTTP calls that take tens to hundreds of milliseconds.
- Separate concurrency levels (1, 4, 8) give P50/P95/P99 latency distributions that reveal queueing behavior, not just single-client behavior.

**Alternatives Considered**:
- *`ThreadPoolExecutor`*: Would work but adds thread overhead; unnecessary given `httpx`'s native async support.
- *`multiprocessing`*: Adds measurement noise from inter-process coordination; overkill for a developer benchmark.
- *Single concurrency level only*: Would miss queueing effects that become significant at higher concurrency.

---

## Topic 4: GitHub Actions PR Regression Comment

**Question**: How should the automated CI job post a benchmark regression comment on pull requests?

**Decision**: A dedicated `benchmark.yml` GitHub Actions workflow triggers on `pull_request` when paths `packages/proxy/**` or `packages/frontend/**` change. It:
1. Starts a `FakeHTTPServer` for both target endpoints.
2. Runs the harness against the stub servers, writing results to a JSON artifact.
3. Compares results to the committed CI baseline (`docs/benchmarks/phase-3-ci-baseline.json`) using `bench compare`.
4. Posts a markdown PR comment using `actions/github-script` with the comparison table and a note that CI results use a stub backend.

The comment is upserted (updated if a prior comment from the same workflow run exists; created otherwise) by matching a sentinel HTML comment in the comment body.

**Rationale**:
- `actions/github-script` is the lowest-friction way to post a PR comment from CI without external actions.
- Using stub servers in CI keeps the workflow fast (< 60 seconds) and free of GPU/model dependencies.
- The committed CI baseline (`-ci-baseline.json`) is distinct from the real baseline (`-baseline.json`) so that CI comparison is apples-to-apples (stub vs. stub).
- Upserted comments avoid comment spam on multiple pushes.

**Alternatives Considered**:
- *`benchmark-action/github-action-benchmark`*: Opinionated, stores benchmark history in a `gh-pages` branch, and requires extra configuration. Overkill for a developer tool.
- *Post a new comment on every push*: Creates comment spam; upsert is strictly better.
- *Run the real benchmark in CI*: Requires a GPU or a long-running CPU inference — incompatible with GitHub Actions free tier and would make the workflow take 5+ minutes per PR.

---

## Topic 5: CI Stub Server Design

**Question**: What should the CI stub server return, and how does it keep benchmark results stable enough for regression detection?

**Decision**: Implement a `FakeHTTPServer` (analogous to Phase 3's `FakeChatServicer`) using `httpx`'s `MockTransport` or a lightweight `asyncio` HTTP server. It serves a pre-recorded JSON response for any `POST /v1/chat/completions` request, with a configurable artificial delay (`FAKE_DELAY_MS`, default 5 ms) to simulate minimal processing. The CI baseline is committed from a CI run using the same delay, so latency comparisons are stable across runs.

**Rationale**:
- A deterministic fixed delay makes CI latency measurements stable within a few percent; stub server latency is dominated by the configured delay, not OS scheduling noise.
- Reusing `httpx.MockTransport` (already a dev dependency) avoids starting a real HTTP server subprocess in tests.
- The CI baseline (stub) and the real baseline (live) serve different purposes: the CI baseline detects regressions in harness code and proxy translation logic; the real baseline documents actual performance.

**Alternatives Considered**:
- *Start a real proxy + `FakeChatServicer` in CI*: This is what Phase 3's integration tests do, and it would be a fair test of the proxy. However, it requires starting two server subprocesses and the gRPC stack, which adds ~10s of setup overhead and is overkill for a benchmark regression check.
- *No CI baseline; always post "no comparison available"*: Eliminates regression detection entirely, which defeats the purpose of FR-010 through FR-012.

---

## Topic 6: Output Format and Corpus Design

**Question**: What JSON structure should `results.json` use, and what requests should the corpus include?

**Decision — Corpus**: Ten fixed chat completion requests covering three input-length tiers (short/medium/long) with `temperature: 0.0` and `seed: 42` for determinism. `max_tokens: 10` to cap model inference time in live runs. Stored in `tools/benchmark/corpus/chat_nonstreaming.json` as a JSON array.

**Decision — Output**: `results.json` is a nested object:
```json
{
  "meta": { "timestamp": "...", "git_sha": "...", "hostname": "...", "corpus": "...", "concurrency_levels": [1, 4, 8] },
  "runs": {
    "proxy": { "1": { "latencies_ms": [...], "request_bytes": [...], "response_bytes": [...], "proxy_ms": [...] }, "4": { ... }, "8": { ... } },
    "native": { "1": { ... }, "4": { ... }, "8": { ... } }
  }
}
```
`results.csv` is a flat table with columns: `target, concurrency, request_id, latency_ms, request_bytes, response_bytes, proxy_ms`.
`summary.md` is a markdown table with one row per metric × concurrency level, showing proxy and native values side by side with a "Δ" column.

**Rationale**:
- Nested JSON allows future phases to add new metric keys without breaking existing parsers.
- The flat CSV format satisfies `FR-006` and is directly importable by spreadsheet tools.
- `proxy_ms` is `null` in native rows (the native server does not emit `X-Bench-Proxy-Ms`).
- Recording `git_sha` and `hostname` in `meta` implements the methodology documentation required by Constitution Principle V.

**Alternatives Considered**:
- *Single JSON array of individual request results*: Simpler but harder to compute percentiles without post-processing.
- *Parquet output*: Better for large datasets but adds a dependency (`pyarrow`) for no gain at the corpus sizes in this project.
