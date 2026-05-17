# Feature Specification: M6.1.2 — Methodology Discipline: Topology Proof + 3-Cohort Reintroduction + Harness QoL

**Feature Branch**: `025-m6-1-2-methodology-discipline`
**Created**: 2026-05-17
**Status**: Draft
**Input**: User description: "M6.1.2 as specified in docs/PLAN.md"

## User Scenarios & Testing *(mandatory)*

<!--
  M6.1.2 is a methodology-discipline bundle that ships three additions on
  the benchmark harness + report side BEFORE M6.2 introduces the
  `max_tokens` axis. Scoped by spike `spike/m6-1-roadmap-additions`
  items #1 + #2 + #3 (findings under `docs/spikes/m6-1-roadmap-additions/`):
    1. Per-sweep tcptraceroute probe → `network_paths` block in artifact JSON
    2. Reintroduce `rest_plain_tcp` cohort (M5.2 had it; M6/M6.1/M6.1.1 dropped it)
    3. Timestamped progress lines on stderr (already implemented on the
       spike branch at commit 3763687; this milestone re-bundles it under
       the M6.1.2 banner so PLAN.md prose reflects the new home)

  The bundle exists because all three items touch the same set of files
  (sweep orchestrator, artifact JSON schema, reporter, stderr emitter) and
  ship together more efficiently than as separate milestones. The bundle
  exists ALSO because M6.2's diff against M6.1.1 must isolate exactly one
  variable (the new `max_tokens` axis) — bundling methodology discipline
  into M6.2 would re-create the methodological confound M6.1.1 was created
  to avoid (Phase Discipline, Constitution Principle III).

  M6.1.2 is harness-only: no engine-cost code changes, no model changes,
  no Modal-endpoint changes, no classifier changes. It strictly extends
  the per-sweep artifact schema (additive), restores a cohort that was
  removed during the M6 simplification, and rebrands an already-implemented
  stderr ergonomic.
-->

### User Story 1 - Capture Per-Sweep Network-Topology Evidence in the Artifact (Priority: P1)

A future benchmark operator (or cohort-comparison reader) needs to know which cloud provider each cohort's endpoint actually routes through *for the specific deploy that produced a given sweep artifact*. The spike's live `tcptraceroute` proof (2026-05-17, `docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md`) showed `rest_https_edge` (`*.modal.run`) enters Microsoft Azure while `rest_plain_tcp` + the gRPC cohorts (`*.modal.host`) enter AWS us-west-1 via Telia. That asymmetry is real but tunnel IDs are ephemeral per deploy; without a per-sweep probe, the published artifact can only assert the architectural pattern observed on the spike date, not for the deploy that produced *this* sweep. Cohort-comparison conclusions ("HTTPS-Edge has higher latency") that don't carry topology evidence in the same artifact are silently load-bearing on a property the data doesn't capture.

**Why this priority**: This is the most operator-visible methodology-discipline addition in M6.1.2 and the one M6.1.3 (proxy-edge probes), M6.2 (`max_tokens` axis), M7 (corpus), and M8 (multi-model) all inherit. Without `network_paths` captured at sweep start, cohort comparisons published from M6.1.2 forward would carry the same architectural-claim-without-data weakness M6 / M6.1 / M6.1.1 carried. It's also the only item in the bundle that requires *new* harness behaviour (item #2 is a restoration; item #3 is already implemented); item #1 carries the most novel implementation risk and the most value, so it gets P1.

**Independent Test**: Can be fully tested by running a single low-cost validation sweep against a fresh Modal deploy and confirming the resulting artifact JSON contains a top-level `network_paths` block keyed by cohort, with each cohort's entry containing `endpoint_ip`, ordered `hops` (with cloud-provider + region annotation where derivable), and `probe_method: tcptraceroute`. The probe runs once at sweep start, not per cell. A reader who has only the artifact (no access to Modal logs or the deploy state) can reconstruct which CSP fronted each cohort for that sweep.

