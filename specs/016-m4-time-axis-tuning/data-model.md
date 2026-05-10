# M4 Data Model

This document enumerates the new and modified data structures the M4 harness needs. All types live under `tools/benchmark/src/vllm_grpc_bench/m3_types.py` (extended in place — keeps the import surface stable for both M3 and M4 callers). Where M3 already has a type, M4 extends rather than replaces.

## Verdict literals

```python
# m3_types.py — extended
Verdict = Literal[
    "recommend",         # candidate's 95% CI strictly clears the comparison baseline's 95% CI
    "no_winner",         # CIs overlap and remained overlapping after the borderline-expand step
    "not_measurable",    # cohort failed to produce usable samples (e.g., RPC errors)
    "noise_bounded",     # M3-only literal; preserved for M3 report compatibility but never emitted from M4
    "client_bound",      # NEW (M4): cohort's per-RPC delta against the baseline is below the baseline's own jitter (R-5)
]
```

`noise_bounded` is preserved so M3's reanalyze path keeps compiling. M4 emits a runtime check: any attempt to construct a `Recommendation(verdict="noise_bounded")` from the M4 sweep raises `ValueError` (FR-007).

## Modified: `MockEngineConfig`

```python
# mock_engine.py
@dataclass(frozen=True)
class MockEngineConfig:
    hidden_size: int
    tokens_per_second: float = 20.0
    pace_tokens: bool = True   # NEW (M4): when False, no inter-token sleep
    # ...existing fields preserved...

    def __post_init__(self) -> None:
        if self.pace_tokens and self.tokens_per_second <= 0:
            raise ValueError("MockEngineConfig.tokens_per_second must be > 0 when pace_tokens=True")
        # When pace_tokens=False, tokens_per_second is unused — no validation needed.
```

When `pace_tokens=False`, the streaming loop in `mock_engine.py` skips the `await asyncio.sleep(interval)` call entirely.

## New: `BaselineRole`

```python
# m3_types.py
BaselineRole = Literal[
    "m1_shared",         # The shared M1_BASELINE cohort (FR-002)
    "frozen_channel",    # A per-path frozen-channel baseline cohort (R-3 / FR-011)
]
```

## New: `ExpansionRecord`

```python
# m3_types.py
@dataclass(frozen=True)
class ExpansionRecord:
    """Documents the FR-002 / R-4 borderline-expand decision for one candidate cohort."""
    initial_n: int                  # always 100 for default M4 sweep
    initial_ci_overlapped: bool     # True iff initial CI overlapped baseline CI (the trigger)
    expanded: bool                  # True iff the cohort was re-measured at n>=250
    final_n: int                    # initial_n if not expanded, else 250
    expansion_reason: str | None    # human-readable note ("ci_overlap", "operator_force", or None if not expanded)
```

A cohort that did *not* trigger the borderline rule still records `ExpansionRecord(initial_n=100, initial_ci_overlapped=False, expanded=False, final_n=100, expansion_reason=None)` so the JSON shape is uniform.

## New: `FrozenChannelBaseline`

```python
# m3_types.py
@dataclass(frozen=True)
class FrozenChannelBaseline:
    """Per-path frozen-channel baseline (R-3). One per path."""
    path: Literal["chat_stream", "embed"]
    cohort_id: str                  # points into Run.cohorts[]
    channel_config_name: str        # e.g., "frozen-chat_stream-h4096"
    per_axis_winners: dict[str, str]  # axis_name -> winning config_name from US2 (or "m1-default" if no winner)
    measured_at_hidden_size: int    # canonical width used for composition (4096)
```

The cohort itself lives in `Run.cohorts[]`; this record is the metadata that links axis-winner provenance to the cohort.

## New: `SchemaCandidatePerWidth` and `SchemaCandidateResult`

