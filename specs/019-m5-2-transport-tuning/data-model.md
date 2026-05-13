# M5.2 Data Model

This file documents the additive dataclasses, Literal-type extensions, and JSON-key additions M5.2 introduces. Every addition is **additive** — no field is renamed, removed, or semantically redefined relative to M5.1's published types. M5.1-aware consumers (existing harness modules, report renderers, JSON readers) continue to work unmodified when M5.2 fields are present but unread (per FR-013's strict-superset rule).

The new types live in:
- `tools/benchmark/src/vllm_grpc_bench/m3_types.py` — the project's central typing module, extended additively (same pattern M5.1 used).
- `tools/benchmark/src/vllm_grpc_bench/m5_2_events.py` — defines the `PerRequestEventRecord` schema and the sidecar writer's emit contract.
- `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` — defines `SymmetryBlock` and its three tier dataclasses.

The companion JSON schema delta (consumed by external tools and the regenerator) is documented in `contracts/m5_2-report-schema.md`; this file pins the in-memory Python shapes.

---

## Verdict literals

```python
# m3_types.py — extended

# Protocol-comparison verdicts: each gRPC cohort vs rest_https_edge (the
# production-equivalent REST baseline). c >= 2 has three rows per cell;
# c == 1 has two rows (tuned/channels collapse to tuned_grpc per FR-006).
ProtocolComparisonVerdict = Literal[
    "tuned_grpc_multiplexed_recommend",
    "tuned_grpc_channels_recommend",
    "tuned_grpc_recommend",              # c=1 only
    "default_grpc_recommend",
    "rest_https_edge_recommend",
    "no_winner",
    "comparison_unavailable",
]

# Transport-only comparison verdict: rest_https_edge vs rest_plain_tcp.
# One row per cell.
TransportOnlyVerdict = Literal[
    "rest_https_edge_recommend",
    "rest_plain_tcp_recommend",
    "no_winner",
    "comparison_unavailable",
]

# Cohort kind extended to label the network path each cohort travels.
M5_2CohortKind = Literal[
    "rest_https_edge",
    "rest_plain_tcp",
    "default_grpc",
    "tuned_grpc_multiplexed",
    "tuned_grpc_channels",
    "tuned_grpc",                        # c=1 collapse of the two above
]

NetworkPath = Literal["https_edge", "plain_tcp"]

# Supersedes-M5.1 row category (FR-016 + R-6). The `confirmed_unavailable`
# literal is added per R-6 for the case where both M5.1 and M5.2 are
# comparison_unavailable on the same cell.
SupersedesM5_1Category = Literal[
    "verdict_changed",
    "verdict_confirmed",
    "noise_resolved",                    # M5.1 was no_winner; M5.2 has named a winner.
    "transport_dependent",               # HTTPS-edge moved the verdict relative to plain-TCP.
    "confirmed_unavailable",             # Both M5.1 and M5.2 are comparison_unavailable.
]
```

The existing `ComparisonVerdict` literal from M5.1 stays in place unchanged — M5.2's `ProtocolComparisonVerdict` is a superset of M5.1's verdict shape with the `rest_https_edge_recommend` literal added in place of M5.1's `rest_recommend` literal (which referred to `rest_plain_tcp`). M5.1's existing `rest_recommend` literal remains importable for back-compatibility but is not emitted by the M5.2 sweep.

---

## New: `RestHttpsEdgeCohortRecord`

```python
# m3_types.py
@dataclass(slots=True, frozen=True)
class RestHttpsEdgeCohortRecord:
    """Per-(path × hidden_size × concurrency) REST cohort measurement over
    Modal's HTTPS edge.

    Built by ``rest_cohort.run_rest_cohort(network_path="https_edge", ...)``
    and folded into the M5.2 JSON aggregate. Extends M5.1's RESTCohortRecord
    with the HTTPS-edge-specific provenance the spec's FR-008 / FR-014 /
    Edge Cases require.
    """

    # Inherited / mirrored from M5.1's RESTCohortRecord — present on
    # rest_plain_tcp too, repeated here so the M5.2 markdown table renderer
    # can iterate both cohorts uniformly.
    shim_overhead_ms_median: float
    shim_overhead_ms_p95: float
    connections_opened: int
    connections_keepalive_reused: int
    request_bytes_median: int
    request_bytes_p95: int
    response_bytes_median: int
    response_bytes_p95: int

    # M5.2-specific HTTPS-edge provenance.
    network_path: Literal["https_edge"]
    https_edge_endpoint: str            # The HTTPS edge URL the cohort
                                        # used (e.g., https://abc.modal.run).
    tls_handshake_ms_first_request: float | None  # Cold-connection TLS
                                        # handshake cost on the first request
                                        # (warmup), recorded once per cohort
                                        # so the report can confirm warmup
                                        # absorbed the handshake.
    measured_rtt_ms_median: float       # Per-cohort RTT probe median.
    measured_rtt_ms_p95: float
    client_external_geolocation_country: str | None  # ISO-3166-1 alpha-2
                                        # (e.g., "US"); None if lookup failed.
    client_external_geolocation_region: str | None   # ISO-3166-2 subdivision
                                        # (e.g., "US-CA"); None if lookup failed.
```

