# M5 Research — Cross-Host Time-Axis Validation

**Phase**: 0 (research)
**Feature**: [spec.md](./spec.md) · [plan.md](./plan.md)
**Date**: 2026-05-10

## Purpose

Resolve every NEEDS-CLARIFICATION-shaped methodology question in the spec and plan before Phase 1 design lands. Each entry below names the question, the decision M5 commits to, the rationale, and the alternatives that were considered and rejected. Decisions cite spec FR numbers and Clarifications (2026-05-10) Q1/Q2/Q3 by anchor.

---

## R-1 — Modal exposure pattern for the cross-host gRPC server

**Question**: Spec FR-002 commits to "TLS credentials plus a bearer token attached as gRPC call-credentials / metadata" (Clarifications 2026-05-10 Q3). The project's existing Modal-frontend pattern (`scripts/python/modal_frontend_serve.py`) uses `modal.forward(port, unencrypted=True)` — plain TCP tunneling, no TLS, no auth beyond tunnel-URL obscurity. What concrete Modal mechanism satisfies the FR-002 TLS + bearer-token commitment?

**Decision**: Open the Modal tunnel with `modal.forward(_GRPC_PORT, unencrypted=False)` so Modal terminates TLS at the tunnel edge with a Modal-issued cert. Add an application-level bearer-token check by registering a gRPC `ServerInterceptor` on the `M3CompletionsServicer` / `M3ChatServicer` that inspects the `authorization` metadata header on every incoming RPC and rejects requests whose token does not match the per-deploy token published via `modal.Dict`. The harness-side client uses `grpc.aio.secure_channel(target, grpc.ssl_channel_credentials(), options=...)` with the bearer token attached as call credentials (`grpc.composite_channel_credentials` or per-RPC metadata).

**Rationale**:
- `modal.forward(unencrypted=False)` is documented as the supported path for HTTPS / TLS-terminated tunnels on Modal. The certificate is Modal-managed (no per-deploy cert work in this repo).
- A gRPC `ServerInterceptor` is the canonical mechanism for attaching auth to gRPC servicers without modifying the servicer source. It runs on every unary and streaming RPC and can short-circuit unauthorized calls with `UNAUTHENTICATED` before the servicer touches the request — important for keeping unauthorized traffic from contaminating the timing window.
- The bearer token itself is generated per-deploy (a `secrets.token_urlsafe(32)` value) and published alongside the tunnel URL in `modal.Dict`; the harness picks both up at handshake time. The token is never written to disk by the harness or the report (per FR-002).
- TLS overhead (handshake + per-frame record overhead) is constant across every cohort in the sweep, so it does not bias any axis verdict. The sweep continues to vary only the four channel axes (`max_message_size`, `keepalive`, `http2_framing`, `compression`).