**Acceptance Scenarios**:

1. **Given** the operator launches an M6.1.2 sweep against a fresh Modal deploy, **When** the sweep starts, **Then** before the first measurement cell runs the harness probes each cohort endpoint with `tcptraceroute` and writes the hop traces into an in-memory `network_paths` structure.
2. **Given** a sweep completes successfully, **When** an automated reader parses the artifact JSON, **Then** the reader finds a top-level `network_paths` block keyed by cohort name, with each cohort's value containing at minimum `{ endpoint_ip, hops: [...], probe_method, probed_at_utc }`.
3. **Given** the spike-observed topology (Azure for `*.modal.run`, AWS us-west-1 for `*.modal.host`), **When** the sweep's probe completes against a fresh deploy that conforms to that pattern, **Then** the `rest_https_edge` cohort's `cloud_provider` field reads "Microsoft Azure" (or equivalent), and the `rest_plain_tcp` / `default_grpc` / `tuned_grpc_multiplexed` cohorts read "AWS" with region "us-west-1" (or equivalent).
4. **Given** a future deploy where the topology has changed (e.g., Modal moves a cohort to a new CSP), **When** the probe runs, **Then** the artifact's `network_paths` faithfully records whatever the probe observed without assertion or schema error — *and* a stderr line surfaces the divergence loudly so the operator notices the architectural change.
5. **Given** the `tcptraceroute` probe fails for one cohort (e.g., binary not installed locally, network blocks the probe, the cohort endpoint is unreachable from the operator's machine), **When** the sweep proceeds, **Then** the artifact records `network_paths.<cohort> = { error: <reason>, probe_method, probed_at_utc }` and the sweep is NOT aborted — the cohort comparison still runs and other cohorts' traces still populate.
6. **Given** a sweep produces a `network_paths` block, **When** the artifact is consumed by an M6.1.1-aware (pre-M6.1.2) reader, **Then** the unknown top-level key is ignored without parse error (strict-superset schema evolution, mirroring M6.0a's `dispatch_mode` precedent).

---

### User Story 2 - Reintroduce the `rest_plain_tcp` Cohort So Protocol Cost Is Separable From Multi-Cloud Routing Cost (Priority: P2)

A benchmark reader comparing gRPC vs REST in M6.x output needs to attribute the observed latency gap to *either* protocol cost (HTTP/1.1+REST vs HTTP/2+gRPC) *or* multi-cloud routing cost (Azure entry vs AWS entry) — not both lumped together. M5.2 had a 4-cohort split (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`) that gave readers this separability via the spike-confirmed property that `rest_plain_tcp` and the gRPC cohorts share a path (same CSP / region / `*.modal.host` entry), differing only in protocol. M6 / M6.1 / M6.1.1 dropped `rest_plain_tcp` during a simplification to a 3-cohort matrix and lost that separability. M6.1.2 restores it.

**Why this priority**: This is the most spec-decision-heavy addition in M6.1.2 (cohort-set evolution touches the sweep iterator, the per-cell schema, reporter table widths, cell-key conventions, and likely `phase_1_runs[]` shape) but it's a restoration of pattern M5.2 already validated. It's not P1 because it's downstream of Story 1's `network_paths` infrastructure — without the topology probe to *confirm* per sweep that `rest_plain_tcp` and `default_grpc` actually share a path, the structural argument for re-adding the cohort is weaker. With Story 1 already wiring topology into the artifact, Story 2 lands cleanly.

**Independent Test**: Can be fully tested by running an M6.1.2 sweep at the new 4-cohort matrix (`rest_https_edge` + `rest_plain_tcp` + `default_grpc` + `tuned_grpc_multiplexed`) at n=50 against the validation cell set, confirming the sweep completes, all four cohorts produce data for every cell where they apply (the existing tuned-pair / collapsed-tuned exclusivity rule at `c=1` is preserved from M5.2), and the artifact's per-cell rows contain the new cohort alongside the inherited three. A reader can compute `rest_plain_tcp` vs `default_grpc` per cell to see the protocol-only cost differential cleanly separated from the Azure-vs-AWS routing differential.

**Acceptance Scenarios**:

1. **Given** an operator launches an M6.1.2 sweep, **When** the sweep iterates cohorts for each cell at `c ≥ 2`, **Then** all four cohorts (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`) execute and report per-cell measurements.
2. **Given** the same sweep at `c=1`, **When** the cohort iterator applies the existing tuned-pair exclusivity rule (inherited from M5.2 — `default_grpc` and `tuned_grpc_multiplexed` collapse to a single gRPC cohort at `c=1` because channel-tuning has no effect at singleton concurrency), **Then** the cell still produces the appropriate 3-cohort row at `c=1` while `c=4` / `c=8` cells produce 4-cohort rows.
3. **Given** the new `rest_plain_tcp` cohort, **When** the M6.0a-corrected concurrent dispatch is applied, **Then** at `c ≥ 2` the cohort issues up to `c` RPCs concurrently to its endpoint (identical dispatch shape to the inherited cohorts).
4. **Given** the new `rest_plain_tcp` cohort, **When** the M6.1.1 classifier instrumentation runs (the segment-decomposition + `engine_cost_drift_warning` machinery already in place), **Then** the classifier produces per-cohort segments for `rest_plain_tcp` just as it does for the other cohorts — no special-casing.
5. **Given** the artifact JSON, **When** a reader extracts the `rest_plain_tcp` row from a chat_stream cell, **Then** the reader can directly subtract / compare against the `default_grpc` row to compute pure protocol cost (same CSP / region / path; only protocol changes), and against the `rest_https_edge` row to compute multi-cloud routing cost.
6. **Given** a sweep where one milestone (current or future) elects to use a subset of the 4 cohorts (e.g., M6.2 may restrict to chat_stream-relevant cohorts for budget reasons), **When** the artifact is produced, **Then** the artifact's metadata explicitly records which cohorts were intentionally omitted and why, so a reader can distinguish "cohort omitted by design" from "cohort failed at runtime".

---

### User Story 3 - Timestamp Progress Lines on Stderr So Long-Running Sweeps Are Diagnosable (Priority: P3)

An operator running a multi-hour sweep (M6.1.3's 5-run multi-sweep at ~$1.45 each, M6.2's `max_tokens` axis sweep, M7's corpus sweep) needs the stderr progress reporter to emit an ISO-8601 UTC timestamp on every progress line, so that when a sweep stalls or terminates unexpectedly the operator can reconstruct what happened from the log without correlating against a separate clock. The user-visible format is `[2026-05-17T12:34:56Z] [1/18] embed × c=1 / rest_https_edge — 50/50 succ — 29786 ms — ETA 75m`. This matches the run-id timestamp convention used elsewhere in the harness.

**Why this priority**: This is already implemented on `spike/m6-1-roadmap-additions` at commit `3763687`. The M6.1.2 deliverable here is purely a re-homing: the code carries forward verbatim, the spec confirms it's part of M6.1.2's bundle, and PLAN.md prose updates to reflect the new home. Lowest implementation risk in the bundle, smallest test surface, but also the least new behavioural surface. P3 reflects the small marginal value of restating an already-done change.

**Independent Test**: Can be fully tested by running any M6.1.2 sweep and confirming each stderr line begins with `[YYYY-MM-DDTHH:MM:SSZ]` — exact ISO-8601 UTC with `Z` suffix and second precision. The timestamp reflects wall-clock at emission time, not at sweep start.

**Acceptance Scenarios**:

1. **Given** any M6.1.2-or-later sweep, **When** the progress reporter emits a stderr line, **Then** the line begins with an ISO-8601 UTC timestamp matching the regex `^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]`.
2. **Given** the progress reporter emits multiple lines during a single cell's execution, **When** the operator inspects the log, **Then** each line's timestamp reflects the wall-clock at the moment that specific line was written (not the sweep start, not the cell start).
3. **Given** a sweep that runs across a UTC midnight boundary, **When** progress lines are emitted before and after midnight, **Then** the date portion of the timestamp advances correctly.
4. **Given** a non-progress stderr emission from the harness (e.g., a warning, an exception traceback), **When** the operator reads the log, **Then** the timestamping convention applied is whatever the harness's existing logging path chose — the M6.1.2 deliverable scope is the *progress-reporter* lines specifically, not a global logging-format change.

---

### Edge Cases

- **What happens if `tcptraceroute` is not installed on the operator's machine?** The probe records `network_paths.<cohort> = { error: "tcptraceroute_unavailable", probe_method, probed_at_utc }` for every cohort and the sweep continues. A loud stderr line surfaces the missing binary at sweep start so the operator can install it for the next run. The sweep is not aborted because the topology probe is methodology-supporting, not measurement-critical.
- **What if the operator's local network blocks outbound TCP-SYN to the cohort endpoints (corporate firewall, VPN, etc.)?** The probe times out per cohort, the `network_paths` block records the timeout, the sweep continues. Operators in firewalled environments get a sweep artifact without topology evidence — strictly weaker than running from an unrestricted host, but the cohort-comparison data itself is unaffected.
- **What if Modal changes its tunnel architecture mid-deploy (unlikely but possible during a long sweep)?** The probe runs once at sweep start; if Modal rolls a tunnel mid-sweep, the recorded `network_paths` reflects the pre-roll state. The sweep would also likely fail with connection errors at the cohort level (recorded in the existing per-cell error fields). Re-probing mid-sweep is out of scope for M6.1.2.
- **What if the `rest_plain_tcp` cohort fails to reach Modal at all (the spike confirmed `r439.modal.host:43209` is reachable for the deploy that produced the spike data, but new deploys could behave differently)?** The cohort records its per-RPC failure rows, the artifact captures the failure count, and the per-cell row indicates the cohort is unhealthy. The other three cohorts still produce data. The validation sweep at n=50 (see Success Criteria) is the gate that confirms `rest_plain_tcp` works against the M6.1.2-era deploy before downstream milestones inherit it.
- **What if a cohort-set evolution after M6.1.2 (e.g., M6.2 elects to drop a cohort, or M8 adds a model-specific cohort) means the 4-cohort set isn't preserved unchanged through M7 / M8?** The artifact's metadata must explicitly enumerate the cohorts present in *this* sweep and document any intentional omission with a one-line reason; readers consult the metadata, not a hard-coded cohort list. M6.1.2 establishes the default; downstream milestones may diverge but must document.
- **What if the timestamp prefix on progress lines collides with downstream tooling that parses stderr by line prefix (e.g., a CI log forwarder that strips ANSI codes)?** The timestamp is unconditional ASCII, no escape codes. Anything that parses stderr-prefix-aware should be updated to expect the timestamp; the M6.1.2 spec does not promise backward compatibility with parsers that assumed the prior un-prefixed format.
- **What if Story 1's probe runs but produces hops that none of the CSP IP-range lookups recognize (e.g., a transit ASN like Telia or Cogent)?** The cohort entry's `hops` list captures the IP + reverse-DNS as the probe observed it, the `cloud_provider` field for that hop reads "unknown" or the resolved ASN if available, and the cohort-level `cloud_provider` reflects the endpoint-IP lookup result (the most authoritative single attribution). No probe-side assertion fails on unknown ASNs.

## Requirements *(mandatory)*

### Functional Requirements

#### Per-sweep traceroute probe (item #1)

- **FR-001**: The M6.1.2 sweep MUST run a `tcptraceroute`-based topology probe against each cohort's endpoint exactly once per sweep, before the first measurement cell executes. The probe MUST NOT run per cell.
- **FR-002**: The probe MUST be TCP-SYN-based (not UDP, not ICMP) so that hops past the AWS / Azure edge ICMP firewall (≈hop 5) are captured. The spike's live data confirmed UDP/ICMP `traceroute` dies at hop 5; `tcptraceroute` reaches further into the cloud network.
- **FR-003**: The probe MUST write its results into a top-level `network_paths` block on the sweep artifact JSON, keyed by cohort name, with each cohort's value containing at minimum: `endpoint_ip` (the resolved IP at probe time), `hops` (ordered list with at least `{ hop_number, ip, rtt_ms_or_null }` per hop), `cloud_provider` (string, derived from the endpoint IP against AWS/Azure/GCP published IP-range files + ARIN whois fallback for transit), `region` (string where derivable, otherwise null), `probe_method` (string, e.g., `"tcptraceroute"`), and `probed_at_utc` (ISO-8601 UTC timestamp).
- **FR-004**: The `network_paths` block addition MUST be a **strict-superset** schema evolution — no schema-version bump, no breaking change. Pre-M6.1.2 readers (including the M6.1.1 reporter and the M6.2 consumer) MUST ignore the unknown top-level key without parse error.
- **FR-005**: If the probe fails for one cohort (binary missing, network blocked, endpoint unreachable, timeout), the harness MUST record `network_paths.<cohort> = { error: <reason>, probe_method, probed_at_utc }` and continue the sweep — the probe is methodology-supporting, not measurement-critical.
- **FR-006**: If the probe observes a cohort entering a DIFFERENT cloud provider than the spike-confirmed expectation (`rest_https_edge` → Azure; `*.modal.host` cohorts → AWS), the harness MUST emit a loud stderr line at sweep start ("WARNING: cohort X entered <CSP> rather than expected <CSP>; topology has changed"), so methodology-disrupting Modal architecture changes are surfaced rather than silently absorbed. The sweep proceeds; the artifact records the observed reality unchanged.
- **FR-007**: The probe MUST attribute the endpoint IP to a cloud provider via the AWS / Azure / GCP published IP-range files (refreshed at probe time or cached with a documented staleness budget; staleness handling is an implementation detail not a spec constraint). Transit ASNs (Telia / Cogent / etc.) MAY be annotated via ARIN whois fallback or recorded as `"unknown"` when not resolved.
- **FR-008**: `ANALYSIS.md` MUST be updated to cite the multi-CSP finding from spike #1, replacing the looser "different network path" language. The exact phrasing should match the spike's "cohorts enter Modal via entirely different cloud providers" framing.
- **FR-009**: `contracts/instrumentation.md` (or the equivalent canonical schema doc) MUST be updated to document the `network_paths` block as part of the M6.1.2-forward artifact schema, including the required keys per cohort and the error-case structure.

#### Reintroduce `rest_plain_tcp` cohort (item #2)

- **FR-010**: The M6.1.2 sweep MUST execute four cohorts when concurrency `c ≥ 2`: `rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`. The `rest_plain_tcp` cohort is the one being reintroduced; the other three are inherited from M6 / M6.1 / M6.1.1.
- **FR-011**: At `c = 1`, the sweep MUST apply the existing tuned-pair exclusivity rule inherited from M5.2 — `default_grpc` and `tuned_grpc_multiplexed` collapse to a single gRPC cohort because channel-tuning has no observable effect at singleton concurrency. The resulting `c = 1` row contains three cohorts (`rest_https_edge`, `rest_plain_tcp`, single gRPC); `c ≥ 2` rows contain four.
- **FR-012**: The reintroduced `rest_plain_tcp` cohort MUST use the M6.0a-corrected concurrent dispatch pattern (concurrent in-flight up to `c` RPCs at the cell's concurrency level) — symmetric with the other cohorts. No special-case sequential dispatch for the reintroduced cohort.
- **FR-013**: The reintroduced `rest_plain_tcp` cohort MUST participate in the M6.1.1-expansion classifier instrumentation (segment decomposition, `engine_cost_drift_warning` machinery) on the same terms as the other cohorts. The classifier produces per-cohort segments for `rest_plain_tcp` with no per-cohort special-casing.
- **FR-014**: The per-cell artifact row MUST include the `rest_plain_tcp` cohort's measurements alongside the inherited cohorts' rows, in the same schema shape (no nested re-organisation, no fork in the per-cell row structure).
- **FR-015**: The reintroduced cohort's endpoint MUST be sourced from the Modal deploy's existing `rest_plain_tcp_url` (the `modal.forward(_REST_PORT, unencrypted=True)` exposure in `scripts/python/modal_bench_rest_grpc_server.py` per the spike's code-surface enumeration — no Modal-side endpoint change required). Verification that the existing wiring still functions is part of the validation sweep (see SC-002).
- **FR-016**: The sweep artifact's metadata MUST explicitly enumerate the cohorts present in that sweep, so that a downstream milestone electing to omit a cohort can record the omission with a one-line reason and a reader can distinguish "cohort omitted by design" from "cohort failed at runtime".
- **FR-017**: M6.1.2 MUST NOT modify the `default_grpc` or `tuned_grpc_multiplexed` cohort definitions, their endpoint resolution, their classifier participation, or their per-cell row shape. The change is additive (one cohort restored), not a re-shape of the existing three.

#### Timestamped progress lines (item #3)

- **FR-018**: The M6 / M6.1 / M6.1.1 progress reporter (which M6.1.2 inherits) MUST emit each stderr line with a leading ISO-8601 UTC timestamp prefix in the form `[YYYY-MM-DDTHH:MM:SSZ]`, where the timestamp reflects the wall-clock at the moment the line is emitted.
- **FR-019**: The timestamp prefix MUST use second precision (no fractional seconds) and the literal `Z` suffix indicating UTC, matching the existing run-id timestamp convention.
- **FR-020**: Non-progress stderr emissions (warnings, exception tracebacks, unrelated harness logging) MUST continue to use whatever format the harness's existing logging path applies — M6.1.2's deliverable is scoped to the progress reporter, not a global logging-format change.
- **FR-021**: The progress-line timestamp implementation MUST carry forward verbatim from the spike branch's commit `3763687` to the M6.1.2 branch — no behavioural change between the spike's working implementation and the milestone's published implementation.

#### Cross-cutting

- **FR-022**: M6.1.2 MUST NOT modify engine-cost code, the prompt-embeds engine path, the M6.1.1-expansion classifier's decision rules, the M6.0a-corrected dispatch mechanics, or any Modal-endpoint code. The bundle is harness + artifact-schema + reporter + ANALYSIS.md prose only.
- **FR-023**: M6.1.2 MUST NOT modify the published verdict tables for M6's main finding, M6.1's main finding, M6.1.1's classifier output, or any prior-milestone artifact body. Cross-references to M6.1.2 from prior artifacts are out of scope (they can be added later if reviewers find them useful).
- **FR-024**: M6.1.2 MUST run a validation sweep at `n = 50` against the new 4-cohort matrix + `network_paths` probe, to confirm the cohort is reachable, the probe captures cleanly, the artifact JSON parses, and the timestamped progress lines emit correctly. Modal compute budget for the validation sweep: ~$0.30, capped at ~$0.50.
- **FR-025**: M6.1.2's `network_paths` block, 4-cohort split, and timestamped progress lines MUST be inherited by M6.1.3, M6.2, M7, and M8 sweeps as the new convention — the artifact schema, cohort iterator, and stderr emitter changes are *the* shared infrastructure those milestones build on. A downstream milestone may diverge from the convention (e.g., omit a cohort) only if it explicitly documents the divergence in its own spec and in the artifact metadata (per FR-016).

### Key Entities *(include if feature involves data)*

- **`network_paths` Block**: a top-level object on the sweep artifact JSON keyed by cohort name. Each cohort entry contains `endpoint_ip`, ordered `hops` with per-hop IP + RTT, `cloud_provider`, `region`, `probe_method`, `probed_at_utc`. Or, on probe failure, `{ error, probe_method, probed_at_utc }`. Strict-superset addition to the M6.1.1 artifact schema.
- **TCP-SYN Topology Probe**: a per-sweep, one-shot probe using `tcptraceroute` (or an equivalent TCP-SYN-based tool) against each cohort endpoint. Captures hop traces past the AWS / Azure edge ICMP firewall. Runs at sweep start, before the first measurement cell. Output feeds the `network_paths` block.
- **Cohort Set (Post-M6.1.2)**: the canonical 4-cohort split (`rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`) at `c ≥ 2`; collapsed to 3 at `c = 1` via the inherited tuned-pair exclusivity rule. Replaces the M6 / M6.1 / M6.1.1 3-cohort matrix. Inherited unchanged by M6.1.3 / M6.2 / M7 / M8 unless a downstream milestone documents a divergence.
- **`rest_plain_tcp` Cohort**: the M5.2-era cohort that issues HTTP/1.1 + REST over plain TCP via Modal's `*.modal.host` tunnel. Shares CSP / region / entry path with the gRPC cohorts; differs only in protocol. Restored by M6.1.2 so cohort comparisons can isolate pure protocol cost from multi-cloud routing cost.
- **Timestamped Progress Line**: a stderr line emitted by the M6 / M6.1 / M6.1.1 progress reporter, prefixed with `[YYYY-MM-DDTHH:MM:SSZ]` (ISO-8601 UTC, second precision, `Z` suffix). Format: `[<timestamp>] [<cell_index>/<total>] <cell_descriptor> — <succ>/<total_n> succ — <wall_ms> ms — ETA <minutes>m`.
- **Validation Sweep**: the M6.1.2 confidence-building sweep at n=50, 4-cohort, with the topology probe enabled. Confirms (a) `rest_plain_tcp` reaches Modal, (b) the probe captures cleanly per cohort, (c) the artifact JSON parses with the new `network_paths` block, (d) timestamped progress lines emit. Modal cost ~$0.30, capped at ~$0.50.
- **Sweep Artifact Metadata**: existing artifact metadata extended to explicitly enumerate the cohort set present in the sweep, with an optional per-omitted-cohort reason string. Lets a future milestone (M6.2, M7, M8) deviate from the 4-cohort default with explicit documentation, distinguishable by a reader from runtime cohort failure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The M6.1.2 validation sweep at n=50, 4-cohort, with `network_paths` probe enabled completes in 35 minutes or less of wall-clock time on Modal A10G eu-west-1 (matching M6.1.1's per-sweep profile within Modal cold-start variance).
- **SC-002**: The validation sweep produces an artifact JSON containing a non-empty `network_paths` block with one entry per cohort (4 entries at `c ≥ 2` cells, 3 at `c = 1`), and the `rest_plain_tcp` cohort entry's `cloud_provider` resolves to "AWS" with region "us-west-1" (or equivalent) for any deploy that conforms to the spike-confirmed topology pattern.
- **SC-003**: The validation sweep produces per-cell rows for all 4 cohorts at `c ≥ 2` (3 at `c = 1` per the tuned-pair collapse rule), with the `rest_plain_tcp` cohort participating in the classifier's segment decomposition on the same terms as the other cohorts.
- **SC-004**: A reader of the validation sweep's published markdown can compute `rest_plain_tcp` vs `default_grpc` per chat_stream cell in a single subtraction to obtain the protocol-only cost differential (same CSP / region / path; protocol-only delta) — and `rest_plain_tcp` vs `rest_https_edge` to obtain the multi-cloud routing differential.
- **SC-005**: Every stderr line emitted by the progress reporter during the validation sweep begins with an ISO-8601 UTC timestamp prefix matching the regex `^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\]`, with the timestamp reflecting wall-clock at emission.
- **SC-006**: An M6.1.1-aware (pre-M6.1.2) reader / consumer parses the M6.1.2 validation sweep artifact JSON without parse error, silently ignoring the unknown `network_paths` top-level key (strict-superset schema confirmation).
- **SC-007**: `ANALYSIS.md` is updated to cite the multi-CSP finding (replacing the "different network path" language), and `contracts/instrumentation.md` (or equivalent) is updated to document the `network_paths` block. Both updates are landed in the same PR as the code change, not deferred.
- **SC-008**: Total Modal compute spend for M6.1.2's validation sweep is ~$0.30 (cap $0.50 — half the M6.1.1 single-sweep budget). No multi-run sweep required for this milestone.
- **SC-009**: A future M6.1.3 / M6.2 / M7 / M8 operator inheriting the M6.1.2 conventions (4-cohort split, `network_paths` capture, timestamped progress lines) needs zero additional configuration — the conventions are the harness defaults, not opt-in flags.
- **SC-010**: A reader unfamiliar with M6.x can determine in under 5 minutes (by reading the validation sweep's markdown + the updated `contracts/instrumentation.md`) which cohort routes through which cloud provider, which cohorts share a path, and which two-cohort subtraction isolates which variable (protocol vs CSP-routing).

## Assumptions

- The spike-confirmed topology pattern (Azure for `*.modal.run`, AWS us-west-1 for `*.modal.host`) is stable for Modal's near-term deploys. If Modal changes architecture, FR-006's loud-stderr surfacing is the mechanism that flags it; the artifact still records reality faithfully.
- `tcptraceroute` (or an equivalent TCP-SYN-based traceroute tool) is available on the operator's machine, or the operator accepts that probe failure will record an error block in `network_paths` without aborting the sweep. The validation sweep documented in SC-002 is presumed to run from an environment where the tool is installed.
- The reintroduced `rest_plain_tcp` cohort's M5.2-era wiring (`m5_2_sweep.py`, `m5_2_symmetry.py`, harness CLI, `rest_shim.py` plain-TCP path, the Modal-side `rest_plain_tcp_url`) is recoverable as-is or with minimal refactoring — the spike's code-surface enumeration confirms the pieces exist. Specific refactoring decisions are deferred to `/speckit-plan`.
- The M6.0a-corrected concurrent dispatch (FR-001 / FR-002 of M6.0a spec `024-m6-0a-concurrent-dispatch/spec.md`) applies uniformly to the reintroduced cohort; no per-cohort dispatch-mode special-casing.
- The M6.1.1-expansion classifier (the segment decomposition + `engine_cost_drift_warning` machinery) accommodates a fourth cohort without re-design; classifier degeneracy on chat_stream cells is the M6.1.1 issue being tracked separately and is not in M6.1.2's scope.
- The timestamped-progress-line implementation on `spike/m6-1-roadmap-additions` at commit `3763687` is the intended carry-forward target and does not need further behavioural change; M6.1.2 re-bundles it without modification.
- The `network_paths` block's strict-superset addition follows the same precedent as M6.0a's `dispatch_mode` top-level key — no schema-version bump, pre-existing readers ignore unknown keys silently.
- AWS / Azure / GCP IP-range lookups are sufficient to attribute the endpoint IP to a CSP for the spike-observed deploys. ARIN whois fallback for transit ASNs is best-effort, not load-bearing; transit hops that don't resolve cleanly are recorded as `"unknown"`.
- The validation sweep at n=50, 4-cohort, with the topology probe enabled does not exceed the M6.1.1 single-sweep wall-clock by more than ~15% (one extra cohort × per-cohort probe overhead). If wall-clock blows out, the spec re-opens via `/speckit-clarify`.
- M6.1.3 depends on M6.1.2's conventions being in place (the new cohort + traceroute infrastructure) and M6.2 depends on M6.1.3's resolved verdicts — the milestone ordering in PLAN.md is presumed unchanged.
- The M6.0a precedent for verbatim preservation of prior-milestone audit artifacts applies — no edits to M6 / M6.1 / M6.1.1 published bodies; cross-references to M6.1.2 from those prior artifacts are out of scope for this milestone (deferrable to a later editing pass).
