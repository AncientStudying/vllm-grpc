# Contract: `m5-cross-host-validation.json` schema

This contract defines the M5 report schema as a **strict superset** of M4's `m4-time-axis-tuning.json` schema (per spec FR-014 / research.md R-8).

> **Compatibility rule**: any reader that successfully parses an `m4-time-axis-tuning.json` file MUST successfully parse an `m5-cross-host-validation.json` file when M5 fields are ignored. New fields are additive only. No M4 field is renamed, removed, or has its semantics redefined. By transitivity, M3 readers also work — M4 already preserved M3 compatibility.

## Top-level shape

```jsonc
{
  // ----- M4-shape fields (preserved unchanged from m4-time-axis-tuning.json) -----
  "mode": "m5-cross-host-validation",        // M4 used "m4-time-axis-tuning"
  "axes": ["max_message_size", "keepalive", "compression", "http2_framing"],
  "widths": [2048, 4096, 8192],
  "paths": ["embed", "chat_stream"],
  "iterations_per_cell": 100,
  "seed": 0,
  "p2_revision": null,
  "frozen_channel": null,
  "pacing_mode": "no_pacing",
  "shared_baseline_cohort_ids": {
    "embed": "embed|h4096|m1-baseline|m5_embed",
    "chat_stream": "chat_stream|h4096|m1-baseline|m5_chat"
  },
  "frozen_channel_baselines": {
    "chat_stream": {
      "path": "chat_stream",
      "cohort_id": "chat_stream|h4096|frozen|m5_frozen",
      "channel_config_name": "frozen-chat_stream-h4096-m5",
      "per_axis_winners": { /* per-axis winners from M5 US1 */ },
      "measured_at_hidden_size": 4096
    }
    /* embed analogous */
  },
  "cohorts": [ /* see per-cohort shape below */ ],
  "schema_candidate_results": [ /* M4 shape — preserved unchanged */ ],
  "supersedes_m3": [ /* M4's M3-supersession table — preserved unchanged from M4 */ ],

  // ----- M5-only top-level additions (FR-004, FR-005, FR-014, FR-015, R-8) -----
  "m5_methodology_version": 1,
  "m5_modal_app_name": "vllm-grpc-bench-mock",
  "m5_modal_region": "eu-west-1",
  "m5_runtime_wallclock_seconds": 4831.2,
  "m5_rtt_summary_ms": {
    "min": 28.4,
    "median": 87.1,
    "p95": 142.6,
    "max": 215.8
  },
  "rtt_validity_threshold_ms": 1.0,
  "rtt_exercise_threshold_ms": 20.0,
  "warmup_n": 32,
  "server_bound_overhead_threshold_ms": 50.0,
  "server_bound_cohort_count": 0,
  "supersedes_m4": [ /* see SupersedesM4Entry shape below */ ]
}
```

## Per-cohort shape (`cohorts[i]`)

```jsonc
{
  // ----- M4-shape fields (preserved unchanged) -----
  "cohort_id": "chat_stream|h4096|max_message_size|mtu_64kb|m5_chat_4096_mms64kb",
  "path": "chat_stream",
  "hidden_size": 4096,
  "axis": "max_message_size",
  "config_name": "mtu_64kb",
  "iterations": 100,
  "n": 100,
  "samples_ms_time": [ /* per-iter wall-clock — preserved */ ],
  "samples_bytes": [ /* per-iter byte counts — preserved */ ],
  "ci_lower_time_ms": 814.2,
  "ci_upper_time_ms": 826.5,
  "ci_lower_bytes": 19834.1,
  "ci_upper_bytes": 19851.0,
  "cv_time": 0.043,
  "cv_bytes": 0.0008,
  "noisy_baseline": false,
  "client_bound": false,
  "loopback_caveat": false,                      // M4 field; M5 always emits `false`
  "expansion_record": { /* M4 shape — preserved */ },

  // ----- M5-only cohort-level additions (FR-004, FR-005, R-3, R-4, R-5, R-8) -----
  "rtt_record": {
    "n": 32,
    "median_ms": 87.4,
    "p95_ms": 142.6,
    "samples_ms": [ /* 32 floats */ ]
  },
  "server_overhead_estimate_ms": 12.4,
  "server_bound": false,
  "low_rtt_caveat": false,
  "discarded": false                             // true on warm-up cohorts (per R-5)
}
```