The plain-TCP REST cohort uses M5.1's existing `RESTCohortRecord` with `network_path="plain_tcp"` added; no new dataclass is needed for it. The M5.2 reporter iterates both cohorts uniformly via a `Protocol`-typed accessor.

---

## New: `SymmetryBlock` and its three tier sub-types

Defined in `m5_2_symmetry.py`:

```python
# m5_2_symmetry.py
@dataclass(slots=True, frozen=True)
class CrossCohortInvariants:
    """Tier (a) — invariants every cohort MUST share.

    Asserted at run start; any mismatch aborts the run. The markdown report
    writer MUST refuse to render the markdown on tier (a) divergence with
    the diverging field named in the failure message (per FR-005b).
    """

    prompt_corpus_hash: str             # SHA-256 hex of the prompt corpus.
    modal_deploy_handle: str            # The single Modal app handle the
                                        # whole run uses.
    mock_engine_config_digest: str      # SHA-256 hex of
                                        # MockEngineConfig serialized as
                                        # canonical JSON.
    warmup_batch_policy: str            # Policy literal, e.g.,
                                        # "discard_first_5_measurement_n_5"


@dataclass(slots=True, frozen=True)
class IntraProtocolPairInvariants:
    """Tier (b) — within-protocol-pair invariants (FR-005b).

    Asserted at run start with c=1 degeneracy skip for the tuned-gRPC pair.
    """

    # REST pair: rest_https_edge and rest_plain_tcp MUST share this digest
    # (computed with the target URL field excepted — URL is the operative
    # variable between the two REST transports).
    rest_client_config_digest_url_excepted: str  # SHA-256 hex.

    # tuned-gRPC pair: tuned_grpc_multiplexed and tuned_grpc_channels MUST
    # share this digest (computed with the channel_topology field excepted —
    # topology is the operative variable between the two tuned shapes). At
    # c=1 the two cohorts collapse to tuned_grpc per FR-006; this field is
    # None in that case and the assertion is skipped (recorded as
    # tier_b_skipped_c1_tuned_grpc_pair=True in tier (c)).
    tuned_grpc_channel_config_digest_topology_excepted: str | None


@dataclass(slots=True, frozen=True)
class PerCohortMetadata:
    """Tier (c) — per-cohort audit metadata (no cross-assertion).

    Recorded for post-hoc auditability. Indexed by cohort name.
    """

    cohort: M5_2CohortKind
    client_config_digest_full: str      # SHA-256 hex of the full
                                        # configuration (no fields excepted).
    modal_app_handle: str               # Modal app handle (same for all
                                        # cohorts in a run; replicated per
                                        # cohort for grep convenience).
    modal_region: str                   # e.g., "eu-west-1".
    warmup_batch_size: int

    # Boolean flag set when tier (b) was skipped for this cohort's pair
    # because of the c=1 collapse. Replicated per cohort so a reader can
    # filter on it directly.
    tier_b_skipped_c1_tuned_grpc_pair: bool


@dataclass(slots=True, frozen=True)
class SymmetryBlock:
    """3-tier symmetry block per FR-005b.

    Persisted as a top-level key in the M5.2 JSON aggregate. The
    `assert_symmetry()` function verifies tier (a) and tier (b) and raises
    on failure; tier (c) is purely audit-only.
    """

    tier_a: CrossCohortInvariants
    tier_b: IntraProtocolPairInvariants
    tier_c: list[PerCohortMetadata]     # One entry per cohort in the run.

    # The run's external client geolocation (Edge Cases — HTTPS-edge
    # anycast geography varies). None if the best-effort lookup failed at
    # run start (per R-12 open item).
    client_external_geolocation_country: str | None
    client_external_geolocation_region: str | None
```