**Alternatives considered and rejected**:
- `modal.forward(unencrypted=True)` + no auth: matches the existing M1 frontend pattern but violates FR-002's TLS commitment from Q3. Rejected.
- Modal `@web_endpoint` / `@fastapi_endpoint`: HTTP-only, not gRPC-friendly (would force gRPC-Web translation, adding a confounding layer that defeats M5's purpose). Rejected.
- mTLS with a client cert: stronger auth posture but requires per-run cert provisioning that the existing project tooling doesn't have. Rejected as over-engineering for a per-deploy single-operator benchmark.
- Modal workspace-private endpoint via VPC peering: strictest ops posture but introduces a VPC-routed RTT path that confounds the wire-overhead measurement (the entire point of M5). Rejected per Q3 Option C explanation.

---

## R-2 — Single-CLI orchestration mechanism (deploy → measure → teardown)

**Question**: Spec SC-005 requires the M5 sweep be reproducible by a single end-to-end harness CLI invocation, with no manual coordination beyond invoking the harness. Two Modal Python-API patterns fit: (a) the harness shells out to `modal run scripts/python/modal_bench_grpc_server.py` as a subprocess, captures stdout for the tunnel URL handshake, and runs `modal app stop` at teardown; (b) the harness imports the Modal app object directly and uses `modal.Function.lookup()` / `app.run()` to manage the lifecycle programmatically. Which?

**Decision**: Pattern (b) — programmatic Modal lifecycle from inside `m5_sweep.py`. The harness imports the Modal app object from `scripts/python/modal_bench_grpc_server.py` and uses `app.run()` (or the async equivalent `app.run.aio()`) as an async context manager that handles deploy on entry and teardown on exit. The tunnel URL + bearer token are published from inside the Modal function via `modal.Dict.from_name(_DICT_NAME).put(...)`, and the harness reads them back via `modal.Dict.from_name(_DICT_NAME).get(...)` after `app.run()` has entered. This matches the pattern in the existing `scripts/python/modal_frontend_serve.py` (which uses `modal.Dict` to publish the gRPC frontend's tunnel address).

**Rationale**:
- Programmatic lifecycle gives the harness one orchestration loop with structured error handling: deploy failures, tunnel-publication timeouts, and teardown errors all surface through the same Python exception path. Subprocess-based orchestration would require parsing `modal run` stdout, which is brittle.
- `modal.Dict` is already the project's chosen Modal-side publish mechanism for tunnel addresses. Reusing it avoids inventing a second handshake mechanism.
- Async context manager wrapping the Modal app means teardown happens deterministically (including on `KeyboardInterrupt` mid-sweep), satisfying the Edge Case "remote host is unavailable mid-run" requirement that partial cohorts be discarded loudly.
- The harness can still be invoked imperatively (`uv run python -m vllm_grpc_bench --m5 ...`) — no separate `modal run` invocation needed.

**Alternatives considered and rejected**:
- Subprocess-based orchestration: brittle stdout parsing and harder failure semantics. Rejected.
- Pre-deployed long-running Modal app + harness pointed at a static URL: simpler for repeated runs, but adds operational state outside the single-CLI-invocation requirement of SC-005 and makes "the run completes when teardown completes" harder to guarantee. Rejected.
- Reuse the existing `modal_frontend_serve.py` and the M1 real-model Modal app: hard violation of Clarifications Q2 (CPU-only), since that app is A10G + a real model. Rejected.

---

## R-3 — RTT probe mechanism

**Question**: FR-004 requires per-cohort RTT measurement (median, p95) by an "active probe (e.g., a unary RPC echo against the same channel)" immediately before the cohort's measurement window opens. Three concrete mechanisms fit: (a) a dedicated unary RPC `HealthCheck.Ping` registered on the servicer that returns a minimal proto immediately; (b) reuse the existing `health.proto` health-check RPC; (c) piggy-back RTT measurement on the first cohort iteration and use that iteration's timing as the cohort baseline. Which?

**Decision**: Mechanism (b) — reuse the existing `health.proto` health-check RPC. The harness runs `n = 32` consecutive unary `Health.Check` calls against the same channel immediately before each cohort's measurement window opens, records every call's wall-clock latency, and produces an `RTTRecord` (median, p95, n, raw samples) that is attached to the cohort entry in the M5 JSON report.

**Rationale**:
- `health.proto` is already defined in `proto/vllm_grpc/v1/health.proto` and already wired into the gRPC server registration path (it's a standard gRPC convention). Reusing it avoids a new proto edit (Constitution I — no `.proto` edit needed for M5).
- 32 probe iterations gives a stable median and p95 in under 5 seconds (at 30–100 ms RTT, 32 × ~60 ms ≈ 2 s) — small overhead per cohort.
- Running the probe before the cohort's measurement window opens means the cohort itself sees a warmed TCP path with full HTTP/2 streams established. This eliminates a confounder where the first cohort iteration pays a stream-creation cost not seen by subsequent iterations.
- Piggy-backing on cohort iterations (option c) would mix RTT measurement with cohort measurement, complicating the timing windows and making the verdict-gating logic (refuse verdict when median RTT < 1 ms) order-dependent.

**Alternatives considered and rejected**:
- Dedicated new `Ping` RPC: requires a `.proto` edit; reuse-existing-health is strictly cheaper. Rejected.
- TCP-level probe (e.g., `socket` round-trip outside the gRPC channel): measures TCP RTT but not HTTP/2-frame-aware RTT. Since M5's axes (`keepalive`, `http2_framing`) operate above TCP, a TCP-only probe would miss HTTP/2-handshake effects. Rejected.
- Piggy-back on cohort iterations: timing-window confounder. Rejected.

---

## R-4 — `server_bound` cohort classification

**Question**: FR-005 requires the harness detect and exclude cohorts whose dominant cost is server-side rather than transport+serialization, parallel to M4's `client_bound`. What concrete client-observable signal classifies a cohort as `server_bound`?

**Decision**: Compute, per cohort, `server_overhead_estimate_ms = cohort_median_wallclock_ms − cohort_median_rtt_ms − client_overhead_floor_ms`, where `client_overhead_floor_ms` is M4's empirically-observed minimum client-side per-RPC overhead under loopback (a per-path constant pulled from `m4-time-axis-tuning.json` — typically 0.5–2 ms for chat_stream and 0.1–0.5 ms for embed). Flag the cohort `server_bound = True` when `server_overhead_estimate_ms > max(2 × cohort_median_rtt_ms, 50ms)` AND the within-cohort CV on `server_overhead_estimate_ms` is materially worse than M4's loopback per-cohort CV for the same path. The harness emits both the boolean flag and the computed `server_overhead_estimate_ms` value alongside the cohort in the M5 JSON report so the reader can adjudicate.

**Rationale**:
- The classification is fully client-observable: it uses the cohort's measured wall-clock, the RTT probe's measured RTT, and a per-path constant from the M4 report. No server-side trailing metadata is required (which would require a servicer edit and would itself be a confounder).
- Setting the threshold at `2 × RTT` ensures borderline cohorts where server overhead is comparable to transport are still emitted (transport is the thing M5 is measuring); only cohorts where server overhead dominates by ≥2× are excluded.
- The 50 ms floor prevents false positives on very-low-RTT cohorts (where `2 × RTT` would be < 10 ms and small server jitter would trip the flag).
- The CV-comparison gate ensures the flag is set only when server overhead is *unstable* (i.e., the server is the bottleneck), not when server overhead is *high but stable* (which would just shift the absolute numbers without invalidating cross-cell comparisons).

**Alternatives considered and rejected**:
- Server-side trailing metadata reporting per-RPC server duration: more accurate, but requires editing M3's servicers to emit trailers and creates an additional time-axis confounder (the trailer emission itself costs wall-clock). Rejected for M5; future enhancement.
- Fixed wall-clock threshold (e.g., flag any cohort with median > 200 ms): defeats the point of M5, since slow cohorts on real wire are the expected outcome. Rejected.
- Only flag on CV (ignore absolute overhead): misses the "server is permanently slow but stable" case where verdicts would still be confounded. Rejected.

---

## R-5 — Warm-up cohort handling

**Question**: Edge Cases name "cold-start or first-cohort skew" — the first cohort against a freshly-started Modal container can run materially slower than steady-state cohorts because of container warm-up, JIT effects, or HTTP/2 connection-pool establishment. How much warm-up is required, and when?

**Decision**: Run a single warm-up cohort of `n = 32` iterations against each path (chat_stream, embed) immediately after the Modal app's tunnel URL is published and before the shared-baseline cohort begins. The warm-up cohort's results are recorded in the JSON report (so a reader can see the cold-vs-warm delta) but tagged `discarded: true` and excluded from every aggregate computation. Each cohort within the sweep does *not* get its own warm-up — the per-cohort RTT probe (R-3) serves that purpose, since 32 probe RPCs are sufficient to keep the channel's HTTP/2 streams active and the Modal container's process resident.

**Rationale**:
- Cold-start cost is dominated by Modal container scheduling + Python import + gRPC server bring-up; this is a one-time cost per deployment, not a per-cohort cost.
- 32 warm-up iterations is sufficient: at 30–100 ms RTT × 32 iters ≈ 1–3 s of channel activity, which covers TCP slow-start and HTTP/2 initial-window-opening behavior.
- Recording the warm-up cohort (with `discarded: true`) rather than silently dropping it gives the reader visibility into the actual cold-vs-warm delta. This is a Constitution V concern.
- Per-cohort warm-up would consume sweep budget without empirical justification — the RTT probe already touches the channel before each cohort.

**Alternatives considered and rejected**:
- No warm-up, accept the cold-start in shared-baseline: spec Edge Cases explicitly disallows this. Rejected.
- Per-cohort warm-up of n=10: redundant with the RTT probe and adds ~10 minutes to total sweep time over the ~48 cells. Rejected.
- Warm-up determined adaptively (run until per-iteration time stabilizes): adds an empirical convergence loop that complicates the harness; the 32-iter fixed warm-up is empirically sufficient based on M3/M4 cohort-stability data. Rejected.

---

## R-6 — Modal region pick

**Question**: Clarifications Q1 commits to cross-region deployment with target measured median RTT 30–100 ms. Which concrete Modal region should the M5 app deploy to?

**Decision**: The harness exposes a `--m5-modal-region` CLI flag whose default is `auto-far` (a sentinel meaning "the harness picks the farthest documented region for the operator's locale by reading a small region-distance table"). The harness's region-distance table starts with: `us-east-1` for operators in EU / AP locales, `eu-west-1` for operators in US / AP locales, `ap-southeast-1` for operators in US / EU locales. The operator MAY override with an explicit region string (e.g., `--m5-modal-region us-east-1`). The selected region is recorded in the M5 JSON report alongside the measured RTT distribution. The harness does NOT auto-detect the operator's locale; default `auto-far` resolves to `us-east-1` and the operator overrides if their client is also in `us-east-1`.

**Rationale**:
- Hard-coding a single region in the spec/plan is brittle (it doesn't survive a Modal region rename or a new operator joining the project from a different locale).
- A CLI flag with a sentinel default keeps the single-CLI-invocation contract (SC-005) while letting different operators land in the 30–100 ms band without code edits.
- The default-`us-east-1` choice matches the project's existing `modal_frontend_serve.py` region (Modal's default) and produces measurable RTT from a US-east-coast operator's local Mac in the 5–20 ms range (which would attach `low_rtt_caveat` and warn) but produces 80–120 ms RTT from EU or West-coast operators. Operators in `us-east-1` are explicitly nudged to override.
- Recording the region in the JSON report means an M5-vs-M5 comparison across operators is possible (and `low_rtt_caveat` annotates any cohort whose RTT fell below the 20 ms exercise threshold per FR-004).

**Alternatives considered and rejected**:
- Hard-code `eu-west-1`: works for US operators but breaks for EU operators. Rejected.
- Auto-detect locale via IP geolocation: privacy concern (the harness would call out to a third-party geolocation API) and adds a dependency. Rejected.
- Run the sweep across multiple regions: triples runtime and triples cost without changing M5's headline-verdict structure. Future enhancement; not M5 scope.

---

## R-7 — Runtime budget and per-RPC cost

**Question**: Spec Assumption ("Cost budget is bounded") targets ≤ 8 hours for the full sweep on a Modal CPU-only instance class. Is this realistic, and what is the expected per-RPC cost?

**Decision**: Adopt the ≤ 8 hour target as the operator's runtime expectation, with the M5 report's executive summary including the actual run wall-clock for traceability. Concretely the expected breakdown (per spec FR scale/scope and Modal CPU-instance pricing as of 2026-05): warm-up (2 paths × 32 iters × ~80 ms RTT) ≈ 5 s; shared-baseline (2 paths × 100 iters) ≈ 20 s; channel sweep (~48 cells × 100 iters with borderline expand averaging 130 iters) ≈ 10 min wall-clock at 80 ms median RTT for chat_stream + 10 min for embed; frozen-channel baselines (2 paths × 100 iters) ≈ 20 s; schema sweep (3 candidates × 100 iters at 4096; cascade to 2048 + 8192 for borderline) ≈ 5 min; Modal-side overhead (deploy + teardown) ≈ 2 min. Total ≈ 30 min wall-clock for cohort measurements + 2 min Modal overhead. **The ≤ 8 hour target is generous by ~10×**; it exists to absorb borderline-expansion explosion (cohort `n` doubling for every cell) and to leave headroom for re-runs when `noisy_baseline` is flagged.

**Rationale**:
- M4's local-loopback sweep took ~30 min of CPU time for the same matrix (per the M4 plan's "≤ 4 hours" budget that was hit at ~30 min in practice). M5 multiplies each per-iter cost by `(real RTT) / (loopback RTT)` ≈ 80 ms / 0.1 ms = 800×, but the per-iter wall-clock for streaming chat_stream cohorts is dominated by the stream duration (many tokens), not RTT. The net multiplier is more like 5–10×, putting realistic total at 1–3 hours.
- Modal CPU-instance pricing (as of 2026-05) is on the order of $0.10–$0.20/hour. A 3-hour run costs < $1; even a degenerate 8-hour run costs < $2. The "well under one Modal CPU-instance-hour-class budget" target in plan.md is comfortable.
- Documenting the breakdown lets the operator estimate the run length before they kick it off and lets a future reviewer detect when a re-run took 10× longer than baseline (signal that something broke in the sweep, not a stable methodology drift).

**Alternatives considered and rejected**:
- Tighter budget (≤ 2 hours): risks under-provisioning for borderline-expansion explosion. Rejected.
- Looser budget (≤ 24 hours): tolerates a methodology issue that should be diagnosed instead of waited out. Rejected.
- Skip the budget documentation entirely: future operators have no expectation-anchor. Rejected.

---

## R-8 — JSON schema additive delta vs `m4-time-axis-tuning.json`

**Question**: FR-014 commits the M5 JSON to be a strict superset of M4's schema. Which fields are added, and where do they attach?

**Decision**: The M5 JSON has the following additive fields relative to `m4-time-axis-tuning.json`:

**At the root level:**
- `m5_methodology_version`: integer; `1` for this release. (M4's `m4_methodology_version: 1` field remains unchanged.)
- `m5_modal_app_name`: string; the Modal app name used for the deployment.
- `m5_modal_region`: string; the Modal region the app was deployed to.
- `m5_runtime_wallclock_seconds`: float; total run wall-clock.
- `m5_rtt_summary_ms`: object with fields `{min, median, p95, max}` aggregated across every non-discarded cohort.
- `supersedes_m4`: array of `SupersedesM4Entry` objects (one per M4 cell M5 supersedes, per FR-015).

**At each cohort level (under `cohorts[*]`):**
- `rtt_record`: object with fields `{n: int, median_ms: float, p95_ms: float, samples_ms: array<float>}`. Required for every M5 cohort.
- `server_overhead_estimate_ms`: float; the computed `server_bound` classifier value (per R-4).
- `low_rtt_caveat`: boolean; `True` when `rtt_record.median_ms < 20` (the FR-004 exercise threshold).
- `discarded`: boolean; `True` for warm-up cohorts (per R-5).

**At each verdict level (under `verdicts[*]`):**
- `supersedes_m4_cell`: object `{m4_axis: string, m4_hidden_size: int, m4_path: string, m4_verdict: string}` cross-referencing the M4 cell this M5 verdict supersedes (null when no M4 cell exists, e.g., for warm-up cohorts).

**Existing M4 fields remain unchanged in semantics and name.** The `loopback_caveat` field continues to exist on every cohort/verdict for M4-reader compat, with value `False` on every M5 cohort (the loopback caveat is no longer physically applicable per FR-007).

**Rationale**:
- The additive list is the minimum needed to satisfy FR-004 (RTT record), FR-005 (server_bound), FR-015 (supersedes_m4), and the cross-host topology narrative (region, methodology version, wall-clock).
- Embedding the raw `samples_ms` array (not just summary stats) supports re-analysis by future readers without re-running the sweep — Constitution V.
- Placing `supersedes_m4_cell` at the *verdict* level (not the cohort level) means schema candidates and channel-sweep cells use the same supersession mechanism without per-section duplication.
- Keeping `loopback_caveat` in the schema (set to `False` on M5 cells) preserves M4-reader bit-compatibility — a tool that filters M4 cells by `loopback_caveat == True` will see zero M5 cells and behave identically.

**Alternatives considered and rejected**:
- Reuse M4's `loopback_caveat` field repurposed for the M5 `low_rtt_caveat` semantics: violates the "strict-superset, additive only, no semantic redefinition" rule of FR-014. Rejected.
- Omit `samples_ms` (only summary stats): loses re-analysis capability. Rejected.
- Add a top-level `supersedes_m4_by_verdict` aggregate alongside per-verdict `supersedes_m4_cell`: redundant with the array at the root. Rejected; readers can compute aggregates from the per-verdict entries.

---

## R-9 — Endpoint-provider abstraction for the M4 harness

**Question**: The plan requires a "small, surgical refactor" of `m4_sweep.py` to replace the direct `serve_in_process(...)` call with an `endpoint_provider` callable so M4 reproductions remain bit-identical while M5 swaps in a remote-channel provider. What is the concrete interface?

**Decision**: Define a `EndpointProvider` Protocol in `tools/benchmark/src/vllm_grpc_bench/m3_types.py`:

```python
class EndpointProvider(Protocol):
    """An async context manager yielding (target, channel_credentials, call_metadata)."""

    def __call__(
        self,
        engine: MockEngine,
        channel_config: ChannelConfig,
    ) -> AbstractAsyncContextManager[
        tuple[str, grpc.ChannelCredentials | None, tuple[tuple[str, str], ...] | None]
    ]: ...
```

The existing `serve_in_process(engine, channel_config)` already returns an async context manager yielding `addr: str` (the in-process socket path). Wrap it in an adapter that yields `(addr, None, None)` — i.e., insecure channel + no call metadata — preserving M4's existing semantics.

The M5 provider (`modal_endpoint.provide_endpoint`) is a separate function that yields `(modal_tunnel_target, grpc.ssl_channel_credentials(), (("authorization", f"Bearer {token}"),))`. The harness's gRPC client picks based on the returned credentials: `grpc.aio.secure_channel(target, credentials, options=...)` when credentials are non-None, else `grpc.aio.insecure_channel(target, options=...)`.

**Rationale**:
- Single argument addition to `m4_sweep.py` (`endpoint_provider: EndpointProvider = serve_in_process_adapter`) preserves bit-identical M4 behavior when the default is used.
- The tuple shape `(target, credentials, metadata)` covers every gRPC channel construction case (insecure, secure, secure-with-auth) without over-engineering.
- Returning a per-call metadata tuple (not a per-channel-call interceptor) means the harness's existing gRPC call sites can attach metadata directly via the `metadata=` kwarg on each RPC call — no interceptor wiring needed in the harness.

**Alternatives considered and rejected**:
- Pass a fully-constructed `grpc.aio.Channel` object instead of `(target, credentials, metadata)`: ties the provider to a specific channel-construction order and makes channel-options injection harder. Rejected.
- Inline the M5 provider in `m4_sweep.py` behind a feature flag: clutters M4 logic with M5-specific concerns. Rejected; the `endpoint_provider` callable abstraction is cleaner.

---

## Open items deferred to implementation

These were intentionally left unresolved at the plan stage because they are operational and best decided when the implementation lands:

- **OP-1**: Concrete Modal app name (`vllm-grpc-bench-mock` vs versioned `vllm-grpc-bench-mock-{git_sha}`). Decision belongs in `scripts/python/modal_bench_grpc_server.py`.
- **OP-2**: `modal.Dict` name for the tunnel-URL + bearer-token handshake. Will reuse the existing convention from `modal_frontend_serve.py` adapted with `_bench_` prefix.
- **OP-3**: Concrete bearer-token-rejection metric (count of rejected RPCs surfaced in the report's executive summary, or silent rejection). The operator's expectation is that bearer-token rejection during a live sweep is a hard error (no other client should be hitting this deploy), so a single non-zero rejection count fails the run.

---

## Closing — all NEEDS-CLARIFICATION resolved

Every research item above resolves to a single concrete decision with rationale. No `NEEDS CLARIFICATION` markers remain in the plan or research. Phase 1 (data-model.md, contracts/, quickstart.md) can proceed.