## SupersedesM4Entry shape (`supersedes_m4[i]`)

```jsonc
{
  "m4_axis": "keepalive",
  "m4_hidden_size": 4096,
  "m4_path": "chat_stream",
  "m4_verdict_time": "no_winner",
  "m4_verdict_bytes": "no_winner",
  "m4_loopback_caveat": true,
  "m5_verdict_time": "recommend",
  "m5_verdict_bytes": "no_winner",
  "m5_supporting_ci_lower": 0.041,                // CI lower bound on the verdict-driver metric delta
  "m5_supporting_ci_upper": 0.067,                // CI upper bound on the verdict-driver metric delta
  "rationale": "real RTT exposed a 5.4% TTFT reduction under keepalive=enabled at hidden_size 4096",
  "verdict_changed": true
}
```

One row exists for:
1. Every M4 cell where `m4_loopback_caveat == true` (FR-015 mandatory — these are the cells M5 exists to resolve).
2. Any other M4 cell where either `m5_verdict_time != m4_verdict_time` or `m5_verdict_bytes != m4_verdict_bytes` (FR-015 conditional — verdicts M5 has changed for reasons other than loopback resolution).

Verdict-changed rows are visually emphasized in the markdown companion (`m5-cross-host-validation.md`) per SC-004; the JSON simply carries the boolean `verdict_changed` field.

## Recommendation-level addition (`verdicts[*]`)

The existing `verdicts[*]` array (preserved unchanged from M4 shape) gains one optional field:

```jsonc
{
  // ...M4 verdict fields preserved unchanged...
  "supersedes_m4_cell": { /* SupersedesM4Entry shape */ }     // present for M5 verdicts that supersede an M4 cell
}
```

When present, `supersedes_m4_cell` carries the same payload as the corresponding `supersedes_m4[i]` entry — readers can use either. The top-level `supersedes_m4` array is the canonical list for table-generation; the per-verdict `supersedes_m4_cell` exists so a reader iterating verdicts has direct access without joining against the array.

## Field semantics notes

- `loopback_caveat`: inherited from M4 schema; **always `false` on every M5 cohort** (FR-007). The field is retained for M4-reader compat (a tool filtering by `loopback_caveat == true` will find zero M5 cohorts, which is the correct M5 result).
- `client_bound`: inherited from M4 semantics; still emitted on M5 cohorts whose dominant cost is client-side overhead (M4 R-5 classifier).
- `server_bound`: NEW in M5. Emitted on cohorts whose dominant cost is remote-server overhead (research.md R-4 classifier). Mutually exclusive with `client_bound` in practice (a cohort cannot be both dominated by client and by server); the M5 sweep tolerates the edge case where both classifiers fire by recording both flags and excluding the cohort from `recommend` tallies under either flag.
- `low_rtt_caveat`: NEW in M5. Emitted when `rtt_record.median_ms < rtt_exercise_threshold_ms` (default 20.0). Cohorts with `low_rtt_caveat: true` still produce verdicts; readers are expected to discount RTT-bounded-axis verdicts (`keepalive`, `http2_framing`) from `low_rtt_caveat` cells.
- `discarded`: NEW in M5. Emitted on warm-up cohorts; readers MUST skip discarded cohorts in any aggregate computation.

## Versioning

`m5_methodology_version: 1` for this release. A future bump (e.g., changing the `server_bound` classifier formula) increments this integer; readers MUST check it before consuming `server_overhead_estimate_ms` or `server_bound` semantics.