The asserter:

```python
def assert_symmetry(block: SymmetryBlock, concurrency_levels: list[int]) -> None:
    """Tier (a) and tier (b) fail-fast assertion. Raises
    SymmetryAssertionFailed with the diverging field + cohort/pair on
    mismatch."""
```

is invoked at run start (before any cohort dispatches) and at report-build time (by the regenerator, before computing aggregates) so post-hoc replays can't accidentally publish a corrupted-symmetry run.

---

## New: `PerRequestEventRecord` (JSONL sidecar schema)

Defined in `m5_2_events.py`:

```python
# m5_2_events.py
@dataclass(slots=True, frozen=True)
class PerRequestEventRecord:
    """One per-request event record. Serialized as one JSON object per
    line in the gzipped events sidecar per FR-012a.
    """

    # Cohort + cell coordinates (FR-012a (a)-(c)).
    cohort: M5_2CohortKind
    path: Literal["chat_stream", "embed"]
    hidden_size: int
    concurrency: int
    network_path: NetworkPath

    # Per-request identity (FR-012a (d)).
    request_uuid: str                   # uuid4-formatted hex.

    # Timestamps (FR-012a (e)). All monotonic wall-clock in milliseconds.
    issue_ts_ms: float
    first_byte_ts_ms: float | None      # Non-null only for chat_stream.
    done_ts_ms: float

    # RTT snapshot at issue time (FR-012a (f)). Replicated from the
    # cohort's RTT probe so a reader can join records to RTT without a
    # second lookup.
    rtt_at_issue_ms: float

    # Phase flag (FR-012a (g)). Warmup records are persisted (so the
    # reader can audit warmup behavior) but excluded from aggregates.
    phase: Literal["warmup", "measurement"]

    # Server-bound flag (FR-012a (h)). Replicated per record at the
    # cohort level for grep convenience.
    server_bound: bool

    # Body sizes (FR-012a (i)-(j)).
    request_body_bytes: int
    response_body_bytes: int            # For chat_stream, sum across
                                        # SSE frames.

    # Outcome (FR-012a (k)).
    status: str                         # "success" | "timeout" |
                                        # "error:<reason>"
```

Serialization rule: `json.dumps(record.__dict__, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` followed by `"\n"`. Deterministic byte ordering so the gzip output is reproducible across runs of the regenerator on equivalent in-memory state.

The sidecar writer:

```python
class EventsSidecarWriter:
    """Context-managed JSONL-append-then-gzip writer (per R-4).

    Usage:
        with EventsSidecarWriter(out_dir, run_id) as writer:
            writer.write(record)
            ...
        # Closing the context flushes, gzips, computes SHA-256, and
        # returns the gzipped path + checksum hex.
        sidecar_path, sha256_hex = writer.result
    """

    def __init__(self, out_dir: Path, run_id: str) -> None: ...
    def __enter__(self) -> "EventsSidecarWriter": ...
    def write(self, record: PerRequestEventRecord) -> None: ...
    def __exit__(self, *args: object) -> None: ...

    @property
    def result(self) -> tuple[Path, str]: ...
```

The reader (for the regenerator):

```python
def read_sidecar_iter(path: Path) -> Iterator[PerRequestEventRecord]:
    """Stream records from a gzipped sidecar. Strictly typed; raises on
    schema mismatch (additional fields are warnings, not errors, so future
    milestones can extend the schema without breaking M5.2's reader)."""
```

---

## New: `SupersedesM5_1Entry`

