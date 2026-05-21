# Benchmark artifact instrumentation schema

This document is the canonical reference for the per-sweep JSON artifact
schema. It documents the top-level keys consumers can rely on, including
the M6.1.2-forward additions (`network_paths`, `cohort_set`,
`cohort_omissions`) and the M6.0a-forward `dispatch_mode` key.

The artifact's `schema_version` field identifies the milestone that owns
the layout; new additions are **strict-superset** (top-level keys with
defaulted-absence semantics — older readers ignore them without error).
No `schema_version` bump on additive evolution. Removals / renames /
type changes WOULD require a bump; none have happened to date.

## Canonical artifact paths

Each milestone writes its sweep artifact to a canonical path under
`docs/benchmarks/`:

| Milestone | Markdown report | JSON companion | Events sidecar |
|---|---|---|---|
| M6 | `m6-real-engine-mini-validation.{md,json}` | same | — |
| M6.1 | `m6_1-real-prompt-embeds.{md,json}` | same | — |
| M6.1.1 | `m6_1_1-engine-cost-instrumentation.{md,json}` | same | `m6_1_1-events.jsonl` (when written) |
| M6.0a | `m6_0a-dispatch-correction.md` (analysis) + corrected M6.1.1 JSON | — | — |
| M6.1.2 | `m6_1_2-methodology-discipline.{md,json}` | same | `m6_1_2-events.jsonl` |
| M6.1.3 (publish) | `m6_1_3-attribution-closure.{md,json}` | same | `m6_1_3-events.jsonl` |
| M6.1.3 (validate sibling) | `m6_1_3-attribution-closure-validate.{md,json}` | same | shared with publish |
| M6.1.3 (Phase B sibling, conditional) | `m6_1_3-attribution-closure-phase-b.{md,json}` | same | shared with publish |

The JSON is authoritative for downstream readers; the markdown is the
human-readable companion.

## Top-level keys

### Inherited from M6 / M6.1 / M6.1.1

The following keys are present on every M6-family artifact:

| Key | Type | Notes |
|---|---|---|
| `schema_version` | string | Identifies the milestone shape. M6.1.1: `"m6_1_1.v1"`. M6.1.2: `"m6_1_2.v1"`. |
| `run_id` | string | `<run_started_at>-<git_sha[:7]>` |
| `run_started_at` | ISO-8601 UTC string | second precision, `Z` suffix |
| `run_completed_at` | ISO-8601 UTC string | same format |
| `run_meta` | object | per-milestone shape; carries `modal_region`, `model_identifier`, `seq_len`, `engine_version`, etc. M6.1.2 adds `sweep_mode: "full" \| "validate"` nested under `run_meta`. |
| `phase_1_classifications` | dict | M6.1.1+ — per-cell classifier verdicts |
| `phase_1_runs` | list | M6.1.1+ — per-run record with per-RPC perturbation audit |
| `multi_point_timings` | list | M6.1.1+ — per-cohort timing aggregates |

