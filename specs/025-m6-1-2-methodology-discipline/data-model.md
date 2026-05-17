# Phase 1 Data Model: M6.1.2 — Methodology Discipline

**Branch**: `025-m6-1-2-methodology-discipline` | **Date**: 2026-05-17 | **Plan**: [plan.md](./plan.md)

## Overview

M6.1.2 adds three new top-level fields to the per-sweep artifact JSON (`network_paths`, `cohort_set`, `cohort_omissions`) and introduces five new Python module files under `tools/benchmark/src/vllm_grpc_bench/` that house the supporting dataclasses + functions. Every addition is a **strict-superset** schema evolution — pre-M6.1.2 readers (M6.1.1 reporter, M6.2 consumer) ignore the unknown top-level keys without parse error (FR-004 + FR-016 + SC-006).

This document captures the entity shapes. The JSON wire format is documented separately in [`contracts/network-paths.md`](./contracts/network-paths.md) and [`contracts/artifact-schema.md`](./contracts/artifact-schema.md); the CLI flag set is in [`contracts/cli.md`](./contracts/cli.md).

## Python Dataclasses (in `m6_1_2_types.py`)

### `M6_1_2CohortKind`

```python
M6_1_2CohortKind = Literal[
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
]

M6_1_2_COHORTS: tuple[M6_1_2CohortKind, ...] = (
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
)
```

**Relationship**: `M6_1_2_COHORTS` extends M6.1.1's `M6_1_COHORTS` (defined `m6_1_types.py:84-88`) by ONE element (`"rest_plain_tcp"` in position 2). M6.1.1's tuple stays frozen per FR-028.

