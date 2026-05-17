# Phase 0 Research: M6.1.2 — Methodology Discipline

**Branch**: `025-m6-1-2-methodology-discipline` | **Date**: 2026-05-17 | **Plan**: [plan.md](./plan.md)

## Overview

Phase 0 captures the implementation-level research that complements the spec-level decisions made during the 3-round `/speckit-clarify` cycle (13 Q/A bullets total). The Technical Context in [`plan.md`](./plan.md) has no `NEEDS CLARIFICATION` markers — every architecturally-significant choice was resolved during clarify. Phase 0 here documents the code-surface investigation needed to write the data model and contracts cleanly.

## Research Items

### R-1 — M6.1.1 module file set + naming convention

**Decision**: M6.1.2 mirrors M6.1.1's module naming convention. Files: `m6_1_2_types.py`, `m6_1_2_sweep.py`, `m6_1_2_reporter.py`, `m6_1_2_validate.py`, `m6_1_2_network_probe.py`. Each follows the `m6_1_2_<role>.py` pattern.

**Rationale**: M6.1.1 has 11 named module files (`m6_1_1_sweep.py`, `m6_1_1_reporter.py`, `m6_1_1_types.py`, `m6_1_1_diagnose.py`, `m6_1_1_phase2.py`, `m6_1_1_perturbation.py`, `m6_1_1_classifier.py`, `m6_1_1_timing.py`, `m6_1_1_contracts_check.py`, `m6_1_1_embed_regression.py`, `m6_1_1_supersedence.py`); the "one module per concern" pattern is the convention. M6.1.2 has fewer concerns (the bundle is methodology-discipline, not a classifier expansion), so 5 named files suffice.

**Alternatives considered**:
- Bundle all M6.1.2 logic into a single `m6_1_2.py` — rejected; breaks the convention readers rely on for navigation.
- Reuse M6.1.1's modules by adding M6.1.2 branches — rejected; violates FR-028 (M6.1.1 historical re-run capability must stay frozen).

### R-2 — Cell matrix reuse vs redefinition

**Decision**: REUSE `M6_1_CELLS` from `m6_1_types.py:72-82` rather than redefining `M6_1_2_CELLS`. M6.1.2's sweep iterates the existing 6-cell tuple; the cell shape (`embed × {c=1, c=4, c=8}`, `chat_stream × {c=1, c=4, c=8}`) is unchanged from M6.1.