(Plus other milestone-specific keys not relevant to the M6.1.2
discussion below; consult each milestone's spec for the full list.)

### `dispatch_mode` (M6.0a-forward — additive)

```jsonc
{ "dispatch_mode": "concurrent" }
```

- **Type**: string. Currently one of `"concurrent"` (M6.0a-corrected
  harness) or `"sequential"` (pre-M6.0a audit baseline, implied by
  absence of the key).
- **Required**: not on M6.0a-or-later artifacts.
- **Default-on-absence**: `"sequential"` — pre-M6.0a manifests parse
  unchanged.
- **See**: [`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`](../specs/024-m6-0a-concurrent-dispatch/contracts/output.md)
  for the M6.0a contract that introduced this key.

### `network_paths` (M6.1.2-forward — additive)

Per-sweep topology evidence captured via `tcptraceroute` against each
cohort's endpoint at sweep start, before warmup. Keyed by cohort name;
values are a discriminated union of success and error entries.

```jsonc
{
  "network_paths": {
    "rest_https_edge": {
      "endpoint_ip": "20.125.113.97",
      "hops": [
        { "hop_number": 1, "ip": "192.168.2.1", "rtt_ms_or_null": 1.2,  "cloud_provider": null },
        { "hop_number": 6, "ip": "104.44.14.37", "rtt_ms_or_null": 21.4, "cloud_provider": "Microsoft Azure" }
      ],
      "cloud_provider": "Microsoft Azure",
      "region": "westeurope",
      "probe_method": "tcptraceroute",
      "probed_at_utc": "2026-05-17T12:34:56Z"
    },
    "rest_plain_tcp": {
      "error": "probe_timeout",
      "probe_method": "tcptraceroute",
      "probed_at_utc": "2026-05-17T12:34:56Z",
      "detail": "tcptraceroute exceeded 30s wall-clock for 54.193.31.244:43209"
    }
  }
}
```

**Discriminator**: success entries carry `endpoint_ip` + `hops` +
`cloud_provider` + `region`; error entries carry an `error` field with
one of `"tcptraceroute_unavailable"` / `"probe_timeout"` /
`"subprocess_error"` / `"parse_error"`. Both shapes always carry
`probe_method` and `probed_at_utc`.

**Cohort-level `cloud_provider`** is a closed enum: `"AWS"` /
`"Microsoft Azure"` / `"GCP"` / `"unknown"`. Per-hop annotations may
additionally hold transit-ASN strings (`"Telia"`, `"Cogent"`, etc.) or
`null` when lookup didn't resolve.

**Probe execution semantics**: runs once per sweep BEFORE warmup,
parallel across cohorts via `asyncio.gather` + `asyncio.to_thread`, 30 s
per-cohort wall-clock timeout. Probe failure NEVER aborts the sweep —
the probe is methodology-supporting, not measurement-critical.

**Warnings**: an all-cohort-failed event triggers a loud stderr warning
at sweep start (FR-005a); a cohort that enters a different CSP than the
spike-confirmed expectation triggers an FR-006 warning. Both warning
lines carry the `[YYYY-MM-DDTHH:MM:SSZ]` ISO-8601 prefix used by all
M6.0a-forward progress lines.

**Closed enum at cohort level, open at per-hop**: cohort-level
`cloud_provider` validates against the 4-element enum; per-hop
`cloud_provider` is best-effort and accepts any string (or `null`). The
implementation algorithm cascades AWS IP-range JSON → Azure JSON → GCP
JSON → ARIN whois (with RIR-referral follow-up to RIPE / APNIC /
AFRINIC / LACNIC) → `"unknown"`.

**See**: [`specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md`](../specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md)
for the full wire-shape contract.

### `cohort_set` (M6.1.2-forward — additive)

```jsonc
{
  "cohort_set": ["default_grpc", "rest_https_edge", "rest_plain_tcp", "tuned_grpc_multiplexed"]
}
```

- **Type**: JSON array of strings, sorted alphabetically (reader-script
  stability across runs).
- **Required**: yes on every M6.1.2-or-later sweep.
- **Element type**: one of the 4 canonical cohort names
  (`"rest_https_edge"`, `"rest_plain_tcp"`, `"default_grpc"`,
  `"tuned_grpc_multiplexed"`).
- **Cardinality**: 1 to 4 elements. A successful sweep always runs at
  least one cohort.

**Semantics**: every cohort that the sweep ACTUALLY RAN appears in
`cohort_set`. If a cohort was supposed to run but every RPC errored
(runtime failure), it STILL appears here — its failure is recorded in
per-cell error rows / `top_failure_reasons`, NOT in `cohort_omissions`.

### `cohort_omissions` (M6.1.2-forward — additive, optional)

```jsonc
{
  "cohort_omissions": {
    "rest_plain_tcp": "M6.2 budget reduction; cohort isolates protocol cost which is not under variation in this milestone"
  }
}
```

- **Type**: JSON object or absent.
- **Required**: no. Absence (or empty `{}`) means "no intentional
  omissions". Both shapes MUST be tolerated by readers.
- **Key type**: one of the 4 canonical cohort names.
- **Value type**: string (one-line human-readable reason).
- **Cardinality**: 0 to 3 keys. Every key MUST NOT appear in
  `cohort_set` (mutual exclusion).

**Invariant** (enforced by the M6.1.2 reporter pre-write):
`set(cohort_set) ∪ set(cohort_omissions.keys()) == {"rest_https_edge",
"rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}` AND
`set(cohort_set) ∩ set(cohort_omissions.keys()) == ∅`. Violation raises
`ValueError` BEFORE the artifact is written — fail loud rather than
publish a malformed artifact.

**What does NOT belong in `cohort_omissions`**:

- A cohort that ran but every RPC errored (runtime failure). Record in
  per-cell `top_failure_reasons`; the cohort still appears in
  `cohort_set`.
- A cohort that wasn't in the milestone's iteration list because of the
  `c=1` tuned-pair collapse rule (M6.1.2 FR-011, inherited from
  `m5_2_sweep.py:228-237`). This is a structural property recorded in
  `run_meta`, not an intentional omission.

**Use cases**:

- M6.2 may omit `rest_plain_tcp` for budget reasons since `max_tokens`
  axis sweeps multiply Modal compute. The `cohort_omissions` reason
  string makes the design-intent decision visible to downstream readers
  without re-reading the spec.
- A reader comparing two artifacts can distinguish "the operator chose
  not to run this cohort" (in `cohort_omissions`) from "this cohort
  failed at runtime" (zero successes recorded in per-cell rows; cohort
  still in `cohort_set`).