**Tuned-pair-collapse-at-c=1 rule (FR-011)**: at `c == 1`, the sweep orchestrator (`m6_1_2_sweep.py`) iterates 3 cohorts — `default_grpc` and `tuned_grpc_multiplexed` collapse to a single gRPC cohort whose `cohort_kind` field is `"default_grpc"` (matches M5.2's `m5_2_sweep.py:228-237` precedent). At `c ≥ 2`, all 4 cohorts iterate. The cohort tuple itself is not modified at runtime; the iteration logic skips one element conditionally.

### `M6_1_2CloudProvider`

```python
M6_1_2CloudProvider = Literal[
    "AWS",
    "Microsoft Azure",
    "GCP",
    "unknown",
]
```

**Notes**:
- The four enum values are the only legal values for the cohort-level `network_paths.<cohort>.cloud_provider` field (per the Key Entities entry in [`spec.md`](./spec.md) + round-1 Q5 + round-3 Q1 + Story 1 AS#3).
- For PER-HOP annotations (`network_paths.<cohort>.hops[].cloud_provider`), the field can ADDITIONALLY hold transit-ASN strings (`"Telia"`, `"Cogent"`, etc.) per round-3 Q1 — the per-hop field is best-effort, so the value-space is not strictly closed. The cohort-level field's enum stays closed.

### `M6_1_2NetworkPathHop`

```python
@dataclass
class M6_1_2NetworkPathHop:
    hop_number: int
    ip: str | None              # None if hop was an asterisk (timeout)
    rtt_ms_or_null: float | None
    cloud_provider: str | None  # Best-effort; null when lookup doesn't resolve.
                                # Cohort-level enum + transit-ASN strings + null.
```

**Validation**:
- `hop_number` ≥ 1, monotonically increasing per cohort.
- `ip` is None when `tcptraceroute` reports an asterisk (filtered hop); otherwise a dotted-decimal IPv4 or colon-separated IPv6 string.
- `rtt_ms_or_null` is None when `ip` is None or when the probe couldn't measure RTT.
- `cloud_provider` is best-effort per FR-003 + round-3 Q1 — no retry / rate-limit handling. Allowed values: `"AWS"`, `"Microsoft Azure"`, `"GCP"`, `"unknown"`, or a transit-ASN string (e.g., `"Telia"`, `"Cogent"`), or null.

### `M6_1_2NetworkPath`

```python
@dataclass
class M6_1_2NetworkPath:
    endpoint_ip: str            # Resolved IP at probe time; non-empty.
    hops: list[M6_1_2NetworkPathHop]  # Ordered by hop_number ascending.
    cloud_provider: M6_1_2CloudProvider  # Cohort-level enum: "AWS" / "Microsoft Azure" / "GCP" / "unknown".
    region: str | None          # e.g., "us-west-1"; null when IP-range lookup doesn't yield a region.
    probe_method: Literal["tcptraceroute"]  # Per FR-002 / round-2 Q3 — literal "tcptraceroute" only.
    probed_at_utc: str          # ISO-8601 UTC with `Z` suffix, second precision (e.g., "2026-05-17T12:34:56Z").
```

**Validation**:
- `endpoint_ip` is required and non-empty when the probe succeeds.
- `hops` is non-empty when the probe reaches at least one hop; empty list is acceptable when ALL hops were asterisks (rare).
- `cloud_provider` is one of the 4 enum values; `"unknown"` is the fallback when neither IP-range lookup nor whois resolves the endpoint IP.
- `region` is null when `cloud_provider == "unknown"` or when the IP-range file's prefix entry doesn't carry a region (rare for AWS / Azure; common for GCP global services).
- `probe_method` is the literal string `"tcptraceroute"` per FR-002 + round-2 Q3.
- `probed_at_utc` matches the regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`.

### `M6_1_2NetworkPathError`

```python
@dataclass
class M6_1_2NetworkPathError:
    error: Literal[
        "tcptraceroute_unavailable",    # binary not on PATH (FR-005)
        "probe_timeout",                # 30s per-cohort timeout exceeded (FR-002a)
        "subprocess_error",             # tcptraceroute exited non-zero with parseable stderr
        "parse_error",                  # tcptraceroute output couldn't be parsed
    ]
    probe_method: Literal["tcptraceroute"]
    probed_at_utc: str
    detail: str | None  # Optional human-readable detail (e.g., the stderr line that surfaced)
```

**Relationship**: The artifact JSON's `network_paths.<cohort>` field is a discriminated union of `M6_1_2NetworkPath` (success) and `M6_1_2NetworkPathError` (failure) — the presence/absence of the `error` key is the discriminator. FR-005 records per-cohort failures; FR-005a fires the all-cohort-failed warning at sweep start.

### `M6_1_2CohortOmission` (lightweight type)

```python
# In the JSON: cohort_omissions is a dict[str, str] — cohort name → one-line reason.
# In Python, treat as a plain dict; no dataclass needed:
M6_1_2CohortOmissions = dict[M6_1_2CohortKind, str]
```

**Invariants** (enforced by `m6_1_2_reporter.py`'s pre-write validation):
- Every key in `cohort_omissions` is a valid `M6_1_2CohortKind` literal.
- The union of `cohort_set` keys and `cohort_omissions` keys equals the canonical 4-cohort universe `{"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}` — every cohort in the universe is in EXACTLY ONE of the two collections (FR-016).
- Runtime cohort failures (a cohort that was supposed to run but every RPC errored) do NOT appear in `cohort_omissions`; they show up in per-cell error rows only (per the spec's "the latter shows up only in per-cell error rows, never in `cohort_omissions`" — round-2 Q2 explicit).

### `M6_1_2SweepArtifact` (top-level entity)

The artifact JSON shape, with M6.1.2's additions called out:

```python
@dataclass
class M6_1_2SweepArtifact:
    # === M6.1.1-inherited top-level keys (preserved verbatim, see m6_1_1_reporter.py:407-453) ===
    schema_version: str
    dispatch_mode: Literal["concurrent"]  # From M6.0a; M6.1.2 inherits "concurrent"
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: dict  # M6.1.1-inherited shape PLUS a NEW `sweep_mode: Literal["full", "validate"]` field
                   # recording which M6.1.2 mode flag launched the sweep (post-`/speckit-analyze` C1
                   # remediation — the two mode flags share code, distinction lives in metadata).
                   # Pre-M6.1.2 readers ignore the unknown nested key without parse error.
    phase_1_classifications: dict
    phase_1_runs: list[dict]
    multi_point_timings: dict
    phase_2_outcome: dict | None
    phase_2_choice: str | None
    chat_stream_baseline_post_symmetrisation: dict
    embed_baseline_post_symmetrisation: dict
    embed_regression_check: dict | None
    m6_1_baseline_pointer: str
    methodology_supersedence: dict
    classifier_notes: list[str]
    # === M6.1.2 NEW top-level keys (strict-superset addition) ===
    network_paths: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]
    cohort_set: list[M6_1_2CohortKind]  # Sorted alphabetically for reader-script stability
    cohort_omissions: M6_1_2CohortOmissions | None  # None / absent when nothing omitted
```

**Strict-superset evolution** (FR-004 + FR-016): an M6.1.1-vintage reader parses this artifact, ignoring the three new keys. The integration test `test_m6_1_2_artifact_schema.py` exercises this: synthesize an M6.1.2 artifact, parse with M6.1.1's reader, assert no parse error and no key-not-found exceptions on the M6.1.1-known keys.

## Module Surface Map

The five new files under `tools/benchmark/src/vllm_grpc_bench/`, with their entity roles:

| File | Entity / Function | Notes |
|------|-------------------|-------|
| `m6_1_2_types.py` | `M6_1_2CohortKind`, `M6_1_2_COHORTS`, `M6_1_2CloudProvider`, `M6_1_2NetworkPathHop`, `M6_1_2NetworkPath`, `M6_1_2NetworkPathError`, `M6_1_2CohortOmissions`, `M6_1_2SweepArtifact` | All shared dataclasses + literals live here. Mirrors `m6_1_1_types.py`'s role. |
| `m6_1_2_sweep.py` | `run_m6_1_2_sweep(...)`, `_stderr_ts()`, `_measure_cell_m6_1_2(...)` | Sweep orchestrator. Inherits M6.0a-corrected concurrent dispatch + M6.1.1 classifier instrumentation. Calls `m6_1_2_network_probe.run_topology_probe(...)` at sweep start. |
| `m6_1_2_reporter.py` | `render_json(...)`, `render_markdown(...)`, `write_m6_1_2_report(...)`, `_sanitize_for_json(...)` | Mirrors `m6_1_1_reporter.py`. Adds the three new top-level keys to the serialized JSON. Pre-write validation of `cohort_set` ∪ `cohort_omissions` = canonical universe (FR-016 invariant). |
| `m6_1_2_validate.py` | `run_m6_1_2(args, *, sweep_mode)` | **Single CLI entry function for BOTH `--m6_1_2` and `--m6_1_2-validate` mode flags** (post-`/speckit-analyze` C1 remediation: per FR-024 the two flags have identical sweep shape; one entry function handles both, with `sweep_mode: Literal["full", "validate"]` recorded in `run_meta.sweep_mode` artifact metadata). Invokes `run_m6_1_2_sweep` (from `m6_1_2_sweep.py`) at `n=50` with the full M6.1.1 6-cell matrix and the 4-cohort iteration. Writes the artifact to `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`. The module's filename retains `validate` for backward-compatibility with the spec's terminology; the function name `run_m6_1_2` accurately reflects that it serves both modes. |
| `m6_1_2_network_probe.py` | `run_topology_probe(...)`, `attribute_cloud_provider(...)`, `parse_tcptraceroute_output(...)`, `_fetch_csp_ip_ranges(...)`, `_whois_lookup(...)` | Net-new module. Owns `tcptraceroute` subprocess invocation (R-5), CSP attribution (R-6), per-cohort 30s timeout (FR-002a), parallel-across-cohorts execution (FR-001a), loud-stderr warnings for FR-005a + FR-006. |

## Modified Files (non-additive)

| File | Change | Notes |
|------|--------|-------|
| `m6_1_rpc_driver.py:305-345` | Add a 4th cohort dispatch case for `"rest_plain_tcp"` | Mirrors `rest_https_edge`'s `httpx.AsyncClient` shape but uses `rest_plain_tcp_url` from the Modal handshake dict. ~30-50 LOC. Existing 3-cohort paths unchanged per FR-017. |
| `__main__.py:525-600 area` | Add `--m6_1_2` + `--m6_1_2-validate` + 12 namespaced sub-flags | Mirrors M6.1.1's argparse block. Mutual-exclusion list per FR-026. Verbatim-inheritance defaults per FR-027 + round-3 Q2. |
| `m6_sweep.py`, `m6_1_sweep.py`, `m6_1_1_sweep.py` | `_stderr_ts()` + timestamped emit sites | Already on the spike branch at commit `3763687`; cherry-pick to the M6.1.2 branch verbatim per FR-021. |
| `tools/benchmark/tests/test_m6_quickstart_format.py` | `_strip_ts_prefix()` + assertion extensions | Already on spike `3763687`; cherry-pick. |
| `ANALYSIS.md` | One-line multi-CSP correction citing spike #1 | Per FR-008. Phrasing: "cohorts enter Modal via entirely different cloud providers" (matches spike's TL;DR). |
| `contracts/instrumentation.md` (or new file if absent) | Document `network_paths` + `cohort_set` + `cohort_omissions` | Per FR-009 + FR-016. SC-007: lands in the same PR as the code. |
| `CLAUDE.md` | Update SPECKIT plan reference | Phase 1 step 3 of `/speckit-plan`. Path: `specs/025-m6-1-2-methodology-discipline/plan.md`. |

## Cohort Iteration Semantics (detailed)

The sweep orchestrator in `m6_1_2_sweep.py` iterates cohorts as follows:

```python
async def run_m6_1_2_sweep(config: M6_1_2Config) -> M6_1_2SweepArtifact:
    # Step 1: Modal deploy + handshake (reuses M6.1.1's pattern)
    handshake = await deploy_and_handshake(config)

    # Step 2: Topology probe (FR-001, FR-001a, FR-002a)
    # Parallel across cohorts, 30s per-cohort timeout
    network_paths = await run_topology_probe(
        handshake_dict=handshake,
        cohorts=M6_1_2_COHORTS,
        per_cohort_timeout_seconds=30,
    )

    # Step 3: For each cell × cohort, run warmup + measurement
    cells = M6_1_CELLS  # Reused from m6_1_types.py:72-82 per R-2
    per_cell_results = []
    for cell in cells:
        path, _, c = cell  # (path, sequence_length, concurrency)
        cohorts_for_this_cell = cohorts_at_concurrency(c)  # Returns 3 or 4 cohorts (R-3)
        for cohort in cohorts_for_this_cell:
            warmup_result = await run_warmup(cell, cohort, handshake)
            measurement_result = await run_measurement(cell, cohort, handshake)
            per_cell_results.append((cell, cohort, warmup_result, measurement_result))

    # Step 4: Reporter writes the artifact
    artifact = build_artifact(
        per_cell_results=per_cell_results,
        network_paths=network_paths,
        cohort_set=sorted(set(c for _, c, _, _ in per_cell_results)),
        cohort_omissions=None,  # M6.1.2 default: no intentional omissions
    )
    return artifact


def cohorts_at_concurrency(c: int) -> tuple[M6_1_2CohortKind, ...]:
    """Returns the cohort tuple to iterate for a cell with the given concurrency.

    Per FR-011 (M5.2-inherited tuned-pair collapse rule):
    - At c == 1: ("rest_https_edge", "rest_plain_tcp", "default_grpc")
      (default_grpc and tuned_grpc_multiplexed collapse to single default_grpc)
    - At c >= 2: ("rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed")
    """
    if c == 1:
        return ("rest_https_edge", "rest_plain_tcp", "default_grpc")
    return M6_1_2_COHORTS
```

**Note** on `cohort_set` ordering: the spec doesn't pin a sort order (round-3 listed it as plan-territory). Plan-level decision: `cohort_set` is **sorted alphabetically** to give reader scripts a stable iteration order across runs. The canonical alphabetical order is `["default_grpc", "rest_https_edge", "rest_plain_tcp", "tuned_grpc_multiplexed"]` for `c ≥ 2` cells.

## Cross-references

- Spec: [`spec.md`](./spec.md) — FR-001 through FR-029 + 10 SCs + 13 Clarifications.
- Plan: [`plan.md`](./plan.md) — Technical Context + Constitution Check + Project Structure.
- Phase 0 research: [`research.md`](./research.md) — R-1 through R-8 inform every dataclass shape above.
- CLI contract: [`contracts/cli.md`](./contracts/cli.md) — flag names, defaults, mutual exclusion.
- Network-paths contract: [`contracts/network-paths.md`](./contracts/network-paths.md) — wire-level JSON shape for the `network_paths` block.
- Artifact-schema contract: [`contracts/artifact-schema.md`](./contracts/artifact-schema.md) — `cohort_set` + `cohort_omissions` wire-level shape.
- M6.1.1 reference: `tools/benchmark/src/vllm_grpc_bench/m6_1_1_reporter.py:407-453` (M6.1.2 mirrors this), `m6_1_types.py:72-82` (M6_1_CELLS reused), `m6_1_types.py:84-88` (M6_1_COHORTS extended).
- M6.0a precedent for `dispatch_mode` strict-superset: `specs/024-m6-0a-concurrent-dispatch/contracts/output.md`.