```python
# m3_types.py
@dataclass(frozen=True)
class SchemaCandidatePerWidth:
    """Per-width verdict for a single schema candidate (R-8 / contracts/m4-report-schema.md)."""
    hidden_size: int                                 # 2048 | 4096 | 8192
    frozen_baseline_cohort_id: str                   # points into Run.cohorts[] (the per-path frozen baseline)
    candidate_cohort_id: str                         # points into Run.cohorts[] (the schema candidate cohort)
    bytes_verdict: Verdict                           # "recommend" | "no_winner" | "not_measurable" | "client_bound"
    time_verdict: Verdict
    primary_metric: Literal["bytes", "time"]         # which metric drove the verdict (per FR-013)
    delta_bytes_pct: float | None                    # percent change vs. frozen baseline; None if metric unavailable
    delta_time_pct: float | None
    ci_overlap_initial: bool                         # initial-n=100 CI overlapped baseline CI (triggered borderline-expand)
    expanded: bool                                   # candidate was re-measured at n>=250 per FR-002

@dataclass(frozen=True)
class SchemaCandidateResult:
    """Top-level schema-candidate verdict aggregating per-width measurements (FR-012, FR-013, FR-014)."""
    candidate_name: str                              # one of M4SweepConfig.schema_candidates
    proto_file: str                                  # repository-relative path to the candidate .proto
    measured_widths: list[int]                       # always includes 4096; includes 2048/8192 only if cascade fired
    per_width: list[SchemaCandidatePerWidth]
    is_negative_result: bool                         # True iff bytes_verdict and time_verdict are both "no_winner" at every measured width (FR-014)
    notes: str | None                                # human-readable supplemental context
```

The `SchemaCandidateResult` records are aggregated views over schema-candidate cohorts in `Run.cohorts[]` (cohorts whose `config_axis` starts with `"schema:"`); the candidate cohorts themselves remain in `Run.cohorts[]` so the M3-shape JSON reader sees them. The `SchemaCandidateResult` aggregation is the M4-only synthesized view that `contracts/m4-report-schema.md`'s top-level `schema_candidate_results` field serializes.

## New: `SupersessionEntry`

```python
# m3_types.py
@dataclass(frozen=True)
class SupersessionEntry:
    """One row in the M4 'Supersedes M3' table (FR-009)."""
    m3_cell_id: str                 # cell_id from m3-channel-tuning-time.json
    m3_verdict: Verdict             # typically "noise_bounded" for chat_stream wall-clock cells
    m4_cell_id: str                 # M4 cell that supersedes the M3 cell
    m4_verdict: Verdict             # never "noise_bounded" (FR-007)
    rationale: str                  # one-line explanation (e.g., "no-pacing exposed 4.2% TTFT win under compression")
```

Generated by `m4_supersede.py` after the M4 sweep completes by reading `m3-channel-tuning-time.json` and matching M3 cells against M4 cohorts on `(path, hidden_size, axis, config_name)`.

## Modified: `Cohort` (per-cohort run record)

```python
# m3_types.py — extended
@dataclass(frozen=True)
class Cohort:
    cell_id: str
    path: Literal["embed", "chat_stream"]
    hidden_size: int
    config_name: str
    config_axis: str                # "baseline" | "max_message_size" | "keepalive" | "compression" | "http2_framing" | "schema:packed_token_ids" | ...
    corpus_subset: str
    iterations: int
    n_successful: int
    measurable: bool
    off_canonical: bool
    bytes: MetricSummary | None     # MetricSummary = {mean, ci_low, ci_high}
    time_seconds: MetricSummary | None
    # NEW (M4) fields below — all default to None/False to preserve M3 JSON shape.
    is_baseline: bool = False
    baseline_role: BaselineRole | None = None
    expansion_record: ExpansionRecord | None = None
    client_bound: bool = False
    time_to_first_token_seconds: MetricSummary | None = None  # cohort-level TTFT summary (FR-003 promotion)
```

M3's existing field `time_seconds` continues to mean total per-RPC wall-clock. M4's TTFT summary is a separate `time_to_first_token_seconds` field — first-class output for chat_stream cohorts (FR-003), null for embed cohorts.

## New: `M4SweepConfig`