**See**: [`specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md`](../specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md)
for the full wire-shape contract.

### `run_meta.sweep_mode` (M6.1.2-forward — additive, nested)

```jsonc
{ "run_meta": { "sweep_mode": "validate" } }
```

- **Type**: string `"full"` or `"validate"`.
- **Required**: yes on M6.1.2-or-later sweeps (nested inside `run_meta`).
- **Semantics**: records which top-level mode flag launched the sweep —
  `"full"` for `--m6_1_2`, `"validate"` for `--m6_1_2-validate`. Both
  modes share an identical sweep shape (n=50 × 6-cell matrix × 4
  cohorts) per FR-024; the metadata field lets downstream readers tell
  PR-merge publishable artifacts apart from harness-wiring
  confidence-builder runs.

### `measurements` (M6.1.2-forward — replaces M6.1.1's per-cell shape)

Per `(cell, cohort)` measurement summary. One entry per pair iterated.

```jsonc
{
  "measurements": [
    {
      "path": "embed",
      "concurrency": 1,
      "cohort": "default_grpc",
      "n_attempts": 50,
      "n_successes": 50,
      "wall_clock_ms_mean": 465.326,
      "engine_ttft_ms_mean": null,
      "top_failure_reasons": {}
    }
  ]
}
```

**`top_failure_reasons`** is a frequency map of distinct
`RPCResult.failure_reason` strings → count, capped at the top 5 entries
by count. Empty dict when every RPC succeeded. Diagnoses 0/N-success
cohorts from the published artifact alone — no need to re-run the sweep
or read container logs.

## M6.1.3 — Phase 1 Attribution Closure (additive)

M6.1.3 closes the c=4 / c=8 `inconclusive` chat_stream verdicts inherited
from M6.1.1 by adding three families of instrumentation: proxy-edge
probes, per-cohort prompt-content audit, and multi-run between-run
variance characterization. Every addition is **strict-superset** per
the convention above — pre-M6.1.3 readers ignore the new keys without
parse error and `schema_version` stays at `"m6_1_1.v1"` (the prefix is
a naming convention distinguishing instrumentation categories within an
extensible vocabulary, NOT a versioning signal — see
[round-3 Q1](../specs/026-m6-1-3-attribution-closure/spec.md)).

### 4 new wire keys (M6.1.3 round-3 Q1 versioning convention)

| Wire key | Type | Source | Streaming-only? | Notes |
|---|---|---|---|---|
| `m6_1_1_t_pre_engine_wall_ns` | `int` ns since epoch (`time.time_ns()`) | Frontend servicer (gRPC trailing metadata + REST SSE terminal event) | YES (per FR-003) | Wall-clock anchor for comparison against vLLM's `RequestStateStats.arrival_time` (wall). |
| `m6_1_1_t_first_chunk_mono_ns` | `int` ns (`time.monotonic_ns()`) | Same servicers | YES | Monotonic anchor for comparison against vLLM's `RequestStateStats.first_token_ts` (monotonic). |
| `m6_1_3_tokenized_prompt_length` | `int` token count | Same servicers (all RPCs per FR-014) | NO | Exact `len(prompt_token_ids)` the engine saw at prefill. |
| `m6_1_3_tokenized_prompt_hash` | `str` 16-char hex (BLAKE2b digest_size=8) | Same servicers (all RPCs per FR-014) | NO | `blake2b(b"".join(t.to_bytes(4, 'little') for t in token_ids), digest_size=8).hex()`. Collision-resistant within a multi-run sweep (≈ 10⁻¹² per R-4). |

The proxy-edge keys are emitted ONLY on streaming RPCs (`CompleteStream`
on both `chat.py` and `completions.py`) per FR-003 — the unary embed
path has no first-chunk-vs-engine-emit delta to bisect. The audit keys
are emitted on EVERY RPC (streaming + unary) per FR-014. Both M6.1.1 +
M6.1.2 + M6.1.3 wire keys share the same vocabulary; the `m6_1_*` /
`m6_1_3_*` prefixes are naming categories, not separate schemas.

### 2 new derived segments (FR-005 + FR-006)

| Segment | Derivation | Notes |
|---|---|---|
| `seg_ingress_ms` | `(engine_arrival_ns - pre_engine_wall_ns) * 1e-6` (wall-clock subtraction) | Frontend → engine handoff. |
| `seg_egress_ms` | `(first_chunk_mono_ns - engine_first_token_ns) * 1e-6` (monotonic subtraction) | Engine → frontend yield. |

