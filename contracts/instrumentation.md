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

## Cross-references

- [`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`](../specs/024-m6-0a-concurrent-dispatch/contracts/output.md)
  — `dispatch_mode` contract.
- [`specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md`](../specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md)
  — `network_paths` wire shape.
- [`specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md`](../specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md)
  — `cohort_set` / `cohort_omissions` wire shape.
- [`specs/025-m6-1-2-methodology-discipline/data-model.md`](../specs/025-m6-1-2-methodology-discipline/data-model.md)
  — Python dataclasses behind the wire shapes.
- [`ANALYSIS.md § M6.1.2`](../ANALYSIS.md) — the methodology
  implications of the per-sweep topology evidence (the spike-era
  multi-cloud topology vs the 2026-05-17 single-AWS consolidation).