```python
# m3_types.py
@dataclass(slots=True, frozen=True)
class SupersedesM5_1Entry:
    """One row in the Supersedes-M5.1 table per FR-016."""

    # M5.1 cell identity (matches M5.1 JSON shape so the row joins back
    # to the M5.1 published cell).
    path: Literal["chat_stream", "embed"]
    hidden_size: int
    concurrency: int
    grpc_cohort: M5_2CohortKind         # default_grpc | tuned_grpc_multiplexed
                                        # | tuned_grpc_channels | tuned_grpc

    # M5.1's verdict literal (against rest_plain_tcp, M5.1's only REST
    # cohort).
    m5_1_verdict: str                   # Free string — accepts M5.1's
                                        # exact literal regardless of M5.1
                                        # type union shape, for
                                        # forward-compatibility.

    # M5.2's protocol-comparison verdict literal (against rest_https_edge,
    # the production-equivalent REST baseline).
    m5_2_verdict: ProtocolComparisonVerdict

    # M5.2's supporting CI-bounded numbers (the same numbers the per-cell
    # comparison matrix shows for this row).
    m5_2_delta_median_ms: float         # M5.2's measured delta on the time
                                        # metric.
    m5_2_ci_lower_ms: float             # 95% CI lower bound on the delta.
    m5_2_ci_upper_ms: float

    category: SupersedesM5_1Category    # Per R-6.

    rationale: str                      # One-line free-text rationale,
                                        # e.g., "M5.2 resolves M5.1's
                                        # no_winner with default_grpc
                                        # winning by 6.2 ms (CI [4.1, 8.3])
                                        # at n=250."
```

---

## Extended: `M5_2Run` cohort root

```python
# m3_types.py — top-level dataclass for the M5.2 sweep's complete record.
@dataclass(slots=True, frozen=True)
class M5_2Run:
    """Top-level container for a complete M5.2 sweep. Serialized into the
    aggregate JSON at docs/benchmarks/m5_2-transport-vs-tuning.json by the
    regenerator (NOT by the harness directly, per FR-012b)."""

    # Run identity + reproducibility.
    run_id: str
    run_started_at_iso: str             # ISO 8601 timestamp; the only
                                        # time-related value the markdown
                                        # writer is allowed to consume
                                        # (per R-5 determinism rule).
    run_realized_runtime_s: float       # SC-007 — recorded so future
                                        # operators can plan.
    seed: int                           # Random seed; tier (a) consumes
                                        # this via prompt_corpus_hash.

    # 3-tier symmetry block.
    symmetry: SymmetryBlock

    # Events sidecar provenance (FR-012a + R-4).
    events_sidecar_path: str            # Repo-relative path to the
                                        # committed gzipped sidecar.
    events_sidecar_sha256: str          # SHA-256 hex of the gzipped sidecar.

    # Payload-parity audit confirmation (FR-005c + R-9).
    payload_parity_audit_no_regression_confirmed_against_pr: str
    payload_parity_audit_measured_payload_bytes: dict[str, int]

    # Smoke-gate outcome (FR-005a + SC-012).
    smoke_run_outcome_iso: str          # ISO 8601 of the smoke's run
                                        # completion timestamp.
    smoke_run_asserted_clauses_count: int
    smoke_run_per_cohort_rtt_probe_medians_ms: dict[M5_2CohortKind, float]

    # Cohort records.
    rest_https_edge_cohorts: list[RestHttpsEdgeCohortRecord]
    rest_plain_tcp_cohorts: list[RESTCohortRecord]  # M5.1 type, reused.
    grpc_cohorts: list[GRPCSubCohortRecord]         # M5.1 type, reused.

    # Per-cell verdicts (two families per cell).
    protocol_comparison_verdicts: list[ProtocolComparisonRow]
    transport_only_verdicts: list[TransportOnlyRow]

    # Supersedes-M5.1 table.
    supersedes_m5_1: list[SupersedesM5_1Entry]

    # Modal + topology continuity.
    modal_region: str
    modal_instance_class: str           # e.g., "cpu-only" or specific class.

    # HTTPS-edge vs plain-TCP RTT delta (computed; surfaced in executive
    # section per FR-014).
    https_edge_vs_plain_tcp_rtt_delta_median_ms: float
    https_edge_vs_plain_tcp_rtt_delta_p95_ms: float

    # Per-cell crash log (added 2026-05-12 post-implementation per
    # research R-13's preemption-aware resilience design). Empty on a
    # clean run; one entry per (cell × exception) when the sweep's
    # per-cell try/except catches a dispatch failure. The regenerator
    # surfaces these as comparison_unavailable rows in the markdown's
    # negative-results appendix so a reader sees which cells were
    # incomplete and why. Each entry carries:
    #   path / hidden_size / concurrency: cell coordinates
    #   exception_type: class name (e.g., "ConnectError")
    #   exception_repr: repr(exc) for diagnostics
    #   traceback: full formatted traceback string
    failed_cells: list[dict[str, Any]]


@dataclass(slots=True, frozen=True)
class ProtocolComparisonRow:
    """One row in the per-cell protocol comparison family (FR-009).
    One row per (cell, gRPC cohort)."""

    path: Literal["chat_stream", "embed"]
    hidden_size: int
    concurrency: int
    grpc_cohort: M5_2CohortKind
    rest_cohort: Literal["rest_https_edge"]    # Always rest_https_edge per FR-009.

    verdict: ProtocolComparisonVerdict
    comparison_unavailable_reason: str | None
    delta_median_ms: float
    ci_lower_ms: float
    ci_upper_ms: float
    grpc_cohort_network_path: Literal["plain_tcp"]
    rest_cohort_network_path: Literal["https_edge"]


@dataclass(slots=True, frozen=True)
class TransportOnlyRow:
    """One row in the per-cell transport-only comparison family (FR-009).
    One row per cell."""

    path: Literal["chat_stream", "embed"]
    hidden_size: int
    concurrency: int

    verdict: TransportOnlyVerdict
    comparison_unavailable_reason: str | None
    delta_median_ms: float                # rest_https_edge - rest_plain_tcp
                                          # on the time metric.
    ci_lower_ms: float
    ci_upper_ms: float
```