**Rationale**: The smoke-equivalent validation sweep is explicitly defined as "the full M6.1.1 6-cell matrix" (FR-024 + round-1 Q4). Redefining the constant tuple would create drift risk (a future edit to `M6_1_CELLS` for M6.2 wouldn't automatically propagate to M6.1.2). Reusing the existing constant is the minimum-coupling choice.

**Alternatives considered**:
- Define `M6_1_2_CELLS = M6_1_CELLS` (re-export) — adds a name without value; same reuse, more indirection.
- Define a freshly-parameterized `M6_1_2_CELLS` tuple — diverges if `M6_1_CELLS` ever changes; rejected.

### R-3 — Cohort iteration delta

**Decision**: Define `M6_1_2_COHORTS = ("rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed")` as a new 4-element tuple in `m6_1_2_types.py`. M6.1.2's sweep iterates this tuple instead of M6.1.1's `M6_1_COHORTS` (3-element). M6.1.1's `M6_1_COHORTS` stays frozen per FR-028.

**Rationale**: The cohort set IS the structural delta between M6.1.1 and M6.1.2 — restoring `rest_plain_tcp` is Story 2's whole point. A 4-element constant is the cleanest representation. At `c=1`, the M5.2-derived tuned-pair-collapse-at-c=1 rule (`m5_2_sweep.py:228-237`) applies — `default_grpc` and `tuned_grpc_multiplexed` collapse to a single gRPC cohort, yielding a 3-element runtime set. The plan-level approach is to handle this in `m6_1_2_sweep.py` (the sweep orchestrator collapses at iteration time), not in the constant itself.

**Alternatives considered**:
- Define `M6_1_2_COHORTS` as a function `cohorts_for_concurrency(c)` returning either 3 or 4 elements — rejected; const-tuple is the existing convention (`M6_1_COHORTS` at `m6_1_types.py:84-88` is a const).
- Subclass / extend `M6_1_COHORTS` — Python tuples don't subclass cleanly; rejected.

### R-4 — `rest_plain_tcp` cohort surviving wiring

**Decision**: Reuse M5.2's `rest_plain_tcp` wiring as-is. Add a single new dispatch case in `m6_1_rpc_driver.py` (lines 305-345) that mirrors `rest_https_edge`'s `httpx.AsyncClient` shape but points at `rest_plain_tcp_url` from the Modal handshake dict.

**Rationale**: Spike #2's code-surface enumeration + the Phase 0 Explore agent's confirmation produced ground truth:
- `m5_2_sweep.py:241-246` still defines `M5_2CellMeasurement.rest_plain_tcp: RESTCohortResult`.
- `rest_cohort.py` (22 KB) and `rest_shim.py` (24 KB) compile cleanly with no bit-rot.
- `scripts/python/modal_bench_rest_grpc_server.py:188-194` still spawns the `modal.forward(_REST_PORT, unencrypted=True)` plain-TCP tunnel.
- `:208` exports `await d.put.aio("rest_plain_tcp_url", rest_plain_tcp_endpoint)` to the handshake dict.
- The ONLY gap: `m6_1_rpc_driver.py:305-345` has dispatch paths for 3 cohorts only.

Adding the 4th cohort case is ~30-50 LOC and reuses every supporting layer. No Modal-side changes required.

**Alternatives considered**:
- Resurrect M5.2's full `m5_2_sweep.py` cohort iterator for M6.1.2 — rejected; that file contains M5.2-specific logic (symmetry, supersedence-vs-M5.1) that's not relevant to M6.1.2's purpose. Per-cohort dispatch is the only piece we need.
- Re-wire the Modal endpoint to expose a SINGLE REST endpoint with a header-based routing flag — rejected; Modal-side change violates FR-022 ("no Modal-endpoint code").

### R-5 — `tcptraceroute` invocation pattern

**Decision**: Port the spike's `docs/spikes/m6-1-roadmap-additions/traceroute_probe.py` invocation pattern (lines 72-90) but swap the binary from `traceroute` to `tcptraceroute` with a port argument. Concrete shape:

```python
cmd = [
    "tcptraceroute",
    "-n",                        # numeric output (no DNS for hops)
    "-w", "2",                   # 2-second per-hop timeout (matches spike's TRACE_PER_HOP_TIMEOUT_S)
    "-q", "1",                   # 1 probe per hop (matches spike's TRACE_PROBES_PER_HOP)
    "-m", "18",                  # max 18 hops (matches spike's TRACE_HOPS_MAX)
    host,                        # cohort endpoint hostname
    str(port),                   # cohort endpoint port — the TCP-SYN target
]
proc = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    timeout=30,                  # FR-002a per-cohort timeout
    check=False,                 # don't raise on non-zero exit; parse failure separately
)
```

**Rationale**:
- The spike used `traceroute` (UDP/ICMP) and explicitly noted in its TL;DR that UDP/ICMP dies at the AWS/Azure ICMP firewall around hop 5; the spike recommended `tcptraceroute` (TCP-SYN) for reach past the edge. FR-002 mandates `tcptraceroute` specifically.
- The flag set (`-n -w 2 -q 1 -m 18`) is compatible across the macOS Homebrew and Linux `tcptraceroute` packages (Michael Toren's tool). Both packages accept these flags identically.
- `tcptraceroute` requires a port argument (the SYN target); ports come from parsing the cohort URLs (the spike's `_parse_url()` at lines 50-67 handles `tcp+plaintext://host:port`, `http://host:port`, `https://host[:443]`).
- 30s timeout per FR-002a maps to the `subprocess.run(timeout=...)` parameter — `subprocess.TimeoutExpired` is caught and converted to `{ error: "probe_timeout", ... }` per FR-002a.

**Alternatives considered**:
- Use `traceroute -T` (the GNU traceroute with TCP mode) — rejected per round-2 Q3 ("Mandate `tcptraceroute` specifically; no cross-platform fallbacks").
- Auto-install `tcptraceroute` via `brew` / `apt` if absent — rejected per round-2 Q3 (Option C).
- Capture per-hop with a Python raw-socket implementation — rejected; major implementation overhead (root/cap_net_raw privilege requirements, cross-platform divergence) for no clear gain over the established system binary.

### R-6 — CSP IP-range attribution

**Decision**: Net-new logic in `m6_1_2_network_probe.py`. Fetch AWS / Azure / GCP public IP-range JSON files at probe time (with a 24-hour cache TTL at `~/.cache/vllm-grpc/ip-ranges/`); attribute each IP by linear search against the parsed prefix list; for IPs not matching any of the three, fall back to ARIN whois (best-effort, single attempt, no retry loop). Resolution → `cloud_provider` enum string (`"AWS"`, `"Microsoft Azure"`, `"GCP"`) or transit-ASN string (`"Telia"`, `"Cogent"`, etc., per whois) or `"unknown"`.

**Rationale**:
- Explore confirmed zero existing project utility for CSP attribution — this is genuinely net-new.
- Public IP-range files are the authoritative source: AWS publishes [`ip-ranges.json`](https://ip-ranges.amazonaws.com/ip-ranges.json) with daily SLAs; Azure publishes [its JSON](https://www.microsoft.com/en-us/download/details.aspx?id=56519) monthly; GCP publishes [`cloud.json`](https://www.gstatic.com/ipranges/cloud.json). Linear search per IP is fine — each file is ~5K-10K prefixes; 5-10K prefix × 4 cohorts × ~10 hops per cohort = ~200K-400K compare ops, well under 1s on a modern machine.
- 24-hour cache TTL balances staleness vs network-fetch cost. The cache miss path is straightforward (`urllib.request.urlopen` → write to disk). FR-007 explicitly says "staleness handling is an implementation detail not a spec constraint" — 24h is a sensible default; M6.2 / M7 may revisit.
- ARIN whois is rate-limited and brittle — round-3 Q1 deliberately scoped per-hop annotation as best-effort with no retry. Single-attempt whois with a short timeout (e.g., 5s) is the cleanest match.
- Per-hop `cloud_provider: null` (or absent) when the IP doesn't match any range AND whois fails. This is the spike-observed Telia transit case → without whois ASN labelling, the hop is recorded as `null`.

**Alternatives considered**:
- Use `maxminddb` (MaxMind GeoIP) — rejected; license is restrictive, requires a paid subscription for the up-to-date dataset, and overkill for CSP attribution (MaxMind is geo + ASN; we only need CSP enum).
- Embed pre-fetched IP-range files in the repository — rejected; staleness handling becomes a release-cadence problem (file updates require new commits) AND the repo bloats.
- Skip per-hop attribution entirely (cohort-level only) — rejected per round-3 Q1 (Option B was accepted: best-effort per-hop annotation).

### R-7 — `_stderr_ts()` helper carry-forward from spike commit 3763687

**Decision**: Apply the spike branch's commit `3763687` verbatim to the M6.1.2 branch — the 5-file change set (`m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py`, `test_m6_quickstart_format.py`, `docs/spikes/m6-1-roadmap-additions/traceroute_probe.py`) plus a parallel addition in the new `m6_1_2_sweep.py`. The `_stderr_ts()` helper signature is:

```python
def _stderr_ts() -> str:
    """ISO-8601 UTC bracket prefix [YYYY-MM-DDTHH:MM:SSZ]."""
    return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")
```

Each `print(..., file=sys.stderr, flush=True)` call gets `_stderr_ts() + " " + ...` prefixed. M6.1.2's new warning emitters (FR-005a, FR-006) in `m6_1_2_network_probe.py` use the same helper per FR-020 (round-2 Q5).

**Rationale**: Round-1 Q5 acknowledged this code is already implemented on the spike branch and just needs to carry forward. The spike's pattern uses two different import shapes (`m6_sweep.py` / `m6_1_sweep.py` use the legacy `import datetime as _datetime`; `m6_1_1_sweep.py` uses the modern `from datetime import UTC, datetime`) — M6.1.2's new files will use the modern shape (`from datetime import UTC, datetime`) consistent with `m6_1_1_sweep.py` to avoid re-establishing the legacy convention.

**Alternatives considered**:
- Centralize `_stderr_ts()` in a shared `m6_progress.py` module — rejected for this milestone; would require touching all 4 inheriting modules (`m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py`, and the new `m6_1_2_sweep.py`) for a refactor unrelated to M6.1.2's stated scope. M6.2 may consolidate.
- Use the `logging` module instead of print-to-stderr — rejected; the project's `feedback_local_lint_chain` memory + M6.1.1's existing pattern uses `print(..., file=sys.stderr, flush=True)`; switching would create a divergent emission path.

### R-8 — Warmup ordering vs probe

**Decision**: The topology probe runs BEFORE warmup, not after. `m6_1_2_sweep.py`'s top-level orchestration is: (1) Modal deploy + handshake, (2) topology probe across cohorts (parallel, 30s timeout each), (3) warmup per cell per cohort, (4) measurement per cell per cohort, (5) artifact write.

**Rationale**: FR-001 says "before the first measurement cell executes (and before warmup)." The probe is a one-shot per sweep (FR-001), the network paths are stable for the duration of a deploy, and warmup itself does RPC work that should be timestamped against the probe-recorded paths. Running the probe AFTER warmup would introduce a small window where warmup RPCs traverse paths the artifact doesn't yet describe — methodologically weaker.

**Alternatives considered**:
- Probe in parallel with warmup (probe is async; warmup starts as soon as the handshake yields) — rejected; the small wall-clock saving (~30s shaved off sweep start) isn't worth the methodology-evidence weakening.
- Probe AFTER warmup — rejected per FR-001 explicit ordering.

## Cross-references

- Spec: [`spec.md`](./spec.md) — the 32-FR + 10-SC contract this research informs.
- Spike notes: [`docs/spikes/m6-1-roadmap-additions/`](../../docs/spikes/m6-1-roadmap-additions/) — items #1, #2, #3 are M6.1.2; items #4, #5, #6 are M6.1.3.
- M6.1.1 precedent: [`specs/023-m6-1-1-engine-cost-instrumentation/plan.md`](../023-m6-1-1-engine-cost-instrumentation/plan.md) — the structural template M6.1.2 mirrors.
- M6.0a precedent for strict-superset JSON evolution: [`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`](../024-m6-0a-concurrent-dispatch/contracts/output.md).
- Spike traceroute probe: [`docs/spikes/m6-1-roadmap-additions/traceroute_probe.py`](../../docs/spikes/m6-1-roadmap-additions/traceroute_probe.py) — the working reference R-5 ports.
- Spike commit `3763687`: the timestamped-progress-line implementation R-7 carries forward.

## Output

All NEEDS CLARIFICATION items resolved. Plan's Technical Context has zero unresolved markers. Phase 0 complete; Phase 1 design proceeds against the decisions above.