Per FR-006, a negative value indicates a wall↔monotonic clock anomaly:
the row is marked `is_clock_anomaly=True`, both new segments are set
to `None`, and the raw `_ns` values are logged to stderr. The aggregator
excludes anomalous rows from per-cell mean / CI compute. The cell
verdict downgrades to `inconclusive` when the
`clock_anomaly_fraction` exceeds the configurable per-cell threshold
(default 0.5% per SC-013).

### 7-bucket classifier + canonical 6-row mapping

M6.1.3 extends M6.1.1's 5-bucket decision tree to 7 buckets per FR-008.
The canonical mapping between classifier labels, abbreviated identifiers
(used in compound-label suffixes), and driving segment fields is the
load-bearing vocabulary for the M6.x family:

| Classifier base label | Abbreviated identifier | Driving segment field |
|---|---|---|
| `channel_dependent_batching` | `channel_batching` | `seg_ab_ms` |
| `queue_dependent_batching` | `queue_batching` | `seg_queue_ms` |
| `engine_compute_variation` | `engine_compute` | `seg_prefill_ms` |
| `frontend_arrival_jitter` | `frontend_arrival` | `seg_arrival_ms` (DORMANT in M6.1.3 per round-4 Q1) |
| `proxy_ingress_dominated` | `proxy_ingress` | `seg_ingress_ms` |
| `proxy_egress_dominated` | `proxy_egress` | `seg_egress_ms` |

Plus `inconclusive` (no driving segment) — fires when no segment carries
sufficient dominance share OR when the clock-anomaly cell-level gate
trips per FR-006 + SC-013.

### Compound-label vocabulary + 5pp dominance margin (FR-008a)

When two or more labels clear their per-rule dominance gates AND the
gap between the top and runner-up shares is below 5 percentage points,
the classifier emits a compound label `multi_factor_<a>_<b>` where
both abbreviated identifiers are sorted alphabetically (per R-8). The
10 valid compound labels are listed in
`specs/026-m6-1-3-attribution-closure/contracts/classifier.md`. The
`frontend_arrival` identifier is dormant — it MUST NOT appear in any
compound label per round-4 Q1. The `inconclusive` label is also
non-compound-mappable; when one near-tie candidate would be
`inconclusive`, the cell collapses to the other candidate's single
label (FR-008a tail clause).

### `inconclusive_high_variance` outer override (FR-026 + round-2 Q3)

When the multi-run between-run stddev for a cell exceeds the unified
high-variance threshold × within-run CI half-width, the classifier
emits `inconclusive_high_variance (<inner>)` where `<inner>` is the
7-bucket inner label rendered as a parenthetical. The unified
threshold (round-2 Q3) drives both the outer-override (FR-026) and the
Phase B publication requirement (FR-043) from a single `/speckit-plan`
knob.

### `between_run_variance` top-level block (FR-024)

```jsonc
"between_run_variance": {
  "chat_stream_c4": {
    "rest_https_edge": { "mean_of_means_ms": 89.5, "stddev_of_means_ms": 7.28, "n_runs": 5 },
    "default_grpc":    { "mean_of_means_ms": 79.7, "stddev_of_means_ms": 4.63, "n_runs": 5 }
  }
  // ... per cell × cohort
}
```

Rendered only when ≥ 3 runs collected (FR-025; validate sweeps and
2-run operator overrides suppress the variance section and the
reporter emits the FR-044 override-fallback message instead). FR-027
cohort-unhealthy handling: cohorts with 0 successful RPCs in a run
drop from the variance estimate; ≥ 3 failures emit `null` for
`mean_of_means_ms` / `stddev_of_means_ms` and surface a
`cohort_unhealthy` warning in `classifier_notes`.

### `frontend_arrival_jitter` dormancy (round-4 Q1)

The label is preserved in M6.1.3's vocabulary for legacy compatibility
(rehydration of pre-M6.1.3 manifests via the 5-bucket fallback per
FR-008 + FR-010) but MUST NOT fire as the primary attribution in the
7-bucket native tree. The dormancy is structurally enforced by the
absence of a `seg_arrival_ms` field on the M6.1.3 per-cell
aggregate — the canonical 5-segment sum invariant per SC-002 is
`seg_ab + seg_queue + seg_prefill + seg_ingress + seg_egress ≈
engine_ttft` within ±1 ms.

### Audit-section reporter (FR-016 + FR-016a)

The per-cohort prompt-content audit pools per-RPC samples across runs
and produces one of three verdicts per cell:

* `H1 confirmed: per-cohort token-count means diverge by >2σ` → FR-017
  (symmetric prompts becomes the M6.x convention).
* `H2 candidate: token-counts identical but hash distributions differ`
  → text note (operator-investigate prompt-content fanout).
