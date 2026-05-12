# M5.1 Research — REST vs gRPC Head-to-Head on Real Wire

## Purpose

Resolve the methodology questions the M5.1 plan defers: what shape the FastAPI shim takes, how the dual-protocol Modal app is structured under Modal's HTTPS-edge / ALPN constraints, how the REST cohort runner integrates with the existing harness, how the dual gRPC sub-cohort matrix is dispatched, how the M1 time-axis supersession mapping handles real-vs-mock-engine continuity, and the JSON schema delta against M5's `m5-cross-host-validation.json`. Each section produces a single decision the plan and downstream code/contract docs rely on.

This file *resolves* NEEDS CLARIFICATION items implicit in the plan. The spec's explicit Clarifications (2026-05-11) already pinned the four methodology choices (SSE for chat; dual gRPC sub-cohorts; REST pool sized = c with keep-alive; default-gRPC control measured at every cell; narrative refresh unconditional on outcome). This research consolidates those clarifications into implementation-actionable decisions and pins the remaining open items.

---

## R-1 — FastAPI shim shape: which OpenAI-style endpoints, and how do they call MockEngine?

**Decision**: The shim exposes exactly two endpoints — `POST /v1/chat/completions` (SSE on `stream=true`, JSON otherwise) and `POST /v1/embeddings` (JSON). Both handlers read the request body, validate the bearer token in `Authorization: Bearer <token>`, hand off to a single in-container `MockEngine` instance (the same instance the gRPC servicers use), and emit either an SSE event stream (chat) or a JSON response (embeddings). The shim does **not** translate to gRPC under the hood — it calls `MockEngine.generate` / `MockEngine.embed` directly, the same call boundary the gRPC servicers use.

**Rationale**: The spec's Background and FR-002 explicitly require *both* protocols to exercise the **identical in-container engine code path** so the engine variable is held constant. The cleanest way to enforce that is for the shim to be a thin wrapper that bypasses gRPC entirely and calls into MockEngine directly. This also avoids a perverse measurement where REST pays "two hops through the box" (HTTP → gRPC → MockEngine) vs gRPC's one hop.

**Alternatives considered**:
- *REST → gRPC translation inside the shim (proxy-style)*: rejected. Would make REST structurally slower by definition (extra serialization round-trip in-container) and would conflate the gRPC-vs-REST measurement with gRPC's own overhead. The spec's "identical engine path" requirement is unambiguous on this.
- *Mount the project's existing `packages/proxy/` FastAPI app inside the Modal container*: rejected. The proxy does REST → gRPC translation specifically (its purpose is to bridge for the REST-via-proxy path). M5.1 needs a *direct* REST endpoint into MockEngine, not the proxy's translation path.
- *Use vLLM's OpenAI server entrypoint*: rejected. Constitution II + the spec's MockEngine continuity assumption forbid running real vLLM in M5.1.

---

## R-2 — Dual-protocol Modal app: how do FastAPI and gRPC coexist under Modal's tunneling constraints?

**Decision**: A single `modal.App` ("vllm-grpc-bench-rest-grpc-mock") hosts both protocols by exposing two ports inside the container: `8000` for FastAPI (uvicorn) and `50051` for the gRPC server. Each gets its own `modal.forward()` call: `modal.forward(8000)` (default HTTPS-terminated edge, used for REST) and `modal.forward(50051, unencrypted=True)` (plain-TCP tunnel, used for gRPC). The two tunnel URLs are written to the same `modal.Dict` the harness reads via `modal_endpoint.provide_endpoint`. A single MockEngine instance is created at container startup and shared by both servers via a module-level singleton.

**Rationale**: M5's `modal_bench_grpc_server.py` documents why gRPC must use `unencrypted=True` — Modal's HTTPS edge does not negotiate HTTP/2 ALPN, and the gRPC handshake fails with "Cannot check peer: missing selected ALPN property" if TLS is in front. REST has no such constraint: HTTP/1.1 over Modal-managed TLS is straightforward and matches the spec's "Modal-managed TLS for REST" assumption. So the two protocols cannot share a single tunnel — they share the container's MockEngine but expose independent forwards. Both run as concurrent asyncio tasks within the single Modal function entrypoint (uvicorn + grpc.aio.server both compatible with the same asyncio loop).

