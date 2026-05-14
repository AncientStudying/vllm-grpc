# M5.2 Research — REST Transport Path × gRPC Tuning Surface

## Purpose

Resolve the methodology questions the M5.2 plan defers: how the HTTPS-edge REST cohort is wired in, how the per-cohort RTT probe travels each cohort's network path, how the 3-tier symmetry block is built and asserted, how the per-request JSONL events sidecar is emitted + checksummed + read back by the regenerator, how the round-trippable regenerator extends `regen_bench_reports.py`, how the Supersedes-M5.1 table categorises rows, how the three discrete narrative commits are composed and ordered, how `ANALYSIS.md` is structured for cumulative growth, and how the README simplification + tooling-validation pass is conducted. Each section produces a single decision the plan and downstream code/contract docs rely on.

This file *resolves* NEEDS CLARIFICATION items implicit in the plan. The spec's 10 explicit Clarifications (Session 2026-05-12) already pinned the major methodology choices (ANALYSIS.md filename + scope; PLAN.md findings-only extraction; SSE for the chat path on both REST transports; smoke harness reuse with M5.2 assertions; 3-tier symmetry assertion with payload-parity audit; per-request JSONL telemetry; regenerator-built report with field provenance; discrete narrative commits; three-tier symmetry scoping with c=1 degeneracy; gzipped sidecar storage). This research consolidates those choices into implementation-actionable decisions and pins the remaining open items.

---

## R-1 — HTTPS-edge REST cohort wiring: where does `rest_https_edge` get its URL, and how does `rest_plain_tcp` keep its M5.1 URL?

> **Revised 2026-05-12 post-implementation.** The original R-1 made two wrong assumptions that the smoke run caught on the first deploy:
> 1. *That M5.1 already forwards REST as HTTPS-edge.* It doesn't — M5.1 deliberately voided FR-019 (see methodology section of `docs/benchmarks/m5_1-rest-vs-grpc.md`) and forwards REST as plain-TCP. The `rest` key in M5.1's handshake dict is an `http://host:port` URL, not `https://`. So M5.2 has to *add* the HTTPS-edge tunnel, not reuse an existing one.
> 2. *That `modal.forward(8000)` and `modal.forward(8000, unencrypted=True)` can coexist on the same in-container port.* They can't. Modal scopes tunnels per port number, not per (port × protocol). Calling `modal.forward` twice on the same port — even with different `unencrypted` flags — raises `modal.exception.InvalidError: Port 8000 is already forwarded`. The error surfaces at `__aenter__` time, so the smoke run aborts before any cohort dispatches. This is the lesson the implementation phase paid for.
>
> The revised R-1 below reflects what actually works.