* `H1 rejected: per-cohort distributions statistically identical` →
  FR-018 (proceed to Phase C engine-config probes).

The pooled verdict at `chat_stream_c1` drives the FR-017 / FR-018
recommendation block on the published artifact. Per-run verdicts are
computed separately for the FR-016a conditional appendix (rendered
when any per-run verdict diverges from the pooled verdict for any
cell — round-2 Q5).

### Additive-strict-superset versioning convention (round-3 Q1)

The convention binds future milestones: **new optional wire keys leave
`schema_version` unchanged** regardless of prefix. M6.2 adding a
`max_tokens` axis (`m6_2_*` prefix) does NOT bump `schema_version`;
neither does M7's corpus diversity (`m7_*` prefix) nor M8's
multi-model. The only legitimate reason to bump is a **wire-breaking
change** — a value type changes from `int` to `str`, or an existing
key is removed. M6.1.3 does neither.

## M6.2 — Token-Budget Characterization (additive)

M6.2 extends the M6.1.3 schema with the `max_tokens` axis + four
exogenous-confound controls (FR-030/031/032/033) + the round-5
three-regime prompt source (FR-034/FR-035) + the KV-pressure sub-probe
(FR-036). All additions are strict-superset; `schema_version` stays at
`"m6_1_1.v1"` per FR-011. The artifact pair lives at
`docs/benchmarks/m6_2-token-budget.{md,json}` (canonical publish) and
`docs/benchmarks/m6_2-token-budget-validate.{md,json}` (validate
sibling) per FR-015.

### Seven new top-level keys

| Key | Type | Notes |
|---|---|---|
| `per_cell` | dict | `cell_id → cohort → max_tokens → MeasurementPoint`. Replaces M6.1.2's flat `measurements` list when M6.2 axis-rows are populated; M6.1.3 `measurements` are still emitted for backward compat by callers that need them. |
| `null_anchor_validation` | list | 48-cell anchor pool: 22 cross-checkable (paired against M6.1.3 CI) + 26 new-baseline (`new_baseline_marker=true`, verdict=null). |
| `max_tokens_axis` | list[int] | Active axis literal (`[10, 50, 256, 512, 1024, 2048]` publish; `[10, 50, 2048]` validate). |
| `protocol_crossover` | list | Per-cell crossover record (winner/second cohort + `crossover_max_tokens` per the symmetric mean-in-CI rule). 6 records (one per cell). |
| `kv_pressure_observation` | list | Per (cohort, cell_type) KV-pressure observation derived from the SUB-PROBE (not budget-table c=8 rows). 8 records (4 cohorts × 2 cell-types). |
| `anchor_latency_trajectory` | dict | `cohort → trajectory`. Per-cohort intra-sweep anchor snapshots with `latency_drift_warning` flag. |
| `failure_summary` | dict | `failed_reason → count`. Always present per SC-014; empty dict when zero failures. |
| `integrity_warnings` | list[str] | Canonical channel labels fired (subset of `{"null_anchor_drift", "failure_summary_threshold", "cohort_csp_mismatch", "intra_sweep_latency_drift", "iteration_discipline_broken", "clock_anomaly_warning"}`). Empty list when none fired. |

### Seven new per-row fields on `M6_2MeasurementPoint`

| Field | Type | Notes |
|---|---|---|
| `max_tokens` | int | Round-4. The axis point this row measures. |
| `block_start_utc` | ISO-8601 string | Round-4 (FR-032). UTC block-start timestamp. |
| `block_end_utc` | ISO-8601 string | Round-4 (FR-032). UTC block-end timestamp. |
| `retry_attempted` | bool | Round-4 (FR-033). `true` if in-window retry fired. |
| `prompt_source` | enum | Round-5 (FR-034/FR-035). Literal `"synthetic_seed_derived" \| "corpus_sharegpt" \| "synthetic_random_tensor" \| "corpus_sharegpt_embed"`. |
| `measurement_regime` | enum | Round-5 (FR-036). Always `"natural_eos"` on budget-table rows. Sub-probe rows live in `kv_pressure_observation` only and carry `"forced_cap_ignore_eos_true"`. |
| `prompt_corpus_idx` | int \| null | Round-5. Corpus-regime `iter_idx` for post-hoc analysis; `null` on synthetic-regime rows. |

### Ten new `run_meta` fields