```python
# m4_sweep.py
@dataclass(frozen=True)
class M4SweepConfig:
    pacing_mode: Literal["paced", "no_pacing"] = "no_pacing"
    shared_baseline: bool = True
    baseline_n: int = 100
    candidate_n: int = 100
    expand_n: int = 250
    baseline_cv_warn: float = 0.05     # FR-005 / R-11: warn-only threshold; never aborts
    widths: tuple[int, ...] = (2048, 4096, 8192)
    paths: tuple[Literal["embed", "chat_stream"], ...] = ("embed", "chat_stream")
    axes: tuple[str, ...] = ("max_message_size", "keepalive", "compression", "http2_framing")
    loopback_caveat_axes: frozenset[str] = frozenset({"keepalive", "http2_framing"})  # R-6
    schema_candidates: tuple[str, ...] = ("packed_token_ids", "oneof_flattened_input", "chunk_granularity")
    schema_canonical_width: int = 4096   # 4096-first cascade per spec Assumptions
```

## Modified: `Run` (top-level run JSON)

```python
# m3_types.py — extended
@dataclass(frozen=True)
class Run:
    mode: str                          # "m4-time-axis-tuning" for M4 runs
    axes: list[str]
    widths: list[int]
    paths: list[str]
    iterations_per_cell: int           # the *default* candidate_n; per-cohort actuals live in Cohort.iterations
    seed: int
    p2_revision: str | None
    frozen_channel: dict | None        # M3's existing field; M4 leaves None and uses frozen_channel_baselines instead
    cohorts: list[Cohort]
    # NEW (M4) fields below — present in M4 runs, absent (or None/[]) in M3 runs.
    pacing_mode: Literal["paced", "no_pacing"] | None = None
    shared_baseline_cohort_ids: dict[str, str] | None = None  # path -> cohort_id
    frozen_channel_baselines: dict[str, FrozenChannelBaseline] | None = None
    supersedes: list[SupersessionEntry] = field(default_factory=list)
    candidate_sizing_policy: dict | None = None  # {"default_n": 100, "expand_n": 250, "expand_rule": "ci_overlap"}
    loopback_caveat_axes: list[str] | None = None
    schema_candidate_results: list[SchemaCandidateResult] = field(default_factory=list)  # synthesized aggregation over Run.cohorts[] schema-axis entries
```

M3 readers see only the M3-shape fields and ignore the M4 additions (per /speckit-clarify Q1: strict superset).

## Validation invariants

The `Run` instance for M4 must satisfy:

1. **No `noise_bounded` verdicts**: every `Cohort.verdict` (where Recommendations are attached, in `Run.recommendations`) is one of `{recommend, no_winner, not_measurable, client_bound}` — never `noise_bounded`. Enforced as a `ValueError` at construction time in M4's recommendation builder. (FR-007)
2. **Shared baseline coverage**: `shared_baseline_cohort_ids` contains an entry for every path in `paths`, and each pointed-to cohort has `is_baseline=True` and `baseline_role="m1_shared"`. (FR-002)
3. **Frozen baseline coverage** (US3 only): if `frozen_channel_baselines` is non-None, it contains an entry for every path in `paths`, and each pointed-to cohort has `is_baseline=True` and `baseline_role="frozen_channel"`. (FR-011)
4. **Expansion records**: every non-baseline cohort has a non-null `expansion_record` (cohorts that didn't trigger the rule still record `expanded=False`). (FR-002)
5. **TTFT presence on chat_stream**: every chat_stream cohort with `measurable=True` has a non-null `time_to_first_token_seconds`. (FR-003)
6. **Loopback caveat consistency**: `loopback_caveat_axes` is a subset of `axes`, and for M4 single-host runs equals `{keepalive, http2_framing}` ∩ `axes`. (FR-010 / R-6)
7. **Supersession completeness**: `supersedes` contains at least one entry per M3 `noise_bounded` cell present in the M3 time report at the matching `(path, hidden_size, axis)`. (FR-007 / FR-009)
8. **Schema-candidate result well-formedness**: every `schema_candidate_results[i].candidate_name` is in `M4SweepConfig.schema_candidates`; every `per_width[i].frozen_baseline_cohort_id` and `per_width[i].candidate_cohort_id` resolves to a cohort in `Run.cohorts[]`; `is_negative_result` is `True` iff every `per_width[i]` has both `bytes_verdict == "no_winner"` and `time_verdict == "no_winner"` (FR-012 / FR-013 / FR-014).

These are checked by `m4_sweep.validate_run(run)` before the JSON is written.