---

## Extended: `RequestSample` (chat corpus loader, post-implementation)

> Added 2026-05-12 post-implementation per research [R-12](research.md). Lives in `tools/benchmark/src/vllm_grpc_bench/corpus.py`.

The existing M3-era `RequestSample` dataclass gains an optional `bucket` field so the chat corpus's auto-derived short/medium/long bucket can be threaded through to per-request diagnostic surfaces without breaking pre-M5.2 corpora that lack the field.

```python
# corpus.py — extended
@dataclass
class RequestSample:
    id: str
    messages: list[dict[str, str]]
    model: str
    max_tokens: int
    temperature: float
    seed: int
    # M5.2 (R-12): auto-derived from prompt length when the corpus is
    # generated by ``scripts/python/gen_chat_corpus.py``. Optional with
    # default "unspecified" so pre-M5.2 corpora (e.g.,
    # ``chat_nonstreaming.json`` without the field) load unchanged.
    bucket: str = "unspecified"  # "short" | "medium" | "long" | "unspecified"


# Module-level constant naming the default chat corpus the M5.2 sweep
# consumes when no override is set. Points at the committed ShareGPT V3
# subset; the companion ``.provenance.json`` records the source revision
# SHA + filter criteria + corpus SHA-256.
DEFAULT_CHAT_CORPUS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "corpus"
    / "chat_sharegpt_1000.json"
)
```

Bucket boundaries: `short` ≤ 100 chars, `medium` ≤ 500 chars, `long` > 500 chars. Boundaries chosen to span the ShareGPT V3 first-turn-prompt length distribution (~56% short / 32% medium / 12% long on the 1k subset).

The corpus file's wire shape:

```json
[
  {
    "id": "sharegpt-0000",
    "messages": [{"role": "user", "content": "..."}],
    "model": "Qwen/Qwen3-0.6B",
    "max_tokens": 128,
    "temperature": 0.0,
    "seed": 42,
    "bucket": "long"
  },
  ...
]
```

The `model` field is M7-aspirational; the M5.2 harness substitutes its own model name (`"mock"` for REST, `"mock-engine"` for gRPC) since MockEngine doesn't dispatch by model.

---

## Extended: `M5_2SweepConfig` chat-corpus + preemption-refresh fields

> Added 2026-05-12 post-implementation per research [R-12](research.md) (chat corpus) and [R-13](research.md) (preemption resilience). Lives in `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py`.

```python
# m5_2_sweep.py — extended
@dataclass
class M5_2SweepConfig:
    # ... (existing fields)

    # M5.2 (R-12): chat corpus override path. ``None`` falls back to
    # ``DEFAULT_CHAT_CORPUS_PATH`` (the committed ShareGPT 1k subset).
    # Empty Path() disables corpus mode and uses the synthetic
    # ``build_chat_prompt`` helper (back-compat with pre-corpus tests).
    chat_corpus_path: Path | None = None

    # M5.2 (R-13): preemption-aware URL refresh callback. When a cell
    # fails with a connect-style error and this is set, the sweep polls
    # ``refresh_endpoints_fn()`` for fresh URLs; if returned, mutates
    # ``rest_https_edge_url`` / ``rest_plain_tcp_url`` / ``grpc_target``
    # in place and retries the cell ONCE. Bounded retry; no infinite
    # loops. ``None`` (e.g., skip-deploy mode) treats connect errors as
    # real failures via the existing failed_cells path.
    #
    # Signature: ``async () -> RESTGRPCEndpoints | None``
    refresh_endpoints_fn: Any = None
```