| Field | Type | Notes |
|---|---|---|
| `iteration_order` | string | Round-4 (FR-030). Always `"cohort_innermost_block"`. |
| `iteration_discipline_verified` | bool | Round-4 (FR-032). Post-hoc machine check on the block sequence. |
| `n_per_point` | int | Round-3 deferred (publish; `--m6_2-n` operator-pinned) or `20` (validate). |
| `validate_axis_subset` | list[int] \| null | `[10, 50, 2048]` in validate; null in publish. |
| `wall_clock_start_utc` | ISO-8601 string | Sweep boundary stamps. |
| `wall_clock_end_utc` | ISO-8601 string | |
| `total_sweep_hours` | float | Derived. |
| `modal_spend_usd_estimate` | float \| null | Best-effort. |
| `chat_corpus_sha256` | string | Round-5 (FR-034 / SC-018). Recorded at sweep start from `chat_sharegpt_1000.provenance.json`. |
| `chat_corpus_path` | string | Default `"tools/benchmark/corpus/chat_sharegpt_1000.json"`. |
| `embed_corpus_sha256` | string | Round-5 (FR-035 / SC-018). Recorded at sweep start from `completions_embeds_qwen3_8b/manifest.json`. |
| `embed_corpus_path` | string | Default `"tools/benchmark/corpus/completions_embeds_qwen3_8b/"`. |
| `sub_probe_ran` | bool | Round-5 (FR-036 / SC-019). `true` in both publish and validate modes. |

### Sweep-level integrity-header firing rules

Five publish-blocking-eligible channels (operator decides) + one soft
diagnostic. Channels render as leading callouts above the markdown
body; the JSON `integrity_warnings` list carries the canonical labels.

| Channel label | Firing rule | FR | SC |
|---|---|---|---|
| `null_anchor_drift` | ≥ 2 of 22 cross-checkable null-anchor cells drifted (verdict ∈ {WARN, FAIL}). New-baseline cells excluded from the count. | FR-014 | SC-004 |
| `failure_summary_threshold` | ≥ 3 cells failed OR any (cell, max_tokens) tuple had all 4 cohorts fail (then tagged `systemic_failure_<reason>`). | FR-029 | SC-014 |
| `cohort_csp_mismatch` | Any cohort's `network_paths` trajectory shows a CSP / region change between consecutive snapshots. | FR-009 | SC-010 |
| `intra_sweep_latency_drift` | ≥ 2 of 4 cohorts' anchor trajectories drifted beyond M6.1.3 baseline CI. | FR-031 | SC-016 |
| `clock_anomaly_warning` | ≥ 0.5% of RPCs flagged for wire-format clock anomaly across the sweep. | FR-006 (inherited) | SC-011 |
| `iteration_discipline_broken` | `run_meta.iteration_discipline_verified = false`. Soft diagnostic only; informational. | FR-032 | SC-017 |

### Derived-field computation rules

**Symmetric mean-in-CI crossover rule** (FR-016 / spec round-1 Q3) — per
cell, walk the `max_tokens` axis ascending and detect the first point
where EITHER the M6.1.3-winner cohort's M6.2 mean lies inside the
M6.1.3-second cohort's CI, OR vice versa. Implemented in
`m6_2_crossover.compute_per_cell_crossover`. Inconclusive base verdicts
short-circuit to `crossover_max_tokens=null` with canonical evidence
text. Rule firing at the first axis point (e.g. 10) emits the
"M6.1.3 verdict not robust to M6.2 resampling" evidence per US2 #3.

**Wall-clock-ratio KV-pressure inference** (FR-017a / spec round-3 Q3 /
round-5 amendment) — per (cohort, cell_type), compute
`R = wall_p50_ms(2048) / wall_p50_ms(1024)` from the **sub-probe rows**
(NOT main-sweep budget-table c=8 rows). `R > 2.2` →
`kv_pressure_inferred_<cell_type>`; else `kv_pressure_not_observable`.
OOM at the 2048 sub-probe pins the label to `kv_pressure_not_observable`
and sets `oom_observed=true`. Implemented in
`m6_2_crossover.compute_kv_pressure_inference`. Threshold 2.2 pinned per
round-3 Q3.

### Three-regime prompt-source contract (FR-034 / FR-035 — round-5)

| `(cell_type, max_tokens)` | Regime | `prompt_source` | `ignore_eos` |
|---|---|---|---|
| `chat_stream`, `10 \| 50` | null-anchor synthetic | `synthetic_seed_derived` | false |
| `chat_stream`, `256 \| 512 \| 1024 \| 2048` | interior-cap corpus | `corpus_sharegpt` | false |
| `embed`, `10 \| 50` | null-anchor synthetic | `synthetic_random_tensor` | false |
| `embed`, `256 \| 512 \| 1024 \| 2048` | interior-cap corpus | `corpus_sharegpt_embed` | false |
| sub-probe `(chat_stream_c8, 1024 \| 2048)` | forced-cap corpus | `corpus_sharegpt` | **true** |
| sub-probe `(embed_c8, 1024 \| 2048)` | forced-cap corpus | `corpus_sharegpt_embed` | **true** |