**Alternatives considered**:
- *Two separate Modal apps (one REST, one gRPC), deployed in lockstep*: rejected. Doubles deploy/teardown cost, breaks the "same MockEngine instance" guarantee (each app would have its own in-container MockEngine), and complicates the harness's deploy-once handshake.
- *Multiplex REST and gRPC on a single port via h2c / Hello-protocol sniffing*: rejected. Wildly increases implementation complexity, no off-the-shelf Modal pattern supports it, and the spec's "real wire under realistic conditions" goal does not warrant the operational risk.
- *REST over the same plain-TCP tunnel as gRPC (no TLS)*: rejected. M5's TLS-continuity assumption requires Modal-managed TLS on the REST side (matches the project's M1/M2 baselines). Stripping TLS from REST would make the comparison no longer apples-to-apples vs M1.

---

## R-3 — REST cohort runner: which client, how is concurrency dispatched, how is RTT probed?

**Decision**: The REST cohort runner lives in a new module `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py`. It uses `httpx.AsyncClient(http2=False, limits=httpx.Limits(max_keepalive_connections=c, max_connections=c, keepalive_expiry=300.0))` (per Clarifications 2026-05-11 / FR-008). Concurrency at c > 1 is dispatched by `asyncio.gather` over c concurrent worker coroutines, each holding one persistent keep-alive connection for the cohort duration. SSE chat is consumed via `client.stream("POST", url, json=body)` and iterated with `async for line in resp.aiter_lines()`; the harness records the wall-clock between request-send and the first non-empty SSE `data:` line as TTFT. JSON embed is a plain `client.post(url, json=body)` with `request_send_at` / `response_recv_at` wall-clock anchors. RTT is probed by a lightweight `GET /healthz` (no auth, no MockEngine call) over the same keep-alive connection immediately before the cohort's measurement window opens.

**Rationale**: Reusing `httpx.AsyncClient` matches M1's REST cohort exactly (same library, same async pattern). Pinning `http2=False` is required by the spec's HTTP/1.1-for-REST constraint. The c-worker `asyncio.gather` dispatch is the same shape as M5's gRPC cohort runner. The dedicated `/healthz` endpoint avoids contaminating cohort measurements with bearer-auth overhead (the auth middleware short-circuits unauthenticated `/healthz` requests). Using the same keep-alive connection for the RTT probe ensures the recorded RTT reflects the cohort's actual TCP path, not a fresh-connection one.

**Alternatives considered**:
- *`aiohttp` client*: rejected. `httpx` is already in the project (M1 used it) and has clean SSE support via `aiter_lines`; switching libraries would introduce gratuitous variance vs M1.
- *Single-coroutine REST client with manual request batching*: rejected. Doesn't match the spec's "c persistent keep-alive connections" pool model and would degrade c=4 / c=8 fairness vs gRPC.
- *RTT probe via an authenticated cohort-relevant endpoint*: rejected. Would conflate transport RTT with FastAPI handler dispatch + bearer-auth time, defeating the probe's purpose.

---

## R-4 — Dual gRPC sub-cohort matrix at c ≥ 2: how is the matrix expanded, what's the verdict semantics?