The refresh callable's implementation is `modal_endpoint.refresh_rest_grpc_urls(cached, *, poll_timeout_s=90.0, poll_interval_s=2.0) -> RESTGRPCEndpoints | None`. It polls `modal.Dict.from_name("vllm-grpc-bench-rest-grpc-mock-handshake")` for fresh URLs (detected via gRPC URL change, the canonical freshness anchor). The 90-second timeout accommodates Modal's worker-startup latency on preemption restart.

---

## ANALYSIS.md milestone section schema

Not a Python dataclass — a Markdown structural contract enforced by code review (verified by the K2 commit's diff and by the maintainer's `quickstart.md` checklist).

Each milestone's H2 section MUST have this structure:

```markdown
## M<N> — <Title>

**Status**: delivered <YYYY-MM-DD> | (upcoming)
**Report**: [`docs/benchmarks/m<N>-...md`](docs/benchmarks/m<N>-...md) (or "(none — process milestone)" for M2-style milestones)

<one-paragraph executive prose with the headline finding(s) in factual prose>

**Headline finding(s)**:
- <one bullet per finding, CI-bounded numbers where applicable>
- <...>

**Cross-milestone notes**: <e.g., "M5.2 resolves M5.1's open question on tuned-vs-default benefit on this path: see § M5.2.">
```

Future milestones add a new H2 section in this shape; existing sections are not rewritten. The M3 § retains the byte-for-byte tables M3's `summary.md` § 4 published (per FR-018).

---

## JSON schema delta (top-level, additive to M5.1's schema)

Per FR-013, the M5.2 JSON is a strict superset of M5.1's. New top-level keys (additive only):

| Key | Source dataclass | Notes |
|-----|------------------|-------|
| `m5_2_run` | `M5_2Run` | Top-level container for M5.2's run. M5.1-aware consumers ignore. |
| `symmetry` | `SymmetryBlock` | 3-tier symmetry block. |
| `events_sidecar_path` | string | Repo-relative path to gzipped sidecar. |
| `events_sidecar_sha256` | string | SHA-256 hex of gzipped sidecar. |
| `protocol_comparison_verdicts` | `list[ProtocolComparisonRow]` | One row per (cell × gRPC cohort). |
| `transport_only_verdicts` | `list[TransportOnlyRow]` | One row per cell. |
| `supersedes_m5_1` | `list[SupersedesM5_1Entry]` | Supersedes-M5.1 table. |
| `payload_parity_audit` | object | `no_regression_confirmed_against_pr: str`, `measured_payload_bytes: dict`. |
| `smoke_run_outcome` | object | `iso: str`, `asserted_clauses_count: int`, `per_cohort_rtt_probe_medians_ms: dict`. |
| `https_edge_vs_plain_tcp_rtt_delta_median_ms` | float | Computed; surfaces in executive section. |
| `https_edge_vs_plain_tcp_rtt_delta_p95_ms` | float | Computed; surfaces in executive section. |
| `failed_cells` | list of object | Per-cell crash log (post-implementation per R-13). Each entry: `{path, hidden_size, concurrency, exception_type, exception_repr, traceback}`. Empty on a clean run. Persisted in the run config JSON (`{run_id}.run_config.json`) so the regenerator can surface failed cells in the negative-results appendix. Currently the regenerator treats this key as optional — older run configs without it remain valid. |

M5.1's existing top-level keys (`m5_1_matrix`, `supersedes_m1_time`, etc.) are present and empty when the M5.2 mode is active — those keys are emitted with empty arrays. The forward-compatibility rule from M5.1's R-6 carries forward.

---

## Closing — no NEEDS CLARIFICATION items remain

Every dataclass, Literal extension, sidecar schema field, and JSON top-level key M5.2 adds is documented above. All shapes are additive to M5.1's published types. The asserter / writer / reader contracts named here are bound to specific Python signatures the implementation tasks (`/speckit-tasks` Phase B / C / E) will implement and unit-test under `tools/benchmark/tests/`.