The regime is selected per-block (not per-cohort or per-iteration) by
`m6_2_prompt_source.resolve_block_inputs`. Sub-probe rows DO NOT appear
in the `per_cell` budget table — they emit to
`kv_pressure_observation` only, preserving the additive-vs-budget
distinction per FR-036.

### KV-pressure sub-probe contract (FR-036 — round-5)

The sub-probe is a separate, additive measurement loop:

- **16 blocks**: 4 cohorts × 2 cell-types `{chat_stream, embed}` × 2 caps
  `{1024, 2048}`. Targets `chat_stream_c8` + `embed_c8` cells per
  FR-017a's high-concurrency focus.
- **`n=20` per block** pinned (`M6_2_SUB_PROBE_N`).
- **`ignore_eos=True`** on every RPC so the engine generates to the
  forced cap.
- **Corpus regime** via `m6_2_prompt_source.resolve_block_inputs(...,
  ignore_eos_override=True)`.
- **FR-030 cohort-innermost discipline** within each (cell_type,
  max_tokens) tuple: all 4 cohorts dispatch back-to-back before
  advancing.
- **FR-032 per-block UTC timestamps + FR-033 in-window retry-once**
  apply to sub-probe blocks identically to main-sweep blocks.
- **Runs in both publish and validate modes** per SC-019.
- Sub-probe results emit to `m6_2_crossover.SubProbeBlockResult` and are
  consumed by `compute_kv_pressure_inference` to produce the 8
  `kv_pressure_observation` records. They DO NOT pollute the
  latency-budget table — `per_cell` c=8 rows stay populated by the
  main-sweep interior-cap regime.

### Corpus SHA validation (SC-018 — round-5)

Both corpora are SHA-pinned at sweep start. The orchestrator reads:

- `tools/benchmark/corpus/chat_sharegpt_1000.provenance.json:corpus_sha256`
- `tools/benchmark/corpus/completions_embeds_qwen3_8b/manifest.json:corpus_sha256`

…compares them against the on-disk corpus, and aborts with exit code 6
(`CorpusDriftError`) on mismatch. The validated SHAs are recorded in
`run_meta.{chat,embed}_corpus_sha256` so post-hoc analysis can detect
silent corpus swaps.

### Validate-mode rendering rules

The validate-sibling artifact shares the same shape as the publish
artifact with these adjustments:

- Interior caps (`max_tokens ∈ {256, 512, 1024}`) carry `failed_reason
  = "not_validated"` placeholder rows so the `per_cell` shape stays
  144 entries (idealized) / 132 entries (live-cohort discipline).
- The "Protocol crossover threshold" section prepends the
  axis-restricted disclaimer callout; `crossover_max_tokens` uses the
  coarse 4-value vocabulary `{10, 50, 2048, survives_to_2048, null}`.
- The "Sweep wall-clock timeline" subsection is OMITTED when
  `total_sweep_hours < 8` (validate sweeps are too short to be
  signal-bearing). Publish mode renders it unconditionally.
- All other auxiliary subsections render normally — anchor trajectory
  carries 2 snapshots (start + end), null-anchor + KV-pressure +
  failure-summary all populate normally.

### Project-wide convention propagation (FR-027)

M6.2 is **harness-only** — no frontend / proxy / engine path changes.
One additive `.proto` field (`ignore_eos` on `ChatCompleteRequest` +
`CompletionRequest`) was added in T003 to support the sub-probe regime;
frontend translation lives in `packages/frontend/src/vllm_grpc_frontend/{chat,completions}.py`
(T003a). The artifact-JSON schema additions are all top-level keys or
per-row fields; `schema_version` unchanged.

## Strict-superset evolution rule

New top-level keys are added without bumping `schema_version` PROVIDED:

1. Existing readers ignore unknown top-level keys without error.
2. The new key has a documented default-on-absence semantic so
   pre-introduction artifacts parse unchanged.
3. The addition doesn't alter the meaning or type of any existing key.

Renames, removals, and type changes do require a `schema_version` bump.
None have happened to date.

The contract precedents are:

- M6.0a (`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`) —
  added `dispatch_mode` with absence → `"sequential"`.
- M6.1.2 (`specs/025-m6-1-2-methodology-discipline/contracts/{network-paths,artifact-schema}.md`)
  — added `network_paths` + `cohort_set` + `cohort_omissions` +
  `run_meta.sweep_mode` + `measurements[*].top_failure_reasons`.