**Decision**: For each (path × hidden_size × concurrency) cell at c ≥ 2, the M5.1 sweep dispatches **three** gRPC cohorts in series (not parallel — Modal's CPU-only instance class has finite scheduling capacity, and parallel cohorts would inflate each other's variance):
  1. `tuned_grpc_multiplexed`: 1 channel using the M5 frozen-tuned-channel configuration, c HTTP/2 streams multiplexed (M5's pattern).
  2. `tuned_grpc_channels`: c independent channels each using the M5 frozen-tuned-channel configuration, one serial RPC per channel (symmetric with REST's connection-per-worker model).
  3. `default_grpc`: 1 channel using the M1-default channel configuration, c HTTP/2 streams multiplexed (FR-007's "does not branch into multiplexed/channels split" rule — only `tuned_grpc_*` cohorts are dual-sub-cohort'd).

At c=1 the three configurations collapse to two (the multiplexed/channels distinction is degenerate; only `tuned_grpc` and `default_grpc` are run). The comparison verdict emitter takes the REST cohort and each gRPC sub-cohort independently and emits up to **three verdict rows per cell at c ≥ 2** (one row per gRPC sub-cohort × REST), or two rows at c=1.

**Rationale**: This is a mechanical expansion of FR-006's "two parallel sub-cohorts" + FR-007's "per-cell default-gRPC control" decision. Running cohorts serially (not in parallel) is the same discipline M5 follows — cross-cohort timing parallelism would introduce co-tenancy interference inside the single Modal container. Three verdict rows per cell at c ≥ 2 is the natural reporting consequence: the reader sees the multiplexing component (multiplexed vs channels), the encoding+framing component (channels vs REST), and the channel-tuning component (multiplexed vs default-gRPC) explicitly.

**Alternatives considered**:
- *Run the three gRPC cohorts in parallel*: rejected. Co-tenancy interference inside the container's single CPU would inflate cross-cohort CV. Serial dispatch matches M5.
- *Skip `default_grpc` at c ≥ 2 entirely (rely on M5's published numbers)*: rejected. Clarifications 2026-05-11 explicitly chose "full re-measurement at every cell" — this is the user's chosen rigor level.
- *Emit a single best-of-gRPC verdict per cell instead of three rows*: rejected. The whole point of the dual-sub-cohort split is decomposability; collapsing back to one row erases the decomposition.

---

## R-5 — Supersede-M1: how does the M5.1 matrix map onto M1's published time-axis cells given mock-vs-real-engine continuity?

**Decision**: M1's published "REST vs gRPC" comparison cells in `docs/benchmarks/summary.md` and `docs/benchmarks/phase-3-modal-comparison.md` are loaded by `m5_1_supersede.py` and mapped to M5.1's matrix on **(path, concurrency)** only — M1 did not vary `hidden_size`, so the M5.1 supersession aggregates across `hidden_size` for the per-(path × concurrency) supersession row, citing the M5.1 verdict pattern across widths (e.g., "REST wins at all three widths" or "tuned-gRPC wins at h2048 and h4096; no_winner at h8192 due to server_bound"). The supersession entry's `comparison_basis` field records that the M5.1 verdict comes from a mock-engine head-to-head while M1's came from a real-vLLM head-to-head — a methodology divergence the reader must understand to interpret the row correctly. The spec's FR-020 + Edge Case 2 already handle this: the MockEngine read-instruction lives in the report's executive section.

**Rationale**: M1 measured real vLLM at one width per path; M5.1 measures MockEngine at three widths per path. The honest comparison is per-(path × concurrency) with M5.1's per-width detail collapsed into the rationale text. The alternative — refusing to map M5.1 onto M1 because of the methodology divergence — would defeat the entire purpose of US3 (the supersession table). The MockEngine continuity caveat is loud enough in the executive section (FR-015 + Edge Case 2) that no reader can miss it.

**Alternatives considered**:
- *Skip the supersession table entirely on the grounds that mock-vs-real engine breaks continuity*: rejected. The spec's US3 is explicit and the user's request for a clean cross-host control needs the supersession table to land its rhetorical purpose.
- *Defer M1 supersession to M7 (when real-vLLM is back in the loop)*: rejected. The supersession table for M5.1 names what M5.1's evidence shows; M7 will produce a *separate* "Supersedes M5.1 (real-vLLM)" table on its own milestone. Forward-only supersession is the project's pattern (M5 supersedes M4; M5.1 supersedes M1's time axis; M7 will supersede M5.1's mock-engine time axis).
- *Only supersede M1 cells whose verdict M5.1 *changes* (skip "M5.1 confirms M1")*: rejected. FR-020 explicitly requires every M1 time-axis cell M5.1's matrix covers to appear in the table, confirmed or changed — the visual distinction (FR-020(b)) is by row highlighting, not by row presence.

---

## R-6 — JSON schema additive delta vs `m5-cross-host-validation.json`

**Decision**: M5.1's JSON schema is a strict superset of M5's. New top-level keys: `m5_1_matrix` (the 18-cell head-to-head matrix), `supersedes_m1_time` (the supersession table), `rest_shim_meta` (FastAPI shim version, uvicorn workers, intra-process overhead aggregates). New per-cohort keys (additive to M5's `CohortResult`): `protocol` (`"rest"` | `"grpc"`), `grpc_channel_model` (`"multiplexed"` | `"channels"` | `"degenerate_c1"` | `null` for REST), `connection_count` (the actually-opened connection count), `shim_overhead_ms` (REST only; `null` for gRPC), `comparison_cell_key` (matrix-cell identifier so a per-cell aggregator can group cohorts back to cells). New per-cell verdict entry under `m5_1_matrix[*]`: `comparison_verdict` (literal: `tuned_grpc_multiplexed_recommend` | `tuned_grpc_channels_recommend` | `tuned_grpc_recommend` | `rest_recommend` | `no_winner` | `comparison_unavailable`), `comparison_unavailable_reason` (string when applicable), supporting CI-bounded deltas. M5's existing keys (`channel_axis`, `recommendations`, `supersedes_m4`, etc.) are present and unchanged when the M5.1 mode is active — those keys are emitted with empty arrays (M5.1 does not re-measure channel axes or schema candidates, those stay M5's domain).

**Rationale**: The "additive only" rule (spec FR-014) lets M5-aware tooling consume M5.1's JSON without modification — every key M5 emits is still present and carries M5-compatible semantics. New M5.1-specific keys live in new namespaces so an M5-only consumer simply ignores them. The choice to keep M5's empty-array keys (rather than omitting them entirely) is a forward-compatibility move: if `summary.md`'s rendering tooling expects those keys to exist, they exist.

**Alternatives considered**:
- *Rename `m5_matrix` (M5's per-cell channel-axis matrix) to something M5.1-specific to avoid confusion*: rejected. Renames are non-additive and break M5 consumers.
- *Emit M5.1 as a separate JSON file with no M5 keys at all*: rejected. The single-file pattern matches M3/M4/M5 and reduces the "which-file-do-I-read" burden on downstream tooling.

---

## R-7 — Narrative-refresh gating: how is the "last commit before PR" invariant enforced?

**Decision**: The narrative-refresh step (FR-017 / FR-018 / FR-019) is **procedural**, executed by the maintainer per `quickstart.md`'s pre-PR checklist. The harness does not enforce ordering. The maintainer's checklist is:

1. Run the full M5.1 sweep. Verify `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}` are produced. Commit as `[Spec Kit] Publish M5.1 report`.
2. Inspect the published numbers. Identify any cells with `comparison_unavailable`, mixed-verdict outcomes, or contradictions vs the anticipated headline.
3. Edit `README.md`, `docs/benchmarks/summary.md`, and `docs/PLAN.md` to (a) flip M5.1 to "(delivered)" with the run date and report path, (b) embed the actual headline finding in the executive prose (whatever shape it takes — unconditional on outcome per Clarifications 2026-05-11), (c) leave M1 bytes-axis claims unchanged (FR-021).
4. Commit as `[Spec Kit] Refresh README + executive narrative for M5.1 delivery`. Verify with `git log -1 --oneline` that this is `HEAD`.
5. Run `gh pr create` with a PR description that cites step-4's commit SHA explicitly.
6. If any auto-commit hook lands additional changes after step 4 (e.g., an `after_implement` hook), squash or reorder so the narrative-refresh commit ends up last.

**Rationale**: The harness has no insight into whether a commit's content is "the narrative refresh" vs any other change, so machine enforcement is impossible without a fragile content-sniffing heuristic. Pre-PR procedural checklists are an established Spec Kit pattern (M5's `quickstart.md` uses the same approach for its publish-then-PR step). The procedural enforcement is reliable because the maintainer reads `quickstart.md` before opening the PR; the auto-commit hook ordering risk is handled by an explicit checklist item.

**Alternatives considered**:
- *Add a pre-commit hook that refuses commits to `main`-adjacent branches if `README.md` is older than `docs/benchmarks/m5_1-rest-vs-grpc.md`*: rejected. Brittle (touches every branch, not just M5.1), assumes too much about file mtimes vs git history.
- *Add a GitHub Actions workflow that fails PR creation if the last commit isn't a "refresh README" commit*: rejected. Adds CI complexity for a single milestone's procedural rule; the rule isn't general enough to warrant infrastructure.
- *Make the narrative refresh part of the same commit as the report publish*: rejected by the user — FR-019 explicitly requires the refresh to be the **last** commit, separate from the report, so a reviewer's first reviewer-facing diff is the current narrative state.

---

## R-8 — REST shim shared-state and concurrency safety

**Decision**: The FastAPI shim holds a module-level singleton reference to the in-container `MockEngine` instance. Each request handler is `async def` and calls `await mock_engine.generate(...)` / `await mock_engine.embed(...)` directly. MockEngine's `generate` and `embed` are already async and stateless across requests (M4 verified this for the gRPC servicers), so no per-request lock or pool is needed. Uvicorn is configured with `workers=1` to keep the singleton invariant intact; concurrent requests are dispatched on the single worker's event loop.

**Rationale**: Multi-worker uvicorn would clone the MockEngine across worker processes, violating "same engine instance for both protocols." Single-worker uvicorn + asyncio matches the gRPC server's concurrency model (one async server, one MockEngine instance) and is sufficient for the c ≤ 8 concurrency band M5.1 measures.

**Alternatives considered**:
- *Multi-worker uvicorn with shared MockEngine via shared memory*: rejected. Adds operational complexity and the cross-worker shared MockEngine pattern doesn't fit MockEngine's current dataclass-singleton shape.
- *Per-request MockEngine instances*: rejected. Defeats the spec's "identical in-container engine path" requirement and adds startup cost per request.

---

## Open items deferred to implementation

These are not blockers — each has a clear default that the implementation can apply, but they are worth noting so `/speckit-tasks` can promote them to discrete task subjects if the implementer wants explicit checkboxes.

- **REST shim's `/healthz` shape**: trivial JSON `{"ok": true}` with HTTP 200. No bearer-auth gating.
- **MockEngine's `embed` call signature when invoked from REST**: REST decodes base64 into bytes, then passes those bytes to MockEngine's existing embed path (which is shape-driven by `hidden_size`, not byte-content). The shim does not need to decode the tensor as a numpy array.
- **JSON request validation**: Pydantic models for the two endpoints' request/response shapes live in the shim module (not in the project's `proto/`-derived dataclasses); these are throwaway and exist only for FastAPI's automatic validation.
- **Bearer-token verification timing**: short-circuit at FastAPI middleware before the request body is parsed (matches the gRPC `BearerTokenInterceptor` discipline of failing fast).

---

## Closing — all NEEDS-CLARIFICATION resolved

All 8 R-items and the open-items list cover the methodology decisions implicit in the plan. The spec's 5 Clarifications (2026-05-11) provided the user-pinned choices for sub-cohort matrix shape, REST streaming model, REST connection pool, default-gRPC cadence, and narrative-refresh unconditionality. This research file translates those choices into implementation-actionable decisions. No NEEDS CLARIFICATION items remain.

**Constitution Check re-evaluation (post-research)**: PASS. No research finding introduces complexity that the initial constitution check did not anticipate. The dual-protocol Modal app (R-2) and the dual-sub-cohort gRPC matrix (R-4) are mechanical expansions of M5 patterns; the FastAPI shim (R-1, R-8) is the only genuinely new component and it is a thin wrapper over the existing MockEngine. No `proto/` edits (Constitution I), no vLLM fork (Constitution II), no phase boundary violations (Constitution III), no CI-bypass (Constitution IV), no honesty-mechanism weakening (Constitution V).