**Decision**: The M5.2 deploy binds uvicorn **twice** inside the container — once on port 8000 (M5.1's existing REST socket, forwarded as plain-TCP via `modal.forward(8000, unencrypted=True)` for M5.1 back-compat and as the `rest_plain_tcp` cohort's transport) and a second time on port 8001 (forwarded as HTTPS-edge via `modal.forward(8001)` for the `rest_https_edge` cohort's transport). Both uvicorn `Server` instances wrap the **same** FastAPI `shim` object and therefore share the in-container `MockEngine` singleton — FR-002's "identical in-container engine code path" holds because only the listening socket differs. The handshake dict publishes four URLs: `grpc` (M5.1, gRPC plain-TCP), `rest` (M5.1, REST plain-TCP, `http://`), `rest_plain_tcp_url` (M5.2 alias for `rest`, scheme `tcp+plaintext://`), and `rest_https_edge_url` (M5.2 new, `https://`). `rest_plain_tcp` points its `httpx.AsyncClient` at `http://<plain_tcp_host>:<plain_tcp_port>/` while `rest_https_edge` points its client at `https://<https_edge_host>/` (Modal-managed TLS).

**Rationale**: Modal's tunnel API is the operative constraint, not the in-container socket layout. Once we know `modal.forward(port)` is the *single allocator* of an in-container port to a tunnel, the design crystallises: one in-container port per tunnel, one uvicorn `Server` instance per in-container port, all wrapping the same shared FastAPI app object. Sharing the app (not just the engine) keeps FR-002 satisfied for free — `build_rest_shim(engine, expected_token=token)` is called once and the resulting ASGI callable is handed to both `uvicorn.Config(...)` invocations. The two `asyncio.create_task(server.serve())` instances run concurrently and listen on independent sockets; they share the event loop, the `MockEngine`, and the bearer-token verification middleware. Cold-start cost adds ~1–2 s for the second uvicorn instance — negligible relative to the 90 s smoke and 25–30 min full sweep.

**Implementation note**: In `scripts/python/modal_bench_rest_grpc_server.py`:

```python
_REST_PORT = 8000               # M5.1's existing REST port (plain-TCP)
_REST_HTTPS_EDGE_PORT = 8001    # M5.2's HTTPS-edge port (NEW)

shim = build_rest_shim(engine, expected_token=token)
rest_server      = uvicorn.Server(uvicorn.Config(shim, port=_REST_PORT,            ...))
rest_edge_server = uvicorn.Server(uvicorn.Config(shim, port=_REST_HTTPS_EDGE_PORT, ...))
rest_task      = asyncio.create_task(rest_server.serve())
rest_edge_task = asyncio.create_task(rest_edge_server.serve())

async with modal.forward.aio(_GRPC_PORT,            unencrypted=True) as grpc_tunnel:
    async with modal.forward.aio(_REST_PORT,        unencrypted=True) as rest_tunnel:
        async with modal.forward.aio(_REST_HTTPS_EDGE_PORT) as edge_tunnel:
            # plain-TCP tunnels expose .tcp_socket (host, port); HTTPS-edge
            # tunnels expose .url ("https://<id>.modal.run"). Different
            # attribute shapes — the dispatcher reads them differently.
            await d.put.aio("rest_https_edge_url", edge_tunnel.url)
            await d.put.aio("rest_plain_tcp_url", f"tcp+plaintext://{rest_host}:{rest_port}")
            ...
```

Teardown must clear both `rest_task` and `rest_edge_task` and pop the new `rest_https_edge_url` key from the dict on context exit. The harness-side `modal_endpoint._wait_for_rest_grpc_handshake` returns a **4-tuple** when `with_rest_plain_tcp=True`: `(grpc_url, rest_url, rest_plain_tcp_url, rest_https_edge_url)`. M5.1 callers leave the flag at its default `False` and receive `None` for the trailing two URLs, preserving back-compat.

**Two more gotchas the implementation surfaced**:

- *`modal.forward(port)` (no `unencrypted=`) vs `modal.forward(port, unencrypted=True)` expose different attribute shapes.* The HTTPS-edge tunnel surfaces its URL on `.url` (a string like `https://<id>.modal.run`); the plain-TCP tunnel surfaces its endpoint on `.tcp_socket` (a `(host, port)` tuple). Forgetting which attribute to read produces silent `AttributeError`s at handshake time. The deploy script reads `.url` for the HTTPS edge and constructs `tcp+plaintext://{host}:{port}` for plain-TCP.
- *The plain-TCP URL still needs an `http://` scheme for `httpx`.* The handshake publishes `tcp+plaintext://host:port` (matches the gRPC convention, makes the scheme operatively visible in the dict); the harness strips that prefix and re-prepends `http://` before handing the URL to `httpx.AsyncClient`. The `__main__._run_m5_2` dispatcher does this transformation explicitly; treat the `tcp+plaintext://` scheme as a *labelling* convention for the dict, not a wire-layer scheme.

**Alternatives considered**:
- *Spin up a second Modal app for `rest_https_edge`*: rejected. Doubles deploy/teardown cost (~6–10 s extra per run), breaks the "same MockEngine instance across protocols" guarantee, and violates the spec's "single Modal deploy per run" assumption.
- *Route `rest_https_edge` through the same `modal.forward(8000)` tunnel by binding uvicorn only on 8000 and forwarding once as HTTPS-edge*: rejected. This is what M5.1 would have looked like under FR-019, but it forces `rest_plain_tcp` to use a *different* in-container socket anyway (otherwise both REST cohorts share the HTTPS-edge tunnel — the experiment's variable collapses to a single value).
- *Use a per-protocol reverse proxy (Caddy / Envoy) in the container that listens on one port and demultiplexes by SNI / port-suffix*: rejected. Inflates implementation complexity for no measurable benefit. The two-uvicorn approach is ~10 lines of Python and stays within the spec's "no new Modal-image deps relative to M5.1" rule.
- *Skip `rest_plain_tcp` entirely and rely on M5.1's published numbers*: rejected. FR-006 requires both REST transports to be re-measured at n=250 so the transport-only verdict family has the same statistical resolution as the protocol-comparison family.

**Lesson for future milestones**: when planning to add a new Modal tunnel that exposes an existing in-container service, the right question is *not* "can we forward port N twice with different flags?" but "**which in-container port does the new tunnel terminate on?**". Modal's `modal.forward(port, unencrypted=True|False)` is a 1-to-1 mapping from in-container ports to external tunnels. Every distinct tunnel needs a distinct in-container listener. The cost is one extra `uvicorn.Server` or equivalent, which is a much cheaper concession than the alternatives.

---

## R-2 — RTT probe over each cohort's network path: how is the probe bound and where does it land?

**Decision**: The REST RTT probe lives at `GET /healthz` on the FastAPI shim (unauthenticated; M5.1's existing endpoint, reused unchanged). The probe is bound to the **same `httpx.AsyncClient` instance** the cohort uses for its measurement window — `rest_https_edge` probes `https://<edge>/healthz` over its HTTPS-edge keep-alive connection; `rest_plain_tcp` probes `http://<tcp_host>:<tcp_port>/healthz` over its plain-TCP keep-alive connection. The gRPC RTT probe is M5.1's `rtt_probe.probe_grpc_rtt` unchanged — it runs over the plain-TCP gRPC tunnel and is used for the three gRPC cohorts. The per-cohort RTT median + p95 are recorded in the M5.2 JSON aggregate, surfaced in the report's executive section per FR-014, and snapshotted onto every per-request event record (`rtt_at_issue` field) per FR-012a.

**Rationale**: Probing over each cohort's own connection ensures the recorded RTT reflects the cohort's actual measurable network path — a fresh-connection probe (TCP SYN + TLS handshake on every probe) would systematically overstate `rest_https_edge`'s RTT relative to its keep-alive measurement path. Using the same `/healthz` endpoint on both REST transports also normalizes the server-side cost of the probe (FastAPI shim's `/healthz` handler is identical regardless of which Modal tunnel the request arrived through).

**Alternatives considered**:
- *Use a TCP-level ping (raw socket round-trip) instead of HTTP `/healthz`*: rejected. Modal's HTTPS edge is anycast-routed; a raw TCP ping wouldn't traverse the same anycast path as an HTTPS request and would mis-attribute the probe's measurement to a different routing decision.
- *Probe once per run instead of per cohort*: rejected. The spec's FR-004 explicitly requires per-cohort probing immediately before the cohort's measurement window opens so RTT drift across the ~25–40 min run is captured cohort-by-cohort.
- *Probe both REST transports over the same connection*: rejected. The probe must travel the cohort's network path to be honest; sharing a connection would defeat the per-cohort probe's purpose.

---

## R-3 — 3-tier symmetry block: how are the three tiers constructed, asserted, and persisted?

**Decision**: `m5_2_symmetry.build_symmetry_block(cohorts: list[CohortConfig]) -> SymmetryBlock` constructs the three-tier `symmetry` block per the spec's Clarifications 2026-05-12 (Round 2, Q1):
- **Tier (a) — cross-cohort invariants** (fail-fast at run start): `prompt_corpus_hash` (SHA-256 of the prompt corpus the run loads), `modal_deploy_handle` (the single Modal app handle the whole run uses), `mock_engine_config_digest` (SHA-256 of `MockEngineConfig` serialized as JSON), `warmup_batch_policy` (the warmup-cohort policy literal). All five cohorts MUST share identical tier (a) values; any mismatch aborts the run with a per-tier diagnostic ("tier_a_divergence: field=<name>, cohort_a=<hash_a>, cohort_b=<hash_b>"). The markdown report writer in `reporter.py` MUST refuse to render the markdown on tier (a) divergence with the diverging field named in the failure message.
- **Tier (b) — intra-protocol pair invariants** (fail-fast at run start, with c=1 degeneracy): the two REST cohorts (`rest_https_edge`, `rest_plain_tcp`) MUST share their REST client-config digest EXCEPT for the target URL field (`base_url`); the two `tuned_grpc_*` cohorts (`tuned_grpc_multiplexed`, `tuned_grpc_channels`) MUST share their channel-config digest EXCEPT for the multiplexing topology field (`channel_topology: multiplexed | channels`). At c=1 the two tuned cohorts collapse to `tuned_grpc` per FR-006, so the tuned-pair intra-protocol assertion is degenerate and is **skipped at that concurrency** (the assertion function records "tier_b_skipped_c1: tuned_grpc pair degenerate" in the symmetry block for audit). Asserted at run start; abort the run on any mismatch with the diverging field and the pair named in the failure message.
- **Tier (c) — per-cohort metadata** (audit-only, no cross-assertion): full per-cohort client-config digest (including topology, target URL, region, instance class), Modal app handle, Modal region, client external geolocation (IP-derived country + region — per Edge Case "HTTPS-edge anycast routing varies by client geography"), warmup batch size. Recorded for audit; does not gate publish.

The symmetry block is persisted as a top-level key in the M5.2 JSON (`symmetry: {tier_a: {...}, tier_b: {...}, tier_c: {...}}`) and the assertion verifier `m5_2_symmetry.assert_symmetry(block)` is invoked at run start (before any cohort dispatch) and at report-build time (by the regenerator, before computing aggregates).

**Rationale**: The three-tier scoping resolves the internal inconsistency the user identified in the spec's first-round symmetry clarification — gRPC cohorts deliberately differ on channel configuration (M1-default vs M5-tuned-multiplexed vs M5-tuned-channels), so a blanket "cross-cohort field divergence" rule would fail-fast on every run. Tier (a) covers the invariants every cohort MUST share (corpus, engine, deploy, warmup policy); tier (b) covers the within-pair invariants that protect against accidental drift (REST clients differing on something other than URL; tuned-gRPC cohorts differing on something other than topology); tier (c) records audit metadata without asserting. The c=1 degeneracy skip for tier (b)'s tuned-pair is necessary because the two `tuned_grpc_*` cohorts collapse to a single `tuned_grpc` cohort at c=1 per FR-006 — there is no pair to assert against.

**Alternatives considered**:
- *Single-tier symmetry block (the first-round clarification's design)*: rejected on the second-round clarification due to the gRPC channel-config divergence-by-design problem.
- *Tier (b) without c=1 skip (assert anyway, with empty-pair-fallback)*: rejected. The spec is explicit that at c=1 the tuned cohorts collapse; asserting on a degenerate pair would either always pass trivially (no signal) or always fail (no measurement progress).
- *Persist only tier (a) + (b) in the JSON; drop tier (c)*: rejected. Tier (c) is the "show your work" record that makes the symmetry block useful to a post-hoc reader who wants to know what region / instance / geolocation the run came from. The cost of persisting it is trivial.

---

## R-4 — Per-request JSONL events sidecar: format, gzip discipline, SHA-256 checksum, and append safety

**Decision**: `m5_2_events.EventsSidecarWriter` is a context manager that opens `bench-results/m5_2-full/<run_id>.events.jsonl` (un-gzipped) at run start, appends one JSON line per per-request event (write-buffered, flushed every N=1000 records), and on `__exit__` (a) closes the file, (b) gzips it to `bench-results/m5_2-full/<run_id>.events.jsonl.gz` and removes the un-gzipped intermediate, (c) computes the gzipped file's SHA-256 hex digest, and (d) returns the gzipped path + the digest. The Phase-K1 narrative-summary commit copies the gzipped file to `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` and records the digest in the M5.2 JSON aggregate's executive metadata (under `events_sidecar_sha256`). The regenerator (R-5) reads the gzipped file in-place via `gzip.open(..., "rt")` and streams `json.loads(line)` per line; field provenance is documented in the markdown report at section-header resolution per FR-012b — e.g., "Per-cell median TTFT computed from `cohort=rest_https_edge AND phase=measurement AND status=success` filter on the events sidecar".

Each line is a single JSON object with these required keys (per FR-012a):
- `cohort` (string literal: one of the five cohort names or `tuned_grpc` at c=1)
- `path` (string: `chat_stream` | `embed`), `hidden_size` (int), `concurrency` (int)
- `network_path` (string literal: `https_edge` | `plain_tcp`)
- `request_uuid` (string: uuid4-formatted, unique within the run)
- `issue_ts_ms` (float: monotonic wall-clock), `first_byte_ts_ms` (float or null), `done_ts_ms` (float)
- `rtt_at_issue_ms` (float: the cohort's measured RTT median at the moment the request was issued — recorded once per cohort but replicated per record for grep convenience)
- `phase` (string literal: `warmup` | `measurement`)
- `server_bound` (bool: replicated per record at the cohort level for grep convenience)
- `request_body_bytes` (int), `response_body_bytes` (int)
- `status` (string: `success` | `timeout` | `error:<reason>`)

**Rationale**: The buffered-append + gzip-on-close model avoids the operational hazard of trying to write directly to a gzipped stream during a 25–40 min run (gzip's framing makes mid-stream appends fragile and partial writes hard to recover from). The intermediate un-gzipped file lives only in the gitignored `bench-results/` dir, so it is not a commit-hazard. SHA-256 computed at close time anchors the file's identity in the executive metadata; the regenerator verifies the digest before computing aggregates per FR-012b. JSONL (one JSON object per line) makes the file `zgrep`-friendly per FR-012a's reader contract.

**Alternatives considered**:
- *Stream-write directly to a gzipped file*: rejected. Append-to-gzip is fragile; a SIGKILL mid-run leaves a partially-corrupt gz that the regenerator can't recover from. Buffered append + atomic gzip-on-close is operationally safer.
- *Parquet or columnar format for the sidecar*: rejected. JSONL is human-readable, `zgrep`-friendly, and matches the existing project convention of JSON-everything for benchmark artifacts. The 14 MB raw / 1.5–3 MB gzipped cost is acceptable.
- *Per-cohort sidecar files (one gz per cohort)*: rejected. Increases the diff/commit complexity; a single sidecar is easier to grep across and easier to checksum.

---

## R-5 — Round-trippable regenerator: how does `scripts/python/regen_bench_reports.py` extend, and what is the round-trip contract?

**Decision**: `scripts/python/regen_bench_reports.py` gains an `--m5_2-sidecar PATH` flag and a corresponding entrypoint `regen_m5_2(sidecar_path, run_config_path, expected_sha256) -> RegenerationResult`. The entrypoint:
1. Opens the gzipped sidecar with `gzip.open(..., "rt", encoding="utf-8")`.
2. Verifies the file's SHA-256 against `expected_sha256` (computed from `run_config["events_sidecar_sha256"]`). On mismatch, raise `SidecarChecksumMismatch` with the expected + observed digests in the message and refuse to produce artifacts.
3. Streams the JSONL lines, computing per-cohort aggregates (median, p95, CI bounds, server-bound flag, recommend tally) into an in-memory `M5_2Aggregates` dataclass. Warmup-phase records are excluded per FR-011.
4. Builds the M5.2 markdown (calling into `reporter.write_m5_2_markdown(aggregates, run_config)`) and the aggregate JSON (`reporter.write_m5_2_json(aggregates, run_config)`).
5. Writes them to `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}` (or to a `--m5_2-report-out` override path) using **deterministic key ordering** (Python's stable-by-insertion-order dicts + alphabetically-sorted aggregate keys + a `sort_keys=True` JSON encoder) so re-running the regenerator on the same sidecar + config produces byte-identical output. The markdown writer uses no `datetime.now()` calls — every timestamp the markdown emits comes from the sidecar's event records or the run config's recorded `run_started_at_iso` value.
6. Returns a `RegenerationResult(markdown_path, json_path, sidecar_path, observed_sha256, computed_aggregates_count)` that the operator's pre-PR checklist diff against the committed published artifacts to confirm zero drift.

The byte-identical round-trip is verified by `tests/test_m5_2_regenerator.py::test_round_trip_byte_identical`: fixture a sample sidecar + config, run the regenerator, capture the markdown + JSON byte content, re-run the regenerator, assert byte-for-byte equality. The Modal-smoke integration test runs this round-trip against a live sweep's sidecar.

**Rationale**: The round-trip contract is what makes "report numbers are read from telemetry" auditable — a reader / CI step / operator can re-run the regenerator on the published sidecar + the run config (which is also committed; lives in the JSON aggregate's `run_config` key) and diff the output against the committed markdown + JSON; any mismatch is a bug in the regenerator or evidence of tampering. The SHA-256 verification step catches sidecar corruption (e.g., git-LFS truncation, manual edit) before aggregates are computed, so the report cannot accidentally publish numbers derived from a corrupted sidecar.

**Alternatives considered**:
- *Compute aggregates in the harness and have the regenerator only render the markdown from a pre-computed aggregate JSON*: rejected. FR-012b explicitly requires aggregates to be **computed from the sidecar at report-build time**, not maintained as a parallel aggregate-only data path inside the harness. The "parallel aggregate path" risk is exactly the regression mode FR-012b protects against.
- *Use a hash-resistant deterministic JSON encoder (e.g., canonicaljson)*: deferred. Python's `json.dumps(..., sort_keys=True, separators=(",", ":"))` is sufficient for byte-identical round-trips on the field set we emit; canonicaljson adds a dependency without buying additional determinism within our schema.
- *Allow the regenerator to lazy-compute aggregates and cache them between rebuilds*: rejected. Caching defeats the audit purpose; every regen MUST re-read the sidecar so the round-trip diff catches drift.

---

## R-6 — Supersedes-M5.1 table: categorisation logic for `verdict_changed` / `verdict_confirmed` / `noise_resolved` / `transport_dependent`

**Decision**: `m5_2_supersede.build_supersedes_m5_1(m5_1_cells: dict, m5_2_cells: dict) -> list[SupersedesM5_1Entry]` loads M5.1's published JSON (`docs/benchmarks/m5_1-rest-vs-grpc.json`), iterates each cell M5.2's matrix covers, and emits one row per (M5.1 verdict, M5.2 protocol-comparison verdict against `rest_https_edge`) pairing. Each row's category is determined by:
- `verdict_changed` — M5.2 verdict literal differs from M5.1 verdict literal AND M5.1 was not `no_winner`.
- `verdict_confirmed` — M5.2 verdict literal matches M5.1 verdict literal AND both are CI-supported (i.e., neither is `no_winner` nor `comparison_unavailable`).
- `noise_resolved` — M5.1 verdict was `no_winner` AND M5.2 verdict is a CI-supported `_recommend` literal. This is the M5.2-headline category — the resolution-increase paid for it.
- `transport_dependent` — M5.2's protocol-comparison verdict against `rest_https_edge` differs from what the same comparison would have produced against `rest_plain_tcp` AND M5.1's verdict (which used `rest_plain_tcp`) matches the latter. In other words, the HTTPS-edge transport cost moved the comparison; the protocol verdict is path-sensitive.

When M5.1's verdict was `comparison_unavailable` (server_bound or one-sided failure), M5.2's row records the M5.1 unavailability and the M5.2 verdict (or unavailability) with category `transport_dependent` if M5.2 is now CI-supported, or with category `confirmed_unavailable` if M5.2 is also unavailable. (The `confirmed_unavailable` literal is added to the category enum.)

The Supersedes-M5.1 table is computed at report-build time (by the regenerator) from M5.2's aggregate JSON + M5.1's published JSON — no harness-side computation. M5.1's published file remains in place; supersession is recorded forward-only in M5.2 per FR-016.

**Rationale**: Categorising on M5.1's verdict literal vs M5.2's verdict literal is the same shape M5's Supersedes-M4 table used and M5.1's Supersedes-M1 table used. The `transport_dependent` category is the new lever M5.2 adds — it explicitly disambiguates "M5.2 disagrees with M5.1 because the noise resolved differently" (would be `noise_resolved` if M5.1 was no_winner) from "M5.2 disagrees with M5.1 because the network path moved the verdict" (`transport_dependent`). The reader gets a categorical answer to "why did this row change."

**Alternatives considered**:
- *Single `verdict_changed` category without sub-classification*: rejected. The reader can't distinguish a noise-floor resolution from a transport-cost shift without the category split; that distinction is the M5.2 report's central rhetorical move.
- *Compare M5.2's transport-only family verdict against M5.1's REST cohort verdict directly*: rejected. M5.1 had no `rest_https_edge` cohort — the comparison can only be against M5.2's reconstructed-from-`rest_plain_tcp` verdict (which is what the `transport_dependent` category measures).

---

## R-7 — Pre-flight smoke gating: how does the M5.2 smoke extend M5.1's smoke, and where does the assertion surface live?

**Decision**: `--m5_2-smoke` is a CLI shortcut that dispatches to the same `run_m5_2_sweep` codepath but with three modifications: (1) cell coverage reduced to the M5.1 smoke set (3 cells: `chat_stream c=1`, `chat_stream c=4`, `embed c=4`) extended with one transport-coverage cell (`embed c=1` to exercise both REST transports against the c=1 collapsed `tuned_grpc` cohort), so the smoke covers all five cohort kinds plus the c=1 degeneracy skip path; (2) per-cohort `n` reduced to 5 measurement requests + 2 warmup (matches M5.1's smoke shape); (3) the assertion surface includes M5.2-specific checks invoked BEFORE the smoke cohorts run — `assert_both_rest_transports_reach_same_modal_deploy` (HTTPS-edge + plain-TCP REST cohorts share `modal_deploy_handle` + identical `/healthz` JSON body), `assert_m5_2_json_schema_round_trips` (writes the M5.2-additive fields per FR-013 to a temp aggregate JSON, reads them back, asserts equivalence), and `assert_per_cohort_rtt_probe_within_thresholds_all_five_cohorts` (the per-cohort RTT probe returns within `--m5_2-rtt-validity-threshold-ms` thresholds for every cohort the full run would exercise). Any assertion failure prints a structured `M5_2SmokeAssertionFailure` line and exits with code 6 (matching M5.1's smoke exit-code convention).

The full sweep (`--m5_2` without `--m5_2-smoke`) does NOT re-invoke the smoke harness — the operator MUST run `--m5_2-smoke` first (the maintainer's pre-PR checklist documents this in quickstart.md). The harness does not enforce the ordering; SC-012 makes it the operator's responsibility to name the smoke outcome in the PR description.

**Rationale**: The spec's Clarifications 2026-05-12 explicitly chose "Reuse M5.1's smoke harness, extend with M5.2-specific assertions, no new smoke step." The implementation realises that as a CLI shortcut + an assertion-surface extension. Running the smoke and the full sweep as the same codepath (with different cell + n + assertion-surface configuration) prevents drift between what the smoke checks and what the full sweep does. The four assertion checks (corpus, deploy, schema round-trip, RTT thresholds × 5 cohorts) cover the FR-005a failure modes the spec enumerates.

**Alternatives considered**:
- *Separate `m5_2_smoke.py` module*: rejected. Duplicates ~80% of `m5_2_sweep.py`'s code and risks the two paths drifting.
- *Encode the smoke assertions as pytest tests run against a deployed Modal app*: rejected. pytest's CI integration assumes the Modal app is up at test-collection time, which is not the smoke-harness's pre-deploy posture; a CLI-driven smoke is the right fit.

---

## R-8 — Three discrete narrative commits + ANALYSIS.md structure + README simplification: composition and ordering

**Decision**: The Phase K1/K2/K3 commits land in this order, each as a single git commit, no squash:

**K1 — "Summarize M5.2 milestone findings"** (touches only `docs/benchmarks/m5_2-transport-vs-tuning.md` plus the JSON aggregate already committed in Phase I):
- Add the milestone executive section (headline finding per verdict family; HTTPS-edge vs plain-TCP RTT delta; `noise_resolved` count from Supersedes-M5.1; payload-parity audit confirmation line citing PR SHA per FR-005c).
- Add or refresh the per-cell comparison matrix with both verdict families and network-path naming per row.
- Add the Supersedes-M5.1 table (categories per R-6).
- Add field-provenance footnotes naming the sidecar filter or aggregate-JSON key per section header (FR-012b).
- Add the negative-results appendix listing cells where verdicts are `no_winner` or `comparison_unavailable` with full per-cohort CI bounds (FR-014 (e)).

**K2 — "Compose ANALYSIS.md § M5.2 narrative"** (touches `ANALYSIS.md`, `docs/benchmarks/summary.md`, `docs/PLAN.md`, and every `docs/benchmarks/m*.md`):
- Create `ANALYSIS.md` at the repo root with sections for M1, M2, M3, M4, M5, M5.1, M5.2. Each section names: title, delivered date (or "(upcoming)" for any not-yet-merged), report path(s), headline finding(s) in factual prose with CI-bounded numbers, cross-milestone supersession notes (e.g., "M5.2 resolves M5.1's open question on tuned-vs-default benefit on this path" if `noise_resolved` count > 0 in K1's table).
- Fold `docs/benchmarks/summary.md`'s M3-era content into `ANALYSIS.md § M3` byte-for-byte equivalent (the M3 §4 channel-tuning tables); replace `summary.md` with a one-line redirect to `ANALYSIS.md` plus the "All benchmarks ran on …" methodology preamble preserved (per US2 acceptance scenario 2).
- Replace `docs/PLAN.md`'s embedded milestone-findings paragraphs with one-line "Findings: see `ANALYSIS.md` § M<N>" pointers; leave goals, phase descriptions, exit criteria, risk register intact (per FR-019).
- Audit `docs/benchmarks/m*.md` and update any cross-reference that previously pointed at `summary.md` to point at `ANALYSIS.md` with the relevant section anchor (per FR-020).

**K3 — "Refresh README narrative for M5.2 delivery"** (touches `README.md` + any drift fixes the FR-022 tooling-validation pass surfaces — could touch `Makefile`, `demo/*.{sh,py}`, env-var consumption code, depending on what drift exists):
- Simplify the README to ≤180 lines per FR-021: trim the Roadmap section to ≤25 lines (one line per milestone + ANALYSIS.md pointer); collapse the Benchmark Headlines section to a single paragraph (≤80 words) with structural numbers only (bytes-axis from M1) per FR-023; preserve Three Access Paths + Prerequisites + Quick Start + Development Commands + Environment Variables + Repository Structure + CI sections in shortened form.
- Run the FR-022 validation pass against every Make target, demo script path, env var, and external dependency in the README. Any drift fix lands in the same commit; the PR description names each fix.
- **MUST be the last commit on the branch at `gh pr create` time** per FR-024. The maintainer verifies with `git log -1 --oneline` before opening the PR.

The PR description cites all three commit SHAs explicitly (per SC-015) so a reviewer can verify the discrete-summarization sequence from the commit log alone without reading the diff.

**Rationale**: The three-commit decomposition makes the operator-visible commit log demonstrate that the milestone-scoped summary (K1) was produced first, the cross-phase narrative (K2) was composed on top of it, and the README narrative-refresh (K3) was performed last with the publishable artifacts already in place. The user's clarification explicitly named this order to prevent the regression where milestone summary and cross-phase narrative are drafted in parallel (and then drift). Putting K3 last preserves M5.1's FR-019 procedural rule.

**Alternatives considered**:
- *Single squashed narrative commit*: rejected by FR-024a — the user explicitly required two discrete commits before K3.
- *K1 + K2 in either order*: rejected by FR-024a — the cross-phase narrative depends on the milestone summary, so K1 before K2 is the only sensible order.
- *K3 before K1 + K2 with K3 amended at the end*: rejected. The amend would rewrite K3's SHA, defeating the PR description's "cite SHA explicitly" rule.

---

## R-9 — Payload-parity code-review audit (FR-005c): checklist content and where the audit's findings live

**Decision**: `specs/019-m5-2-transport-tuning/contracts/m5_2-payload-parity-audit.md` is the operator's checklist. The maintainer reads the file and performs the audit at the start of Phase J (after the harness implementation lands, before the full sweep runs). The audit covers:
1. **Chat-path payload parity**: both REST cohorts and all three gRPC cohorts construct the same prompt body for `chat_stream` from the corpus (same prompt content, same `max_tokens`, same `temperature`, same `stream=true` flag) — verify by reading `rest_cohort.py::run_rest_cohort_chat` and `m5_1_grpc_cohort.py::run_grpc_chat_cohort` side-by-side and confirming the request-body field set matches modulo protocol-required wrappers (HTTP JSON body vs gRPC `ChatCompletionRequest` protobuf).
2. **Embed-path payload parity**: both REST cohorts and all three gRPC cohorts construct the same embedding-input payload (same shape derived from `hidden_size`, same dtype, same byte size — this is the regression's exact failure mode). The audit MUST cite the past incident by name ("the REST harness was sending a different-sized embedding payload than gRPC") and confirm by reading the harness HEAD that the regression has not been reintroduced — record the per-path measured payload byte size for both protocols + the request-body schema sketch.
3. **No protocol-specific normalization that changes effective payload size**: verify neither protocol's harness applies a per-protocol input normalization (e.g., resizing, padding, dtype conversion) that would make the in-flight bytes diverge between protocols.

The audit's findings are recorded in the M5.2 report's executive metadata as two fields:
- `payload_parity_audit.no_regression_confirmed_against_pr: "<SHA-or-#>"` (the commit SHA or PR number the audit was conducted against — typically the K1 commit's SHA at first audit, refreshed if subsequent commits touch the harness payload paths)
- `payload_parity_audit.measured_payload_bytes: {chat_rest_https_edge: N1, chat_rest_plain_tcp: N1, chat_grpc: N2, embed_rest_https_edge: N3, embed_rest_plain_tcp: N3, embed_grpc: N4}` (per-path measured payload byte size — chat REST/gRPC are not byte-equal because the JSON wrapper is different from the protobuf wrapper, but the **engine-input content** byte size MUST match within protocol-wrapper tolerance; the embed path's REST/gRPC bytes are the regression-relevant comparison and MUST match exactly).

SC-013 makes this metadata mandatory: the M5.2 report MUST publish both fields, and the PR description MUST cite them explicitly so a reviewer can verify the audit was performed without re-running the harness.

**Rationale**: The user's explicit anti-regression requirement is what makes this audit a discrete, code-review-driven step (not a harness-automated assertion). FR-005b's symmetry-block assertions catch cross-cohort *configuration* divergence; FR-005c protects against the harness computing the *wrong payload* in the first place — a failure mode no within-harness assertion can catch because both protocols would compute the wrong payload self-consistently. Recording the audit's findings in executive metadata makes the audit auditable: a future operator confirms the audit was performed by reading the executive section.

**Alternatives considered**:
- *Automate the payload-parity check as a unit test*: rejected. A unit test can compare two functions' outputs but cannot detect the deeper regression mode where both functions are correct individually but compute different effective payloads via different upstream calculation paths. The audit is a code-reading step that catches the deeper regression mode by reading the call graphs side-by-side. (A unit test alongside the audit, asserting byte-equality of the embedding-input payload across protocols, is added as a belt-and-suspenders defense in Phase H.)
- *Skip the audit on subsequent M5.2 sweeps after the first*: rejected. The audit's PR-SHA-or-# reference makes it cheap to re-confirm; the cost of re-running the audit is ~10 minutes of code reading per resubmit.

---

## R-10 — Round-trip diff in CI: should the regenerator's round-trip be a CI gate?

**Decision**: Not in M5.2's CI runtime budget. The round-trip is verified (a) by the unit test `test_m5_2_regenerator.py::test_round_trip_byte_identical` (a fixture-driven test that runs at every `make check`), and (b) by the maintainer's pre-PR checklist in quickstart.md, which calls for an operator-run regenerator-round-trip diff against the published artifacts after the sweep completes. The full-sweep sidecar is too large to commit and re-run in CI without inflating CI cost; the unit-test fixture is the right balance.

**Rationale**: The unit test catches regression in the regenerator's logic; the operator's pre-PR round-trip catches drift in the published artifacts. Together they cover the FR-012b "round-trippable" contract without making CI slow. The unit test uses a 50-record synthetic sidecar (smaller than 1 KB gzipped) and runs in <1 second.

**Alternatives considered**:
- *Commit a tiny canonical sidecar in `tests/fixtures/` and run a full regenerator on it in CI*: that is the chosen approach; the unit test IS that.
- *Add a slow CI job that runs the regenerator on the actual committed `m5_2-transport-vs-tuning.events.jsonl.gz`*: rejected. Adds ~5 seconds to every PR's CI run for a check the operator already performs by hand; not worth the CI minutes.

---

## R-11 — README simplification audit: how is the ≤180-line target achieved without losing conceptual coverage?

**Decision**: The K3 commit applies these specific edits, measured against the current README's 285 lines (verified by `wc -l README.md` at K3 start):

1. **"Benchmark Headlines" → one paragraph (≤80 words)** with structural numbers only: "89% chat response byte reduction (M1, structural / encoding-driven)". Numbers tied to a specific transport (TTFT deltas, p95 wall-clock, RTT) are moved to `ANALYSIS.md` where they carry the network-path caveat. Savings: ~30 lines.
2. **"Roadmap" → ≤25 lines**, one line per milestone naming the deliverable + linking to `ANALYSIS.md § M<N>`. Savings: ~85 lines.
3. **"Three Access Paths"**: preserved, trimmed of redundant bullets if any exist. Target: no change in conceptual coverage; ~5 line reduction.
4. **"Prerequisites"**: validated against current install commands; trimmed of duplicated install steps. Target: ~5 line reduction.
5. **"Quick Start"**: validated end-to-end against the current Makefile + scripts; trimmed of obsolete steps. Target: ~5 line reduction.
6. **"Development Commands"**: validated against the current Makefile (every target referenced exists). Trimmed of obsolete targets if any. Target: net-neutral.
7. **"Environment Variables"**: validated against current consumption (every env var listed is genuinely read somewhere); trimmed of unused vars. Target: ~5 line reduction.
8. **"Repository Structure"**: re-checked against the current `packages/` + `tools/` + `scripts/` layout; updated for any drift (e.g., `summary.md` path → ANALYSIS.md). Target: net-neutral.
9. **"CI"**: preserved; updated to reference the current CI gates (ruff check, ruff format check, mypy, tests, proto-stub-compile per `.github/workflows/`). Target: net-neutral.

Total target: 285 → ≤180 lines (≥105-line reduction). The K3 commit message includes the before/after line count.

The FR-022 tooling-validation pass is woven into each edit: every Make target, demo script path, env var, and external dependency reference is checked as the corresponding section is edited. Any drift (e.g., a Make target that no longer exists, a demo script that's been removed, an env var that's no longer consumed) is fixed in K3 — in the README if the README is wrong, in the consuming code / Makefile / demo script if the code is wrong. The PR description names each drift fix per FR-022.

**Rationale**: The line-budget approach makes the simplification measurable (SC-008 names ≤180 lines as a success criterion); the section-by-section walkthrough ensures conceptual coverage is preserved (per US3 acceptance scenario 4: "the same conceptual coverage is preserved … but the total document is roughly ≤ 180 lines"). The tooling-validation pass is woven into the simplification rather than separated to avoid double-passing over the file.

**Alternatives considered**:
- *Smaller line target (e.g., ≤120 lines)*: rejected. Too aggressive for the conceptual-coverage requirement; testing shows ~180 is the floor for fitting all required sections.
- *Tooling validation as a separate PR commit*: rejected. K3 is a single commit per FR-024; bundling the validation in K3 keeps the PR's narrative-refresh commits at three.

---

## R-12 — Chat-corpus methodology: ShareGPT V3 subset, pinning, filter, and field semantics

> **Added 2026-05-12 post-implementation.** The original spec deferred chat-prompt sourcing to "synthetic per-request strings shaped by `(iteration, cell_id)`". The FR-005c audit's Step 1 strict reading on the first audit pass flagged this as a parity gap (REST and gRPC used different prompt formats and different max_tokens — M5.1-inherited). The fix routes both protocols through a shared chat corpus. The choice of corpus matters for two reasons: (a) industry-comparability with vLLM / SGLang / TGI's published throughput numbers, and (b) representativeness of real chat workloads (length distribution, multi-turn structure) for the future M7 real-engine validation.

**Decision**: M5.2 sources chat prompts from **ShareGPT V3** (`anon8231489123/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json`, pinned to commit SHA `192ab2185289094fc556ec8ce5ce1e8e587154ca` from HuggingFace). The de-facto reference corpus for LLM serving benchmarks; vLLM's `benchmarks/benchmark_serving.py` historically uses this exact file. Pinning to the source revision SHA gives byte-stable corpus identity across re-runs; pinning the file's SHA-256 (`35f0e213…ba4`) in `scripts/python/gen_chat_corpus.py` hard-fails on upstream force-push.

The corpus is generated by `scripts/python/gen_chat_corpus.py`:
1. Download the 673 MB raw file into gitignored `bench-results/sharegpt-raw/` (cached; re-download skipped on SHA match).
2. Extract the **first `from=human` turn** of each conversation (vLLM benchmark convention — single-turn TTFT measurement, no multi-turn context).
3. Filter by prompt length: 4 ≤ chars ≤ 2048 (excludes empties + heavy outliers; covers ~95% of ShareGPT first-turn-prompt distribution).
4. Random-sample N=1000 prompts with seed=42 (vLLM benchmark convention).
5. Emit a `RequestSample[]` JSON at `tools/benchmark/corpus/chat_sharegpt_<N>.json` with: `id`, `messages=[{role:user, content:...}]`, `model="Qwen/Qwen3-0.6B"` (M7-aspirational; the harness substitutes the engine-side model name), `max_tokens=128` (vLLM benchmark convention), `temperature=0.0`, `seed=42`, `bucket` (auto-derived: short/medium/long by char count).
6. Emit a companion `.provenance.json` recording source URL, source revision SHA, source-file SHA-256, filter criteria, random seed, and the corpus file's SHA-256 so the audit trail is reproducible without re-downloading.

**Rationale**: ShareGPT is the corpus every published vLLM throughput number uses. Hand-curating 50 samples — which was the initial implementation reflex — would produce numbers that don't compare to any published reference. The pinning + provenance file lets the corpus be regenerated byte-for-byte from source forever (HuggingFace preserves historical revisions). The first-turn-only filter matches vLLM's `benchmark_serving.py` convention; the 4–2048 char filter excludes degenerate samples; max_tokens=128 is vLLM's default cap.

Cohort runners cycle through the corpus by `iteration % len(corpus)` so:
- The same iteration index produces the same sample on REST and gRPC (FR-005c Step 1 parity holds by construction).
- 1000 samples × ~24× repetition per cohort over a full 18-cell sweep (each prompt is used ~24 times across the sweep) — enough cycling that prompt-content variance averages out.
- Warmup phase uses corpus indices 0..warmup_n-1 (sample 0 is reused as both a warmup and a measurement prompt; fine for MockEngine which has no caching effects).

**Alternatives considered**:
- *Hand-curated 50 samples*: rejected for the industry-comparability reason. Hand-curation also introduces author bias and unreproducible content.
- *ShareGPT V4.3 (Aeala/ShareGPT_Vicuna_unfiltered)*: rejected. V4 is a later cleaning pass with different sample content; vLLM's benchmark convention still references V3. Pinning V3 keeps the M5.2 numbers comparable to historical vLLM publications.
- *Multi-turn conversation context*: rejected for first-pass. vLLM's own benchmark uses first-turn-only; multi-turn would require harness changes to thread message history through both protocols and would diverge from the comparable-reference goal.
- *Per-sample max_tokens from ShareGPT's actual assistant response length*: rejected. Introduces additional variance per request, harder to compare cohorts cleanly. Fixed max_tokens=128 (vLLM default) makes engine workload uniform.
- *Download-and-subset at sweep time (not commit the corpus)*: rejected. Operationally fragile (depends on HuggingFace at sweep time), and a 500 KB committed JSON is cheap. Committed corpus = reproducible without network.

**Implementation note**: `tools/benchmark/src/vllm_grpc_bench/corpus.py::load_corpus` reads the corpus into `list[RequestSample]`. The dataclass gained an optional `bucket` field (default `"unspecified"`) so pre-M5.2 corpora (e.g., `chat_nonstreaming.json` without the field) load unchanged. `m5_2_sweep.M5_2SweepConfig.chat_corpus_path` (default `None` → uses `DEFAULT_CHAT_CORPUS_PATH = chat_sharegpt_1000.json`) controls which corpus the sweep consumes. Setting the path to an empty Path disables corpus mode and falls back to the synthetic `build_chat_prompt` helper (back-compat with pre-corpus tests).

---

## R-13 — Modal preemption-aware URL refresh: detection, polling, and bounded retry

> **Added 2026-05-12 post-implementation.** Modal preempts running Functions for worker maintenance / failure recovery (per [https://modal.com/docs/guide/preemption](https://modal.com/docs/guide/preemption): "Modal occasionally restarts running Functions"). The first M5.2 full sweep that exercised the resilience plumbing got preempted mid-cell-2. Modal restarted `serve_bench` on a new worker, which wrote fresh tunnel URLs to the same `modal.Dict` — but the harness's URL cache from the original handshake stayed stale, causing cells 3–18 to fail with `httpx.ConnectError`. The fix below makes the harness preemption-aware.

**Decision**: When a cell's dispatch fails with a connect-style exception (`httpx.ConnectError`, `httpx.ReadError`, `httpx.RemoteProtocolError`, `ConnectionError`, or any of these found via exception-chain walk through `__cause__` / `__context__` / `ExceptionGroup` children), the harness MUST poll the Modal handshake Dict for fresh URLs and retry the cell ONCE if fresh URLs are detected. Implementation:

1. `m5_2_sweep._is_connect_error(exc)` walks the exception chain and returns True iff any link is an httpx connect-family error or a plain `ConnectionError`. Returns False for unrelated `RuntimeError` / `ValueError` so the refresh path isn't triggered for real code bugs.
2. `modal_endpoint.refresh_rest_grpc_urls(cached, *, poll_timeout_s=90.0, poll_interval_s=2.0)` polls `modal.Dict.from_name("vllm-grpc-bench-rest-grpc-mock-handshake")` for up to 90 seconds. Returns a fresh `RESTGRPCEndpoints` when the gRPC URL differs from `cached`'s URL (gRPC URL is the canonical freshness anchor — REST URLs may match transiently across preemptions if anycast routes to the same edge POP). Returns `None` if no fresh URLs appear within the timeout (probably not preemption — the original ConnectError reflects a real failure).
3. `m5_2_sweep.run_m5_2_sweep` wraps each cell dispatch with: on connect error → call `config.refresh_endpoints_fn` (if set) → if fresh URLs returned, mutate `config.rest_https_edge_url` / `config.rest_plain_tcp_url` / `config.grpc_target` / `config.https_edge_endpoint` in place and retry the cell. Bounded retry: ONE retry per cell. If the retry also fails, the cell lands in `failed_cells` per the existing resilience path.
4. `__main__._run_m5_2` wires up a `_refresh()` closure inside the `provide_rest_grpc_endpoint` context manager. The closure captures the current `RESTGRPCEndpoints` and calls `refresh_rest_grpc_urls` against it. Skip-deploy mode does not own a Dict reference; `refresh_endpoints_fn` stays `None` and connect errors there are treated as real failures.

**Rationale**: Modal's preemption model writes new URLs to the same shared Dict on restart, which means the recovery information is already in the system — the harness just needs to read it. Polling-based detection is robust to the restart latency (new worker takes 30–60 s to spin up + run the handshake before writing new URLs). The gRPC URL as the freshness anchor avoids false positives — REST URLs can match transiently across preemptions when anycast routing is stable; gRPC tunnels are plain-TCP with worker-specific addresses. The bounded-1-retry budget prevents infinite retry loops if a deeper Modal failure leaves the Dict in a stuck state.

**Alternatives considered**:
- *Use Modal's `restart_strategy=KEEP_RUNNING` or similar to suppress preemption*: investigated; Modal doesn't expose a "never preempt" toggle for CPU-only Functions on the default worker pool. Preemption is part of Modal's serverless model; the harness must adapt.
- *Deploy `serve_bench` as a persistent `modal.App.deploy()` and run the harness in `--m5_2-skip-deploy` mode*: rejected for first-pass. Bigger architecture change; the operator's deploy/teardown workflow becomes two-step. Worth revisiting in a future milestone if preemption becomes frequent.
- *Re-handshake on EVERY cell (not just on connect error)*: rejected. Adds 2–4 s per cell × 18 cells = 36–72 s of overhead on the happy path with no benefit. Detection-on-failure is strictly cheaper.
- *Walk only `__cause__` (not `__context__` and `ExceptionGroup`)*: rejected. cohort runners sometimes wrap httpx errors in higher-level exceptions; the chain walk catches those. Tests in `test_m5_2_preemption_resilience.py` cover the chained-exception case.
- *Unbounded retry budget*: rejected. If Modal's worker pool is genuinely down (not preemption — outage), an unbounded retry would burn time without making progress. One retry per cell + per-cell catch-and-continue gives the operator a clear failed_cells log and bounded loss.

**Operator-visible behavior**: On detection, the harness prints to stderr:
```
[m5_2] cell N/18 <cell_key>: connect error (ConnectError); polling Modal Dict for fresh URLs (preemption check) …
[m5_2] cell N/18 <cell_key>: preemption detected — updating URLs and retrying. new grpc=<host>:50051, new rest_edge=https://<id>.modal.run
```
If refresh returns None:
```
[m5_2] cell N/18 <cell_key>: no fresh URLs detected within timeout — treating original error as a real connect failure.
```
The cell falls through to the existing failed_cells path. The sweep continues to cell N+1 either way.

---

## Open items deferred to implementation

These are not blockers — each has a clear default that the implementation can apply, but they are worth noting so `/speckit-tasks` can promote them to discrete task subjects if the implementer wants explicit checkboxes.

- **Hash algorithm for corpus / engine-config / channel-config digests**: SHA-256 (matches the sidecar checksum; one algorithm across the milestone is cheaper to reason about than mixing SHA-256 + SHA-1 + md5).
- **Random seed pinning**: M5.1 used a default seed via `--seed`; M5.2 reuses M5.1's seed default unchanged so the corpus-hash invariant in tier (a) is byte-stable across smoke and full-sweep runs. The seed value is recorded in the sidecar's per-run config and in tier (a) of the symmetry block.
- **Client external geolocation lookup**: a single `https://ipinfo.io/json` lookup at run start writes the country + region into tier (c) of the symmetry block. The lookup is best-effort; if it fails (no network, rate-limited), tier (c) records `client_external_geolocation: null` and the report's executive metadata notes the lookup failure. Not a publish-blocker (tier (c) is audit-only per R-3).
- **Regenerator's deterministic JSON encoder configuration**: `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` with `default=str` for `Path` / `datetime` fields. Documented in `contracts/m5_2-regenerator.md`.
- **Sidecar reader convenience helpers**: a small `m5_2_events.read_sidecar_iter(path)` generator is added so test fixtures and the regenerator both consume the same code path; not part of the public CLI.
- **Markdown table column ordering**: alphabetical by column header within each section, except the verdict literal column which is leftmost (mirrors M5.1's reporter convention).

---

## Closing — all NEEDS-CLARIFICATION resolved

All 13 R-items (R-1 through R-13) and the open-items list cover the methodology decisions implicit in the plan. The spec's Clarifications (Session 2026-05-12 + post-implementation revisions 2026-05-12) provided the user-pinned choices for ANALYSIS.md filename + scope, PLAN.md findings-only extraction, REST streaming model parity, smoke harness reuse + assertion-surface extension, 3-tier symmetry assertion + payload-parity audit, per-request JSONL telemetry, regenerator-built report with field provenance, discrete narrative commits, three-tier symmetry scoping with c=1 degeneracy, gzipped sidecar storage, ShareGPT chat-corpus integration, topology-aware framing for Supersedes-M5.1, two-uvicorn Modal architecture (R-1 revision), and Modal preemption-aware URL refresh. This research file translates those choices into implementation-actionable decisions. No NEEDS CLARIFICATION items remain.

**Constitution Check re-evaluation (post-research)**: PASS. No research finding introduces complexity that the initial constitution check did not anticipate. The single-line additive change to `scripts/python/modal_bench_rest_grpc_server.py` (adding `modal.forward(8000, unencrypted=True)` to expose the FastAPI shim over plain-TCP for the `rest_plain_tcp` cohort) is the only Modal-side change M5.2 makes; everything else is harness-side wiring. The 3-tier symmetry block, the JSONL events sidecar, the round-trippable regenerator, the Supersedes-M5.1 categoriser, the payload-parity audit, and the discrete narrative commits are mechanical expansions of M5.1 patterns plus the user's explicit clarifications. No `proto/` edits (Constitution I), no vLLM fork (Constitution II), no phase boundary violations (Constitution III), no CI-bypass (Constitution IV), no honesty-mechanism weakening — instead, three strengthening mechanisms per the Constitution Check table (network-path naming, 3-tier symmetry, sidecar-derived aggregates) (Constitution V).