- M6.1.3 (`specs/026-m6-1-3-attribution-closure/contracts/{wire-vocabulary,classifier,artifact-schema}.md`)
  — added 4 wire keys + 2 derived segments + 7-bucket classifier
  extension + `inconclusive_high_variance` outer override +
  `between_run_variance` top-level block + audit reporter sections
  per FR-001 / FR-002 / FR-005 / FR-008 / FR-008a / FR-016 / FR-024
  / FR-026 + round-3 Q1 (the additive-strict-superset convention
  binding future M6.2 / M7 / M8 milestones).
- M6.2 (`specs/027-m6-2-token-budget/contracts/{artifact-schema,iteration-order,prompt-source,wire-vocabulary}.md`)
  — added the `max_tokens` axis + 7 top-level keys (`per_cell`,
  `null_anchor_validation`, `max_tokens_axis`, `protocol_crossover`,
  `kv_pressure_observation`, `anchor_latency_trajectory`,
  `failure_summary`, `integrity_warnings`) + 7 per-row fields
  (`max_tokens`, `block_start_utc`, `block_end_utc`,
  `retry_attempted`, `prompt_source`, `measurement_regime`,
  `prompt_corpus_idx`) + 10 `run_meta` fields + the three-regime
  prompt-source contract (FR-034/FR-035) + the KV-pressure sub-probe
  contract (FR-036) + the corpus SHA validation rule (SC-018) + one
  additive `ignore_eos` wire field per FR-036.

## Cross-references

- [`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`](../specs/024-m6-0a-concurrent-dispatch/contracts/output.md)
  — `dispatch_mode` contract.
- [`specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md`](../specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md)
  — `network_paths` wire shape.
- [`specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md`](../specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md)
  — `cohort_set` / `cohort_omissions` wire shape.
- [`specs/025-m6-1-2-methodology-discipline/data-model.md`](../specs/025-m6-1-2-methodology-discipline/data-model.md)
  — Python dataclasses behind the wire shapes.
- [`specs/026-m6-1-3-attribution-closure/contracts/wire-vocabulary.md`](../specs/026-m6-1-3-attribution-closure/contracts/wire-vocabulary.md)
  — M6.1.3 wire keys + extractor mapping + additive-strict-superset
  versioning convention.
- [`specs/026-m6-1-3-attribution-closure/contracts/classifier.md`](../specs/026-m6-1-3-attribution-closure/contracts/classifier.md)
  — 7-bucket decision tree + FR-008a tie-breaking + compound vocabulary
  + `inconclusive_high_variance` outer override.
- [`specs/026-m6-1-3-attribution-closure/contracts/artifact-schema.md`](../specs/026-m6-1-3-attribution-closure/contracts/artifact-schema.md)
  — three-path publishing scheme + `between_run_variance` + Phase B
  trigger verdict.
- [`specs/026-m6-1-3-attribution-closure/data-model.md`](../specs/026-m6-1-3-attribution-closure/data-model.md)
  — Python dataclasses for M6.1.3 additions.
- [`specs/027-m6-2-token-budget/contracts/artifact-schema.md`](../specs/027-m6-2-token-budget/contracts/artifact-schema.md)
  — M6.2 top-level keys + per-row fields + integrity-header firing rules
  + symmetric mean-in-CI crossover + wall-clock-ratio inference +
  validate-mode rendering rules.
- [`specs/027-m6-2-token-budget/contracts/iteration-order.md`](../specs/027-m6-2-token-budget/contracts/iteration-order.md)
  — FR-030 cohort-innermost discipline + FR-031 anchor cadence +
  FR-032 timestamps + FR-033 in-window retry.
- [`specs/027-m6-2-token-budget/contracts/prompt-source.md`](../specs/027-m6-2-token-budget/contracts/prompt-source.md)
  — three-regime prompt-source contract + corpus paths + SHA pinning +
  `ignore_eos` plumbing + sub-probe regime selection.
- [`specs/027-m6-2-token-budget/contracts/wire-vocabulary.md`](../specs/027-m6-2-token-budget/contracts/wire-vocabulary.md)
  — `ignore_eos` additive wire field on `ChatCompleteRequest` +
  `CompletionRequest`.
- [`specs/027-m6-2-token-budget/data-model.md`](../specs/027-m6-2-token-budget/data-model.md)
  — Python dataclasses for M6.2 additions
  (`M6_2MeasurementPoint`, `M6_2NullAnchor`, `M6_2CrossoverThreshold`,
  `M6_2KVPressureObservation`, `M6_2AnchorLatencyTrajectory`,
  `M6_2RunMeta`, `M6_2SweepArtifact`).
- [`ANALYSIS.md § M6.1.2`](../ANALYSIS.md) — the methodology
  implications of the per-sweep topology evidence (the spike-era
  multi-cloud topology vs the 2026-05-17 single-AWS consolidation).
